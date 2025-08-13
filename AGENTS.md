# AGENTS.md

## Overview

This project runs on a Raspberry Pi Zero. On boot, it starts a pipeline that waits for a physical **trigger button**, captures a photo of a 4-band resistor on a white background under fixed LED lighting, and returns the computed resistance (Ω). Failures return an error code (also shown on a 4-digit, 16-segment display). Classical computer vision techniques are used (NumPy + Pillow; other lightweight libs allowed). Processing target: **< 1s** per capture on Pi Zero.

---

## Architecture at a Glance

```
[Startup Service]
      │
      ▼
[Orchestrator Agent] ──(button)──► [Image Acquisition Agent]
      │                                │
      │                                ▼
      │                        [Preprocessing Agent]
      │                                │
      │                                ▼
      │                         [ROI Detection Agent]
      │                                │
      │                                ▼
      │                        [Band Segmentation Agent]
      │                                │
      │                                ▼
      │                       [Color Classification Agent]
      │                                │
      │                                ▼
      │                          [Value Resolver]
      │                                │
      ├────────► on success ───────────┤
      │                                ▼
      │                         [Result Exporter]
      │                                │
      │                                ▼
      └────────► on error ───► [Error Handler + Display]
```

All agents are pure-Python modules designed to be callable functions/classes with small, explicit inputs/outputs. Debug mode persists intermediates.

---

## Agents

### 1) Orchestrator Agent

**Purpose:** Top-level controller; handles the run-loop, debouncing the button, invoking agents, enforcing time budget, and routing success/error to the display/export.

* **Inputs:** hardware events (button), `config`
* **Outputs:** final `Result` or `ErrorCode`
* **Key responsibilities:**

  * Debounce trigger and start capture
  * Pass `debug=True/False` through pipeline
  * Enforce **< 1s** processing; abort with timeout error if exceeded
  * Call Exporter or Error Handler
* **Interface (example):**

  * `run_once(config) -> Result | ErrorCode`

---

### 2) Image Acquisition Agent

**Purpose:** Capture a still image under LED illumination.

* **Inputs:** camera device ID, exposure/white-balance settings
* **Outputs:** `PIL.Image` (RGB)
* **Assumptions:** White background; fixed LEDs provide consistent light
* **Interface:** `capture_image(config) -> Image`
* **Errors:** `E01_CAPTURE_FAIL`

---

### 3) Preprocessing Agent

**Purpose:** Normalize and stabilize the image for downstream steps.

* **Ops (suggested):**

  * Resize to working resolution (e.g., 640px wide) for speed
  * White-balance via `auto_white_balance`
  * Light denoise (median/box), mild contrast normalization
  * Optional deskew/rotation invariance helpers
* **Inputs:** `Image`
* **Outputs:** `Image` (processed), optional grayscale/HSV buffers
* **Interface:** `preprocess(img, config) -> PreprocArtifacts`
* **Errors:** `E02_PREPROC_FAIL`

---

### 4) ROI Detection Agent

**Purpose:** Locate the resistor in the scene.

* **Approach (classical):**

  * Edge/contour search to find elongated body
  * Color/texture cues against white background
* **Inputs:** `PreprocArtifacts`
* **Outputs:** crop bounding box + cropped image
* **Interface:** `detect_resistor_roi(artifacts, config) -> ROI`
* **Errors:** `E03_ROI_NOT_FOUND` (or low confidence)

---

### 5) Band Segmentation Agent

**Purpose:** Segment the resistor body into 4 color bands (orientation agnostic).

* **Approach (classical):**

  * Determine major axis; unwrap along length
  * Project color/gradient along axis; find band boundaries (peaks/valleys)
  * Handle 4-band schema (2 significant + multiplier + tolerance)
* **Inputs:** `ROI`
* **Outputs:** ordered band regions (left→right or canonicalized orientation)
* **Interface:** `segment_bands(roi, config) -> list[BandRegion]`
* **Errors:** `E04_BAND_SEG_FAIL` (insufficient separation)

---

### 6) Color Classification Agent

**Purpose:** Map each segmented band to an EIA color (black, brown, red, … gold, silver).

* **Approach (classical):**

  * Convert to HSV or LAB; compute mean/median per band; classify via thresholds or small k-NN lookup
  * Return class label + confidence
* **Inputs:** band crops
* **Outputs:** list of `{label, confidence}`
* **Interface:** `classify_bands(band_regions, config) -> list[BandLabel]`
* **Errors:** `E05_LOW_CONF_COLOR` (if any band < threshold)

---

### 7) Value Resolver

**Purpose:** Convert ordered band labels to resistance (Ω) and tolerance.

* **Logic:**

  * 4-band code: D1 D2 × multiplier, tolerance
  * Validate against allowed color sets; compute numeric value
  * Attach overall confidence (min of band confidences and segmentation score)
* **Inputs:** labeled bands
* **Outputs:** `Result = {ohms: float|int, tolerance: str, confidence: float}`
* **Interface:** `resolve_value(labels, config) -> Result`
* **Errors:** `E06_RESOLVE_FAIL` (inconsistent or invalid sequence)

---

### 8) Result Exporter

**Purpose:** For now, return the value; later, drive the 4-digit, 16-segment display.

* **Inputs:** `Result`
* **Outputs:** return value; (future) display IO
* **Debug:** Optionally save an annotated overlay image (boxes, labels, value)
* **Interface:** `export_result(result, img, debug, config) -> None`

---

### 9) Error Handler + Display

**Purpose:** Uniform error reporting and display of error codes prompting retry.

