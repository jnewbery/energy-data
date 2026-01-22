This repository contains [Marimo](https://marimo.io/) notebooks.

- When editing Marimo notebooks, always run `uvx marimo check` on the file and fix all issues that you find.
- When adding new python dependencies, make sure to add them to `pyproject.toml` and run `uv lock` to update the lock file.
- Import all required libraries in the first cell of the notebook. Do not import libraries in later cells.
- Prefer pure, deterministic cells; keep side effects (file writes, network calls) gated behind explicit user intent or a clear parameter.
- Keep cell order logical: imports/config, data loading, transforms, modeling/analysis, visualization/output.
- Use marimo UI elements (`mo.ui.*`) for parameters instead of ad-hoc input parsing; bind values once and reuse.
- Keep state explicit: avoid hidden globals or implicit mutation across cells; prefer returning values from functions or clear, named variables.
- If a cell is expensive, add a small guard or parameter to control recomputation.
