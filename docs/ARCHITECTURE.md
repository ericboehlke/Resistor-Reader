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
To accomplish this, the function calls these stages in turn: preprocess, roi, bands, resolve.

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

Segmentation and classification of the resistor bands happens in `bands.py`. Here the code converts the cropped
image into LAB and tries to create a one dimensional signal so that a peak finding algorithm can identify the colored
bands on the resistor. Once the peaks are identified as coordinates in the cropped image, the classification function
can look at that part of the image and try to match it to the closest value in the reference image.

I believe this stage is where most of the problems are coming from. The conversion to a 1D signal and peak finding
algorithm works for darker colors but struggles with lighter colors that match the tan resistor body too closely.
This is where we might be able to tune the 1D signal better or may need to pivot to a different approach such as
k-means clustering.

This stage should also be split into two stages. Segmenting and classifying are significantly different responsibilities.
Segmentation should take the cropped image and return the bounding box around each band. If segmentation results in !=4
bands this is an error.

```python
@dataclass
class SegmentationInput:
    image: np.ndarray  # this is the cropped roi image
    config: dict[str, Any]

@dataclass
class SegmentationOutput:
    bounding_boxes: list[tuple[int, int, int, int]]
    success: bool
    _metadata: dict[str, Any]
```

Classification should take a list of bounding box coordinates for each band and the cropped image and return a list of
four strings with the proper colors.

```python
@dataclass
class ClassificationInput:
    image: np.ndarray  # this is the cropped roi image
    bounding_boxes: list[tuple[int, int, int, int]]
    config: dict[str, Any]

@dataclass
class ClassificationOutput:
    colors: tuple[ColorsEnum, ColorsEnum, ColorsEnum, ColorsEnum]
    success: bool
    _metadata: dict[str, Any]
```

#### Resolving

The last stage in `resolve.py` takes an array of color bands and converts it too a resistance value in ohms. This
method is fairly straight forward and will work if the rest of the pipeline does.

```python
@dataclass
class ResolveInput:
    image: np.ndarray  # this is the cropped roi image
    bounding_boxes: list[tuple[int, int, int, int]]
    config: dict[str, Any]

@dataclass
class ResolveOutput:
    image: np.ndarray
    success: bool
    _metadata: dict[str, Any]
```

### Error Handling

Currently there is very little error handling. We need a system to communicate to the user that the scan
failed and the reason for the failure. When an error is detected we should save as much log information
as possible including the input image, version of software, configuration, and output images from each 
stage. The current failure modes I see are:

| Error Code | Reason | Stage |
| --- | --- | --- |
| E01 | camera failure | main |
| E02 | no resistor found | roi |
| E03 | too many/few bands found | segmentation |
| E04 | invalid band set | resolve |

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
