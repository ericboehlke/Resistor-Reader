import pytest
import numpy
import PIL
from resistor_reader.bands import _segment_columns


def close_enough(segments, expected) -> bool:
    """Return True if `segments` (predicted) are close to `expected`.

    Rules (per-band, after left->right sort):
      - PASS if IoU >= 0.35
        OR (center distance <= 3% of width + 2 px) AND (width diff <= 50% of expected width or 2 px)
      - All bands must pass.
    """
    if len(segments) != len(expected) or len(expected) == 0:
        return False

    # Sort left->right
    segs = sorted(segments, key=lambda x: x[0])
    exps = sorted(expected, key=lambda x: x[0])

    # Overall image width estimate (for relative tolerances)
    max_end = max(max(s[1] for s in segs), max(e[1] for e in exps))
    min_start = min(min(s[0] for s in segs), min(e[0] for e in exps))
    total_w = max(1, max_end - min_start)

    iou_thresh = 0.35
    center_tol_px = 0.03 * total_w + 2.0  # ~3% of width + 2 px
    width_tol_frac = 0.50  # 50% of expected width
    min_px_tol = 2.0

    def iou_1d(a, b):
        (a0, a1), (b0, b1) = a, b
        inter = max(0, min(a1, b1) - max(a0, b0))  # treat as [start, end)
        union = max(1, (a1 - a0) + (b1 - b0) - inter)
        return inter / union

    for (s0, s1), (e0, e1) in zip(segs, exps):
        # IoU check
        if iou_1d((s0, s1), (e0, e1)) >= iou_thresh:
            continue

        # Center/width fallback
        sc = 0.5 * (s0 + s1)
        ec = 0.5 * (e0 + e1)
        sw = max(1.0, s1 - s0)
        ew = max(1.0, e1 - e0)

        center_ok = abs(sc - ec) <= center_tol_px
        width_ok = abs(sw - ew) <= max(min_px_tol, width_tol_frac * ew)

        if not (center_ok and width_ok):
            return False

    return True


def test_segment_columns_0():
    fname = "tests/data/roi_0.jpg"
    segments = _segment_columns(numpy.asarray(PIL.Image.open(fname)), debug=True)
    expected = [(37, 45), (64, 76), (90, 101), (116, 128)]
    assert close_enough(segments, expected)


def test_segment_columns_1():
    fname = "tests/data/roi_1.jpg"
    segments = _segment_columns(numpy.asarray(PIL.Image.open(fname)), debug=True)
    expected = [(39, 48), (92, 105), (92, 105), (119, 130)]
    assert close_enough(segments, expected)


def test_segment_columns_2():
    fname = "tests/data/roi_2.jpg"
    segments = _segment_columns(numpy.asarray(PIL.Image.open(fname)), debug=True)
    expected = [(51, 63), (75, 87), (100, 113), (131, 142)]
    assert close_enough(segments, expected)


def test_segment_columns_3():
    fname = "tests/data/roi_3.jpg"
    segments = _segment_columns(numpy.asarray(PIL.Image.open(fname)), debug=True)
    expected = [(33, 45), (60, 71), (85, 95), (114, 122)]
    assert close_enough(segments, expected)


def test_segment_columns_4():
    fname = "tests/data/roi_4.jpg"
    segments = _segment_columns(numpy.asarray(PIL.Image.open(fname)), debug=True)
    expected = [(34, 44), (63, 74), (88, 100), (113, 124)]
    assert close_enough(segments, expected)


def test_segment_columns_5():
    fname = "tests/data/roi_5.jpg"
    segments = _segment_columns(numpy.asarray(PIL.Image.open(fname)), debug=True)
    expected = [(34, 43), (63, 74), (91, 102), (113, 124)]
    assert close_enough(segments, expected)


def test_segment_columns_6():
    fname = "tests/data/roi_6.jpg"
    segments = _segment_columns(numpy.asarray(PIL.Image.open(fname)), debug=True)
    expected = [(32, 44), (56, 68), (81, 92), (114, 124)]
    assert close_enough(segments, expected)


def test_segment_columns_7():
    fname = "tests/data/roi_7.jpg"
    segments = _segment_columns(numpy.asarray(PIL.Image.open(fname)), debug=True)
    expected = [(29, 41), (53, 65), (79, 89), (111, 121)]
    assert close_enough(segments, expected)


def test_segment_columns_8():
    fname = "tests/data/roi_8.jpg"
    segments = _segment_columns(numpy.asarray(PIL.Image.open(fname)), debug=True)
    expected = [(33, 43), (59, 70), (83, 95), (114, 124)]
    assert close_enough(segments, expected)
