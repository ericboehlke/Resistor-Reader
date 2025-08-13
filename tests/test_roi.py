import numpy as np
import PIL.Image
import pytest
import yaml
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from resistor_reader import preprocess, roi

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
    artifacts = preprocess.preprocess(array, TEST_CONFIG)
    result = roi.detect_resistor_roi(artifacts, TEST_CONFIG)
    crop = result["crop"]
    assert crop.ndim == 3
    assert crop.shape[0] > 0 and crop.shape[1] > 0
    assert crop.shape[1] > crop.shape[0]
