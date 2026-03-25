"""Band segmentation and color classification.

The resistor is assumed to be already cropped and aligned horizontally.
This module segments the resistor body into four color bands and returns
their color labels using simple color distance in LAB space.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
from scipy.signal import find_peaks

from .logging_utils import save_image
from .models import (
    BandBoundingBox,
    ClassificationInput,
    ClassificationOutput,
    ColorsEnum,
    ErrorCodeEnum,
    SegmentationInput,
    SegmentationOutput,
)

# Reference RGB colors for resistor bands
COLOR_RGB: Dict[ColorsEnum, Tuple[int, int, int]] = {
    ColorsEnum.BLACK: (0.193 * 255, 0.121 * 255, 0.092 * 255),
    ColorsEnum.BROWN: (0.421 * 255, 0.163 * 255, 0.130 * 255),
    ColorsEnum.RED: (0.479 * 255, 0.114 * 255, 0.113 * 255),
    ColorsEnum.ORANGE: (0.583 * 255, 0.235 * 255, 0.121 * 255),
    ColorsEnum.YELLOW: (0.485 * 255, 0.345 * 255, 0.093 * 255),
    ColorsEnum.GREEN: (0.085 * 255, 0.170 * 255, 0.169 * 255),
    ColorsEnum.BLUE: (0.084 * 255, 0.146 * 255, 0.216 * 255),
    ColorsEnum.VIOLET: (0.199 * 255, 0.163 * 255, 0.267 * 255),
    ColorsEnum.GRAY: (0.379 * 255, 0.305 * 255, 0.281 * 255),
    ColorsEnum.WHITE: (0.510 * 255, 0.403 * 255, 0.356 * 255),
    ColorsEnum.GOLD: (0.472 * 255, 0.251 * 255, 0.154 * 255),
    ColorsEnum.SILVER: (192, 192, 192),
}

# Pre-compute LAB references for classification
_REF_LAB = {
    name: cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0]
    for name, rgb in COLOR_RGB.items()
}

_TOLERANCE_COLORS = {ColorsEnum.GOLD, ColorsEnum.SILVER}


def _segmentation_cfg(config: dict[str, Any]) -> dict[str, Any]:
    seg = config.get("segmentation", {}) or {}
    k = int(seg.get("band_smooth_window", 9))
    if k % 2 == 0:
        k += 1
    k = max(1, k)
    return {
        "band_smooth_window": k,
        "min_band_width_px": max(1, int(seg.get("min_band_width_px", 6))),
        "min_band_separation_px": max(1, int(seg.get("min_band_separation_px", 8))),
        "edge_margin": max(0, int(seg.get("edge_margin", 4))),
        "max_band_width_ratio": float(seg.get("max_band_width_ratio", 0.35)),
        "create_plot": bool(seg.get("create_plot", False)),
    }


def _classification_cfg(config: dict[str, Any]) -> dict[str, Any]:
    cls = config.get("classification", {}) or {}
    p = float(cls.get("highlight_keep_percentile", 80.0))
    p = max(0.0, min(100.0, p))
    return {"highlight_keep_percentile": p}


def _debug_dir_from_config(config: dict[str, Any]) -> Path:
    return Path(config.get("runtime", {}).get("debug", {}).get("dir", "logs"))


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


def _segment_columns(
    image: np.ndarray,
    body_mask: np.ndarray,
    cfg: dict[str, Any],
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    """Return column ranges ``(start, end)`` with ``end`` exclusive; plus debug arrays."""
    h, w = image.shape[:2]
    if body_mask.shape != (h, w):
        raise ValueError("body_mask must match image H×W")
    mask_bin = (body_mask > 0).astype(np.uint8)
    col_sum = mask_bin.sum(axis=0)
    valid = col_sum > 0
    if not np.any(valid):
        raise ValueError("empty body mask")
    xs = np.where(valid)[0]
    xl_raw, xr_raw = int(xs.min()), int(xs.max())
    em = int(cfg["edge_margin"])
    xl = xl_raw + em
    xr = xr_raw - em
    if xl >= xr:
        raise ValueError("edge margin too large for body mask")

    usable_width = xr - xl + 1
    max_w = max(1, int(cfg["max_band_width_ratio"] * usable_width))
    min_w = int(cfg["min_band_width_px"])

    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    col_means = lab.mean(axis=0)
    sub = col_means[xl : xr + 1]
    base = np.median(sub, axis=0)
    dist = np.zeros(w, dtype=np.float64)
    dist[xl : xr + 1] = np.linalg.norm(col_means[xl : xr + 1] - base, axis=1)

    ksz = int(cfg["band_smooth_window"])
    dist_smooth = cv2.GaussianBlur(dist[None, :], (1, ksz), 0).ravel()

    min_sep = int(cfg["min_band_separation_px"])
    slice_smooth = dist_smooth[xl : xr + 1]
    # Legacy spacing uses full ROI width (~w/20), not the masked usable span, so nearby
    # peaks (e.g. 92 vs 99) are not both returned by find_peaks.
    peak_dist = max(min_sep, max(1, w // 20))
    peaks_rel, _ = find_peaks(slice_smooth, distance=peak_dist)
    peaks = peaks_rel + xl

    if len(peaks) < 4:
        raise ValueError("unable to find four bands")

    # Ignore spurious peaks on rounded caps / shadow at body edges (still use mask xl/xr).
    pin = max(em, min_sep * 2)
    cand_mask = (peaks >= xl + pin) & (peaks <= xr - pin)
    cand = peaks[cand_mask]
    if len(cand) < 4:
        cand = peaks

    # Strongest four peaks among candidates, then left→right order.
    peak_vals = dist_smooth[cand]
    centers = np.sort(cand[np.argsort(peak_vals)[-4:]])

    # Half-height expansion per peak; ``right`` is exclusive end index (matches legacy).
    adjusted: list[tuple[int, int]] = []
    for c in centers:
        val = float(dist_smooth[int(c)])
        if val <= 0.0:
            raise ValueError("invalid peak height")
        left = int(c)
        while left > xl and float(dist_smooth[left]) > 0.5 * val:
            left -= 1
        right = int(c)
        while right < xr and float(dist_smooth[right]) > 0.5 * val:
            right += 1
        adjusted.append((left, right))

    adjusted.sort(key=lambda x: x[0])

    # Enforce max width (shrink around peak center).
    for i in range(4):
        s, e = adjusted[i]
        wseg = e - s
        c = int(centers[i])
        if wseg > max_w:
            half = max_w // 2
            ns = max(s, c - half)
            ne = min(e, ns + max_w)
            if ne - ns < wseg:
                ns = max(xl, min(c - half, xr + 1 - max_w))
                ne = min(xr + 1, ns + max_w)
            s, e = ns, ne
        adjusted[i] = (s, e)

    debug_info: dict[str, Any] = {
        "dist_smooth": dist_smooth,
        "xl": xl,
        "xr": xr,
        "peaks_selected": np.asarray(centers, dtype=np.int32),
        "min_band_width_px": min_w,
    }
    return adjusted, debug_info


def _classify(segment: np.ndarray, config: dict[str, Any]) -> ColorsEnum:
    """Return color label for the given segment."""
    h = segment.shape[0]
    y0, y1 = int(h * 0.2), int(h * 0.8)
    central = segment[y0:y1]
    cfg = _classification_cfg(config)
    p = float(cfg["highlight_keep_percentile"])
    pixels = central.reshape(-1, 3).astype(np.float32)
    if pixels.shape[0] == 0:
        mean_rgb = np.zeros(3, dtype=np.uint8)
    else:
        brightness = pixels.mean(axis=1)
        thr = float(np.percentile(brightness, p))
        mask_hi = brightness <= thr
        filtered = pixels[mask_hi]
        if filtered.shape[0] < 10:
            mean_rgb = central.mean(axis=(0, 1)).astype(np.uint8)
        else:
            mean_rgb = np.median(filtered, axis=0).astype(np.uint8)
    mean_lab = cv2.cvtColor(mean_rgb.reshape(1, 1, 3), cv2.COLOR_RGB2LAB)[0, 0].astype(
        np.float32
    )
    dists = {
        name: float(np.linalg.norm(mean_lab - ref.astype(np.float32)))
        for name, ref in _REF_LAB.items()
    }
    return min(dists, key=dists.get)


def segment_bands(
    stage_input: SegmentationInput,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> SegmentationOutput:
    """Locate four band bounding boxes in ROI image."""
    image = stage_input.image
    body_mask = stage_input.body_mask
    cfg = _segmentation_cfg(stage_input.config)
    try:
        segments, dbg_cols = _segment_columns(image, body_mask, cfg)
    except ValueError as exc:
        return SegmentationOutput(
            bounding_boxes=[],
            success=False,
            _metadata={
                "error_code": ErrorCodeEnum.E03.value,
                "error_msg": str(exc),
            },
        )

    h = image.shape[0]
    boxes: list[BandBoundingBox] = [(int(s), 0, int(e), int(h)) for s, e in segments]
    success = len(boxes) == 4
    metadata: dict[str, object] = {"raw_segments": segments}
    if not success:
        metadata["error_code"] = ErrorCodeEnum.E03.value
        metadata["error_msg"] = f"Expected 4 bands, found {len(boxes)}"

    dbg = debug and stage_input.config.get("segmentation", {}).get("debug_image", False)
    if dbg:
        target_w, target_h = 600, 400
        overlay = cv2.resize(
            image, (target_w, target_h), interpolation=cv2.INTER_NEAREST
        )
        h_img, w_img = image.shape[:2]
        scale_x = target_w / w_img
        rect_th = 2
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        text_th = 1

        for idx, (s, e) in enumerate(segments):
            s_up = int(s * scale_x)
            e_up = int(e * scale_x)

            cv2.rectangle(
                overlay,
                (s_up, 0),
                (e_up - 1, target_h - 1),
                (0, 255, 0),
                rect_th,
                lineType=cv2.LINE_AA,
            )
            cv2.putText(
                overlay,
                f"band_{idx + 1}",
                (s_up + 2, 20),
                font,
                font_scale,
                (0, 0, 255),
                text_th,
                cv2.LINE_AA,
            )

        debug_path = save_image(
            overlay, "segmentation", debug=True, config=stage_input.config, ts=ts
        )
        metadata["debug_image_path"] = str(debug_path) if debug_path else None

    plot_cfg = stage_input.config.get("segmentation", {}) or {}
    if (
        debug
        and bool(plot_cfg.get("create_plot", False))
        and ts is not None
    ):
        ds = dbg_cols["dist_smooth"]
        xl = int(dbg_cols["xl"])
        xr = int(dbg_cols["xr"])
        plot_slice = ds[xl : xr + 1]
        peaks = dbg_cols["peaks_selected"] - xl
        plot_dir = _debug_dir_from_config(stage_input.config)
        plot_dir.mkdir(parents=True, exist_ok=True)
        plot_path = plot_dir / f"{ts}_segmentation_plot.png"
        tw, th = min(600, image.shape[1]), min(400, image.shape[0])
        small_img = cv2.resize(image, (tw, th))
        _save_matplotlib_plot(
            [(plot_slice, "dist_smooth")],
            ["LAB distance (masked)"],
            image=small_img,
            peaks=peaks,
            segments=[(s - xl, e - xl) for s, e in segments],
            out_path=str(plot_path),
        )
        metadata["segmentation_plot_path"] = str(plot_path)

    return SegmentationOutput(
        bounding_boxes=boxes,
        success=success,
        _metadata=metadata,
    )


def classify_bands(
    stage_input: ClassificationInput,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> ClassificationOutput:
    """Classify segmented bands using LAB nearest-reference matching."""
    image = stage_input.image
    boxes = stage_input.bounding_boxes
    if len(boxes) != 4:
        return ClassificationOutput(
            colors=None,
            success=False,
            _metadata={
                "error_code": ErrorCodeEnum.E03.value,
                "error_msg": f"Expected 4 bounding boxes, found {len(boxes)}",
            },
        )

    segments: list[tuple[int, int]] = []
    colors: list[ColorsEnum] = []
    for x0, y0, x1, y1 in boxes:
        x0c, y0c = max(0, x0), max(0, y0)
        x1c, y1c = min(image.shape[1], x1), min(image.shape[0], y1)
        if x1c <= x0c or y1c <= y0c:
            return ClassificationOutput(
                colors=None,
                success=False,
                _metadata={
                    "error_code": ErrorCodeEnum.E04.value,
                    "error_msg": "Invalid bounding box dimensions.",
                },
            )
        segment = image[y0c:y1c, x0c:x1c]
        segments.append((x0c, x1c))
        colors.append(_classify(segment, stage_input.config))

    # Canonical orientation: tolerance band should be last.
    if colors[0] in _TOLERANCE_COLORS and colors[-1] not in _TOLERANCE_COLORS:
        colors = colors[1:] + colors[:1]
        segments = segments[1:] + segments[:1]

    colors_tuple = (colors[0], colors[1], colors[2], colors[3])
    metadata: dict[str, object] = {"segments": segments}

    dbg = debug and stage_input.config.get("classification", {}).get("debug_image", False)
    if dbg:
        target_w, target_h = 600, 400
        overlay = cv2.resize(
            image, (target_w, target_h), interpolation=cv2.INTER_NEAREST
        )
        scale_x = target_w / image.shape[1]
        rect_th = 2
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        text_th = 1
        for (s, e), color in zip(segments, colors):
            s_up = int(s * scale_x)
            e_up = int(e * scale_x)
            cv2.rectangle(
                overlay,
                (s_up, 0),
                (e_up - 1, target_h - 1),
                (0, 255, 0),
                rect_th,
                lineType=cv2.LINE_AA,
            )
            cv2.putText(
                overlay,
                color.value,
                (s_up + 2, 20),
                font,
                font_scale,
                (0, 0, 255),
                text_th,
                cv2.LINE_AA,
            )

        debug_path = save_image(
            overlay,
            "classification",
            debug=True,
            config=stage_input.config,
            ts=ts,
        )
        metadata["debug_image_path"] = str(debug_path) if debug_path else None

    return ClassificationOutput(
        colors=colors_tuple,
        success=True,
        _metadata=metadata,
    )
