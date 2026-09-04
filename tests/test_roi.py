import numpy as np
import PIL.Image
import pytest

from resistor_reader import preprocess, roi
from resistor_reader.models import ErrorCodeEnum, PreprocessInput, RoIInput

from .conftest import IMAGE_DIR

SAMPLES = ["0000.jpg", "0001.jpg", "0002.jpg"]


@pytest.mark.parametrize("fname", SAMPLES)
def test_detect_roi(fname, pipeline_config):
    array = np.asarray(PIL.Image.open(IMAGE_DIR / fname))
    pre_out = preprocess.preprocess(
        PreprocessInput(image=array, config=pipeline_config)
    )
    assert pre_out.success
    roi_out = roi.detect_resistor_roi(
        RoIInput(image=pre_out.image, config=pipeline_config)
    )
    assert roi_out.success
    crop = roi_out.image
    assert roi_out.body_mask is not None
    assert roi_out.body_mask.shape == crop.shape[:2]
    assert np.any(roi_out.body_mask > 0)
    assert crop.ndim == 3
    assert crop.shape[0] > 0 and crop.shape[1] > 0
    assert crop.shape[1] > crop.shape[0]


def test_preprocess_rejects_a_frame_the_crop_does_not_fit(pipeline_config):
    """A capture at the wrong resolution must fail, not silently mis-crop."""
    small = np.full((120, 160, 3), 200, dtype=np.uint8)
    out = preprocess.preprocess(PreprocessInput(image=small, config=pipeline_config))
    assert not out.success
    assert out.error == ErrorCodeEnum.E07


def test_preprocess_rejects_a_non_rgb_frame(pipeline_config):
    gray = np.full((480, 640), 200, dtype=np.uint8)
    out = preprocess.preprocess(PreprocessInput(image=gray, config=pipeline_config))
    assert not out.success
    assert out.error == ErrorCodeEnum.E07


def test_preprocess_honours_a_configured_crop(pipeline_config):
    pipeline_config["processing"]["crop"] = [10, 20, 110, 220]
    frame = np.full((480, 640, 3), 200, dtype=np.uint8)
    out = preprocess.preprocess(PreprocessInput(image=frame, config=pipeline_config))
    assert out.success
    assert out.image.shape[:2] == (100, 200)
