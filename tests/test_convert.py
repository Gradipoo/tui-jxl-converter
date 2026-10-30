import threading
from pathlib import Path

from PIL import Image

from mkjxl.convert import (
    CommandResult,
    convert_image,
    parse_effort,
    parse_quality,
)


def _write_jxl(argv: list[str], cancel: threading.Event | None = None) -> CommandResult:
    del cancel
    Path(argv[2]).write_bytes(b"jxl-bytes")
    return CommandResult(0, "")


def test_parse_settings() -> None:
    assert parse_quality("90") == 90
    assert parse_quality("0") is None
    assert parse_quality("101") is None
    assert parse_quality("no") is None
    assert parse_effort("7") == 7
    assert parse_effort("10") is None


def test_jpeg_falls_back_to_quality(tmp_path: Path) -> None:
    source = tmp_path / "a.jpg"
    source.write_bytes(b"jpeg")
    target = tmp_path / "a.jxl"
    calls: list[list[str]] = []

    def runner(argv: list[str], cancel: threading.Event | None = None) -> CommandResult:
        del cancel
        calls.append(argv)
        if "--lossless_jpeg" in argv and argv[argv.index("--lossless_jpeg") + 1] == "1":
            return CommandResult(1, "lossless failed")
        Path(argv[2]).write_bytes(b"jxl-bytes")
        return CommandResult(0, "")

    result = convert_image(
        source,
        target,
        cjxl="cjxl",
        quality=80,
        effort=4,
        sanitize=False,
        delete_original=False,
        runner=runner,
    )
    assert result.ok
    assert calls[0][calls[0].index("--effort") + 1] == "4"
    assert "--lossless_jpeg" in calls[0]
    assert "-q" in calls[1]
    assert calls[1][calls[1].index("-q") + 1] == "80"


def test_png_uses_quality_once(tmp_path: Path) -> None:
    source = tmp_path / "a.png"
    source.write_bytes(b"png")
    target = tmp_path / "a.jxl"
    calls: list[list[str]] = []

    def runner(argv: list[str], cancel: threading.Event | None = None) -> CommandResult:
        del cancel
        calls.append(argv)
        return _write_jxl(argv)

    result = convert_image(
        source,
        target,
        cjxl="cjxl",
        quality=90,
        effort=7,
        sanitize=False,
        delete_original=False,
        runner=runner,
    )
    assert result.ok
    assert len(calls) == 1
    assert calls[0][calls[0].index("--lossless_jpeg") + 1] == "0"
    assert result.size_before == len(b"png")
    assert result.size_after == len(b"jxl-bytes")


def test_failure_removes_a_partial_target_and_delete_removes_the_source(tmp_path: Path) -> None:
    source = tmp_path / "a.png"
    source.write_bytes(b"png")
    target = tmp_path / "nested" / "a.jxl"

    def fail(argv: list[str], cancel: threading.Event | None = None) -> CommandResult:
        del cancel
        Path(argv[2]).write_bytes(b"partial")
        return CommandResult(1, "encoder exploded\nbad image")

    failed = convert_image(
        source,
        target,
        cjxl="cjxl",
        quality=90,
        effort=7,
        sanitize=False,
        delete_original=False,
        runner=fail,
    )
    assert not failed.ok
    assert failed.message == "bad image"
    assert not target.exists()

    deleted = convert_image(
        source,
        target,
        cjxl="cjxl",
        quality=90,
        effort=7,
        sanitize=False,
        delete_original=True,
        runner=_write_jxl,
    )
    assert deleted.ok
    assert target.is_file()
    assert not source.exists()


def test_cancel_before_start(tmp_path: Path) -> None:
    source = tmp_path / "a.png"
    source.write_bytes(b"png")
    cancel = threading.Event()
    cancel.set()
    result = convert_image(
        source,
        tmp_path / "a.jxl",
        cjxl="cjxl",
        quality=90,
        effort=7,
        sanitize=False,
        delete_original=False,
        cancel=cancel,
        runner=_write_jxl,
    )
    assert result.cancelled


def test_sanitize_uses_pillow_and_passes_a_png_to_cjxl(tmp_path: Path) -> None:
    source = tmp_path / "a.jpg"
    Image.new("RGB", (4, 4), "red").save(source)
    target = tmp_path / "a.jxl"
    seen: list[str] = []

    def runner(argv: list[str], cancel: threading.Event | None = None) -> CommandResult:
        del cancel
        seen.append(Path(argv[1]).suffix)
        return _write_jxl(argv)

    result = convert_image(
        source,
        target,
        cjxl="cjxl",
        quality=90,
        effort=7,
        sanitize=True,
        delete_original=False,
        runner=runner,
    )
    assert result.ok
    assert seen == [".png"]
    assert not list(tmp_path.glob("mkjxl-*.png"))


def test_sanitize_falls_back_to_imagemagick(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "a.png"
    source.write_bytes(b"not an image")
    target = tmp_path / "a.jxl"

    def broken_pillow(source_path: Path, dest: Path) -> None:
        del source_path, dest
        raise OSError("cannot read")

    monkeypatch.setattr("mkjxl.convert._sanitize_pillow", broken_pillow)
    monkeypatch.setattr("mkjxl.convert.find_imagemagick", lambda: "magick")

    def runner(argv: list[str], cancel: threading.Event | None = None) -> CommandResult:
        del cancel
        if "-strip" in argv:
            Path(argv[-1]).write_bytes(b"png-data")
            return CommandResult(0, "")
        return _write_jxl(argv)

    result = convert_image(
        source,
        target,
        cjxl="cjxl",
        quality=90,
        effort=7,
        sanitize=True,
        delete_original=False,
        runner=runner,
    )
    assert result.ok
    assert target.read_bytes() == b"jxl-bytes"
