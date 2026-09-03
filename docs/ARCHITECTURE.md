# Resistor Reader

This project takes a picture of a resistor when a button is pressed.
The picture is taken using a raspberry pi camera module with a raspberry pi zero.
This picture is then fed into an opencv pipeline determines the resistance of the
resistor in ohms based on the color code. This value is then displayed on a 14
segment display to the user. There are leds to help provide some consistency in
the lighting of the images.

For now, only tan 4 band resistors are considered in scope.

## Usage

The `main.py` file contains the entry point to the program. There are 3 modes available.

The first is gather mode. It is used to gather test images from the camera onboard the
resistor reader and match them up with known resistance values. This is what was used to
make the test suite of images.

The second is camera mode. It simply takes a picture and saves the image whenever the button
is pressed.

The third mode, read, is the most important. In this mode the resistor reader waits for
a button press, takes, a picture, reads the resistance values via the opencv pipeline,
and displays the image on the display.

## What is working

Several parts of this project have been implemented such that the program works with about
50% accuracy according to the test suite.

Specifically the test suite, display, camera, lights, and command line interface are all
working well. That code can be found in `main.py`.

## What is not working

Things that need improvement are the configuration options, opencv pipeline and architecture
of the program.

### Configuration

The configuration is read in via a yaml file. These options were made before many changes to
the code base so some of the options don't do anything at all. These need to be adjusted once
the opencv pipeline is working well to allow the user some control over the system without
changing code.

### OpenCV Pipeline and Architecture

The pipeline is currently divided into multiple stages. Each of these stages is in a different file.
It may be unnecessary to split them up by file but that depends on how much logic is needed for each
stage in the finished pipeline. For now we will keep them separate.

The `orchestrator.py` has a function called `read_resistor` which is the entry point into the pipeline.
It takes in an image as a numpy array and the configuration options and returns the resistance in ohms.
To accomplish this, the function calls these stages in turn: preprocess, roi, bands (segmentation then
classification), and decode.

In debug mode or if there is a failure, orchestrator should take all of the information from each stage
and create a debug image which combines the pictures vertically to create a visual snapshot of the pipeline.

For the last image, if segmentation fails, just print the cropped image with an overlay of the error message.
If classification fails print all the bounding boxes in a default red color with an error message.
If resolving fails, print the error instead of the Ohms value.

```text
+-----------------------------+
| Input                       |
+-----------------------------+
| Preprocessed                |
+-----------------------------+
| ROI Cropped                 |
+-----------------------------+
| Segmentation 1D signal plot | # if using this approach
+-----------------------------+
| Cropped w/ colored bbxs     |
| matching classified colors  |
| and Ohms printed if valid.  |
+-----------------------------+
```

To enable debugging, orchestrator should return the following dataclass.

```python
@dataclass
class PipelineInput:
    image: np.ndarray
    config: dict[str, Any]


@dataclass
class PipelineResult:
    failure: ErrorCodeEnum
    error_msg: str
    debug_image: np.ndarray
    bands: list[tuple[int, int, int, int]] | None
    colors: tuple[ColorsEnum, ColorsEnum, ColorsEnum, ColorsEnum] | None
    resistance: float | None
    # A place to put any output data that would be useful purely for debugging
    # should not be used for anything outside the tests
    _metadata: dict[str, Any]  
```

Each stage accepts a config dictionary. This dictionary is to be used to pass debugging configuration
variables to the function to fine tune parameters to improve performance. You this however you see fit.

Each stage also returns a metadata dictionary. This is to be used during debugging to return data
from inside the function that would be useful for debugging. Use this however you see fit. It is
not part of the final API.

#### Preprocess

The preprocess (`preprocess.py`) step crops the image so that only the white acrylic background is showing and none of the
mdf frame is in the image. Then it applies a gray-world algorithm to white balance the image. Finally it
creates an HSV version of the image and returns the white balanced image and the hsv image for the rest
of the pipeline.

This step is working fairly well however to clean it up we should remove the HSV calculation and only return a single
image as an `np.ndarray`.

```python
@dataclass
class PreprocessInput:
    image: np.ndarray
    config: dict[str, Any]

@dataclass
class PreprocessOutput:
    image: np.ndarray
    success: bool
    _metadata: dict[str, Any]
```

#### Region of Interest Cropping

The cropping step happens in `roi.py`. The four main steps include creating a mask using the inverse of the
background color to isolate the resistor, removing the leads from that mask using dilation and erosion, deleting
all but the largest component in the mask assuming this is the resistor, and rotating and cropping the RGB image with
the mask. Then the bounding box and cropped image are returned.

I believe the biggest problem with this stage is getting the entire resistor in the mask consistently. Ideally we
wouldn't need to be perfect as long as we get enough of the color bands that the next stage can segment them properly
but the better this stage, the easier it is for the next stage to work.

This stage should no longer return the bounding box but only the cropped image as an `np.ndarray`. This stage will
also have to calculate its own HSV image after preprocess is changed to only return the rgb.

```python
@dataclass
class RoIInput:
    image: np.ndarray  # this is the preprocessed image
    config: dict[str, Any]

@dataclass
class RoIOutput:
    image: np.ndarray
    success: bool
    _metadata: dict[str, Any]
```

