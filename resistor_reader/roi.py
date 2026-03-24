"""Resistor ROI detection using fast library routines.

The heavy lifting is delegated to OpenCV and SciPy to keep this module
compact and efficient.  The main ``detect_resistor_roi`` function is a thin
wrapper that orchestrates the helper utilities below.
"""

from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np
from scipy import ndimage

from .logging_utils import save_image
from .models import ErrorCodeEnum, RoIInput, RoIOutput

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _foreground_mask(hsv: np.ndarray) -> np.ndarray:
    """Return a binary mask separating the resistor from the white background."""

    h, s, v = cv2.split(hsv)
    border = np.concatenate([h[0], h[-1], h[:, 0], h[:, -1]])
    bg_hue = np.median(border).astype(np.uint8)

    hue_diff = cv2.absdiff(h, np.full_like(h, bg_hue))
    mask = (hue_diff > 8) & (s > 40) & (v < 220)
    mask = mask.astype(np.uint8)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    kernel = np.ones((10, 10), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    return mask


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


def _rotate_and_crop(
    image: np.ndarray, mask: np.ndarray, pad: int = 8
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    """Rotate the image so the resistor is horizontal and return the tight crop."""

    pts = cv2.findNonZero(mask)
    rect = cv2.minAreaRect(pts)
    center, (w_rect, h_rect), angle = rect
    if h_rect > w_rect:
        angle += 90.0

    rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
    h, w = image.shape[:2]
    rotated_img = cv2.warpAffine(
        image, rot_mat, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)
    )
    rotated_mask = cv2.warpAffine(mask, rot_mat, (w, h), flags=cv2.INTER_NEAREST)

    ys, xs = np.where(rotated_mask > 0)
    if ys.size == 0 or xs.size == 0:
        # Nothing in mask → return rotated full image and no bbox
        return rotated_img, (0, 0, h, w)

    y0, y1 = ys.min(), ys.max() + 1
    x0, x1 = xs.min(), xs.max() + 1

    # Apply padding and clamp to bounds
    y0 = max(0, y0 - pad)
    x0 = max(0, x0 - pad)
    y1 = min(h, y1 + pad)
    x1 = min(w, x1 + pad)

    crop = rotated_img[y0:y1, x0:x1]
    return crop, (y0, x0, y1, x1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_resistor_roi(
    stage_input: RoIInput,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> RoIOutput:
    """Return a rotated/cropped resistor image via stage contract."""
    dbg = debug and stage_input.config.get("region_of_interest", {}).get(
        "debug_image", False
    )

    image = stage_input.image
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)

    mask = _foreground_mask(hsv)
    mask = _remove_leads(mask, dist_thresh=15.0)
    try:
        mask = _largest_component(mask)
    except ValueError:
        return RoIOutput(
            image=image,
            success=False,
            _metadata={
                "error_code": ErrorCodeEnum.E02.value,
                "error_msg": "No resistor foreground component found.",
            },
        )

    crop, bbox = _rotate_and_crop(image, mask)

    mask_path = None
    roi_path = None
    if dbg:
        mask_path = save_image(
            mask * 255, "roi_mask", debug=True, config=stage_input.config, ts=ts
        )
        roi_path = save_image(crop, "roi", debug=True, config=stage_input.config, ts=ts)

    return RoIOutput(
        image=crop,
        success=True,
        _metadata={
            "bbox": bbox,
            "debug_mask_path": str(mask_path) if mask_path else None,
            "debug_roi_path": str(roi_path) if roi_path else None,
        },
    )
