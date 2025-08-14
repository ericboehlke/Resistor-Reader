"""Band segmentation and color classification.

The resistor is assumed to be already cropped and aligned horizontally.
This module segments the resistor body into four color bands and returns
their color labels using simple color distance in LAB space.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
from scipy.signal import find_peaks

from .logging_utils import save_image

# Reference RGB colors for resistor bands
COLOR_RGB: Dict[str, Tuple[int, int, int]] = {
    "black": (0, 0, 0),
    "brown": (165, 42, 42),
    "red": (255, 0, 0),
    "orange": (255, 165, 0),
    "yellow": (255, 255, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "violet": (238, 130, 238),
    "gray": (128, 128, 128),
    "white": (255, 255, 255),
    "gold": (255, 215, 0),
    "silver": (192, 192, 192),
}

# Pre-compute LAB references for classification
_REF_LAB = {
    name: cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0]
    for name, rgb in COLOR_RGB.items()
}

_TOLERANCE_COLORS = {"gold", "silver"}


def _segment_columns(image: np.ndarray) -> List[Tuple[int, int]]:
    """Return ``(start, end)`` columns for the four color bands."""
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    col_means = lab.mean(axis=0)
    base = np.median(col_means, axis=0)
    dist = np.linalg.norm(col_means - base, axis=1)
    dist_smooth = cv2.GaussianBlur(dist[None, :], (1, 9), 0).ravel()
    peaks, _ = find_peaks(dist_smooth, distance=max(1, image.shape[1] // 20))
    if len(peaks) < 4:
        raise ValueError("unable to find four bands")
    peak_vals = dist_smooth[peaks]
    centers = np.sort(peaks[np.argsort(peak_vals)[-4:]])
    segments: List[Tuple[int, int]] = []
    for c in centers:
        val = dist_smooth[c]
        left = c
        while left > 0 and dist_smooth[left] > 0.5 * val:
            left -= 1
        right = c
        w = dist_smooth.size - 1
        while right < w and dist_smooth[right] > 0.5 * val:
            right += 1
        segments.append((int(left), int(right)))
    segments.sort(key=lambda x: x[0])
    return segments


def _classify(segment: np.ndarray) -> str:
    """Return color label for the given segment."""
    h = segment.shape[0]
    y0, y1 = int(h * 0.2), int(h * 0.8)
    central = segment[y0:y1]
    mean_rgb = central.mean(axis=(0, 1)).astype(np.uint8)
    mean_lab = cv2.cvtColor(mean_rgb.reshape(1, 1, 3), cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)
    dists = {
        name: float(np.linalg.norm(mean_lab - ref.astype(np.float32)))
        for name, ref in _REF_LAB.items()
    }
    return min(dists, key=dists.get)


def segment_and_classify_bands(
    roi: Dict[str, Any],
    config: Dict[str, Any] | None = None,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> List[str]:
    """Return a list of four color labels for the resistor bands."""
    config = config or {}
    image: np.ndarray = roi["crop"]
    segments = _segment_columns(image)
    labels = [_classify(image[:, s:e]) for s, e in segments]

    # Canonical orientation: tolerance band should be last
    if labels and labels[0] in _TOLERANCE_COLORS and labels[-1] not in _TOLERANCE_COLORS:
        labels = labels[1:] + labels[:1]
        segments = segments[1:] + segments[:1]

    dbg = debug and config.get("band_segmentation", {}).get("debug_image", False)
    if dbg:
        overlay = image.copy()
        for (s, e), lbl in zip(segments, labels):
            cv2.rectangle(overlay, (s, 0), (e, image.shape[0] - 1), (0, 255, 0), 1)
            cv2.putText(
                overlay,
                lbl,
                (s + 2, 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.3,
                (255, 0, 0),
                1,
                cv2.LINE_AA,
            )
        save_image(overlay, "bands", debug=True, config=config, ts=ts)

    return labels
