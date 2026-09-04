# Code Review — Actionable TODO

Review date: 2026-09-04 · Branch `claude-rewrite` @ `3e8e295`

Scope: architecture, dead code, and documentation consistency. Algorithm quality
(segmentation cues, colour references, decode priors) is explicitly **out of
scope** — measured pass rate is **94.5% (121/128)** on the sample set, which is
good enough for now.

Measured facts used below:

| Fact | Value |
| --- | --- |
| `uv run pytest` | 18 passed, 1 failed (`test_resistors`, 7/128 images) |
| Pipeline latency (x86 dev box, debug off) | ~6.8 ms/image |
| `ruff check .` | 38 findings (1 × F821 undefined-name is a real bug) |
| Pi-side latency | **never measured** |

---

## P0 — Bugs and wrong behaviour

### 1. Error codes collide between `main.py` and `ErrorCodeEnum`

`resistor_reader/main.py:198` reports a pipeline crash as `E02`, but
`models.ErrorCodeEnum.E02` is `"no resistor found"`. `main.py:184` reports a
camera failure as `E01`, while `orchestrator.py:135` uses that same `E01` for a
preprocess failure. `docs/ARCHITECTURE.md:260-265` documents `E01` as
"camera failure / main". The display therefore shows a code whose meaning
depends on which module raised it.

- [ ] Decide one owner for the code space. Suggested: `E01` camera, `E02` ROI,
      `E03` segmentation, `E04` band set/decode, and add `E05` for
      "pipeline crashed" and `E06` for "low confidence".
