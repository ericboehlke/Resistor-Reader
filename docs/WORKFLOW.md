# Development Workflow

## Setup

```bash
uv sync          # dependencies
uv run pytest    # the whole suite
uvx ruff check . # lint (clean; keep it that way)
```

Everything runs on a dev machine except `main.py`, which imports `board`,
`RPi.GPIO` and `picamera2` and only works on the Pi. Exercise the pipeline with
`orchestrator.read_pipeline` or the test suite instead.

## The regression suite

`test_resistors` in `tests/test_orchestrator.py` runs every photo in
`resistor_pictures/` against the known values in `resistor_pictures/resistors.csv`
(gathered with `main.py gather`). It is the source of truth for accuracy — 121
of 128 as of this writing.

Each run writes `logs/<timestamp>/test_failures.md`: a table of every failure
with the stage that failed, the error, the decoded colours, and a path to the
most useful debug image. Images that pass are run once with debug off; only
failures are re-run with debug on, so a clean run stays fast and does not fill
`logs/`.

The report is one file per run, not a running log across runs — use git if you
want history.

### Honest accuracy numbers

The thresholds were tuned against these photos, so a pass rate over all of them
flatters itself. `RESISTOR_SPLIT` cuts the set in half **by resistor value**
(every value was photographed twice, so splitting by filename would leak one
photo of a pair into the other half):

```bash
RESISTOR_SPLIT=tune    uv run pytest    # tune against this half
RESISTOR_SPLIT=holdout uv run pytest    # then read the honest number here
```

Unset runs everything. Currently 95.3% tune / 93.8% holdout.

## Interactive tuning

`scripts/live_trackbar.py` reruns the whole pipeline on one image as you drag
sliders, showing the debug montage live. It calls the same `read_pipeline` the
appliance does, so what you tune is what runs.

```bash
uv run python scripts/live_trackbar.py \
  --image resistor_pictures/0044.jpg --debug --save-config tuned.yaml
```

Keys: `s` saves the current values to `--save-config`, `r` resets to the file's
values, `q` or Escape quits.

The sliders are integers, so `seg_max_w` and `seg_tex_w` carry their real value
scaled by 100. Adding a slider means adding a row to `TRACKBARS` and, for a
fractional parameter, to `_PERCENT_TRACKBARS`.

## Configuration

One file, `config.yaml`, holds every tunable, and it is what the appliance runs.
Tests load it and force the debug switches in code — there is deliberately no
second copy of the tunables under `tests/`, because a second copy only drifts.

Debug is **off** by default: `logs/` on the appliance is a Log2Ram RAM disk, and
each enabled stage writes a JPEG per button press. `runtime.debug.max_files`
caps the directory when it is on.

Note that stage defaults currently live in two places — `config.yaml` and the
`_*_cfg()` fallbacks in each stage — so a key typo silently falls back to the
code default. See [CODE_REVIEW_TODO.md](CODE_REVIEW_TODO.md).

## Conventions

* Every stage takes an input dataclass and returns an output dataclass; see the
  stage contract in [ARCHITECTURE.md](ARCHITECTURE.md).
* A stage names its own failure with an `ErrorCodeEnum`. Do not add a code
  without adding it to the table in ARCHITECTURE.md.
* `_metadata` is for diagnostics. If the next stage needs it, it is a field.
* Performance matters: the target is under a third of a second on a Pi Zero.
  Vectorize with NumPy/OpenCV; no Python loops over pixels, no ML frameworks.
