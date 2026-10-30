from pathlib import Path

from mkjxl.deps import find_cjxl, find_imagemagick, install_commands


def which_map(found: dict[str, str]):
    def which(name: str) -> str | None:
        return found.get(name)

    return which


def test_brew_command() -> None:
    commands = install_commands("darwin", which_map({"brew": "/opt/homebrew/bin/brew"}), euid=501)
    assert [(item.manager, item.command) for item in commands] == [
        ("Homebrew", "brew install jpeg-xl")
    ]


def test_linux_commands_include_sudo_for_a_normal_user() -> None:
    commands = install_commands(
        "linux",
        which_map(
            {
                "apt-get": "/usr/bin/apt-get",
                "dnf": "/usr/bin/dnf",
                "pacman": "/usr/bin/pacman",
                "zypper": "/usr/bin/zypper",
                "sudo": "/usr/bin/sudo",
            }
        ),
        euid=1000,
    )
    by_manager = {item.manager: item.command for item in commands}
    assert by_manager == {
        "apt": "sudo apt-get install -y libjxl-tools",
        "dnf": "sudo dnf install -y libjxl-utils",
        "pacman": "sudo pacman -S --noconfirm libjxl",
        "zypper": "sudo zypper --non-interactive install libjxl-tools",
    }


def test_root_apt_skips_sudo_and_prefers_apt_get() -> None:
    commands = install_commands(
        "linux",
        which_map({"apt-get": "apt-get", "apt": "apt", "sudo": "sudo"}),
        euid=0,
    )
    assert len(commands) == 1
    assert commands[0].command == "apt-get install -y libjxl-tools"


def test_windows_commands_skip_chocolatey() -> None:
    commands = install_commands(
        "win32",
        which_map({"winget": "winget", "scoop": "scoop", "choco": "choco"}),
        euid=0,
    )
    assert [item.manager for item in commands] == ["winget", "Scoop"]
    assert "libjxl.libjxl" in commands[0].command
    assert commands[1].command == "scoop install libjxl"


def test_no_package_manager() -> None:
    assert install_commands("linux", which_map({}), euid=1000) == []
    assert install_commands("darwin", which_map({}), euid=501) == []


def test_find_cjxl_prefers_env_then_path_then_extra_dir(tmp_path: Path) -> None:
    override = tmp_path / "from-env"
    override.write_text("x")
    on_path = tmp_path / "from-path"
    on_path.write_text("x")
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "cjxl").write_text("x")

    assert find_cjxl(
        env={"MKJXL_CJXL": str(override)},
        which=lambda _name: str(on_path),
        extra_dirs=[extra],
    ) == str(override)

    def path_which(name: str) -> str | None:
        return str(on_path) if name == "cjxl" else None

    assert find_cjxl(env={}, which=path_which, extra_dirs=[]) == str(on_path)
    assert find_cjxl(env={}, which=lambda _name: None, extra_dirs=[extra]) == str(extra / "cjxl")
    missing = tmp_path / "missing"
    assert (
        find_cjxl(env={"MKJXL_CJXL": str(missing)}, which=lambda _name: None, extra_dirs=[]) is None
    )


def test_windows_system_convert_is_not_imagemagick() -> None:
    system32 = r"C:\Windows\System32\convert.exe"
    magick = find_imagemagick(
        which=lambda name: system32 if name == "convert" else None,
        probe=lambda _command: "Microsoft Windows",
    )
    assert magick is None
    accepted = find_imagemagick(
        which=lambda name: system32 if name == "convert" else None,
        probe=lambda _command: "ImageMagick 7.1",
    )
    assert accepted == system32


def test_linux_convert_must_report_imagemagick() -> None:
    rejected = find_imagemagick(
        which=lambda name: "/usr/bin/convert" if name == "convert" else None,
        probe=lambda _command: "filesystem utility",
    )
    assert rejected is None


def test_magick_is_preferred() -> None:
    assert (
        find_imagemagick(
            which=lambda name: "/usr/bin/magick" if name == "magick" else "/usr/bin/convert",
            probe=lambda _command: "",
        )
        == "/usr/bin/magick"
    )
