# AGENTS.md

Instructions for AI agents working in this repo. Keep this file short and true:
the previous version described a program that did not exist, which was worse
than having no file at all.

## Orientation

* [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — the pipeline, the stage
  contract, the error codes. Read this first.
* [docs/WORKFLOW.md](docs/WORKFLOW.md) — testing, tuning, configuration.
* [docs/CODE_REVIEW_TODO.md](docs/CODE_REVIEW_TODO.md) — the open work list.

## Commands

| Action | Command |
| --- | --- |
| Install deps | `uv sync` |
| Tests | `uv run pytest` |
| Lint | `uvx ruff check .` |
| Build | `uv build` |
| Honest accuracy | `RESISTOR_SPLIT=holdout uv run pytest` |
| Tune interactively | `uv run python scripts/live_trackbar.py --image <jpg> --debug` |

`uv` installs to `~/.local/bin`; if it is missing,
`curl -LsSf https://astral.sh/uv/install.sh | sh`.

## Rules

* **`test_resistors` is the source of truth.** It runs all 128 photos in
  `resistor_pictures/` against `resistors.csv`. Aim for 100% without cheating —
  do not special-case images, and do not relax the comparison. It currently
  fails at 121/128; that is expected and is the number to improve.
* Do not delete or skip that test to make the suite green.
* Keep `ruff check .` clean.
* Every pipeline stage takes an input dataclass and returns an output dataclass
  inheriting `StageResult`. A stage names its own failure with an
  `ErrorCodeEnum`; the orchestrator propagates it unchanged.
* `_metadata` is diagnostics only. If the next stage needs a value, make it a
  typed field.
* Type-hint every signature.
* Performance matters: a Pi Zero, under a third of a second end to end.
  NumPy/OpenCV vectorization, no Python loops over pixels, no ML frameworks, no
  heavy new dependencies.
* No backwards compatibility is required. Delete rather than deprecate.
* Prefer the code over the docs when they disagree, then fix the docs.
