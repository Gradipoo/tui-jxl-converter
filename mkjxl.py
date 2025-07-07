#!/usr/bin/env python3
"""
TUI JXL Converter - A terminal-based image to JXL conversion tool.

Features:
- Browse files with smooth, buffered scrolling (full-line highlighting).
- Real-time UI updates during non-blocking background conversions.
- Interactive filter to show all files or only failed conversions.
- Automated prompt to "Sanitize & Retry" failed files after a batch.
- Optional debug logging to a .txt file for troubleshooting.
- Full customization of cjxl parameters (Quality, Effort).
- Toggles for recursive search and deleting originals.
- User-configurable output directory (defaults to ./converted).
- Dynamic header that shows setup when idle and progress when converting.
- Automatic conflict resolution for output filenames.
- Dynamic footer bar with clear, context-aware keybindings.
- Graceful handling of small terminal window sizes.

Dependencies:
- `cjxl` (from libjxl-tools) must be in the system's PATH.
- `magick` or `convert` (from ImageMagick) is optional for the "Sanitize" feature.
"""

import os
import sys
import curses
import time
import threading
import queue
import shutil
import argparse
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

# --- Helper Classes (Dialogs) ---

class ConfirmationDialog:
    def __init__(self, stdscr, question):
        self.stdscr = stdscr; self.question = question
    def run(self):
        curses.curs_set(0); h, w = self.stdscr.getmaxyx()
        height, width = 3, len(self.question) + 6
        start_y = (h - height) // 2; start_x = (w - width) // 2
        win = curses.newwin(height, width, start_y, start_x); win.keypad(True); win.box()
        try: win.addstr(1, 2, self.question)
        except curses.error: pass
        self.stdscr.nodelay(False); win.refresh()
        choice = False
        while True:
            key = win.getch()
            if key in [ord('y'), ord('Y')]: choice = True; break
            if key in [ord('n'), ord('N'), 27]: choice = False; break
        self.stdscr.nodelay(True)
        return choice

class InputDialog:
    def __init__(self, stdscr, prompt, initial_value=""):
        self.stdscr = stdscr; self.prompt = prompt; self.text = str(initial_value)
    def run(self):
        curses.curs_set(1); h, w = self.stdscr.getmaxyx()
        height, width = 3, max(len(self.prompt) + len(self.text), 40) + 6
        start_y = (h - height) // 2; start_x = (w - width) // 2
        win = curses.newwin(height, width, start_y, start_x); win.keypad(True)
        while True:
            win.erase(); win.box()
            try: win.addstr(1, 2, f"{self.prompt}: {self.text}")
            except curses.error: pass
            win.refresh()
            key = win.getch()
            if key == curses.KEY_RESIZE: return None
            if key in [10, curses.KEY_ENTER]: return self.text
            if key == 27: return None
            if key in [curses.KEY_BACKSPACE, 127]: self.text = self.text[:-1]
            elif 32 <= key <= 126: self.text += chr(key)

