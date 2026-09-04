"""Small image helpers shared by the segmentation and classification stages."""

from __future__ import annotations

import cv2
import numpy as np


def strip_bounds(height: int, top: float, bottom: float) -> tuple[int, int]:
    """Row range of a central horizontal strip, as fractions of ``height``.

    Falls back to the full height when the fractions leave too little to
    measure, which keeps a very short crop from producing an empty slice.
    """
    y0 = int(height * top)
    y1 = int(height * bottom)
    if y1 - y0 < 3:
        y0, y1 = 0, height
    return y0, y1


def matte_mean(values: np.ndarray, order: np.ndarray) -> np.ndarray:
    """Mean over the rows selected by ``order`` for each column."""
    return np.take_along_axis(values, order, axis=0).mean(axis=0)


def annotate_bands(
    image: np.ndarray, segments: list[tuple[int, int]], labels: list[str]
) -> np.ndarray:
    """Return an upscaled copy of ``image`` with labelled band rectangles."""
    target_w, target_h = 600, 400
    overlay = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
    scale_x = target_w / image.shape[1]
    for (s, e), label in zip(segments, labels):
        s_up, e_up = int(s * scale_x), int(e * scale_x)
        cv2.rectangle(
            overlay,
            (s_up, 0),
            (e_up - 1, target_h - 1),
            (0, 255, 0),
            2,
            lineType=cv2.LINE_AA,
        )
        cv2.putText(
            overlay,
            label,
            (s_up + 2, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )
    return overlay
