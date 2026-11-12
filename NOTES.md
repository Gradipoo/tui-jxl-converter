# Notes

## Discovered facts

- CI (`.github/workflows/ci.yml`) uses Python 3.12: `python -m pip install -e ".[dev]"`, then `ruff check .`, `ruff format --check .`, and `python -m pytest`. This machine has no `python` on PATH. The existing `.venv` has ruff. Pytest was not run for the formula work.
- PyPI trusted publisher is set: project `mkjxl`, owner `Gradipoo`, repository `tui-jxl-converter`, workflow `release.yml`, environment `pypi`.
- Formula path: `packaging/homebrew-tap/Formula/mkjxl.rb`. Updater: `python packaging/update_homebrew_formula.py` (here, `.venv/bin/python`, because `python` is not on PATH). `uv` resolves the Python 3.12 deps. If `uv` is missing, the script falls back to `pip install --dry-run .`.
- `Gradipoo/homebrew-tap` `Formula/mkjxl.rb` points at the PyPI sdist for `mkjxl` 1.0.3. `brew update-python-resources` could not see the new formula without a local `homebrew/core` tap, so `packaging/update_homebrew_formula.py` filled the 10 dependency resources itself. The local Homebrew tap checkout must stay on `main`.
- Release version is `1.0.3` (`pyproject.toml` and `src/mkjxl/__init__.py`). Tags `v1.0.0` and `v1.0.1` already existed while the project version was still `1.0.0`. `v1.0.2` published a GitHub release, then the PyPI job failed because `tomllib.loads` was given bytes. The version check now uses `tomllib.load` on a binary file. The PyPI job refuses a tag that is not exactly `v` plus the pyproject version.
