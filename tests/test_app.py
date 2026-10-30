from pathlib import Path

from textual.widgets import Input

from mkjxl.app import MissingCjxlScreen, MkJxlApp
from mkjxl.convert import ConvertResult
from mkjxl.deps import InstallCommand


def _images(root: Path) -> Path:
    (root / "photo.jpg").write_bytes(b"jpeg")
    (root / "scan.png").write_bytes(b"png")
    nested = root / "sub"
    nested.mkdir()
    (nested / "nested.png").write_bytes(b"png")
    return root


def _app(root: Path, cjxl: str | None) -> MkJxlApp:
    binary = cjxl
    if binary is None:
        return MkJxlApp(root, cjxl=None)
    path = root / "fake-cjxl"
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    app = MkJxlApp(root, cjxl=str(path))
    app.output_dir = root / "out"
    return app


async def test_file_list_keys_and_quit(tmp_path: Path) -> None:
    app = _app(_images(tmp_path), "cjxl")
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        assert app.table.row_count == 2
        assert "photo.jpg" in str(app.table.get_cell("0", "file"))
        await pilot.press("r")
        await pilot.pause()
        assert app.recursive is True
        assert app.table.row_count == 3
        await pilot.press("space")
        await pilot.pause()
        assert str(app.table.get_cell("0", "sel")).strip() == "*"
        await pilot.press("a")
        await pilot.pause()
        assert app.selected == {0, 1, 2}
        await pilot.press("A")
        await pilot.pause()
        assert app.selected == set()
        await pilot.press("enter")
        await pilot.pause()
        assert "No files selected" in app.status_message
        await pilot.press("f5")
        await pilot.pause()
        assert "refreshed" in app.status_message
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("q")


async def test_small_terminal_still_starts(tmp_path: Path) -> None:
    app = _app(_images(tmp_path), "cjxl")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.table.row_count == 2
        await pilot.press("q")


async def test_missing_cjxl_screen_can_copy_a_command(tmp_path: Path) -> None:
    app = _app(tmp_path, None)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, MissingCjxlScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, MissingCjxlScreen)
        command = InstallCommand("Homebrew", "brew install jpeg-xl")
        app.push_screen(MissingCjxlScreen([command]))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, MissingCjxlScreen)
        assert screen.query_one("#cmd-0", Input).value == "brew install jpeg-xl"
        await pilot.click("#copy-0")
        await pilot.pause()
        assert screen.notice.startswith("Copied.")
        await pilot.press("escape")


async def test_conversion_updates_the_table(tmp_path: Path, monkeypatch) -> None:
    root = _images(tmp_path)
    app = _app(root, "cjxl")

    def fake(source: Path, target: Path, **kwargs: object) -> ConvertResult:
        del kwargs
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"jxl")
        return ConvertResult(True, "", source.stat().st_size, 3)

    monkeypatch.setattr("mkjxl.app.convert_image", fake)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        await pilot.press("space")
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause(0.05)
            if app.states[0].status == "SUCCESS":
                break
        else:
            raise AssertionError(app.status_message)
        assert (root / "out" / "photo.jxl").is_file()
        assert "1 ok" in app.status_message
        await pilot.press("q")


async def test_cancel_counts_the_files_not_started(tmp_path: Path, monkeypatch) -> None:
    root = _images(tmp_path)
    (root / "third.png").write_bytes(b"png")
    app = _app(root, "cjxl")
    seen = {"n": 0}

    def fake(source: Path, target: Path, cancel=None, **kwargs: object) -> ConvertResult:
        del kwargs
        seen["n"] += 1
        if cancel is not None:
            cancel.set()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"jxl")
        return ConvertResult(True, "", source.stat().st_size, 3)

    monkeypatch.setattr("mkjxl.app.convert_image", fake)
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause(0.05)
            if not app._converting and app._batch_done:
                break
        else:
            raise AssertionError(app.status_message)
        assert seen["n"] == 1
        assert app._batch_done == 3
        assert app._batch_ok == 1
        assert app._batch_cancelled == 2
        assert "2 cancelled" in app.status_message
        await pilot.press("q")
