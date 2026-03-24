"""Helpers to build debug montage images for pipeline observability."""

from __future__ import annotations

from typing import Iterable

import cv2
import numpy as np

from .models import BandBoundingBox, ColorsEnum, ErrorCodeEnum


def _ensure_rgb(image: np.ndarray | None) -> np.ndarray | None:
    if image is None:
        return None
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    if image.ndim == 3 and image.shape[2] == 3:
        return image
    return None


def _panel(
    image: np.ndarray | None,
    title: str,
    width: int,
    subtitle: str | None = None,
) -> np.ndarray:
    """Create a single labeled panel with normalized width."""
    if image is None:
        canvas = np.full((80, width, 3), 245, dtype=np.uint8)
    else:
        rgb = _ensure_rgb(image)
        if rgb is None:
            canvas = np.full((80, width, 3), 245, dtype=np.uint8)
            subtitle = (subtitle + " | " if subtitle else "") + "unavailable"
        else:
            h, w = rgb.shape[:2]
            scale = width / max(1, w)
            target_h = max(1, int(h * scale))
            canvas = cv2.resize(rgb, (width, target_h), interpolation=cv2.INTER_AREA)

    cv2.putText(
        canvas,
        title,
        (8, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (20, 20, 20),
        1,
        cv2.LINE_AA,
    )
    if subtitle:
        cv2.putText(
            canvas,
            subtitle,
            (8, 42),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (50, 50, 50),
            1,
            cv2.LINE_AA,
        )
    return canvas


def render_final_overlay(
    roi_image: np.ndarray | None,
    bounding_boxes: list[BandBoundingBox] | None,
    colors: tuple[ColorsEnum, ColorsEnum, ColorsEnum, ColorsEnum] | None,
    resistance: float | None,
    failure: ErrorCodeEnum | None,
    error_msg: str,
) -> np.ndarray | None:
    """Render final stage overlay panel with boxes/colors/result."""
    base = _ensure_rgb(roi_image)
    if base is None:
        return None

    overlay = base.copy()
    if bounding_boxes:
        box_color = (255, 0, 0) if failure == ErrorCodeEnum.E04 and colors is None else (0, 255, 0)
        for idx, (x0, y0, x1, y1) in enumerate(bounding_boxes):
            cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1), box_color, 2, cv2.LINE_AA)
            if colors and idx < len(colors):
                cv2.putText(
                    overlay,
                    colors[idx].value,
                    (max(0, x0 + 1), max(12, y0 + 14)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (0, 0, 255),
                    1,
                    cv2.LINE_AA,
                )

    if failure is None and resistance is not None:
        text = f"ohms: {resistance:g}"
        text_color = (0, 128, 0)
    else:
        text = f"error: {error_msg or 'pipeline failure'}"
        text_color = (220, 20, 20)

    cv2.putText(
        overlay,
        text,
        (8, max(18, overlay.shape[0] - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        text_color,
        2,
        cv2.LINE_AA,
    )
    return overlay


def build_debug_montage(
    *,
    input_image: np.ndarray | None,
    preprocessed_image: np.ndarray | None,
    roi_image: np.ndarray | None,
    final_overlay: np.ndarray | None,
    failure: ErrorCodeEnum | None,
    error_msg: str,
    panel_width: int = 640,
    extra_panels: Iterable[tuple[str, np.ndarray | None, str | None]] | None = None,
) -> np.ndarray:
    """Build vertical montage with all available pipeline stage views."""
    failure_label = "ok" if failure is None else failure.name
    panels = [
        _panel(input_image, "Input", panel_width),
        _panel(preprocessed_image, "Preprocessed", panel_width),
        _panel(roi_image, "ROI Cropped", panel_width),
    ]

    if extra_panels:
        for title, img, subtitle in extra_panels:
            panels.append(_panel(img, title, panel_width, subtitle))

    panels.append(
        _panel(
            final_overlay,
            "Final Overlay",
            panel_width,
            subtitle=f"{failure_label}: {error_msg}" if error_msg else failure_label,
        )
    )
    sep = np.full((6, panel_width, 3), 255, dtype=np.uint8)
    stacked: list[np.ndarray] = []
    for idx, p in enumerate(panels):
        if idx > 0:
            stacked.append(sep)
        stacked.append(p)
    return np.vstack(stacked)
