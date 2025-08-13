"""Resistor ROI detection using fast library routines.

The heavy lifting is delegated to OpenCV and SciPy to keep this module
compact and efficient.  The main ``detect_resistor_roi`` function is a thin
wrapper that orchestrates the helper utilities below.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import cv2
import numpy as np
from scipy import ndimage

from .logging_utils import save_image


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _foreground_mask(hsv: np.ndarray) -> np.ndarray:
    """Return a binary mask separating the resistor from the white background."""

    h, s, v = cv2.split(hsv)
    border = np.concatenate([h[0], h[-1], h[:, 0], h[:, -1]])
    bg_hue = np.median(border).astype(np.uint8)

    hue_diff = cv2.absdiff(h, np.full_like(h, bg_hue))
    mask = (hue_diff > 15) & (s > 30) & (v < 220)
    mask = mask.astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)


def _largest_component(mask: np.ndarray) -> np.ndarray:
    """Keep only the largest connected component in ``mask``."""

    labeled, num = ndimage.label(mask)
    if num == 0:
        raise ValueError("no foreground found")
    sizes = ndimage.sum(mask, labeled, range(1, num + 1))
    label = int(np.argmax(sizes)) + 1
    return (labeled == label).astype(np.uint8)


def _remove_leads(mask: np.ndarray, dist_thresh: float = 3.0) -> np.ndarray:
    """Remove thin leads using a distance transform."""

    dist = ndimage.distance_transform_edt(mask)
    return (dist >= dist_thresh).astype(np.uint8)


def _rotate_and_crop(image: np.ndarray, mask: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """Rotate the image so the resistor is horizontal and return the tight crop."""

    pts = cv2.findNonZero(mask)
    rect = cv2.minAreaRect(pts)
    center, (w_rect, h_rect), angle = rect
    if h_rect > w_rect:
        angle += 90.0

    rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
    h, w = image.shape[:2]
    rotated_img = cv2.warpAffine(image, rot_mat, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
    rotated_mask = cv2.warpAffine(mask, rot_mat, (w, h), flags=cv2.INTER_NEAREST)

    ys, xs = np.where(rotated_mask > 0)
    y0, y1 = ys.min(), ys.max() + 1
    x0, x1 = xs.min(), xs.max() + 1
    crop = rotated_img[y0:y1, x0:x1]
    return crop, (y0, x0, y1, x1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_resistor_roi(
    artifacts: Dict[str, np.ndarray],
    config: Dict[str, Any] | None = None,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> Dict[str, Any]:
    """Return a rotated and cropped image of the resistor."""

    config = config or {}
    dbg = debug and config.get("region_of_interest", {}).get("debug_image", False)

    image = artifacts["image"]
    hsv = artifacts["hsv"]

    mask = _foreground_mask(hsv)
    mask = _largest_component(mask)
    mask = _remove_leads(mask, dist_thresh=3.0)

    crop, bbox = _rotate_and_crop(image, mask)

    if dbg:
        save_image(mask * 255, "roi_mask", debug=True, config=config, ts=ts)
        save_image(crop, "roi", debug=True, config=config, ts=ts)

    return {"bbox": bbox, "crop": crop}

