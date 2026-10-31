from pathlib import Path

from mkjxl.cli import main


class _Stdin:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_missing_directory(capsys) -> None:
    code = main(["/no/such/mkjxl-directory"])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_cli_starts_the_app(monkeypatch, tmp_path: Path) -> None:
    started: dict[str, object] = {}

    class FakeApp:
        def __init__(self, directory: Path) -> None:
            started["directory"] = directory

        def run(self) -> None:
            started["ran"] = True

    monkeypatch.setattr("mkjxl.cli.sys.stdin", _Stdin(True))
    monkeypatch.setattr("mkjxl.cli.MkJxlApp", FakeApp)
    assert main([str(tmp_path)]) == 0
    assert started["directory"] == tmp_path
    assert started["ran"] is True


def test_cli_refuses_a_non_tty(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr("mkjxl.cli.sys.stdin", _Stdin(False))

    def fail_run(self) -> None:
        raise AssertionError("run should not be called")

    monkeypatch.setattr("mkjxl.cli.MkJxlApp.run", fail_run)
    assert main([str(tmp_path)]) == 1
    assert capsys.readouterr().err == "Error: mkjxl needs a terminal.\n"
