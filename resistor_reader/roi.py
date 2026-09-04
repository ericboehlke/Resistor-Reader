"""Resistor ROI detection using fast OpenCV routines.

``detect_resistor_roi`` is a thin wrapper that orchestrates the helpers below:
mask the resistor against the white background, erode away the thin leads, keep
the largest remaining component, then rotate the body horizontal and crop it.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from .logging_utils import save_image
from .models import ErrorCodeEnum, RoIInput, RoIOutput

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _roi_cfg(config: dict[str, Any]) -> dict[str, Any]:
    cfg = config.get("region_of_interest", {}) or {}
    return {
        # Foreground test: far enough from the background hue, saturated
        # enough, and not as bright as the white acrylic.
        "hue_diff_min": int(cfg.get("hue_diff_min", 8)),
        "sat_min": int(cfg.get("sat_min", 40)),
        "value_max": int(cfg.get("value_max", 220)),
        "open_kernel": int(cfg.get("open_kernel", 5)),
        "dilate_kernel": int(cfg.get("dilate_kernel", 10)),
        "close_kernel": int(cfg.get("close_kernel", 5)),
        # Leads are thinner than this many pixels from the body's edge.
        "lead_distance": float(cfg.get("lead_distance", 15.0)),
        "crop_pad": int(cfg.get("crop_pad", 8)),
    }


def _foreground_mask(hsv: np.ndarray, cfg: dict[str, Any]) -> np.ndarray:
    """Return a binary mask separating the resistor from the white background."""

    h, s, v = cv2.split(hsv)
    border = np.concatenate([h[0], h[-1], h[:, 0], h[:, -1]])
    bg_hue = np.median(border).astype(np.uint8)

    hue_diff = cv2.absdiff(h, np.full_like(h, bg_hue))
    mask = (
        (hue_diff > cfg["hue_diff_min"])
        & (s > cfg["sat_min"])
        & (v < cfg["value_max"])
    ).astype(np.uint8)
    for op, size in (
        (cv2.MORPH_OPEN, cfg["open_kernel"]),
        (None, cfg["dilate_kernel"]),
        (cv2.MORPH_CLOSE, cfg["close_kernel"]),
    ):
        kernel = np.ones((size, size), np.uint8)
        if op is None:
            mask = cv2.dilate(mask, kernel, iterations=1)
        else:
            mask = cv2.morphologyEx(mask, op, kernel, iterations=1)
    return mask


def _largest_component(mask: np.ndarray) -> np.ndarray:
    """Keep only the largest connected component in ``mask``."""

    num, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=4
    )
    if num <= 1:
        raise ValueError("no foreground found")
    # Row 0 is the background component; pick the largest of the rest.
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return (labels == largest).astype(np.uint8)


def _remove_leads(mask: np.ndarray, dist_thresh: float) -> np.ndarray:
    """Remove thin leads using a distance transform."""

    dist = cv2.distanceTransform(
        mask.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
    )
    return (dist >= dist_thresh).astype(np.uint8)


def _rotate_and_crop(
    image: np.ndarray, mask: np.ndarray, pad: int
) -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    """Rotate so the resistor is horizontal; return the tight crop and aligned mask."""

    pts = cv2.findNonZero(mask)
    rect = cv2.minAreaRect(pts)
    center, (w_rect, h_rect), angle = rect
    if h_rect > w_rect:
        angle += 90.0

    rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
    h, w = image.shape[:2]

    # Where the foreground lands after rotation, from the points alone -- no need
    # to warp the whole frame just to read off a bounding box.
    rot_pts = cv2.transform(pts.astype(np.float32), rot_mat).reshape(-1, 2)
    if rot_pts.size == 0:
        empty_mask = np.zeros((h, w), dtype=np.uint8)
        rotated_img = cv2.warpAffine(
            image, rot_mat, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)
        )
        return rotated_img, empty_mask, (0, 0, h, w)

    x0 = max(0, int(np.floor(rot_pts[:, 0].min())) - pad)
    y0 = max(0, int(np.floor(rot_pts[:, 1].min())) - pad)
    x1 = min(w, int(np.ceil(rot_pts[:, 0].max())) + pad)
    y1 = min(h, int(np.ceil(rot_pts[:, 1].max())) + pad)

    # Warp straight into the crop: fold the crop origin into the translation so
    # the output is only the box we keep, not the full rotated frame.
    crop_mat = rot_mat.copy()
    crop_mat[0, 2] -= x0
    crop_mat[1, 2] -= y0
    dsize = (max(1, x1 - x0), max(1, y1 - y0))
    crop = cv2.warpAffine(
        image, crop_mat, dsize, flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255)
    )
    crop_mask = cv2.warpAffine(mask, crop_mat, dsize, flags=cv2.INTER_NEAREST)
    return crop, crop_mask, (y0, x0, y1, x1)


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
    cfg = _roi_cfg(stage_input.config)
    dbg = debug and stage_input.config.get("region_of_interest", {}).get(
        "debug_image", False
    )

    image = stage_input.image
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)

    mask = _foreground_mask(hsv, cfg)
    mask = _remove_leads(mask, cfg["lead_distance"])
    try:
        mask = _largest_component(mask)
    except ValueError:
        return RoIOutput(
            image=image,
            error=ErrorCodeEnum.E02,
            error_msg="No resistor foreground component found.",
        )

    crop, crop_mask, bbox = _rotate_and_crop(image, mask, cfg["crop_pad"])

    mask_path = None
    roi_path = None
    if dbg:
        mask_path = save_image(
            mask * 255, "roi_mask", debug=True, config=stage_input.config, ts=ts
        )
        roi_path = save_image(crop, "roi", debug=True, config=stage_input.config, ts=ts)

    return RoIOutput(
        image=crop,
        body_mask=(crop_mask * 255).astype(np.uint8),
        _metadata={
            "bbox": bbox,
            "debug_mask_path": str(mask_path) if mask_path else None,
            "debug_roi_path": str(roi_path) if roi_path else None,
        },
    )
