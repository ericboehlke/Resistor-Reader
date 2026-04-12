# Browser-Based Pipeline Visualization and Live Tuning Design

## 1) Goal

Design a web browser visualization system for the resistor-reading pipeline where:

- each pipeline function is represented as a **card**,
- each card exposes **arguments/parameters** that can be tuned in the browser,
- changing any value updates the pipeline output **immediately** in the UI.

This document is design-only and does not include implementation code.

---

## 2) Scope and Constraints

### In scope

- Developer-facing tuning UI (desktop browser).
- Fast feedback loop for static test images.
- Card-per-function model for current pipeline functions.
- Live updates of images and metadata after parameter changes.

### Out of scope (first version)

- Raspberry Pi hardware control from browser (GPIO button, camera capture loop).
- Authentication/multi-user permissions.
- Production-grade persistence of tuning presets.

### Existing codebase alignment

Current top-level function flow:

1. `preprocess.preprocess(array, config, debug, ts) -> {"image", "hsv"}`
2. `roi.detect_resistor_roi(artifacts, config, debug, ts) -> {"bbox", "crop"}`
3. `bands.segment_and_classify_bands(roi, config, debug, ts) -> list[str]`
4. `resolve.resolve_value(labels) -> float`

The UI design maps directly to these functions and can later extend to helper-level cards.

---

## 3) System Architecture

## 3.1 High-level components

1. **Frontend (Web UI)**  
   - Card grid for function stages.  
   - Image viewer per stage output.  
   - Controls for function arguments (sliders, toggles, selects, numeric inputs).  
   - Receives incremental updates over WebSocket.

2. **Backend API + Execution Engine**  
   - Hosts session state (current image, parameter values, last outputs).  
   - Runs pipeline functions with current parameter set.  
   - Emits stage outputs immediately after execution.

3. **Function Registry / Adapter Layer**  
   - Defines which functions become cards.
   - Defines argument schema for each card.
   - Adapts UI values into function call signatures.

4. **Debug Artifact Serializer**  
   - Converts stage outputs (`numpy` arrays, masks, metadata) into browser-consumable payloads (PNG/JPEG bytes + JSON metadata).

## 3.2 Suggested runtime stack

- Backend: `FastAPI` + `uvicorn`
- Live channel: native WebSocket endpoint
- Frontend: `React` + lightweight state store (or vanilla JS if minimal)
- Serialization: `Pillow` for image encoding and optional base64 transport

This stack is lightweight and compatible with the current Python project.

---

## 4) Function-to-Card Model

## 4.1 Card abstraction

Each card is defined by a registry record:

```text
id: "roi.detect_resistor_roi"
display_name: "ROI Detection"
function_ref: callable
inputs_from: ["preprocess.preprocess"]
args_schema: [ ... controls ... ]
output_schema: {
  image_keys: ["crop", "mask_overlay"],
  json_keys: ["bbox", "timing_ms", "confidence"]
}
```

## 4.2 Initial card set (mapped to current pipeline)

1. **Preprocess Card**
   - Function: `preprocess.preprocess`
   - Inputs: original image
   - Outputs: preprocessed RGB, HSV preview, processing metadata

2. **ROI Detection Card**
   - Function: `roi.detect_resistor_roi`
   - Inputs: preprocess artifacts
   - Outputs: ROI crop image, optional mask debug, bbox

3. **Band Segmentation + Classification Card**
   - Function: `bands.segment_and_classify_bands`
   - Inputs: ROI crop
   - Outputs: annotated bands image, labels list

4. **Value Resolver Card**
   - Function: `resolve.resolve_value`
   - Inputs: labels list
   - Outputs: ohms value, format-friendly string

5. **Pipeline Summary Card (computed)**
   - Not a function call itself, but displays aggregate result:
     - final resistance,
     - stage timings,
     - current parameter preset name.

---

## 5) Argument/Control Schema

Each card declares argument controls in a machine-readable schema.  
Example control definition:

```json
{
  "key": "hue_diff_threshold",
  "label": "Hue Difference Threshold",
  "type": "slider",
  "min": 0,
  "max": 30,
  "step": 1,
  "default": 8,
  "path": "region_of_interest.hue_diff_threshold"
}
```

## 5.1 Why schema-based controls

- Keeps UI independent from function internals.
- Allows adding new cards without writing custom frontend code.
- Enables server-side validation (type/range checks).

## 5.2 Parameter source-of-truth

Session-scoped parameter object:

```yaml
processing:
  crop_top: 64
  crop_left: 36
  crop_bottom: 480
  crop_right: 598
  wb_enabled: true
region_of_interest:
  hue_diff_threshold: 8
  sat_threshold: 40
  val_max_threshold: 220
  lead_distance_threshold: 15.0
segmentation:
  peak_distance_divisor: 20
  half_height_ratio: 0.5
  min_required_peaks: 4
```

The backend merges this over `config.yaml` defaults before each run.

---

## 6) Live Update Behavior

## 6.1 Update trigger model

When a control value changes:

1. Frontend emits `param_changed` event to backend.
2. Backend validates and updates session parameters.
3. Backend schedules a pipeline run with debounce + cancellation.
4. Results stream back stage-by-stage over WebSocket.
5. Cards update immediately as each stage completes.

## 6.2 Debounce and cancellation

