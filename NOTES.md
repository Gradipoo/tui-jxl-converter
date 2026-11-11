# Notes

## Discovered facts

- CI (`.github/workflows/ci.yml`) uses Python 3.12: `python -m pip install -e ".[dev]"`, then `ruff check .`, `ruff format --check .`, and `python -m pytest`. This machine has no `python` on PATH. The existing `.venv` has ruff. Pytest was not run for the formula work.
- PyPI trusted publisher is set: project `mkjxl`, owner `Gradipoo`, repository `tui-jxl-converter`, workflow `release.yml`, environment `pypi`.
- Formula path: `packaging/homebrew-tap/Formula/mkjxl.rb`. Updater: `python packaging/update_homebrew_formula.py` (here, `.venv/bin/python`, because `python` is not on PATH). `uv` resolves the Python 3.12 deps. If `uv` is missing, the script falls back to `pip install --dry-run .`.
- `Gradipoo/homebrew-tap` is not updated until a real mkjxl sdist exists on PyPI. The formula header url stays a placeholder until then. Dependency resource urls are real PyPI sdists.
- Release version is `1.0.2` (`pyproject.toml` and `src/mkjxl/__init__.py`). Tags `v1.0.0` and `v1.0.1` already existed while the project version was still `1.0.0`. The PyPI job refuses a tag that is not exactly `v` plus the pyproject version.
