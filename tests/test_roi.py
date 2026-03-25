import sys
from pathlib import Path

import numpy as np
import PIL.Image
import pytest
import yaml

sys.path.append(str(Path(__file__).resolve().parents[1]))

from resistor_reader import preprocess, roi
from resistor_reader.models import PreprocessInput, RoIInput

with open("tests/test.yaml", "r") as f:
    TEST_CONFIG = yaml.safe_load(f)

SAMPLES = [
    "resistor_pictures/0000.jpg",
    "resistor_pictures/0001.jpg",
    "resistor_pictures/0002.jpg",
]


@pytest.mark.parametrize("fname", SAMPLES)
def test_detect_roi(fname):
    array = np.asarray(PIL.Image.open(fname))
    pre_out = preprocess.preprocess(PreprocessInput(image=array, config=TEST_CONFIG))
    assert pre_out.success
    roi_out = roi.detect_resistor_roi(RoIInput(image=pre_out.image, config=TEST_CONFIG))
    assert roi_out.success
    crop = roi_out.image
    assert roi_out.body_mask is not None
    assert roi_out.body_mask.shape == crop.shape[:2]
    assert np.any(roi_out.body_mask > 0)
    assert crop.ndim == 3
    assert crop.shape[0] > 0 and crop.shape[1] > 0
    assert crop.shape[1] > crop.shape[0]