- Debounce window: ~75-150 ms for slider drags.
- If a new change arrives while running:
  - mark current run stale,
  - cancel if possible,
  - start new run with latest values.

This prevents UI lag and stale image flashes.

## 6.3 Progressive rendering

Do not wait for full pipeline completion before updating UI.

- Emit:
  - `stage_started`
  - `stage_result`
  - `stage_error`
  - `pipeline_result`

Each card listens for its stage events and rerenders independently.

---

## 7) Backend API Design

## 7.1 HTTP endpoints

1. `POST /api/session`
   - Creates tuning session.
   - Returns `session_id`, default schema, defaults.

2. `POST /api/session/{id}/image`
   - Uploads source image for the session.
   - Triggers initial run.

3. `GET /api/session/{id}/cards`
   - Returns card definitions + control schemas.

4. `POST /api/session/{id}/params`
   - Body: partial parameter patch.
   - Applies patch and triggers rerun.

5. `GET /api/session/{id}/snapshot`
   - Returns latest full state (for page refresh recovery).

## 7.2 WebSocket endpoint

`GET /api/session/{id}/ws`

Server-to-client event examples:

```json
{"type":"stage_started","run_id":"r42","stage":"roi.detect_resistor_roi"}
{"type":"stage_result","run_id":"r42","stage":"roi.detect_resistor_roi","images":{"crop":"data:image/jpeg;base64,..."},"meta":{"bbox":[12,20,180,410],"timing_ms":17}}
{"type":"pipeline_result","run_id":"r42","meta":{"ohms":4700,"total_ms":64}}
{"type":"stage_error","run_id":"r42","stage":"bands.segment_and_classify_bands","error":{"code":"E04","message":"unable to find four bands"}}
```

---

## 8) Frontend UI Design

## 8.1 Layout

- Left panel: image source + global controls (image selector, reset params, save preset).
- Main panel: responsive card grid ordered by pipeline stages.
- Right panel (optional): final value, timings, event log.

## 8.2 Card anatomy

Each card contains:

1. Header
   - stage name
   - timing badge
   - run status indicator
2. Output viewport
   - image canvas (zoom/pan optional)
   - metadata chips (bbox, labels, confidence)
3. Controls section
   - generated from schema
   - reset-to-default per control

## 8.3 UX details

- Control changes should feel immediate; stale outputs dim while rerun is in progress.
- Invalid values show inline validation messages.
- “Pin output” option preserves previous image for visual comparison.

---

## 9) Execution Model and Data Contracts

## 9.1 Stage contract

Each function adapter returns:

```python
{
  "artifacts": {...},      # internal chaining payload
  "images": {...},         # browser-visible images
  "meta": {...},           # json-safe metadata
  "timing_ms": float
}
```

## 9.2 Adapter responsibilities

- Call underlying function with merged config + stage arguments.
- Catch exceptions and map to error payloads.
- Extract displayable artifacts without modifying core algorithm logic.

This avoids heavy refactors to existing modules.

---

## 10) Suggested Parameterization Changes for Current Functions

To make cards tunable, expose currently hardcoded values as config parameters:

1. `preprocess.preprocess`
   - crop rectangle (`top,left,bottom,right`)
   - white-balance enable/disable

2. `roi._foreground_mask` and `detect_resistor_roi`
   - hue difference threshold (`8`)
   - saturation threshold (`40`)
   - value max (`220`)
   - morphology kernel sizes (`5`, `10`)
   - lead distance threshold (`15.0`)
   - crop padding (`8`)

3. `bands._segment_columns`
   - smoothing kernel width (`9`)
   - peak distance divisor (`image_width // 20`)
   - minimum required peaks (`4`)
   - segment half-height ratio (`0.5`)

4. `bands._classify`
   - vertical sampling range (`20%-80%`)
   - optional color distance metric selection

These should be surfaced through the card schemas and merged into stage config.

---

## 11) Error Handling and Diagnostics

- Stage-level exceptions should not crash UI session.
- Failed card displays:
  - error code/message,
  - last successful output (if available),
  - quick reset button for that card’s params.
- Keep a per-session rolling log of last N events for debugging.

---

## 12) Performance Considerations

- Encode display images at moderate JPEG quality (e.g., 80) to reduce WS payloads.
- Reuse cached results for unchanged upstream stages where possible:
  - If only resolver params change, skip preprocess/ROI/bands rerun.
- Limit max image width in UI pipeline (e.g., 800 px).

Target for interactive tuning on development machine: sub-200 ms perceived updates for most adjustments.

---

## 13) Security and Safety

- Restrict uploaded files to image MIME types.
- Enforce bounds on all numeric controls server-side.
- Session IDs should be unguessable.
- Do not expose arbitrary Python execution through function cards.

---

## 14) Implementation Plan (after design approval)

1. Add `docs`-driven function/card registry and schema definitions.
2. Build FastAPI session + websocket service.
3. Build frontend card renderer from schema.
4. Add adapters around current pipeline functions.
5. Add rerun/debounce/cancel manager.
6. Add tests:
   - schema validation,
   - stage event ordering,
   - parameter patch and immediate rerun behavior.

---

## 15) Acceptance Criteria

Design is considered implemented when:

1. Browser shows one card per pipeline function.
2. Each card exposes editable arguments.
3. Changing any argument triggers immediate rerun and updates visible outputs.
4. Stage timings and errors are visible per card.
5. Final resolved resistance updates live without manual refresh.

