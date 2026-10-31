"""Textual interface for batch JPEG XL conversion."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Static,
)
from textual.widgets._data_table import CellDoesNotExist

from mkjxl.convert import (
    ConvertResult,
    DebugLog,
    convert_image,
    parse_effort,
    parse_quality,
    sanitize_available,
)
from mkjxl.deps import InstallCommand, find_cjxl, install_commands
from mkjxl.paths import (
    display_path,
    format_bytes,
    format_elapsed,
    list_images,
    parse_output_dir,
    plan_targets,
    savings_text,
    target_directory,
)

_AUTO = object()


def linux_stdin_deleted() -> bool:
    """True when Linux reports that the terminal device for stdin is gone."""
    if sys.platform != "linux":
        return False
    try:
        fd = sys.__stdin__.fileno()
        if not os.isatty(fd):
            return False
        target = os.readlink(f"/proc/self/fd/{fd}")
    except (OSError, ValueError):
        return False
    return target.endswith(" (deleted)")


HELP_TEXT = """\
Navigation
  Up/Down or j/k     Move
  g / G              Top / bottom
  PageUp / PageDown  Page

Files
  Space or click     Select or clear the current file
  a / A              Select all / select none
  Enter              Convert the selected files
  f                  Show failed files only
  F5                 Refresh the list

Settings
  Q                  Quality (1-100)
  E                  Effort (1-9)
  r                  Recursive
  d                  Delete originals
  o                  Output directory
  b                  Debug log
  S                  Sanitize failed files

Other
  s                  cjxl install command
  ?                  This help
  q                  Quit
