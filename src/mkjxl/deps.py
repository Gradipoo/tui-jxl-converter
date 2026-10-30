"""Find cjxl and the install command for this machine.

The app does not install anything. It only prints a command the user can copy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Which = Callable[[str], str | None]


@dataclass(frozen=True)
class InstallCommand:
    manager: str
    command: str


def install_commands(
    system: str | None = None,
    which: Which | None = None,
    euid: int | None = None,
) -> list[InstallCommand]:
    """Commands for package managers that are actually on PATH."""
    system = sys.platform if system is None else system
    which = shutil.which if which is None else which
    if euid is None:
        euid = 0 if system == "win32" else os.geteuid()

    if system == "darwin":
        if which("brew"):
            return [InstallCommand("Homebrew", "brew install jpeg-xl")]
        return []

    if system == "win32":
        commands: list[InstallCommand] = []
        if which("winget"):
            commands.append(
                InstallCommand(
                    "winget",
                    "winget install -e --id libjxl.libjxl "
                    "--accept-package-agreements --accept-source-agreements",
                )
            )
        if which("scoop"):
            commands.append(InstallCommand("Scoop", "scoop install libjxl"))
        return commands

    if system != "linux":
        return []

    sudo = "" if euid == 0 or not which("sudo") else "sudo "
    commands = []
    if which("apt-get"):
        commands.append(InstallCommand("apt", f"{sudo}apt-get install -y libjxl-tools"))
    elif which("apt"):
        commands.append(InstallCommand("apt", f"{sudo}apt install -y libjxl-tools"))
    if which("dnf"):
        commands.append(InstallCommand("dnf", f"{sudo}dnf install -y libjxl-utils"))
    if which("pacman"):
        commands.append(InstallCommand("pacman", f"{sudo}pacman -S --noconfirm libjxl"))
    if which("zypper"):
        commands.append(
            InstallCommand("zypper", f"{sudo}zypper --non-interactive install libjxl-tools")
        )
    return commands


def find_cjxl(
    env: dict[str, str] | None = None,
    which: Which | None = None,
    extra_dirs: list[Path] | None = None,
) -> str | None:
    """Return a cjxl path, or None.

    MKJXL_CJXL wins when that file exists. Then PATH. Then a few well known install dirs.
    """
    env = os.environ if env is None else env
    which = shutil.which if which is None else which
    override = env.get("MKJXL_CJXL")
    if override and Path(override).is_file():
        return override
    found = which("cjxl")
    if found:
        return found
    directories = _default_search_dirs() if extra_dirs is None else extra_dirs
    for directory in directories:
        hit = _search_dir(directory)
        if hit:
            return hit
    return None


def _default_search_dirs() -> list[Path]:
    directories: list[Path] = []
    if sys.platform == "darwin":
        directories.extend([Path("/opt/homebrew/bin"), Path("/usr/local/bin")])
    elif sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            directories.append(Path(local) / "Microsoft" / "WinGet" / "Links")
        directories.append(Path.home() / "scoop" / "shims")
    return directories


def _search_dir(directory: Path) -> str | None:
    if not directory.is_dir():
        return None
    names = ("cjxl.exe", "cjxl") if os.name == "nt" else ("cjxl", "cjxl.exe")
    for name in names:
        candidate = directory / name
        if candidate.is_file():
            return str(candidate)
    for pattern in ("bin/cjxl", "bin/cjxl.exe", "*/cjxl", "*/cjxl.exe"):
        for candidate in directory.glob(pattern):
            if candidate.is_file():
                return str(candidate)
    return None


def find_imagemagick(
    which: Which | None = None,
    probe: Callable[[str], str] | None = None,
) -> str | None:
    """Return magick, or a convert binary that reports itself as ImageMagick.

    Windows ships a convert.exe that is not ImageMagick. Other systems can too.
    """
    which = shutil.which if which is None else which
    magick = which("magick")
    if magick:
        return magick
    convert = which("convert")
    if not convert:
        return None
    if "imagemagick" not in str(convert).lower():
        text = _probe_version(convert) if probe is None else probe(convert)
        if "ImageMagick" not in text:
            return None
    return convert


def _probe_version(command: str) -> str:
    try:
        result = subprocess.run(
            [command, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return f"{result.stdout}\n{result.stderr}"
