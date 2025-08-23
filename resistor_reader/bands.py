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
    "black": (0.193 * 255, 0.121 * 255, 0.092 * 255),
    "brown": (0.421 * 255, 0.163 * 255, 0.130 * 255),
    "red": (0.479 * 255, 0.114 * 255, 0.113 * 255),
    "orange": (0.583 * 255, 0.235 * 255, 0.121 * 255),
    "yellow": (0.485 * 255, 0.345 * 255, 0.093 * 255),
    "green": (0.085 * 255, 0.170 * 255, 0.169 * 255),
    "blue": (0.084 * 255, 0.146 * 255, 0.216 * 255),
    "violet": (0.199 * 255, 0.163 * 255, 0.267 * 255),
    "gray": (0.379 * 255, 0.305 * 255, 0.281 * 255),
    "white": (0.510 * 255, 0.403 * 255, 0.356 * 255),
    "gold": (0.472 * 255, 0.251 * 255, 0.154 * 255),
    "silver": (192, 192, 192),
}

# Pre-compute LAB references for classification
_REF_LAB = {
    name: cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0]
    for name, rgb in COLOR_RGB.items()
}

_TOLERANCE_COLORS = {"gold", "silver"}


# --- helper for debug plotting without introducing new dependencies in your save_image
def _save_matplotlib_plot(
    curves,
    titles,
    image=None,
    peaks=None,
    segments=None,
    out_path="segmentation_debug.png",
):
    """
    curves: list of (y_values, label) where y_values is 1D numpy array
    titles: list of subtitles for each curve panel
    image:  optional RGB image to show at top
    peaks:  optional 1D array of peak x positions (on the smoothed curve)
    segments: optional list of (L, R) to shade on the smoothed curve
    """
    import matplotlib.pyplot as plt  # lazy import

    n_rows = 1 + len(curves) if image is not None else len(curves)
    fig = plt.figure(figsize=(10, 2.2 * n_rows), dpi=150)

    row = 1
    if image is not None:
        ax = fig.add_subplot(n_rows, 1, row)
        ax.imshow(image)
        ax.set_title("Input (debug view)")
        ax.axis("off")
        row += 1

    for (y, label), title in zip(curves, titles):
        ax = fig.add_subplot(n_rows, 1, row)
        ax.plot(y)
        ax.set_xlim(0, len(y) - 1)
        ax.grid(True, alpha=0.25)
        ax.set_title(title)
        if (
            segments is not None and row == n_rows
        ):  # shade segments on last curve (usually smoothed)
            for L, R in segments:
                ax.axvspan(L, R, alpha=0.2, color="tab:orange")
        if peaks is not None and row == n_rows:
            ax.scatter(peaks, y[peaks], s=20, color="tab:red", zorder=3, label="peaks")
            ax.legend(loc="upper right")
        row += 1

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def _segment_columns(image: np.ndarray, debug: bool = False) -> List[Tuple[int, int]]:
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
    mean_lab = cv2.cvtColor(mean_rgb.reshape(1, 1, 3), cv2.COLOR_RGB2LAB)[0, 0].astype(
        np.float32
    )
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
    segments = _segment_columns(image, debug=True)
    labels = [_classify(image[:, s:e]) for s, e in segments]

    # Canonical orientation: tolerance band should be last
    flipped = False
    if (
        labels
        and labels[0] in _TOLERANCE_COLORS
        and labels[-1] not in _TOLERANCE_COLORS
    ):
        labels = labels[1:] + labels[:1]
        segments = segments[1:] + segments[:1]
        flipped = True

    dbg = debug and config.get("segmentation", {}).get("debug_image", False)
    if dbg:
        # Upscale to fixed size for legibility
        target_w, target_h = 600, 400
        overlay = cv2.resize(
            image, (target_w, target_h), interpolation=cv2.INTER_NEAREST
        )

        # Flip horizontally if needed
        if flipped:
            overlay = cv2.flip(overlay, 1)  # flip over y-axis

        # Calculate scale ratios for coordinates
        h, w = image.shape[:2]
        scale_x = target_w / w
        scale_y = target_h / h

        rect_th = 2
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        text_th = 1

        for (s, e), lbl in zip(segments, labels):
            # Scale coordinates
            s_up = int(s * scale_x)
            e_up = int(e * scale_x)
            top_y = int(0 * scale_y)
            bottom_y = int((h - 1) * scale_y)

            # If flipped, adjust coordinates so bands line up with mirrored image
            if flipped:
                s_up, e_up = target_w - e_up, target_w - s_up

            cv2.rectangle(
                overlay,
                (s_up, top_y),
                (e_up - 1, bottom_y),
                (0, 255, 0),
                rect_th,
                lineType=cv2.LINE_AA,
            )
            cv2.putText(
                overlay,
                lbl,
                (s_up + 2, int(15 * scale_y)),
                font,
                font_scale,
                (255, 0, 0),
                text_th,
                cv2.LINE_AA,
            )

        save_image(overlay, "bands", debug=True, config=config, ts=ts)

    return labels
