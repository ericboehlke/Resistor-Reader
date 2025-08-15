import numpy as np

from resistor_reader.bands import COLOR_RGB, segment_and_classify_bands


def make_roi(colors):
    h, w = 40, 120
    base = np.array([180, 160, 110], dtype=np.uint8)
    img = np.full((h, w, 3), base, dtype=np.uint8)
    positions = [10, 35, 60, 85]
    for x, name in zip(positions, colors):
        img[:, x : x + 10] = COLOR_RGB[name]
    return {"bbox": (0, 0, h, w), "crop": img}


def test_segment_and_classify_bands_returns_colors():
    roi = make_roi(["brown", "black", "red", "gold"])
    labels = segment_and_classify_bands(roi, {})
    assert labels == ["brown", "black", "red", "gold"]


def test_segment_and_classify_bands_handles_tolerance_left():
    roi = make_roi(["gold", "brown", "black", "red"])
    labels = segment_and_classify_bands(roi, {})
    assert labels == ["brown", "black", "red", "gold"]
