import numpy as np

from resistor_reader.bands import COLOR_RGB, classify_bands, segment_bands
from resistor_reader.models import ClassificationInput, ColorsEnum, SegmentationInput


def make_roi(colors):
    h, w = 40, 120
    base = np.array([180, 160, 110], dtype=np.uint8)
    img = np.full((h, w, 3), base, dtype=np.uint8)
    positions = [10, 35, 60, 85]
    for x, name in zip(positions, colors):
        img[:, x : x + 10] = COLOR_RGB[ColorsEnum(name)]
    return {"bbox": (0, 0, h, w), "crop": img}


def test_segment_and_classify_bands_returns_colors():
    roi = make_roi(["brown", "black", "red", "gold"])
    seg = segment_bands(SegmentationInput(image=roi["crop"], config={}))
    assert seg.success
    cls = classify_bands(
        ClassificationInput(image=roi["crop"], bounding_boxes=seg.bounding_boxes, config={})
    )
    assert cls.success
    assert cls.colors == (
        ColorsEnum.BROWN,
        ColorsEnum.BLACK,
        ColorsEnum.RED,
        ColorsEnum.GOLD,
    )


def test_segment_and_classify_bands_handles_tolerance_left():
    roi = make_roi(["gold", "brown", "black", "red"])
    seg = segment_bands(SegmentationInput(image=roi["crop"], config={}))
    assert seg.success
    cls = classify_bands(
        ClassificationInput(image=roi["crop"], bounding_boxes=seg.bounding_boxes, config={})
    )
    assert cls.success
    assert cls.colors == (
        ColorsEnum.BROWN,
        ColorsEnum.BLACK,
        ColorsEnum.RED,
        ColorsEnum.GOLD,
    )
