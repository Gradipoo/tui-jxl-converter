from pathlib import Path

from mkjxl.cli import main


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

    monkeypatch.setattr("mkjxl.cli.MkJxlApp", FakeApp)
    assert main([str(tmp_path)]) == 0
    assert started["directory"] == tmp_path
    assert started["ran"] is True