class JxlConverterTUI:
    def __init__(self, stdscr, initial_dir):
        self.stdscr = stdscr; self.initial_dir = Path(initial_dir).resolve()
        self.files = []; self.selected = set(); self.statuses = {}; self.failed_indices = set()
        self.current_row = 0; self.scroll_offset = 0; self.status_message = ""; self.status_message_color = 5
        self.quality = 90; self.effort = 7; self.recursive = False; self.delete_originals = False
        self.show_only_failed = False; self.debug_enabled = False
        self.output_dir = Path.cwd() / "converted"
        self.log_file = Path("jxl_converter_debug.txt")
        self.conversion_queue = queue.Queue(); self.status_queue = queue.Queue()
        self.conversion_thread = None; self.is_converting = False; self.stop_thread = threading.Event()
        self.total_bytes_before = 0; self.total_bytes_after = 0
        self.conversions_success = 0; self.conversions_failed = 0; self.start_time = 0; self.last_conversion_summary = ""
        self.cjxl_cmd = shutil.which("cjxl"); self.imagemagick_cmd = shutil.which("magick") or shutil.which("convert")
        curses.start_color()
        for i, (fg, bg) in enumerate([(curses.COLOR_BLACK, curses.COLOR_WHITE), (curses.COLOR_GREEN, curses.COLOR_BLACK),
                                      (curses.COLOR_YELLOW, curses.COLOR_BLACK), (curses.COLOR_RED, curses.COLOR_BLACK),
                                      (curses.COLOR_CYAN, curses.COLOR_BLACK), (curses.COLOR_BLACK, curses.COLOR_GREEN),
                                      (curses.COLOR_MAGENTA, curses.COLOR_BLACK), (curses.COLOR_BLUE, curses.COLOR_BLACK)], 1):
            curses.init_pair(i, fg, bg)
        self.load_files()

    def _log_debug(self, message):
        if not self.debug_enabled: return
        try:
            if not self.log_file.exists():
                header = f"TUI JXL Converter Debug Log\n\nSession started: {datetime.now().isoformat()}\n\n"
                self.log_file.write_text(header, encoding="utf-8")
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat()}] {message}\n")
        except OSError:
            self.debug_enabled = False; self.show_message("Error writing to debug log. Disabling.", 4)

    def _update_status(self, idx, status, **kwargs):
        self.status_queue.put({'idx': idx, 'status': status, **kwargs})

    def _process_status_queue(self):
        just_finished = False
        while not self.status_queue.empty():
            update = self.status_queue.get(); idx = update['idx']
            if idx in self.statuses:
                self.statuses[idx].update(update)
                status = update.get('status')

                info_text = ""
                if status == 'SUCCESS':
                    self.conversions_success += 1
                    b_before=update.get('size_before',0); b_after=update.get('size_after',0)
                    if b_before and b_after:
                        self.total_bytes_before += b_before; self.total_bytes_after += b_after
                        savings=b_before-b_after; savings_pct=(savings/b_before*100) if b_before>0 else 0
                        info_text=f"{self._format_bytes(savings)} saved ({savings_pct:.1f}%)"
                elif status == 'FAILED':
                    self.conversions_failed += 1; self.failed_indices.add(idx)
                    info_text = update.get('message', 'Unknown Error')
                self.statuses[idx]['info_str'] = info_text

        if self.is_converting and self.conversion_queue.empty():
            total_processed = self.conversions_success + self.conversions_failed
            if total_processed >= len(self.selected):
                self.is_converting = False
                elapsed = time.time() - self.start_time
                self.show_message(f"Finished {total_processed} files in {elapsed:.2f}s.", 2)
                total_savings = self.total_bytes_before - self.total_bytes_after
                savings_str = self._format_bytes(total_savings)
                if self.total_bytes_before > 0:
                    savings_pct = (total_savings / self.total_bytes_before) * 100
                    summary = f"Finished: {total_processed} files | Total Saved: {savings_str} ({savings_pct:.1f}%) | Time: {elapsed:.2f}s"
                else:
                    summary = f"Finished: {total_processed} files | Time: {elapsed:.2f}s"
                self.last_conversion_summary = summary
                just_finished = True

        if just_finished and self.failed_indices:
            self._prompt_for_sanitize()

    def _prompt_for_sanitize(self):
        if not self.imagemagick_cmd:
            self.show_message("Some files failed. Install ImageMagick to enable sanitize/retry.", 3); return

        prompt = f"{len(self.failed_indices)} files failed. Sanitize & retry them now? (y/n)"
        if ConfirmationDialog(self.stdscr, prompt).run():
            self.show_message("Re-queueing failed files for sanitized conversion...")
            self.selected = self.failed_indices.copy()
            self._start_conversion_session(is_sanitize_run=True)

    def _format_bytes(self, size_bytes):
        if size_bytes <= 0: return "0B"
        power=1024; n=0; power_labels={0:'', 1:'K', 2:'M', 3:'G', 4:'T'}
        while size_bytes >= power and n < len(power_labels): size_bytes /= power; n += 1
        return f"{size_bytes:.1f}{power_labels[n]}B"

    def load_files(self):
        self.files.clear(); self.statuses.clear(); self.selected.clear(); self.failed_indices.clear()
        self.current_row = 0; self.scroll_offset = 0
        pattern = '**/*.*' if self.recursive else '*.*'
        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.apng', '.tiff', '.tif'}
        try:
            found_files = sorted([f for f in self.initial_dir.glob(pattern) if f.is_file() and f.suffix.lower() in image_exts], key=lambda p: p.name.lower())
            self.files = found_files
            for i in range(len(self.files)): self.statuses[i] = {'status': 'PENDING', 'message': '', 'info_str': ''}
        except Exception as e: self.show_message(f"Error loading files: {e}", 4)

    def draw_header(self, h, w):
        try:
            self.stdscr.addstr(0, 0, " " * (w - 1), curses.color_pair(8))
            title = " TUI JXL Converter "; self.stdscr.addstr(0, 2, title, curses.color_pair(1) | curses.A_BOLD)

            header_content_x = len(title) + 4; available_width = w - header_content_x - 1

            header_content = ""
            if self.is_converting:
                total = len(self.selected); done = self.conversions_success + self.conversions_failed
                elapsed_time = time.time() - self.start_time
                time_str = time.strftime('%M:%S', time.gmtime(elapsed_time))
                savings_str = f"Saved: {self._format_bytes(self.total_bytes_before - self.total_bytes_after)}"
                header_content = f"Converting: {done}/{total} | {savings_str} | Elapsed: {time_str}"
            elif self.last_conversion_summary:
                header_content = self.last_conversion_summary
            else:
                source_label = "Source: "; output_label = " | Output: "; chrome_len = len(source_label) + len(output_label)
                path_space = available_width - chrome_len; max_len_per_path = path_space // 2
                source_str = self._abbreviate_path(self.initial_dir, max_len_per_path)
                output_str = "Same as Source" if self.output_dir is None else self._abbreviate_path(self.output_dir, max_len_per_path)
                filter_str = " | FILTER: FAILED" if self.show_only_failed else ""
                header_content = f"{source_label}{source_str}{output_label}{output_str}{filter_str}"
            self.stdscr.addstr(0, header_content_x, header_content[:available_width], curses.color_pair(8))
        except curses.error: pass

    def _abbreviate_path(self, path, max_len):
        path_str = str(path)
        if len(path_str) <= max_len: return path_str
        parts = path.parts
        if len(parts) <= 2: return "..." + path_str[-(max_len-3):]
        first, last = parts[0], parts[-1]
        chrome_len = len(first) + len(last) + len(os.sep) * 2 + 3
        if chrome_len > max_len: return "..." + path_str[-(max_len-3):]
        return os.path.join(first, "...", last)

    def get_visible_files(self):
        if self.show_only_failed:
            return [(i, self.files[i]) for i in sorted(list(self.failed_indices))]
        return list(enumerate(self.files))

    def draw_file_list(self, h, w, visible_files):
        layout = self._get_layout(); header_attr = curses.color_pair(2) | curses.A_BOLD
        try:
            self.stdscr.addstr(1, 0, " " * (w - 1), header_attr)
            self.stdscr.addstr(1, 2, "Original", header_attr)
            self.stdscr.addstr(1, layout['preview_x'], "Target JXL (*=Selected)", header_attr)
            self.stdscr.addstr(1, layout['status_x'], "Status", header_attr)
            self.stdscr.addstr(1, layout['info_x'], "Info / Savings", header_attr)
        except curses.error: pass

        max_rows = h - 5
        for i in range(max_rows):
            y = 2 + i;
            if i + self.scroll_offset >= len(visible_files): break
            original_idx, file_path = visible_files[i + self.scroll_offset]
            status_info = self.statuses.get(original_idx, {'status': 'ERROR'})
            attr = curses.A_REVERSE if i + self.scroll_offset == self.current_row else curses.A_NORMAL
            try:
                self.stdscr.addstr(y, 0, " " * (w-1), attr)
                display_orig = (file_path.name[:layout['orig_w']-2]+'…') if len(file_path.name)>layout['orig_w']-1 else file_path.name
                self.stdscr.addstr(y, 2, display_orig.ljust(layout['orig_w']), attr)
                select_char = "*" if original_idx in self.selected else " "
                target_path = status_info.get('target_path', file_path.with_suffix('.jxl'))
                new_name = f"{select_char} {target_path.name}"
                preview_attr = attr | (curses.color_pair(3) if original_idx in self.selected else 0)
                display_new = (new_name[:layout['preview_w']-2]+'…') if len(new_name)>layout['preview_w']-1 else new_name
                self.stdscr.addstr(y, layout['preview_x'], display_new.ljust(layout['preview_w']), preview_attr)

                status_text = status_info.get('status', 'PENDING')
                if original_idx in self.selected and status_text == 'PENDING': status_text = 'SELECTED'
                color_map={'PENDING':5,'SELECTED':3,'QUEUED':8,'SKIPPED':5,'CONVERTING':7,'SUCCESS':2,'FAILED':4,'SANITIZING':7,'IGNORED':5}
                status_color = color_map.get(status_text, 4)
                self.stdscr.addstr(y, layout['status_x'], status_text.ljust(layout['status_w']), attr | curses.color_pair(status_color))

                info_text = status_info.get('info_str', '')
                display_info = (info_text[:layout['info_w']-2]+'…') if len(info_text)>layout['info_w']-1 else info_text
                self.stdscr.addstr(y, layout['info_x'], display_info.ljust(layout['info_w']), attr | curses.color_pair(status_color))
            except curses.error: pass

    def _get_layout(self):
        w = self.stdscr.getmaxyx()[1]
        info_w=24; status_w=12; sep_len=3; info_x=max(w-info_w,0); status_x=max(info_x-sep_len-status_w,0)
        orig_x=2; middle_area_w=max(status_x-sep_len-orig_x,0); orig_w=middle_area_w*2//5; preview_w=middle_area_w-orig_w
        preview_x=orig_x+orig_w+sep_len
        return {'orig_w':max(0,orig_w),'preview_x':preview_x,'preview_w':max(0,preview_w),
                'status_x':status_x,'status_w':max(0,status_w),'info_x':info_x,'info_w':max(0,info_w)}

    def draw_status_bar(self, h, w):
        try:
            self.stdscr.addstr(h-3, 0, " " * (w-1))
            if self.status_message: self.stdscr.addstr(h-3, 2, self.status_message, curses.color_pair(self.status_message_color))
        except curses.error: pass

    def _draw_key_helper(self, y, x, key, text, is_active=False):
        key_attr = curses.color_pair(6)|curses.A_BOLD if is_active else curses.color_pair(2)
        text_attr = curses.color_pair(3)|curses.A_BOLD if is_active else curses.color_pair(5)
        try:
            self.stdscr.addstr(y, x, f"({key})", key_attr)
            self.stdscr.addstr(y, x+len(key)+2, text, text_attr)
        except curses.error: pass
        return x + len(f"({key}) {text}") + 2

    def draw_footer(self, h, w):
        y_top, y_bot = h - 2, h - 1
        try:
            for i in range(2): self.stdscr.addstr(h-1-i, 0, " " * (w-1))
        except curses.error: return
        x = 2
        toggles = [('Q',f"Qual:{self.quality}",False), ('E',f"Eff:{self.effort}",False), ('R',"Recur",self.recursive),
                   ('D',"DelOrig",self.delete_originals), ('O',"Out Dir", self.output_dir is not None),
                   ('B', "Bug Log", self.debug_enabled)]
        if self.failed_indices: toggles.append(('F', "Filter Failed", self.show_only_failed))

        for key, text, is_active in toggles:
            if x + len(key) + len(text) + 5 > w: break
            x = self._draw_key_helper(y_top, x, key, text, is_active)

        x = 2
        x = self._draw_key_helper(y_bot, x, "↑↓/jk", "Nav"); x = self._draw_key_helper(y_bot, x, "Space", "Select")
        x = self._draw_key_helper(y_bot, x, "a/A", "All/None"); x = self._draw_key_helper(y_bot, x, "Enter", "Convert")
        x = self._draw_key_helper(y_bot, x, "F5", "Refresh")
        quit_str = "(ESC/q) Quit"; self.stdscr.addstr(y_bot, w - len(quit_str) - 2, quit_str, curses.color_pair(2))

    def _get_unique_target_path(self, in_path, existing_targets):
        target_dir = self.output_dir if self.output_dir is not None else in_path.parent
        if self.output_dir and self.recursive:
             try: target_dir = self.output_dir/in_path.parent.relative_to(self.initial_dir)
             except ValueError: pass
        target_dir.mkdir(parents=True, exist_ok=True)

        target_path = target_dir / f"{in_path.stem}.jxl"
        counter = 1
        while str(target_path) in existing_targets or target_path.exists():
             target_path = target_dir / f"{in_path.stem}-{counter}.jxl"; counter += 1
        return target_path

    def _start_conversion_session(self, is_sanitize_run=False):
        if self.is_converting: self.show_message("A conversion is already in progress.", 3); return
        if not self.selected: self.show_message("No files selected to convert.", 3); return
        if not self.cjxl_cmd: self.show_message("cjxl command not found in PATH.", 4); return
        if self.delete_originals and not is_sanitize_run and not ConfirmationDialog(self.stdscr, "Delete originals is ON. Proceed? (y/n)").run():
            self.show_message("Conversion cancelled."); return

        self._log_debug("--- Preparing new conversion session ---")
        tasks = []
        existing_targets_in_batch = set()
        for idx in sorted(list(self.selected)):
            input_path = self.files[idx]
            target_path = self._get_unique_target_path(input_path, existing_targets_in_batch)
            existing_targets_in_batch.add(str(target_path))
            self.statuses[idx]['target_path'] = target_path
            tasks.append({'idx': idx, 'target_path': target_path, 'sanitize': is_sanitize_run})
            self._log_debug(f"  - Queued Task: {input_path.name} -> {target_path.name}")

        if not is_sanitize_run:
            self.is_converting = True; self.start_time = time.time(); self.conversions_success = 0
            self.conversions_failed = 0; self.total_bytes_before = 0; self.total_bytes_after = 0

        for task in tasks:
            self.conversion_queue.put(task)
            idx = task['idx']
            self.statuses[idx]['status'] = 'QUEUED'
            if idx in self.failed_indices: self.failed_indices.remove(idx)

        self._log_debug(f"--- Starting worker thread with {len(tasks)} tasks ---")
        if self.conversion_thread is None or not self.conversion_thread.is_alive():
            self.stop_thread.clear()
            self.conversion_thread = threading.Thread(target=self.conversion_worker, daemon=True)
            self.conversion_thread.start()

    def conversion_worker(self):
        while not self.stop_thread.is_set():
            try:
                task=self.conversion_queue.get(timeout=1)
                idx, target_path, use_sanitize = task['idx'], task['target_path'], task['sanitize']
                input_path = self.files[idx]

                self._log_debug(f"PULLED TASK: Idx={idx}, Target={target_path.name}, Sanitize={use_sanitize}")

                if use_sanitize:
                    self._log_debug(f"SANITIZING {input_path.name}")
                    self._update_status(idx, 'SANITIZING')
                    if not self.imagemagick_cmd: self._update_status(idx,'FAILED',message="ImageMagick not found"); continue
                    temp_png = Path(tempfile.gettempdir())/f"sanitized_{input_path.name}.png"
                    sanitize_cmd = [self.imagemagick_cmd, str(input_path), "-strip", str(temp_png)]
                    result = subprocess.run(sanitize_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
                    self._log_debug(f"Sanitize Result: code={result.returncode}, stderr={result.stderr.strip()}")
                    if result.returncode!=0 or not temp_png.exists() or temp_png.stat().st_size==0:
                        self._update_status(idx,'FAILED',message="Sanitize failed"); temp_png.unlink(missing_ok=True); continue
                    source_file_for_cjxl = temp_png
                else: source_file_for_cjxl = input_path

                self._update_status(idx,'CONVERTING')

                cmd = [self.cjxl_cmd, str(source_file_for_cjxl), str(target_path), "--effort", str(self.effort)]
                is_jpeg = input_path.suffix.lower() in ['.jpg','.jpeg']

                if is_jpeg and not use_sanitize:
                    lossless_cmd = cmd + ['--lossless_jpeg', '1', '--quiet']
                    self._log_debug(f"Executing lossless: {lossless_cmd}")
                    result=subprocess.run(lossless_cmd,capture_output=True,text=True, encoding='utf-8', errors='ignore')
                    self._log_debug(f"Lossless Result: code={result.returncode}, stderr={result.stderr.strip()}")
                    if result.returncode!=0:
                        self._log_debug("Lossless failed, falling back to quality.")
                        quality_cmd = cmd + ['-q', str(self.quality),'--quiet']
                        self._log_debug(f"Executing quality: {quality_cmd}")
                        result=subprocess.run(quality_cmd, capture_output=True,text=True, encoding='utf-8', errors='ignore')
                        self._log_debug(f"Quality Result: code={result.returncode}, stderr={result.stderr.strip()}")
                else:
                    quality_cmd = cmd + ['--lossless_jpeg', '0', '-q', str(self.quality),'--quiet']
                    self._log_debug(f"Executing quality (non-JPEG/sanitized): {quality_cmd}")
                    result = subprocess.run(quality_cmd,capture_output=True,text=True, encoding='utf-8', errors='ignore')
                    self._log_debug(f"Quality Result: code={result.returncode}, stderr={result.stderr.strip()}")

                if use_sanitize: source_file_for_cjxl.unlink(missing_ok=True)
                if result.returncode == 0 and target_path.exists():
                    shutil.copystat(input_path, target_path)
                    self._update_status(idx,'SUCCESS',size_before=input_path.stat().st_size,size_after=target_path.stat().st_size)
                    if self.delete_originals:
                        try: input_path.unlink()
                        except OSError: pass
                else:
                    error_msg = result.stderr.strip().splitlines()[-1] if result.stderr else "cjxl error"
                    self._update_status(idx,'FAILED',message=error_msg); target_path.unlink(missing_ok=True)
            except queue.Empty: continue
            except Exception as e:
                self._log_debug(f"WORKER CRASH: {e}")
                if 'idx' in locals(): self._update_status(idx,'FAILED',message=f"Worker crash: {type(e).__name__}")

    def handle_input(self, key, visible_files):
        self.status_message = ""; h,w=self.stdscr.getmaxyx(); max_rows=h-5
        char_key = chr(key) if 32<=key<=126 else None

        if key in [curses.KEY_UP,ord('k')] and self.current_row>0: self.current_row-=1
        elif key in [curses.KEY_DOWN,ord('j')] and self.current_row<len(visible_files)-1: self.current_row+=1
        elif key == curses.KEY_PPAGE: self.current_row=max(0,self.current_row-max_rows)
        elif key == curses.KEY_NPAGE: self.current_row=min(len(visible_files)-1,self.current_row+max_rows)
        elif char_key=='g' and self.current_row>0: self.current_row=self.scroll_offset=0
        elif char_key=='G': self.current_row = len(visible_files)-1
        elif key == ord(' '):
            if self.current_row < len(visible_files):
                original_idx = visible_files[self.current_row][0]
                if original_idx in self.selected: self.selected.remove(original_idx)
                else: self.selected.add(original_idx)
        elif char_key=='a': self.selected = {idx for idx, path in visible_files}
        elif char_key=='A': self.selected.clear()
        elif key in [curses.KEY_ENTER,10]: self._start_conversion_session()
        elif key == curses.KEY_F5: self.load_files()
        elif char_key in ['F','f'] and self.failed_indices:
            self.show_only_failed = not self.show_only_failed; self.current_row = self.scroll_offset = 0
        elif char_key in ['B','b']:
            self.debug_enabled = not self.debug_enabled
            self.show_message(f"Debug logging {'ENABLED' if self.debug_enabled else 'DISABLED'}")
        elif char_key in ['Q','q']: self.set_quality()
        elif char_key in ['E','e']: self.set_effort()
        elif char_key in ['R','r']: self.recursive=not self.recursive; self.load_files()
        elif char_key in ['O','o']: self.set_output_dir()
        elif char_key in ['D','d']: self.delete_originals=not self.delete_originals

        if self.current_row<self.scroll_offset: self.scroll_offset=self.current_row
        if self.current_row>=self.scroll_offset+max_rows: self.scroll_offset=self.current_row-max_rows+1

    def set_quality(self):
        new_val = InputDialog(self.stdscr, "Quality (1-100)", self.quality).run()
        if new_val and new_val.isdigit() and 1<=int(new_val)<=100:
            self.quality=int(new_val); self.show_message(f"Quality set to {self.quality}")
        elif new_val is not None: self.show_message("Quality must be between 1 and 100.", 4)
    def set_effort(self):
        new_val = InputDialog(self.stdscr, "Effort (1-9)", self.effort).run()
        if new_val and new_val.isdigit() and 1<=int(new_val)<=9:
            self.effort=int(new_val); self.show_message(f"Effort set to {self.effort}")
        elif new_val is not None: self.show_message("Effort must be between 1 and 9.", 4)
    def set_output_dir(self):
        prompt = "Output Dir (blank=Same as Source)"; current = "" if self.output_dir is None else str(self.output_dir)
        new_val = InputDialog(self.stdscr, prompt, current).run()
        if new_val is not None:
            if not new_val.strip(): self.output_dir=None; self.show_message("Output set to same directory as source files.")
            else: self.output_dir=Path(new_val).expanduser().resolve(); self.show_message(f"Output directory set to {self.output_dir}")

    def show_message(self, msg, color=5): self.status_message = msg; self.status_message_color = color

    def run(self):
        curses.curs_set(0); self.stdscr.nodelay(True)
        if not self.cjxl_cmd: self.show_message("FATAL: cjxl not found in PATH. Install libjxl-tools.", 4)
        while True:
            # Collect all pending keys and keep only the last navigation key
            keys = []
            while True:
                key = self.stdscr.getch()
                if key == -1:
                    break
                keys.append(key)
            
            if keys: # Any user input clears the post-conversion summary.
                self.last_conversion_summary = ""
            
            # Process non-navigation keys first
            non_nav_keys = []
            last_nav_key = None
            
            for key in keys:
                if key in [curses.KEY_UP, ord('k'), curses.KEY_DOWN, ord('j'), 
                           curses.KEY_PPAGE, curses.KEY_NPAGE, ord('g'), ord('G')]:
                    last_nav_key = key  # Keep only the last navigation key
                else:
                    non_nav_keys.append(key)
            
            # Process all non-navigation keys
            for key in non_nav_keys:
                if key in [27, ord('q')] and not self.is_converting: 
                    return
                if key in [27, ord('q')] and self.is_converting and ConfirmationDialog(self.stdscr, "Still converting. Quit anyway?").run(): 
                    return
                
                visible_files_before_input = self.get_visible_files()
                self.handle_input(key, visible_files_before_input)
            
            # Process only the last navigation key if there was one
            if last_nav_key is not None:
                if last_nav_key in [27, ord('q')] and not self.is_converting: 
                    return
                if last_nav_key in [27, ord('q')] and self.is_converting and ConfirmationDialog(self.stdscr, "Still converting. Quit anyway?").run(): 
                    return
                
                visible_files_before_input = self.get_visible_files()
                self.handle_input(last_nav_key, visible_files_before_input)
            
            self._process_status_queue()
        
            visible_files = self.get_visible_files()
            if self.current_row >= len(visible_files): self.current_row = max(0, len(visible_files) - 1)
        
            self.stdscr.erase(); h,w=self.stdscr.getmaxyx()
            if h<10 or w<80: self.stdscr.addstr(0,0,"Terminal too small...")
            else: self.draw_header(h,w); self.draw_file_list(h,w,visible_files); self.draw_status_bar(h,w); self.draw_footer(h,w)
            self.stdscr.refresh(); time.sleep(0.02)

        self.stop_thread.set()
        if self.conversion_thread and self.conversion_thread.is_alive(): self.conversion_thread.join()

def main_wrapper(stdscr, args):
    try: JxlConverterTUI(stdscr, args.directory).run()
    except KeyboardInterrupt: pass
    except curses.error as e: curses.endwin(); print(f"A curses error occurred: {e}\nThis can happen if the terminal was resized too quickly.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TUI JXL Image Converter.")
    parser.add_argument('directory', nargs='?', default='.', help="The directory to process. Defaults to current directory.")
    args = parser.parse_args()
    if not Path(args.directory).is_dir(): print(f"Error: Directory not found at '{args.directory}'"); sys.exit(1)
    print("Launching TUI...")
    if not shutil.which("cjxl"):
        print("\n\033[1;33mWARNING: 'cjxl' command not found in your PATH.\033[0m")
        print("Please install libjxl-tools. On Debian/Ubuntu: sudo apt install libjxl-tools")
        input("Press Enter to attempt to continue anyway...")
    curses.wrapper(main_wrapper, args)