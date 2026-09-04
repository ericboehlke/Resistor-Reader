# Open work

What is left after the September 2026 cleanup. The review that produced this
list is in the git history; everything below is still open.

Current state: **121/128** sample images (94.5%; 95.3% tune / 93.8% holdout),
**6.3 ms** per image on an x86 dev box, `ruff check .` clean, 52 tests passing
plus `test_resistors` failing at the 7 images below.

---

## The seven failures

Ranked by how wrong they are. `logs/<run>/test_failures.md` links a debug
montage for each after any test run.

| Image | Expected | Read as | Confidence | Note |
| --- | --- | --- | --- | --- |
| 0110 | 1 M | 88 | 8.10 | worst miss; confident and wrong |
| 0067 | 22 k | 1.2 k | 0.22 | caught by the E06 gate |
| 0064 | 33 k | 43 k | 0.53 | caught by the E06 gate |
| 0044 | 3.9 k | 390 | 5.42 | multiplier band misread |
| 0127 | 2.2 | 220 | 3.95 | multiplier band misread |
| 0123 | 5.1 | 510 | 4.32 | multiplier band misread |
| 0126 | 5.1 | 5.0 | 3.33 | brown/black on the second digit |

- [ ] Four of the seven are **multiplier-band errors off by exactly 100x**
      (0044, 0127, 0123), or a gold/black multiplier confusion (0126). That is
      a pattern, not seven separate bugs — a metallic-vs-dark multiplier is the
      thing to look at first.
- [ ] 0110 is the only high-confidence miss and the only one the E06 gate
      cannot catch. Worth understanding on its own.

## Accuracy and calibration

- [ ] Take **50 more photos** with `main.py gather`. The current 128 are the
      set every threshold was tuned against; the holdout split says the tuning
      generalizes, but 64 held-out images is a thin basis for a 95% claim.
- [ ] Re-derive `decode.min_confidence` once there is more data. It is 1.0 now,
      measured on 128 images where only three fall below it — a threshold set
      from three data points.

## Pi Zero (Phase D)

- [ ] **Measure the pipeline on the actual Pi Zero.** Nothing here has ever
      been timed on target hardware. The budget is 1 s, ideally 0.33 s;
      per-stage timings are already recorded in `_metadata["timings_ms"]`, so
      this is a matter of reading them off a real run.
- [ ] Confirm the systemd unit works end to end on a fresh image: does it start
      on boot, does the button work, does the display come up, does it recover
      after a crash.

## Architecture

- [ ] **Stage defaults live in two places.** Every tunable is declared in
      `config.yaml` *and* in the `_*_cfg()` fallback in its stage, and a third
      time as the default column in `live_trackbar.TRACKBARS`. A typo'd YAML
      key silently falls back to the code default with no warning. Replace the
      `dict` config with typed dataclasses (`SegmentationConfig`,
      `ClassificationConfig`, `DecodeConfig`, `RuntimeConfig`) loaded once by
      `load_config`, rejecting unknown keys, and generate the trackbar list
      from their fields.
- [ ] `SegmentationOutput.bounding_boxes` always spans the full crop height
      (`(x0, 0, x1, h)`), so two of the four coordinates carry no information.
      Either make them mean something or make the type a column range.
- [ ] `main.py` uses bare `print()`. That works — the systemd unit sends stdout
      to the journal — but a real logger would let the appliance run quieter
      than the tuning session. Low priority.
- [ ] `tests/_best_debug_path` has three near-identical branches that differ
      only in ordering. Collapse.

## Deployment (Phase E)

- [ ] `docs/STEPS.md` planned a **pi-gen fork**. `scripts/prep-sd-card.sh`
      solved the same problem differently — staging a Raspbian Lite image on a
      loop device through a qemu-arm chroot — and is what actually works today.
      Decision: no pi-gen fork; delete the idea rather than carry it. Recorded
      here because the plan is otherwise only in the deleted file's history.
- [ ] Verify Log2Ram is actually configured on the built image. The debug-image
      cap and the journal both assume it.

---

## Done in this pass

For anyone reading the diff: unified the error code space (E01-E07, one owner
per code) and made stages report their own typed error; promoted `body_tex` and
the classifier `scores` matrix from the debug-only `_metadata` dict to real
fields; merged `resolve.py` into `decode.py`; rebuilt the orchestrator around a
run context, removing five copies of the result construction and the round-trip
that re-read stage overlays back off disk as JPEGs; split the 692-line
`bands.py` into `segment.py`/`classify.py`/`imageops.py`; moved the preprocess
crop and every ROI constant into config; made preprocess reject a frame it
cannot crop (E07) instead of silently truncating; turned debug off by default
and capped the debug directory; deleted the duplicate `tests/test.yaml`; wired
up the long-ignored decode confidence as an E06 gate; added
`scripts/resistor-reader.service`; fixed the `live_trackbar` slider that opened
the tool at 1/100th of the configured texture weight; deleted `read_resistor`,
`PipelineInput`, the unrunnable matplotlib plot path, nine unused test fixtures
and four stale documents; and brought `ruff` from 38 findings to zero and the
test count from 18 to 52.

Accuracy was 121/128 before and after — none of it was an algorithm change.
