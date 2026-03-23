# Development Workflow

This document describes the development workflow to work on this project.

## Testing

The tests can be run using `uv run pytest`. This runs the whole suite of tests.
The `test_resistors` test case in `test_orchestrator.py` runs through all of the pictures
in the `resistor_pictures/` directory. These pictures were gathered with the `gather` mode
so they are paired with known resistance values in `resistor_pictures/resistors.csv`.

We need to change `test_resistors` so that it outputs a summary of all of the failures.
The test case should return a markdown document with the date and time, commit hash, and a
table with every failed test case. The table should have the following format.

| filename | failed stage | error message | segmentation bounding boxes (optional) | classification colors (optional) | resistance (optional) | debug image path |
| --- | --- | --- | --- | --- | --- | --- |
| 0000.jpg | result | incorrect resistance | [segmentation coords] | red, green, orange, gold | 100 Ohms | debug/0000_debug.jpg |

We can append to the markdown file each test run to create a running log of progress and to easily identify regressions.

These changes will make it easier to communicate with each other about problems in the pipeline.
We need to create a guide to map pixels in the combined debug image into individual images for each
stage of the pipeline so we can easily "crop" the debug image back into the stage outputs.

## Interactive Tuning

To allow for interactive tuning and visualization of the pipeline we will implement a gui that allows us
to adjust variables with slider bars, called trackbars in opencv. Here is a tutorial describing the process.
https://docs.opencv.org/3.4/da/d6a/tutorial_trackbar.html

The trackbars should edit values that get passed into each stage with the config dictionary.
We will likely need to create another file defining the gui and trackbars but we should reuse orchestrator
so that the code is the same as will be run by the application.