#### Segmenting and Classifying the Bands

Segmentation and classification of the resistor bands happens in `bands.py`.

Segmentation builds a one dimensional "bandness" signal across the body from two cues:

* **colour** -- LAB distance of each column from the resistor body colour, measured on a central horizontal
  strip and averaged over only the darkest rows so specular blobs cannot drag it toward white;
* **texture** -- the specular spread of each column, which is the only thing that makes a metallic gold band
  stand out from the beige body it is printed on.

Plain glare on the body sparkles exactly as hard as a metallic band, so the texture cue is gated on the
*chroma of the highlight*: a metallic sparkle stays a saturated gold, a specular reflection off the body
washes out to near-white. The texture contribution is also capped, so a gold band cannot tower over the
others and drag the detection threshold up with it.

Bands are then extracted as runs above a threshold. No single threshold works for every resistor -- a
metallic band scores several times higher than a gray band next to the body -- so the code sweeps the
threshold looking for one that yields exactly four runs, and when none does, it keeps the runs it did find
and fills the rest by claiming the strongest peaks among the leftover columns. Filling never subdivides a
run that was already found, which is what stops two boxes from landing on the same band.

Classification returns a *score for every colour* on every band rather than a hard label. Alongside the LAB
distance to each reference colour it adds a metallic term: gold and silver carry their identity in their
sparkle, which the matte median that identifies every other colour deliberately throws away. Without that
term a gold band is indistinguishable from brown, which was the single largest source of wrong readings.

Segmenting and classifying are separate responsibilities and are separate stages.
Segmentation takes the cropped image and returns the bounding box around each band. If segmentation results in !=4
bands this is an error.

```python
@dataclass
class SegmentationInput:
    image: np.ndarray  # this is the cropped roi image
    body_mask: np.ndarray
    config: dict[str, Any]

@dataclass
class SegmentationOutput:
    bounding_boxes: list[tuple[int, int, int, int]]
    success: bool
    _metadata: dict[str, Any]
```

Classification takes a list of bounding box coordinates for each band and the cropped image and returns the top
scoring colour per band, with the full score matrix in `_metadata["scores"]` for the decoder.

```python
@dataclass
class ClassificationInput:
    image: np.ndarray  # this is the cropped roi image
    bounding_boxes: list[tuple[int, int, int, int]]
    config: dict[str, Any]
    body_tex: float  # body specular spread, the metallic baseline

@dataclass
class ClassificationOutput:
    colors: tuple[ColorsEnum, ColorsEnum, ColorsEnum, ColorsEnum]
    success: bool
    _metadata: dict[str, Any]
```

#### Decoding and Resolving

`resolve.py` is a pure decoder: given four ordered colours it returns a resistance in ohms. It knows nothing
about which end of the resistor is which.

Choosing that order is `decode.py`'s job, and it is not a detail -- a resistor is as likely to be
photographed tolerance-band-left as tolerance-band-right, and the colours are the only cue to which end is
which. `decode_best` searches both band orders and the top few colour candidates per band, keeps only
sequences that form a legal resistor code, and returns the best scoring one. The rules it applies are
published standards rather than anything learned from the sample images:

* the tolerance band is never black, orange, yellow or white (EIA-RS-279), so an end band confidently in
  that set cannot be the tolerance end;
* the first significant digit is never black -- there are no leading-zero resistors;
* real parts come from the E24 preferred-value series (IEC 60063), applied as a bonus rather than a filter
  so an unusual part still decodes;
* the resulting value must be within a plausible range.

It also returns a confidence -- the score margin over the best alternative value -- which the Pi can use to
ask for a retry instead of displaying a reading it is unsure of.

```python
@dataclass
class DecodeInput:
    scores: list[dict[ColorsEnum, float]]  # per-colour score per band, image order
    config: dict[str, Any]

@dataclass
class DecodeOutput:
    resistance: float | None
    colors: tuple[ColorsEnum, ColorsEnum, ColorsEnum, ColorsEnum] | None
    reversed_: bool
    confidence: float
    success: bool
    _metadata: dict[str, Any]
```

| Error Code | Reason | Stage |
| --- | --- | --- |
| E01 | camera failure | main |
| E02 | no resistor found | roi |
| E03 | too many/few bands found | segmentation |
| E04 | invalid band set | classification / decode |

We need to determine if there are other failure modes and capture them as well.

## Performance

Since we are running on a fairly weak piece of hardware, performance is particularly important.
The whole pipeline must run in under a second but preferably in under a third of a second to
minimize lag for the user. The experience for the user should seem very accurate. I want ~95%
accuracy identifying the correct value for a resistor as long as the resistor is present on
the tray and has legible bands. Errors should be very rare. Giving an incorrect result is worse
than giving an error.

To keep the system slim, we will be creating a custom image for this resistor reader with pi-gen.
This will allow us to create an extremely minimal image. Then the resistor reader program will be
started automatically on boot with systemd. All of the logging for the system will stay in ram
using Log2Ram in the final image.

We will create the image once the program is working well as a final touch to finish off the project.