* **Inputs:** `ErrorCode`, optional context images
* **Outputs:** returns error to caller; displays error code
* **Debug:** Save input and last successful intermediate image
* **Interface:** `handle_error(code, context, debug, config) -> None`

---

## Error Codes (proposed)

| Code | Meaning                             | Typical cause                              |
| ---- | ----------------------------------- | ------------------------------------------ |
| E01  | Capture failed                      | Camera not ready, I/O error                |
| E02  | Preprocessing failed                | Image decode, numeric overflow, bad format |
| E03  | Resistor ROI not found              | Framing off, glare, background not white   |
| E04  | Band segmentation failed            | Low contrast bands, orientation artifacts  |
| E05  | Low-confidence color classification | Shadows, saturation/clipping               |
| E06  | Value resolution failed             | Invalid band set/order                     |
| E07  | Timeout                             | >1s budget exceeded                        |
| E08  | I/O persistence failure (debug)     | Disk full, path permissions                |

> Display these codes on the 4-digit display; keep them two–three characters (e.g., “E03”).

---

## Performance Targets

* **End-to-end latency:** < 1 second on Pi Zero for a single capture
* **Strategies:**

  * Work at reduced resolution; only keep full-res for debug
  * Prefer integer/NumPy vectorized ops; avoid Python loops on pixels
  * Cache lookups (color thresholds, band geometry)
  * Short-circuit early on clear failures

---

## Configuration

Suggested `config.yaml` keys (or CLI/env):

```yaml
camera:
  device: 0
  resolution: [640, 480]
  exposure: "auto"   # or fixed value
  white_balance: "auto"
  debug_image: true

processing:
  work_width: 640
  debug_image: true

region_of_interest:
  debug_image: true

segmentation:
  min_band_width_px: 6
  band_smooth_window: 9
  debug_image: true

classification:
  confidence_threshold: 0.65
  debug_image: true

runtime:
  timeout_ms: 900
  debug:
    enabled: true
    timings: true
    dir: "logs/"
  save_overlay: true

display:
  enabled: false     # set true when hardware connected
```

All config should be overridable via CLI flags when running on a dev machine.

---

## Logging & Debug Mode

* **Normal:** minimal logs (INFO-level milestones + final result)
* **Debug:** save:

  * Raw capture: `logs/{ts}_raw.jpg`
  * Preprocessed: `logs/{ts}_pre.jpg`
  * ROI crop: `logs/{ts}_roi.jpg`
  * Band mask/visualization: `logs/{ts}_bands.jpg`
  * Annotated overlay with labels/value: `logs/{ts}_overlay.jpg`
  * A `logs/{ts}.json` with timings, confidences, chosen thresholds
* On error, also save the most recent successful intermediate image.

---

## Startup & Service

* Launch at boot via `systemd`:

  * `resistor-reader.service` runs the Orchestrator
  * Restarts on failure; writes to `journalctl`
* Button GPIO debounced in software; LEDs may be toggled by Orchestrator before capture.

---

## Testing & Golden Data

* **Golden images:** `resistor_pictures/`
* **Ground truth:** `resistors.csv` (filename → expected Ω and tolerance)
* **Tests:**

  * Unit tests per agent (ROI detection, segmentation, classification)
  * Golden regression test: run pipeline on all images and compare against CSV
  * Performance test: assert p95 latency < 1s on Pi Zero build
  * Never delete or comment out tests; even if the pipeline is incomplete, keep
    existing tests in place and allow them to fail until the implementation
    supports them.

---

## Hardware/Scene Assumptions

* White, matte background
* Fixed LED illumination (avoid specular glare on bands)
* Resistor may be in any orientation; pipeline must be rotation-invariant
* Camera focus fixed; subject distance roughly consistent

---

## Dependencies

* **Core:** Python 3.x, NumPy, Pillow
* **Allowed lightweight helpers:** `scikit-image` or `opencv-python-headless` (optional), `RPi.GPIO`/`gpiozero` for button/display control when added
* Keep footprint small for Pi Zero. Avoid heavy ML frameworks.

---

## Future Extensions

* Drive 4-digit, 16-segment display for both result and error codes
* Add simple calibration routine (white reference, color chart)
* Add retry-with-guidance: blink LED pattern suggesting better placement

---

## Licensing

* **MIT License** for the project.
* Ensure any added third-party data/models comply with MIT-compatible terms.

---

## Minimal Agent Interfaces (example stubs)

```python
# orchestrator.py
def run_once(config) -> dict | str:
    """Returns Result dict or ErrorCode string like 'E03'."""

# acquisition.py
def capture_image(config) -> "PIL.Image.Image": ...

# preprocess.py
def preprocess(img, config) -> dict:  # includes 'image', 'gray', 'hsv' keys
    ...

# roi.py
def detect_resistor_roi(artifacts, config) -> dict:  # {'bbox': (x,y,w,h), 'crop': Image}
    ...

# bands.py
def segment_bands(roi, config) -> list:  # list of {'bbox':..., 'crop': Image}
    ...

# classify.py
def classify_bands(band_regions, config) -> list:  # [{'label':'red','conf':0.92}, ...]
    ...

# resolve.py
def resolve_value(labels, config) -> dict:  # {'ohms': 4700, 'tolerance': '±5%', 'confidence': 0.88}
    ...

# export.py
def export_result(result, img, debug, config) -> None: ...

# errors.py
def handle_error(code, context, debug, config) -> None: ...
```

---

## Contribution & Ownership

* **Maintainer:** Eric (default) across all agents for now.

---
