# Steps

These are the high level steps we need to work through to complete this project.

## Phase A: The Data Contract

[ ] Define Models.py: Create dataclasses for StageInput and StageOutput and redefine the function signatures.

Requirement: Every stage must take an input object and return an output object containing the calculation result, a success flag, and a metadata dictionary.

[ ] Implement the E01-E04 codes into a formal Enum.

[ ] Create the ColorsEnum

## Phase B: Observability

[ ] Create a function called by orchestrator that stitches together all of the output images according to ARCHITECTURE.md to create a single debug image showing the result of each stage.

[ ] Enhance the `test_resistors` function to create a markdown document keeping track of all of the failures and all of the reasons according to WORKFLOW.md.

[ ] Create the Live Trackbar tool. Create a standalone script that calls orchestrator with config options set by the trackbar gui so we can tune parameters interactively.

## Phase C: The Pipeline Overhaul

[ ] Refactor orchestrator.py: Update it to call the new function structures and return the new dataclass.

[ ] Step-by-Step Logic Fixes: Start at the beginning of the pipeline and fix each stage one by one until they each work on every test image in `resistor_pictures/`.

Top: Fix preprocess.py (White balance/Cropping).

Middle: Fix roi.py (Background subtraction & Lead removal).

Bottom: Fix bands.py (Peak finding vs. K-Means clustering).

[ ] Based on the specific implementation, clean up the config.yaml to only include values that exist.

## Phase D: Testing on Pi Zero

[ ] Test the pipeline on the pi zero to confirm the timing is quick enough

[ ] Take pictures of 50 more resistors to verify accuracy on new data

## Phase E: Pi Gen

[ ] Create a systemd service for the resistor reader program

[ ] Create a pi-gen fork for resistor reader and build an image

[ ] Test the final program in the new image
