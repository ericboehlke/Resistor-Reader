# Architecture

How the resistor reader works today. This describes the code as it is; work
still to be done lives in [CODE_REVIEW_TODO.md](CODE_REVIEW_TODO.md).

## The device

A Raspberry Pi Zero with a camera module looks down at a white acrylic tray
under fixed LEDs. Press the button, and it photographs the 4-band resistor on
the tray, decodes the colour code, and shows the resistance on a 14-segment
display. A failure shows an error code instead.

Only tan-bodied 4-band resistors are in scope.

## The pipeline

`orchestrator.read_pipeline(image, config) -> PipelineResult` runs five stages
in order and short-circuits on the first failure.

| Stage | Module | Produces | Fails with |
| --- | --- | --- | --- |
| Preprocess | `preprocess.py` | tray crop, white balanced | `E07` |
| ROI | `roi.py` | resistor body, rotated horizontal, + body mask | `E02` |
| Segmentation | `segment.py` | four band bounding boxes, + body texture | `E03` |
| Classification | `classify.py` | a score per colour per band | `E04` |
| Decode | `decode.py` | resistance, band order, confidence | `E04` |

### Preprocess

Crops to the tray interior (`processing.crop`, default `[64, 36, 480, 598]` for
a 640x480 capture — outside it is the MDF frame) and applies a gray-world white
balance. A frame the crop does not fit fails with `E07` rather than being
silently truncated.

### ROI

Masks the resistor against the white background by hue distance from the
border's median hue, erodes away the thin leads with a distance transform,
keeps the largest connected component, then rotates the body horizontal and
crops it. Returns the crop and the aligned body mask.

Getting the whole resistor into the mask consistently is still the weak point;
the next stage only needs enough of the bands to segment them, but the better
this stage does, the easier that is.

### Segmentation

Builds a one-dimensional "bandness" signal across the body from two cues:

* **colour** — LAB distance of each column from the resistor body colour,
  measured on a central horizontal strip and averaged over only the darkest
  rows, so specular blobs cannot drag it toward white;
* **texture** — the specular spread of each column, which is the only thing
  that makes a metallic gold band stand out from the beige body it is on.

Plain glare sparkles exactly as hard as a metallic band, so the texture cue is
gated on the *chroma of the highlight*: a metallic sparkle stays a saturated
gold, a reflection off the body washes out to near-white. The texture
contribution is capped so a gold band cannot tower over the others and drag the
detection threshold up with it.

Bands are then extracted as runs above a threshold. No single threshold works
for every resistor — a metallic band scores several times higher than a gray
band next to the body — so the code sweeps for a threshold yielding exactly four
runs, and when none does, keeps the runs it found and fills the rest by claiming
the strongest peaks among the leftover columns. Filling never subdivides a run
already found, which is what stops two boxes landing on the same band.

### Classification

Returns a *score for every colour* on every band rather than a hard label.
Alongside the LAB distance to each reference colour it adds a metallic term:
gold and silver carry their identity in their sparkle, which the matte median
that identifies every other colour deliberately throws away. Without that term
a gold band is indistinguishable from brown, which was the single largest
source of wrong readings.

### Decode

`decode_best` searches both band orders and the top few colour candidates per
band, keeps only sequences forming a legal resistor code, and returns the best
scoring one. Choosing the order is not a detail: a resistor is as likely to be
photographed tolerance-band-left as tolerance-band-right, and the colours are
the only cue to which end is which. The rules are published standards, not
anything learned from the sample images:

* the tolerance band is never black, orange, yellow or white (EIA-RS-279);
* the first significant digit is never black — no leading-zero resistors;
* real parts come from the E24 preferred-value series (IEC 60063), applied as a
  bonus rather than a filter so an unusual part still decodes;
* the result must land in a plausible range.

`resolve_value` in the same module is the pure part: four ordered colours in, a
resistance out, no knowledge of which end is which.

It also returns a **confidence** — the winning reading's score margin over the
best alternative *value*. `main.py` refuses a reading below
`decode.min_confidence` with `E06`, because a wrong answer is worse than an
error. The gate lives in `main.py`, not in `read_pipeline`, so the test suite
keeps measuring raw algorithm accuracy rather than accuracy-after-policy.

## Stage contract

Every stage takes an input dataclass (image + config, plus whatever the previous
stage produced) and returns an output dataclass inheriting `StageResult`:

```python
@dataclass(kw_only=True)
class StageResult:
    error: ErrorCodeEnum | None = None   # None means success
    error_msg: str = ""
    debug_overlay: np.ndarray | None = None
    _metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.error is None
```

Two rules make this work:

1. **A stage names its own failure.** The orchestrator propagates `error`
   unchanged; it never re-derives a code from a stage's position in the
   pipeline.
2. **`_metadata` is diagnostics only** — timings, thresholds, debug image
   paths. Anything the next stage needs is a real typed field. That is why
   `SegmentationOutput.body_tex` and `ClassificationOutput.scores` are fields
   and not dictionary keys.

## Error codes

`models.ErrorCodeEnum` is the single source of truth. Names are three
characters so they fit the display.

| Code | Meaning | Raised by |
| --- | --- | --- |
| E01 | camera failure | `main.py` |
| E02 | no resistor found | `roi` |
| E03 | too many/few bands found | `segment`, `classify` |
| E04 | invalid band set | `classify`, `decode` |
| E05 | pipeline crashed | `main.py` |
| E06 | low confidence | `main.py` |
| E07 | bad input image | `preprocess` |

## Debug montage

With `runtime.debug.enabled`, the orchestrator stacks a vertical montage of
every stage's view. Stages hand back their overlay in `debug_overlay`, so
building it never reads back a JPEG the same process just wrote.

```text
+-----------------------------+
| Input                       |
+-----------------------------+
| Preprocessed                |
+-----------------------------+
| ROI Cropped                 |
+-----------------------------+
| Segmentation                |  band boxes
+-----------------------------+
| Classification              |  boxes labelled with the arg-max colour
+-----------------------------+
| Final Overlay               |  boxes + decoded colours + ohms, or the error
+-----------------------------+
```

On failure the final overlay shows what was known at that point: the cropped
image with the error if segmentation failed, red boxes if the bands could not
be classified, the error text in place of the ohms value if decoding failed.

## Performance

Target: under 1 s per capture, preferably under 0.33 s.

Measured on an x86 dev box with debug off, median over 20 images: **6.3 ms**
total (ROI 2.5, classification 1.5, segmentation 1.1, preprocess 0.9, decode
0.2). Per-stage timings are recorded in `_metadata["timings_ms"]` on every run,
so the same numbers can be read off the Pi.

**Not yet measured on the Pi Zero** — that is Phase D and the number that
actually matters.

## Accuracy

121/128 sample images (94.5%). Splitting by resistor value with
`RESISTOR_SPLIT` gives 95.3% on the tuning half and 93.8% on the holdout half,
so the thresholds are not badly overfit to the sample set.

The goal is ~95% on resistors that are present and legible, with errors rare and
wrong answers rarer.

## Deployment

`scripts/prep-sd-card.sh` builds the SD card image on a fast machine via a
qemu-arm chroot: installs the packages, clones the repo, builds the venv,
installs `scripts/resistor-reader.service`, and sets up a CDC-NCM USB gadget at
a static 10.42.0.1 so the Pi is reachable over USB.

The reader starts at boot via systemd and restarts on failure. Logs go to the
journal, which Log2Ram keeps in RAM; debug images are off by default and capped
by `runtime.debug.max_files` when enabled, because `logs/` is that same RAM
disk.
