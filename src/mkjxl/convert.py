"""Run cjxl, with an optional sanitize step first."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mkjxl.deps import find_imagemagick

JPEG_SUFFIXES = {".jpg", ".jpeg"}


def parse_quality(text: str) -> int | None:
    text = text.strip()
    if not text.isdigit():
        return None
    value = int(text)
    if 1 <= value <= 100:
        return value
    return None


def parse_effort(text: str) -> int | None:
    text = text.strip()
    if not text.isdigit():
        return None
    value = int(text)
    if 1 <= value <= 9:
        return value
    return None


@dataclass
class CommandResult:
    returncode: int
    stderr: str = ""
    cancelled: bool = False


@dataclass
class ConvertResult:
    ok: bool
    message: str = ""
    size_before: int = 0
    size_after: int = 0
    cancelled: bool = False


class SanitizeError(Exception):
    pass


class DebugLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.enabled = False
        self._lock = threading.Lock()

    def __call__(self, message: str) -> None:
        if not self.enabled:
            return
        stamp = datetime.now().isoformat(timespec="seconds")
        line = f"[{stamp}] {message}\n"
        try:
            with self._lock:
                new_file = not self.path.exists()
                with self.path.open("a", encoding="utf-8") as handle:
                    if new_file:
                        handle.write("mkjxl debug log\n\n")
                    handle.write(line)
        except OSError:
            self.enabled = False


def cjxl_commands(
    cjxl: str,
    source: Path,
    target: Path,
    quality: int,
    effort: int,
    *,
    lossless_jpeg: bool,
) -> list[list[str]]:
    """JPEG inputs try a lossless transcode first, then the quality setting."""
    base = [cjxl, str(source), str(target), "--effort", str(effort)]
    if lossless_jpeg:
        return [
            [*base, "--lossless_jpeg", "1", "--quiet"],
            [*base, "-q", str(quality), "--quiet"],
        ]
    return [[*base, "--lossless_jpeg", "0", "-q", str(quality), "--quiet"]]


def run_command(argv: list[str], cancel: threading.Event | None = None) -> CommandResult:
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return CommandResult(1, str(exc))
    while True:
        try:
            _stdout, stderr = proc.communicate(timeout=0.2)
            return CommandResult(proc.returncode or 0, stderr or "")
        except subprocess.TimeoutExpired:
            if cancel is None or not cancel.is_set():
                continue
            proc.terminate()
            try:
                _stdout, stderr = proc.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                _stdout, stderr = proc.communicate()
            code = proc.returncode if proc.returncode is not None else -1
            return CommandResult(code, stderr or "", cancelled=True)


Runner = Callable[[list[str], threading.Event | None], CommandResult]


def sanitize_available() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return find_imagemagick() is not None
    return True


def _sanitize_pillow(source: Path, dest: Path) -> None:
    from PIL import Image

    with Image.open(source) as image:
        image.load()
        if getattr(image, "n_frames", 1) > 1:
            image.seek(0)
        if image.mode == "P":
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        elif image.mode not in {"RGB", "RGBA", "L", "LA"}:
            image = image.convert("RGB")
        image.save(dest, format="PNG")


def sanitize_image(
    source: Path,
    dest: Path,
    runner: Runner,
    cancel: threading.Event | None = None,
) -> str:
    """Rewrite the image as a plain PNG. Returns 'pillow' or 'imagemagick'."""
    pillow_error = "Pillow could not read this image."
    try:
        _sanitize_pillow(source, dest)
        if dest.is_file() and dest.stat().st_size > 0:
            return "pillow"
    except Exception as exc:
        dest.unlink(missing_ok=True)
        pillow_error = f"{type(exc).__name__}: {exc}"
    else:
        dest.unlink(missing_ok=True)

    magick = find_imagemagick()
    if not magick:
        raise SanitizeError(f"{pillow_error} ImageMagick is not installed.")
    result = runner([magick, str(source), "-strip", str(dest)], cancel)
    if result.cancelled or (cancel is not None and cancel.is_set()):
        dest.unlink(missing_ok=True)
        raise SanitizeError("Cancelled")
    if result.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        detail = _last_line(result.stderr) or "ImageMagick failed"
        raise SanitizeError(detail)
    return "imagemagick"


def convert_image(
    source: Path,
    target: Path,
    *,
    cjxl: str,
    quality: int,
    effort: int,
    sanitize: bool,
    delete_original: bool,
    log: Callable[[str], None] | None = None,
    cancel: threading.Event | None = None,
    runner: Runner | None = None,
) -> ConvertResult:
    write = log or (lambda _message: None)
    run = runner or run_command
    temp_png: Path | None = None
    encode_source = source
    try:
        if cancel is not None and cancel.is_set():
            return ConvertResult(False, "Cancelled", cancelled=True)
        if sanitize:
            handle = tempfile.NamedTemporaryFile(prefix="mkjxl-", suffix=".png", delete=False)
            temp_png = Path(handle.name)
            handle.close()
            write(f"SANITIZE {source}")
            try:
                backend = sanitize_image(source, temp_png, run, cancel)
            except SanitizeError as exc:
                if str(exc) == "Cancelled":
                    return ConvertResult(False, "Cancelled", cancelled=True)
                return ConvertResult(False, str(exc))
            write(f"SANITIZE via {backend}")
            encode_source = temp_png

        target.parent.mkdir(parents=True, exist_ok=True)
        lossless = source.suffix.lower() in JPEG_SUFFIXES and not sanitize
        commands = cjxl_commands(
            cjxl,
            encode_source,
            target,
            quality,
            effort,
            lossless_jpeg=lossless,
        )
        last = CommandResult(1, "cjxl failed")
        for index, command in enumerate(commands):
            if cancel is not None and cancel.is_set():
                target.unlink(missing_ok=True)
                return ConvertResult(False, "Cancelled", cancelled=True)
            write("RUN " + " ".join(command))
            last = run(command, cancel)
            write(f"EXIT {last.returncode} {last.stderr.strip()}")
            if last.cancelled:
                target.unlink(missing_ok=True)
                return ConvertResult(False, "Cancelled", cancelled=True)
            if last.returncode == 0 and target.is_file() and target.stat().st_size > 0:
                break
            target.unlink(missing_ok=True)
            if index < len(commands) - 1:
                write("Lossless JPEG failed, trying quality.")
        else:
            return ConvertResult(False, _short(_last_line(last.stderr) or "cjxl failed"))

        try:
            shutil.copystat(source, target)
        except OSError:
            pass
        before = source.stat().st_size if source.exists() else 0
        after = target.stat().st_size
        if delete_original:
            try:
                source.unlink()
            except OSError as exc:
                write(f"DELETE FAILED {exc}")
        return ConvertResult(True, "", before, after)
    except Exception as exc:
        target.unlink(missing_ok=True)
        write(f"ERROR {type(exc).__name__}: {exc}")
        return ConvertResult(False, _short(f"{type(exc).__name__}: {exc}"))
    finally:
        if temp_png is not None:
            temp_png.unlink(missing_ok=True)


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _short(text: str) -> str:
    if len(text) <= 80:
        return text
    return text[:79] + "..."
