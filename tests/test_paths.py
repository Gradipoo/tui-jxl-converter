from pathlib import Path

from mkjxl.paths import (
    format_bytes,
    format_elapsed,
    list_images,
    parse_output_dir,
    plan_targets,
    savings_text,
)


def test_list_images_skips_other_files_and_can_recurse(tmp_path: Path) -> None:
    (tmp_path / "photo.jpg").write_bytes(b"a")
    (tmp_path / "notes.txt").write_bytes(b"a")
    (tmp_path / ".hidden.png").write_bytes(b"a")
    nested = tmp_path / "album"
    nested.mkdir()
    (nested / "cover.png").write_bytes(b"a")

    flat = [path.name for path in list_images(tmp_path, recursive=False)]
    assert flat == ["photo.jpg"]

    recursive = [path.relative_to(tmp_path).as_posix() for path in list_images(tmp_path, True)]
    assert recursive == ["album/cover.png", "photo.jpg"]


def test_output_next_to_source_when_dir_is_blank(tmp_path: Path) -> None:
    source = tmp_path / "a.png"
    source.write_bytes(b"a")
    planned = plan_targets([source], [0], tmp_path, None, False)
    assert planned == [(0, source.with_suffix(".jxl"))]
    assert parse_output_dir("  ") is None
    assert parse_output_dir("out") == Path("out")


def test_recursive_mirrors_directories(tmp_path: Path) -> None:
    files = [tmp_path / "a" / "x.png", tmp_path / "b" / "x.png"]
    for path in files:
        path.parent.mkdir()
        path.write_bytes(b"a")
    output = tmp_path / "out"
    planned = plan_targets(files, [0, 1], tmp_path, output, True)
    assert planned[0][1] == output / "a" / "x.jxl"
    assert planned[1][1] == output / "b" / "x.jxl"


def test_flat_output_renames_conflicts_in_the_batch_and_on_disk(tmp_path: Path) -> None:
    files = [tmp_path / "a" / "x.png", tmp_path / "b" / "x.png"]
    for path in files:
        path.parent.mkdir()
        path.write_bytes(b"a")
    output = tmp_path / "out"
    output.mkdir()
    (output / "x.jxl").write_bytes(b"old")
    planned = plan_targets(files, [0, 1], tmp_path, output, False)
    assert [path.name for _index, path in planned] == ["x-1.jxl", "x-2.jxl"]


def test_file_outside_the_source_root_uses_the_output_dir(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    source_root.mkdir()
    other = tmp_path / "other.png"
    other.write_bytes(b"a")
    output = tmp_path / "out"
    planned = plan_targets([other], [0], source_root, output, True)
    assert planned[0][1] == output / "other.jxl"


def test_format_bytes_and_savings() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(-2048) == "-2.0 KB"
    assert savings_text(100, 40) == "60 B saved (60.0%)"
    assert savings_text(0, 10) == ""
    assert format_elapsed(65) == "01:05"
    assert format_elapsed(3661) == "1:01:01"