"""

STATUS_STYLE = {
    "PENDING": "dim",
    "SELECTED": "yellow",
    "QUEUED": "cyan",
    "CONVERTING": "yellow",
    "SANITIZING": "yellow",
    "SUCCESS": "green",
    "FAILED": "red",
    "CANCELLED": "dim",
}


class FileState:
    def __init__(self) -> None:
        self.status = "PENDING"
        self.info = ""
        self.target: Path | None = None


class FileTable(DataTable):
    BINDINGS = [
        Binding("enter", "app.convert", "Convert"),
        Binding("space", "app.toggle_select", "Select"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g", "scroll_top", show=False),
        Binding("G", "scroll_bottom", show=False),
    ]

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id, cursor_type="row", zebra_stripes=True)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "answer(True)", show=False),
        Binding("n,escape,q", "answer(False)", show=False),
    ]

    def __init__(
        self,
        question: str,
        *,
        yes_label: str = "Yes",
        no_label: str = "No",
        danger: bool = False,
        focus_yes: bool = False,
    ) -> None:
        super().__init__()
        self.question = question
        self.yes_label = yes_label
        self.no_label = no_label
        self.danger = danger
        self.focus_yes = focus_yes

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self.question, id="confirm-question")
            yield Button(self.yes_label, id="yes", variant="error" if self.danger else "primary")
            yield Button(self.no_label, id="no")

    def on_mount(self) -> None:
        self.query_one("#yes" if self.focus_yes else "#no", Button).focus()

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        elif event.button.id == "no":
            self.dismiss(False)


class MissingCjxlScreen(ModalScreen[None]):
    """Shows the install command. Does not run it."""

    BINDINGS = [Binding("escape,q", "dismiss_setup", show=False)]

    def __init__(self, commands: list[InstallCommand]) -> None:
        super().__init__()
        self.commands = commands
        self.notice = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="setup-dialog"):
            yield Static("cjxl was not found", id="setup-title")
            yield Static(
                "mkjxl needs the cjxl encoder from libjxl. "
                "Copy a command below, run it in a terminal, then press s to look again."
            )
            if not self.commands:
                yield Static(
                    "No supported package manager was found on PATH "
                    "(Homebrew, apt, dnf, pacman, zypper, winget, Scoop)."
                )
            for index, command in enumerate(self.commands):
                yield Label(command.manager)
                with Horizontal(classes="copy-row"):
                    yield Input(command.command, id=f"cmd-{index}", select_on_focus=True)
                    yield Button("Copy", id=f"copy-{index}")
            yield Static("", id="setup-status")
            yield Button("Not now", id="dismiss")

    def on_mount(self) -> None:
        if self.commands:
            self.query_one("#cmd-0", Input).focus()
        else:
            self.query_one("#dismiss", Button).focus()

    def action_dismiss_setup(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "dismiss":
            self.dismiss(None)
            return
        if not button_id.startswith("copy-"):
            return
        index = int(button_id.removeprefix("copy-"))
        self.app.copy_to_clipboard(self.commands[index].command)
        self.notice = "Copied. If paste is empty, select the command and copy it from the terminal."
        self.query_one("#setup-status", Static).update(self.notice)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,question_mark", "close_help", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static("Keys", id="help-title")
            yield Static(HELP_TEXT, id="help-body")
            yield Button("Close", id="close-help")

    def action_close_help(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-help":
            self.dismiss(None)


class MkJxlApp(App):
    TITLE = "mkjxl"
    SUB_TITLE = "JPEG XL"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    #paths {
        height: 1;
        background: $boost;
        color: $text-muted;
        padding: 0 1;
    }
    #body {
        height: 1fr;
    }
    #file-pane {
        border: round $primary;
        width: 1fr;
        height: 1fr;
    }
    #files {
        height: 1fr;
    }
    #progress-row {
        height: 1;
        padding: 0 1;
    }
    #progress {
        width: 20;
        height: 1;
    }
    #progress-label {
        width: 1fr;
        height: 1;
        padding: 0 1;
    }
    #settings {
        border: round $accent;
        width: 42;
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }
    #settings Label {
        height: 1;
        margin-top: 1;
        color: $text-muted;
    }
    #settings Checkbox {
        height: 1;
    }
    #cjxl {
        height: 2;
        margin-top: 1;
    }
    #cjxl.ready {
        color: $success;
    }
    #cjxl.missing {
        color: $error;
    }
    #action-row {
        height: auto;
        margin-top: 1;
    }
    #action-row Button {
        margin-right: 1;
    }
    #sanitize {
        margin-top: 1;
    }
    #status {
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    ConfirmScreen, MissingCjxlScreen, HelpScreen {
        align: center middle;
    }
    #confirm-dialog, #setup-dialog, #help-dialog {
        width: 78;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        background: $panel;
        border: round $primary;
        overflow-y: auto;
    }
    #confirm-question, #help-body {
        height: auto;
    }
    #setup-title, #help-title {
        text-style: bold;
        height: 1;
    }
    #confirm-dialog Button, #setup-dialog Button, #help-dialog Button {
        margin-top: 1;
    }
    .copy-row {
        height: 3;
    }
    .copy-row Input {
        width: 1fr;
    }
    .copy-row Button {
        width: 12;
        margin-left: 1;
        margin-top: 0;
    }
    """
    BINDINGS = [
        Binding("a", "select_all", "All"),
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        Binding("r", "toggle_recursive", "Recursive"),
        Binding("f5", "refresh_files", "Refresh"),
        Binding("s", "setup", "cjxl"),
        Binding("A", "select_none", "None", show=False),
        Binding("d", "toggle_delete", "Delete", show=False),
        Binding("o", "focus_output", "Output", show=False),
        Binding("f", "toggle_failed", "Failed", show=False),
        Binding("b", "toggle_debug", "Debug", show=False),
        Binding("Q", "focus_quality", "Quality", show=False),
        Binding("E", "focus_effort", "Effort", show=False),
        Binding("S", "sanitize", "Sanitize", show=False),
        Binding("escape", "focus_files", show=False),
        Binding("up,k", "cursor_up", show=False),
        Binding("down,j", "cursor_down", show=False),
        Binding("pageup", "page_up", show=False),
        Binding("pagedown", "page_down", show=False),
        Binding("home,g", "go_top", show=False),
        Binding("end,G", "go_bottom", show=False),
    ]

    def __init__(self, directory: Path, cjxl: str | None | object = _AUTO) -> None:
        super().__init__()
        self.theme = "nord"
        self.directory = Path(directory).resolve()
        self._autodetect = cjxl is _AUTO
        resolved: str | None
        if cjxl is _AUTO:
            resolved = find_cjxl()
        elif isinstance(cjxl, str):
            resolved = cjxl
        else:
            resolved = None
        self.cjxl = resolved
        self.quality = 90
        self.effort = 7
        self.output_dir: Path | None = Path("converted")
        self.recursive = False
        self.delete_originals = False
        self.show_failed_only = False
        self.files: list[Path] = []
        self.states: list[FileState] = []
        self.selected: set[int] = set()
        self.failed: set[int] = set()
        self.debug_log = DebugLog(Path.cwd() / "jxl_converter_debug.txt")
        self.status_message = ""
        self._converting = False
        self._cancel = threading.Event()
        self._batch_total = 0
        self._batch_done = 0
        self._batch_ok = 0
        self._batch_failed = 0
        self._batch_cancelled = 0
        self._bytes_before = 0
        self._bytes_after = 0
        self._batch_started = 0.0
        self._batch_sanitize = False

    def format_title(self, title: str, sub_title: str) -> Content:
        if sub_title:
            return Content.assemble(title, (" | ", "dim"), sub_title)
        return Content(title)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="paths")
        with Horizontal(id="body"):
            with Vertical(id="file-pane"):
                yield FileTable(id="files")
                with Horizontal(id="progress-row"):
                    yield ProgressBar(
                        id="progress",
                        total=1,
                        show_eta=False,
                        show_percentage=False,
                    )
                    yield Static("", id="progress-label")
            with Vertical(id="settings"):
                yield Label("Quality (1-100)")
                yield Input(value="90", id="quality", type="integer", compact=True)
                yield Label("Effort (1-9)")
                yield Input(value="7", id="effort", type="integer", compact=True)
                yield Label("Output directory")
                yield Input(
                    value="" if self.output_dir is None else str(self.output_dir),
                    id="output",
                    placeholder="blank = next to each source file",
                    compact=True,
                )
                yield Checkbox("Recursive", id="recursive", compact=True)
                yield Checkbox(
                    "Delete originals after success",
                    id="delete",
                    compact=True,
                    tooltip="Asks before converting. Only a successful convert deletes the source.",
                )
                yield Checkbox("Debug log", id="debug", compact=True)
                yield Checkbox("Show failed only", id="failed", compact=True)
                yield Static("", id="cjxl")
                with Horizontal(id="action-row"):
                    yield Button("Convert", id="convert", variant="success")
                    yield Button("Refresh", id="refresh")
                yield Button("Sanitize failed", id="sanitize", disabled=True)
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.table
        table.add_column("Sel", key="sel", width=5)
        table.add_column("File", key="file")
        table.add_column("Target", key="target")
        table.add_column("Status", key="status", width=12)
        table.add_column("Info", key="info")
        self.query_one("#file-pane").border_title = "Images"
        self.query_one("#settings").border_title = "Settings"
        self.query_one("#progress-row").display = False
        self._load_files()
        self._refresh_paths()
        self._update_cjxl_label()
        self._apply_layout(self.size.width)
        self.set_interval(0.5, self._tick)
        table.focus()
        if not self.cjxl:
            self.action_setup()

    def on_resize(self, event: events.Resize) -> None:
        if self.is_mounted:
            self._apply_layout(event.size.width)

    def _apply_layout(self, width: int) -> None:
        body = self.query_one("#body")
        settings = self.query_one("#settings")
        if width < 100:
            body.styles.layout = "vertical"
            settings.styles.width = "100%"
            settings.styles.height = "auto"
            settings.styles.max_height = 16
        else:
            body.styles.layout = "horizontal"
            settings.styles.width = 42
            settings.styles.height = "1fr"
            settings.styles.max_height = "100%"

    @property
    def table(self) -> FileTable:
        return self.query_one("#files", FileTable)

    def _set_status(self, message: str) -> None:
        self.status_message = message
        status = self.query_one("#status", Static)
        status.update(message)

    def _tick(self) -> None:
        if linux_stdin_deleted():
            self.exit()
            return
        if self._converting:
            self._render_progress()

    def _load_files(self) -> None:
        self.files = list_images(self.directory, self.recursive)
        self.states = [FileState() for _path in self.files]
        self.selected.clear()
        self.failed.clear()
        self._rebuild_table()
        self._sync_sanitize_button()
        if not self.files:
            self._set_status(
                "No images in this folder. Toggle recursive, or press F5 after adding files."
            )

    def _visible_indices(self) -> list[int]:
        if self.show_failed_only:
            return sorted(self.failed)
        return list(range(len(self.files)))

    def _current_index(self) -> int | None:
        table = self.table
        if table.row_count == 0:
            return None
        row_key, _column = table.coordinate_to_cell_key(table.cursor_coordinate)
        if row_key.value is None:
            return None
        try:
            return int(row_key.value)
        except ValueError:
            return None

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.directory).as_posix()
        except ValueError:
            return path.name

    def _preview_target(self, index: int) -> Path:
        source = self.files[index]
        directory = target_directory(source, self.directory, self.output_dir, self.recursive)
        return directory / f"{source.stem}.jxl"

    def _target_label(self, index: int) -> str:
        path = self.states[index].target or self._preview_target(index)
        if self.output_dir is not None:
            try:
                return path.relative_to(self.output_dir).as_posix()
            except ValueError:
                return path.name
        return path.name

    def _display_status(self, index: int) -> str:
        status = self.states[index].status
        if index in self.selected and status == "PENDING":
            return "SELECTED"
        return status

    def _status_text(self, index: int) -> Text:
        label = self._display_status(index)
        return Text(label, style=STATUS_STYLE.get(label, ""))

    def _sel(self, index: int) -> str:
        return "*" if index in self.selected else ""

    def _rebuild_table(self) -> None:
        previous = self._current_index()
        table = self.table
        table.clear()
        visible = self._visible_indices()
        for index in visible:
            table.add_row(
                self._sel(index),
                self._relative(self.files[index]),
                self._target_label(index),
                self._status_text(index),
                self.states[index].info,
                key=str(index),
            )
        if previous in visible:
            table.move_cursor(row=visible.index(previous))

    def _paint_row(self, index: int) -> None:
        try:
            self.table.update_cell(str(index), "sel", self._sel(index))
            self.table.update_cell(str(index), "target", self._target_label(index))
            self.table.update_cell(str(index), "status", self._status_text(index))
            self.table.update_cell(str(index), "info", self.states[index].info)
        except CellDoesNotExist:
            return

    def _update_row(self, index: int) -> None:
        if self.show_failed_only:
            self._rebuild_table()
        else:
            self._paint_row(index)

    def _refresh_paths(self) -> None:
        source = display_path(self.directory, 40)
        if self.output_dir is None:
            output = "next to each source file"
        else:
            output = display_path(self.output_dir, 40)
        extra = "    Failed only" if self.show_failed_only else ""
        self.query_one("#paths", Static).update(f" Source  {source}    Output  {output}{extra}")

    def _update_cjxl_label(self) -> None:
        label = self.query_one("#cjxl", Static)
        label.set_class(bool(self.cjxl), "ready")
        label.set_class(not self.cjxl, "missing")
        if self.cjxl:
            label.update(f"cjxl  {display_path(Path(self.cjxl), 36)}")
        else:
            label.update("cjxl not found. Press s for the install command.")

    def _refresh_target_cells(self) -> None:
        for index in self._visible_indices():
            self._paint_row(index)

    def _sync_sanitize_button(self) -> None:
        self.query_one("#sanitize", Button).disabled = self._converting or not self.failed

    def _set_converting(self, active: bool) -> None:
        self._converting = active
        self.query_one("#recursive", Checkbox).disabled = active
        self.query_one("#convert", Button).disabled = active
        self.query_one("#refresh", Button).disabled = active
        self._sync_sanitize_button()

    def _read_settings(self) -> bool:
        quality = parse_quality(self.query_one("#quality", Input).value)
        effort = parse_effort(self.query_one("#effort", Input).value)
        if quality is None:
            self._set_status("Quality must be a whole number from 1 to 100.")
            return False
        if effort is None:
            self._set_status("Effort must be a whole number from 1 to 9.")
            return False
        self.quality = quality
        self.effort = effort
        self.output_dir = parse_output_dir(self.query_one("#output", Input).value)
        return True

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        checkbox_id = event.checkbox.id
        if checkbox_id == "recursive":
            if self._converting:
                return
            self.recursive = event.value
            self._load_files()
        elif checkbox_id == "delete":
            self.delete_originals = event.value
            if event.value:
                self._set_status("Delete originals is on. You will be asked to confirm.")
        elif checkbox_id == "debug":
            self.debug_log.enabled = event.value
            if event.value:
                self._set_status(f"Debug log on: {self.debug_log.path}")
            else:
                self._set_status("Debug log off.")
        elif checkbox_id == "failed":
            self.show_failed_only = event.value
            self._rebuild_table()
            self._refresh_paths()
            if event.value and not self.failed:
                self._set_status("No failed files yet.")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "output":
            return
        self.output_dir = parse_output_dir(event.value)
        self._refresh_paths()
        self._refresh_target_cells()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id in {"quality", "effort", "output"}:
            self._read_settings()
            self.table.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "convert":
            self.action_convert()
        elif button_id == "refresh":
            self.action_refresh_files()
        elif button_id == "sanitize":
            self.action_sanitize()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value is None:
            return
        self._toggle_index(int(event.row_key.value))

    def _toggle_index(self, index: int) -> None:
        if index in self.selected:
            self.selected.remove(index)
        else:
            self.selected.add(index)
        self._update_row(index)

    def action_toggle_select(self) -> None:
        index = self._current_index()
        if index is not None:
            self._toggle_index(index)

    def action_select_all(self) -> None:
        self.selected.update(self._visible_indices())
        self._rebuild_table()

    def action_select_none(self) -> None:
        self.selected.clear()
        self._rebuild_table()

    def action_toggle_recursive(self) -> None:
        if self._converting:
            self._set_status("Wait for the current conversion to finish.")
            return
        box = self.query_one("#recursive", Checkbox)
        box.value = not box.value

    def action_toggle_delete(self) -> None:
        box = self.query_one("#delete", Checkbox)
        box.value = not box.value

    def action_toggle_debug(self) -> None:
        box = self.query_one("#debug", Checkbox)
        box.value = not box.value

    def action_toggle_failed(self) -> None:
        if not self.failed and not self.show_failed_only:
            self._set_status("No failed files yet.")
            return
        box = self.query_one("#failed", Checkbox)
        box.value = not box.value

    def action_focus_output(self) -> None:
        self.query_one("#output", Input).focus()

    def action_focus_quality(self) -> None:
        self.query_one("#quality", Input).focus()

    def action_focus_effort(self) -> None:
        self.query_one("#effort", Input).focus()

    def action_focus_files(self) -> None:
        if isinstance(self.screen, (ConfirmScreen, MissingCjxlScreen, HelpScreen)):
            return
        self.table.focus()

    def action_cursor_up(self) -> None:
        self.table.action_cursor_up()

    def action_cursor_down(self) -> None:
        self.table.action_cursor_down()

    def action_page_up(self) -> None:
        self.table.action_page_up()

    def action_page_down(self) -> None:
        self.table.action_page_down()

    def action_go_top(self) -> None:
        self.table.action_scroll_top()

    def action_go_bottom(self) -> None:
        self.table.action_scroll_bottom()

    def action_help(self) -> None:
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen())

    def action_refresh_files(self) -> None:
        if self._converting:
            self._set_status("Wait for the current conversion to finish.")
            return
        self._load_files()
        self._set_status("File list refreshed.")

    def action_setup(self) -> None:
        if isinstance(self.screen, MissingCjxlScreen):
            return
        if self._autodetect:
            self.cjxl = find_cjxl()
        if self.cjxl:
            self._update_cjxl_label()
            self._set_status(f"cjxl found: {self.cjxl}")
            return
        self._update_cjxl_label()
        self.push_screen(MissingCjxlScreen(install_commands()))

    def action_quit(self) -> None:
        if self._converting:
            self.push_screen(
                ConfirmScreen("A conversion is still running. Quit anyway?"),
                self._quit_if,
            )
            return
        self._cancel.set()
        self.exit()

    def _quit_if(self, yes: bool | None) -> None:
        if yes:
            self._cancel.set()
            self.exit()

    def on_unmount(self) -> None:
        self._cancel.set()

    def action_convert(self) -> None:
        if self._converting:
            self._set_status("A conversion is already running.")
            return
        if not self._read_settings():
            return
        if not self.selected:
            self._set_status("No files selected.")
            return
        if not self.cjxl:
            self.action_setup()
            return
        if self.delete_originals:
            self.push_screen(
                ConfirmScreen(
                    "Delete originals is on. Convert and delete the source files?",
                    yes_label="Convert and delete",
                    no_label="Cancel",
                    danger=True,
                ),
                self._convert_if_confirmed,
            )
            return
        self._start_batch(False)

    def _convert_if_confirmed(self, yes: bool | None) -> None:
        if yes:
            self._start_batch(False)
        else:
            self._set_status("Conversion cancelled.")

    def action_sanitize(self) -> None:
        if self._converting:
            self._set_status("A conversion is already running.")
            return
        if not self.failed:
            self._set_status("No failed files to sanitize.")
            return
        if not sanitize_available():
            self._set_status("Sanitize needs Pillow or ImageMagick.")
            return
        if not self.cjxl:
            self.action_setup()
            return
        if self.delete_originals:
            self.push_screen(
                ConfirmScreen(
                    "Delete originals is on. Sanitize, convert, and delete the source files?",
                    yes_label="Sanitize and delete",
                    no_label="Cancel",
                    danger=True,
                ),
                self._sanitize_if_confirmed,
            )
            return
        self._start_batch(True)

    def _sanitize_if_confirmed(self, yes: bool | None) -> None:
        if yes:
            self._start_batch(True)
        else:
            self._set_status("Sanitize cancelled.")

    def _start_batch(self, sanitize: bool) -> None:
        if not self._read_settings():
            return
        indices = sorted(self.failed if sanitize else self.selected)
        if not indices:
            self._set_status("No failed files to sanitize." if sanitize else "No files selected.")
            return
        if not self.cjxl:
            self.action_setup()
            return
        planned = plan_targets(self.files, indices, self.directory, self.output_dir, self.recursive)
        items = [(index, self.files[index], target) for index, target in planned]
        self._cancel = threading.Event()
        self._batch_total = len(items)
        self._batch_done = 0
        self._batch_ok = 0
        self._batch_failed = 0
        self._batch_cancelled = 0
        self._bytes_before = 0
        self._bytes_after = 0
        self._batch_started = time.monotonic()
        self._batch_sanitize = sanitize
        for index, _source, target in items:
            self.states[index].target = target
            self.states[index].status = "QUEUED"
            self.states[index].info = ""
            self.failed.discard(index)
        if self.show_failed_only:
            self._rebuild_table()
        else:
            for index, _source, _target in items:
                self._paint_row(index)
        self._set_converting(True)
        self.query_one("#progress-row").display = True
        self._render_progress()
        self.debug_log(
            f"--- batch of {len(items)} files, sanitize={sanitize}, "
            f"q={self.quality}, e={self.effort} ---"
        )
        self._run_batch(
            items,
            sanitize,
            self.quality,
            self.effort,
            self.delete_originals,
            self.cjxl,
        )

    @work(thread=True, exclusive=True, group="convert", exit_on_error=False)
    def _run_batch(
        self,
        items: list[tuple[int, Path, Path]],
        sanitize: bool,
        quality: int,
        effort: int,
        delete_original: bool,
        cjxl: str,
    ) -> None:
        cancelled = False
        try:
            for index, source, target in items:
                if self._cancel.is_set():
                    cancelled = True
                    self.call_from_thread(
                        self._on_result,
                        index,
                        ConvertResult(False, "Cancelled", cancelled=True),
                    )
                    continue
                phase = "SANITIZING" if sanitize else "CONVERTING"
                self.call_from_thread(self._mark, index, phase, "")
                result = convert_image(
                    source,
                    target,
                    cjxl=cjxl,
                    quality=quality,
                    effort=effort,
                    sanitize=sanitize,
                    delete_original=delete_original,
                    log=self.debug_log,
                    cancel=self._cancel,
                )
                if result.cancelled:
                    cancelled = True
                self.call_from_thread(self._on_result, index, result)
        except Exception as exc:
            self.call_from_thread(self._set_status, f"Conversion stopped: {exc}")
        self.call_from_thread(self._batch_finished, cancelled)

    def _mark(self, index: int, status: str, info: str) -> None:
        if not self.is_running or index >= len(self.states):
            return
        self.states[index].status = status
        if info:
            self.states[index].info = info
        self._update_row(index)

    def _on_result(self, index: int, result: ConvertResult) -> None:
        if not self.is_running or index >= len(self.states):
            return
        self._batch_done += 1
        if result.cancelled:
            self._batch_cancelled += 1
            self.states[index].status = "CANCELLED"
            self.states[index].info = "Cancelled"
        elif result.ok:
            self._batch_ok += 1
            self._bytes_before += result.size_before
            self._bytes_after += result.size_after
            self.states[index].status = "SUCCESS"
            self.states[index].info = savings_text(result.size_before, result.size_after)
            self.failed.discard(index)
        else:
            self._batch_failed += 1
            self.states[index].status = "FAILED"
            self.states[index].info = result.message or "Failed"
            self.failed.add(index)
        self._update_row(index)
        self._render_progress()
        self._sync_sanitize_button()

    def _render_progress(self) -> None:
        elapsed = time.monotonic() - self._batch_started if self._batch_started else 0
        saved = self._bytes_before - self._bytes_after
        label = (
            f"{self._batch_done}/{self._batch_total}    "
            f"saved {format_bytes(saved)}    {format_elapsed(elapsed)}"
        )
        self.query_one("#progress-label", Static).update(label)
        self.query_one("#progress", ProgressBar).update(
            total=max(self._batch_total, 1),
            progress=self._batch_done,
        )

    def _summary(self, elapsed: float) -> str:
        saved = self._bytes_before - self._bytes_after
        saved_text = ""
        if self._bytes_before > 0:
            percent = saved / self._bytes_before * 100
            saved_text = f" Saved {format_bytes(saved)} ({percent:.1f}%)."
        cancelled_text = f" {self._batch_cancelled} cancelled." if self._batch_cancelled else ""
        return (
            f"Finished {self._batch_done} files in {elapsed:.1f}s. "
            f"{self._batch_ok} ok, {self._batch_failed} failed.{cancelled_text}{saved_text}"
        )

    def _batch_finished(self, cancelled: bool) -> None:
        if not self.is_running:
            return
        self._set_converting(False)
        elapsed = time.monotonic() - self._batch_started
        summary = self._summary(elapsed)
        self._set_status(summary)
        self._render_progress()
        if cancelled or self._batch_sanitize or not self.failed:
            return
        if not sanitize_available():
            self._set_status(summary + " Pillow and ImageMagick are both unavailable.")
            return
        count = len(self.failed)
        noun = "file" if count == 1 else "files"
        if self.delete_originals:
            question = f"{count} {noun} failed. Sanitize, retry, and delete the originals?"
        else:
            question = f"{count} {noun} failed. Sanitize and retry them now?"
        self.push_screen(
            ConfirmScreen(
                question,
                yes_label="Sanitize and retry",
                no_label="Not now",
                focus_yes=True,
            ),
            self._retry_if_confirmed,
        )

    def _retry_if_confirmed(self, yes: bool | None) -> None:
        if yes:
            self._start_batch(True)