- [ ] Remove the `E01`-for-preprocess mapping in `orchestrator.py` (see #3).
- [ ] Regenerate the table in `ARCHITECTURE.md` from the enum, or at minimum
      make them agree.

### 2. `preprocess.py` has unreachable code that ruff flags as undefined

`resistor_reader/preprocess.py:61` is a bare `return output` after the real
`return`. `output` is not defined anywhere in the function — it only survives
because it is unreachable (`ruff` F821).

- [ ] Delete line 61.

### 3. The preprocess failure path is dead

`preprocess.preprocess` hardcodes `success=True` and can never fail, so the
whole `if not pre_out.success:` block in `orchestrator.py:128-141` is
unreachable. It is also the only producer of `E01` in the pipeline.

- [ ] Either make preprocess actually validate its input (frame size, dtype,
      channel count — see #4) and return `success=False`, or drop the branch.
      Validating is the better option, because #4 makes a wrong-sized frame
      silently produce garbage.

### 4. Preprocess crop is hardcoded to one camera resolution

`preprocess.py:46` is `stage_input.image[64:480, 36:598]`, which only makes
sense for a 640×480 capture. `main.py` exposes `--resolution` with a
640×480 default, so any other value silently mis-crops with no error. A frame
smaller than the crop yields an empty or truncated array rather than a failure.

- [ ] Move the crop rectangle into config (`processing.crop: [top, left, bottom,
      right]`), and fail the stage when the crop does not fit the frame.
- [ ] Either drop `--resolution` from `main.py` or validate it against the crop.

### 5. `live_trackbar.py` initialises the `seg_tex_w` slider wrong

`_PERCENT_TRACKBARS = {"seg_max_w", "seg_tex_w"}` scales *both* sliders by 100
when reading them (`scripts/live_trackbar.py:86-88`), but `_init_trackbars` and
`_reset_trackbars` special-case only `seg_max_w` (lines 117, 134). With
`texture_weight: 1.0` in config the slider starts at position `1`, i.e. an
effective weight of `0.01` instead of `1.0` — the tool opens showing a pipeline
that isn't the configured one.

- [ ] Replace the two ad-hoc `name == "seg_max_w"` checks with a single
      `name in _PERCENT_TRACKBARS` check, and factor the duplicated
      init/reset conversion into one helper.

### 6. Shipped `config.yaml` writes a debug JPEG set on every read

`config.yaml:68-71` has `runtime.debug.enabled: true` with `processing`,
`region_of_interest`, `segmentation` and `classification` all at
`debug_image: true`. On the appliance that is 5–6 JPEGs per button press into
`logs/`, which under Log2Ram is a RAM disk with no rotation and no cleanup.

- [ ] Ship `enabled: false` as the appliance default; keep the debug-on config
      as a separate `config.debug.yaml` (or set it from `tests/test.yaml` only).
- [ ] Add a retention cap (keep last N runs) to `logging_utils.save_image`.

---

## P1 — Architecture

### 7. `_metadata` is load-bearing, which the contract forbids

`ARCHITECTURE.md:98-100` and `:106-108` say `_metadata` is debug-only and "not
part of the final API". In practice the orchestrator threads required pipeline
data through it:

- `orchestrator.py:193` reads `seg_out._metadata["body_tex"]` and feeds it to
  classification;
- `orchestrator.py:218-221` reads `cls_out._metadata["scores"]` and feeds it to
  the decoder — this is the entire input to `decode_best`.

So the two most important edges in the pipeline are untyped dict lookups with
silent defaults (`.get("body_tex", 0.0)` will happily pass `0.0` if the key is
ever renamed, degrading gold detection with no error).

- [ ] Promote to real fields: `SegmentationOutput.body_tex: float` and
      `ClassificationOutput.scores: list[dict[ColorsEnum, float]]`.
- [ ] Keep `_metadata` for genuinely diagnostic values only (timings, chosen
      threshold, debug paths).

### 8. Debug images round-trip through JPEG files inside the pipeline

`orchestrator._read_debug_image` (lines 29-37) re-reads the segmentation and
classification overlays **off disk** (`cv2.imread` + colour convert) to build
the montage — images the same process wrote seconds earlier. That is an encode,
a write, a read and a decode per panel, and it silently produces a blank panel
if the write was skipped or the path was `None`.

- [ ] Have `segment_bands` / `classify_bands` return the overlay array (e.g. in
      a `debug: StageDebug` field) and have the orchestrator use it directly.
      Saving to disk becomes a separate, optional concern.

### 9. `_finalize_pipeline_result` is called five times with near-identical kwargs

`orchestrator.py:115-266` is ~150 lines where the same 11-argument call is
repeated five times, differing only in which stage failed. Every new stage
means another copy; every new field means editing five call sites.

- [ ] Restructure as a small run-context object (or a stage list) that
      accumulates `stage_outputs` as the pipeline advances, so failure return
      becomes one `return ctx.finish(failure=..., msg=...)`.
- [ ] The per-stage `metadata={...}` dicts, which re-list every prior stage each
      time, collapse into that context for free.

### 10. Defaults for every tunable are declared in four places

Each segmentation/classification/decode parameter appears in:

1. `config.yaml`
2. `tests/test.yaml` — **byte-identical duplicate** of `config.yaml`
3. the `_segmentation_cfg` / `_classification_cfg` / `_decode_cfg` fallbacks in
   `bands.py:54-101` and `decode.py:72-80`
4. the `TRACKBARS` default column in `scripts/live_trackbar.py:58-76`

Nothing keeps them in sync, and a typo'd YAML key silently falls back to the
code default with no warning.

- [ ] Replace the `dict` config with typed dataclasses (`SegmentationConfig`,
      `ClassificationConfig`, `DecodeConfig`, `RuntimeConfig`) holding the
      defaults, loaded once by `load_config` and passed down. Unknown keys
      should raise rather than be ignored.
- [ ] Delete `tests/test.yaml`; have the tests load `config.yaml` and override
      `runtime.debug` in code (they already do exactly this — see
      `test_orchestrator.py:157-158`).
- [ ] Generate the trackbar list from the config dataclass fields.

### 11. `debug_montage_path` is a test-only key living at config top level

`orchestrator.py:55` reads `config["debug_montage_path"]`, set only by
`tests/test_orchestrator.py:176`. It sits at the top level while every other
debug knob is under `runtime.debug`.

- [ ] Move it under `runtime.debug.montage_path`, or better: return the montage
      array (already in `PipelineResult.debug_image`) and let the test write it.

### 12. `decode.confidence` is computed and thrown away

`decode.py:170` computes a score margin, `orchestrator.py:264` buries it in
`_metadata["confidence"]`, and nothing reads it. `ARCHITECTURE.md:241-242`
describes it as the signal "the Pi can use to ask for a retry instead of
displaying a reading it is unsure of" — that behaviour does not exist.

- [ ] Add `confidence: float` to `PipelineResult`.
- [ ] In `main.read_mode`, show a retry/low-confidence code below a configurable
      threshold. This directly serves the stated goal that "giving an incorrect
      result is worse than giving an error" (`ARCHITECTURE.md:275`).

### 13. Per-stage `error_code` in metadata is ignored by the orchestrator

Stages report their own code (`bands.py:534`, `bands.py:639` returns `E03` from
*classification* for a wrong box count), but the orchestrator overwrites it
based on position in the pipeline (`orchestrator.py:205` → `E04`). Two parallel
error representations, one of which is never read.

- [ ] Pick one. Simplest: stages return a typed `ErrorCodeEnum` field on their
      output; the orchestrator propagates it instead of re-deriving.

### 14. `resolve.py` and `decode.py` should probably be one module

`resolve.py` is 76 lines of two lookup tables plus arithmetic, called from
exactly one place (`decode.py:143`), inside the decode search loop. The split
adds a dataclass pair (`ResolveInput`/`ResolveOutput`) whose success flag is
checked on every iteration of a hot loop.

- [ ] Merge `resolve_value` into `decode.py` as a plain function returning
      `float | None`, and drop `ResolveInput`/`ResolveOutput` from `models.py`.
      Keep `test_resolve.py` pointed at the merged function.

### 15. `bands.py` is 692 lines doing four jobs

Segmentation, classification, matplotlib plotting (`_save_matplotlib_plot`, 50
lines) and OpenCV annotation (`_annotate`) all live in one file.

- [ ] Split into `segment.py` and `classify.py`, and move `_save_matplotlib_plot`
      + `_annotate` into `debug_montage.py` (or a `debug/` package) so the
      appliance import path never touches matplotlib.

### 16. No timing instrumentation despite a hard latency budget

`ARCHITECTURE.md:271-273` requires <1 s and prefers <0.33 s; `AGENTS.md:188`
defines an `E07` timeout code; `AGENTS.md:238` documents `runtime.timings`.
None of it exists — there is no per-stage timing anywhere in the codebase, and
the pipeline has never been timed on the Pi.

- [ ] Record `timing_ms` per stage into metadata (cheap: `time.perf_counter()`
      around each call in the orchestrator).
- [ ] Measure on the Pi Zero and record the number in `ARCHITECTURE.md`.
      (Dev-box reference: ~6.8 ms/image with debug off.)

### 17. `main.py` is untestable and reloads config on every button press

- Module-level `import board`, `RPi.GPIO`, `picamera2` (lines 10-13) mean the
  file cannot even be imported on a dev machine, so `resistance_str`,
  `show_error` and the arg parsing have **zero test coverage**.
- `orchestrator.load_config(...)` is called *inside* `read_mode`
  (`main.py:191`), so the YAML is re-read from disk on every capture.
- `Config` uses `SCREAMING_CASE` instance fields, and `main()` reconstructs
  subcommand arguments with a chain of `hasattr(args, ...)` guards
  (lines 333-358) instead of per-subcommand parsing.

Actions:

- [ ] Split the pure logic (`resistance_str`, config parsing, error formatting)
      into a `display.py` / `cli.py` that imports no hardware, and add tests.
- [ ] Load the pipeline config once in `run_loop`.
- [ ] Lower-case the `Config` fields; give each subcommand its own dataclass or
      use `set_defaults(func=...)` instead of `hasattr` juggling.

### 18. No centralized logging

`.cursorrules:14` requires "a centralized logger … compatible with Log2Ram".
There is none: `main.py` uses bare `print()` and `traceback.print_exc()`, and
`logging_utils.py` — despite the name — only writes JPEGs.

- [ ] Add `logging` setup (stderr → journald under systemd), replace the
      `print`s, and rename `logging_utils.py` to `image_log.py` to match what it
      actually does.

---

## P2 — Dead code and cleanup

- [ ] `orchestrator.read_resistor` (line 269) is labelled "Backward-compatible
      convenience API". Nothing in the codebase calls it — only `AGENTS.md`
      references it. No backwards compatibility is required. **Delete it** and
      fix the two `AGENTS.md` snippets.
- [ ] `models.PipelineInput` (line 42-45) is never constructed anywhere. Delete.
- [ ] `models.BandColorTuple` / `BandBoundingBox` aliases are used unevenly —
      `debug_montage.render_final_overlay` re-spells the 4-tuple longhand
      (line 70). Use the aliases consistently or drop them.
- [ ] `bands.segment_bands:541` computes `success = len(boxes) == 4`, but
      `_extract_bands` raises unless it produces exactly 4 runs, so the
      `if not success:` block (lines 548-550) is unreachable. Remove it or make
      `_extract_bands` return a partial result instead of raising.
- [ ] `bands._segmentation_cfg` puts `create_plot` in the returned cfg
      (line 82) but `segment_bands` re-reads it straight from the raw config
      (line 563). Pick one.
- [ ] `ClassificationOutput.colors` (the arg-max label per band) is only ever
      used to decorate a failure path (`orchestrator.py:233`); the decoder
      re-derives its own labels from the score matrix. Consider dropping it once
      #7 promotes `scores` to a real field.
- [ ] `scripts/live_trackbar.py:154-159`: the `--stage` argument is documented
      as "Reserved for stage-focused views" and is never read. Delete it.
- [ ] `tests/data/roi_*.jpg` (9 tracked images) are referenced only by
      `AGENTS.md:386`; no test opens them. Delete the directory or write the ROI
      unit test that uses it.
- [ ] `resistor_reader/__init__.py` eagerly imports every submodule (pulling in
      cv2 at package import) and its `__all__` omits `decode` and
      `debug_montage`. Trim to a docstring, or list all modules.
- [ ] `scripts/prep-sd-card*.log` (5 files) are untracked build noise in the
      working tree. Add `scripts/*.log` to `.gitignore`.
- [ ] `tests/test_resolve.py`: `test_case_and_whitespace_insensitivity`
      (line 44) no longer tests case or whitespace — inputs are enums now. It
      duplicates a `test_resolve_value_basic` case. Delete or rename.
      Lines 6-7 still carry a stale "adjust the import path as needed" comment,
      and lines 82-86 are stray blank lines.
- [ ] `roi.py` magic numbers are not configurable and contradict the tuning
      story: hue diff `8`, sat `40`, val `220`, kernels `5/10/5`
      (`_foreground_mask`), `dist_thresh=15.0` passed at the call site while the
      default says `3.0` (lines 55, 124), `pad=8` (line 63). Promote to config —
      `docs/web-visualization-design.md:312-318` already lists exactly these.

---

## P3 — Tooling and packaging

- [ ] `pyproject.toml:10` declares `requires-python = ">=3.8"`, but the code
      needs **3.10+**: `main.py` has no `from __future__ import annotations` yet
      uses `str | None` in a dataclass (line 28), and `models.py` imports
      `TypeAlias`. Set `>=3.11` (Bookworm ships 3.11) and note the Pi's system
      Python version.
- [ ] `[tool.uv] dev-dependencies` is deprecated — `uv` warns on every run.
      Move to `[dependency-groups] dev`.
- [ ] Declare the dev/test deps that are actually imported: `ruff`, and
      `matplotlib` (lazily imported by `bands._save_matplotlib_plot`).
      **Confirmed broken:** matplotlib is not in the lockfile and not installed,
      so `segmentation.create_plot: true` raises `ModuleNotFoundError` today.
      Either add it as a dev dep or delete the plotting code (see #15).
- [ ] Add a `[project.scripts] resistor-reader = "resistor_reader.main:main"`
      entry point; `python3 resistor_reader/main.py read` bypasses the package.
- [ ] Add `[tool.pytest.ini_options]` with `testpaths`/`pythonpath`. Tests
      currently rely on CWD being the repo root (`open("tests/test.yaml")`,
      `open("resistor_pictures/resistors.csv")`) and on `sys.path.append` hacks
      duplicated in `tests/__init__.py`, `test_orchestrator.py:13` and
      `test_roi.py:9`.
- [ ] Fix the 38 ruff findings, or narrow the ruleset if some are intentional.
      Most are `BLE001` blind-except (11) and `UP006` legacy typing (6);
      `bands.py:15` still imports `Dict`/`Tuple` from `typing`.
- [ ] There is still **no `resistor-reader.systemd` unit** — `prep-sd-card.sh`
      installs only `usb-gadget-ncm.service`. Phase E in `docs/STEPS.md` is
      unstarted. Add the unit (with `WorkingDirectory=`, since `main.py`
      defaults to the relative path `config.yaml`).

---

## P4 — Documentation

`docs/` currently describes at least three different versions of the program.
The cheapest fix for most of this is deletion, not rewriting.

### `README.md`

- [ ] Line 30 claims **~50% accuracy**. Actual is **94.5%**.
- [ ] Lines 41-51 tell you to `apt install python3-scipy` — scipy was removed in
      `9c48d74`, and the manual install steps are superseded by
      `scripts/prep-sd-card.sh`, which the README never mentions.
- [ ] Line 61 documents `python3 resistor_reader/main.py read`; update once the
      entry point exists.

### `AGENTS.md` — the most stale file in the repo

Lines 178-189 define **E01-E08** with completely different meanings than
`ErrorCodeEnum` (`E03 = ROI not found` vs the code's `E02`). Lines 211-245
document config keys that do not exist (`camera:`, `display:`,
`processing.work_width`, `runtime.timeout_ms`, `classification.confidence_threshold`).
Lines 325-357 stub functions that were never written (`acquisition.py`,
`export.py`, `errors.py`) and signatures that no longer exist
(`preprocess -> dict with 'gray'/'hsv'`). Line 302 says the core deps are
"NumPy, Pillow" — the pipeline is OpenCV. Line 385 says "many
`test_orchestrator.py` parametrized cases are expected to fail"; there is one
non-parametrized test.

- [ ] Cut `AGENTS.md` down to what is true: the agent workflow commands
      (lines 368-386, themselves needing the `read_resistor` and `tests/data`
      corrections) plus a pointer to `ARCHITECTURE.md`. Delete the aspirational
      agent catalogue and the parallel error-code table.

### `docs/ARCHITECTURE.md`

- [ ] Lines 116-118 ("we should remove the HSV calculation") and 144-146 ("this
      stage should no longer return the bounding box") are completed work
      written in the future tense. `roi.py` does still return `bbox` in metadata
      — either finish that or delete the instruction.
- [ ] Line 53 names `read_resistor` as the pipeline entry point; it is
      `read_pipeline`.
- [ ] Lines 65-79's montage diagram omits the Segmentation and Classification
      panels that `build_debug_montage` actually emits.
- [ ] Line 267 "We need to determine if there are other failure modes" — resolve
      it against #1 and #12 and delete the line.

### `docs/WORKFLOW.md`

- [ ] Lines 12-21 request the failure-report feature **that already exists**
      (`test_orchestrator._append_report`). Rewrite as documentation of the
      current behaviour. Note the mismatch: the doc says "append … to create a
      running log", but `_append_report` opens with `"w"` into a fresh
      timestamped directory each run — the name is a lie and there is no
      cross-run history.
- [ ] Line 28's config list is stale: it names `highlight_keep_percentile`,
      which does not exist, and omits the ~20 keys that do.
- [ ] Lines 31-39 request the trackbar tool, which exists at
      `scripts/live_trackbar.py`. Document it (including the `s`/`r`/`q` keys)
      instead of requesting it.
- [ ] The `RESISTOR_SPLIT=tune|holdout` env var
      (`test_orchestrator._apply_split`) is a genuinely useful feature that is
      documented **only** in a docstring. Put it in WORKFLOW.md.

### `docs/STEPS.md`

- [ ] Every checkbox is unchecked, but Phases A and B are done and C is mostly
      done. Mark them, and note that C's "clean up `config.yaml` to only include
      values that exist" is complete while Phase D (Pi timing, 50 more photos)
      and Phase E (systemd, pi-gen) are untouched.

### `docs/COLOR_SPEC.md` and `docs/READING_RESISTORS.md`

- [ ] Both are verbatim copies of code that now lives in `bands.COLOR_RGB` and
      `resolve.DIGIT_MAP`/`MULTIPLIER_MAP`. `READING_RESISTORS.md` still has
      `"grey"` keys that `ColorsEnum` does not define, and line 45 claims the
      tolerance band "doesn't matter" — `decode._sequence_prior` depends on it
      for orientation. Replace both files with a one-line pointer to the source,
      or delete them.

### `docs/web-visualization-design.md`

- [ ] Lines 34-37 describe a function flow that no longer exists
      (`segment_and_classify_bands`, `preprocess -> {"image","hsv"}`,
      `resolve_value(labels)`). The design is unimplemented and overlaps
      `live_trackbar.py`. Either mark it explicitly as a superseded proposal or
      refresh §3.1/§10 against the current stage contracts.

---

## Suggested order

1. **P0 #1-#6** — small, and #1/#6 affect the appliance's real behaviour.
2. **P2 deletions** — pure subtraction, shrinks the surface before refactoring.
3. **P1 #7, #10, #9** — the typed-output/typed-config/context refactor. These
   three are one change; doing them together is much cheaper than separately.
4. **P4 documentation** — after the refactor, so the docs describe the result.
5. **P1 #12, #16 + P3 systemd** — confidence gating, timings, Phase D/E.
