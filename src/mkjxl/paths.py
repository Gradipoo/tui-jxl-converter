"""Image listing and output paths."""

from __future__ import annotations

import os
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".apng", ".tif", ".tiff"}


def list_images(root: Path, recursive: bool) -> list[Path]:
    """Return image files under root, sorted by relative path."""
    iterator = root.rglob("*") if recursive else root.glob("*")
    files: list[Path] = []
    for path in iterator:
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        files.append(path)
    files.sort(key=lambda item: item.relative_to(root).as_posix().lower())
    return files


def parse_output_dir(text: str) -> Path | None:
    """Blank means save each .jxl next to its source file."""
    stripped = text.strip()
    if not stripped:
        return None
    return Path(stripped).expanduser()


def target_directory(
    source: Path,
    source_root: Path,
    output_dir: Path | None,
    recursive: bool,
) -> Path:
    if output_dir is None:
        return source.parent
    if not recursive:
        return output_dir
    try:
        return output_dir / source.parent.relative_to(source_root)
    except ValueError:
        return output_dir


def path_key(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().absolute()))


def unique_target(source: Path, directory: Path, reserved: set[str]) -> Path:
    """Pick source.jxl, then source-1.jxl, and so on."""
    candidate = directory / f"{source.stem}.jxl"
    counter = 1
    while path_key(candidate) in reserved or candidate.exists():
        candidate = directory / f"{source.stem}-{counter}.jxl"
        counter += 1
    return candidate


def plan_targets(
    files: list[Path],
    indices: list[int],
    source_root: Path,
    output_dir: Path | None,
    recursive: bool,
) -> list[tuple[int, Path]]:
    """Plan output paths for a batch, including names already used in this batch."""
    reserved: set[str] = set()
    planned: list[tuple[int, Path]] = []
    for index in indices:
        source = files[index]
        directory = target_directory(source, source_root, output_dir, recursive)
        target = unique_target(source, directory, reserved)
        reserved.add(path_key(target))
        planned.append((index, target))
    return planned


def format_bytes(size: int) -> str:
    sign = "-" if size < 0 else ""
    value = float(abs(size))
    units = ("B", "KB", "MB", "GB", "TB")
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{sign}{int(value)} B"
    return f"{sign}{value:.1f} {unit}"


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def savings_text(before: int, after: int) -> str:
    if before <= 0:
        return ""
    saved = before - after
    percent = saved / before * 100
    return f"{format_bytes(saved)} saved ({percent:.1f}%)"


def display_path(path: Path, max_len: int = 48) -> str:
    text = str(path)
    home = str(Path.home())
    if text == home or text.startswith(home + os.sep):
        text = "~" + text[len(home) :]
    if len(text) <= max_len:
        return text
    return "..." + text[-(max_len - 3) :]
