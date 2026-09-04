"""Band segmentation and color classification.

The resistor is assumed to be already cropped and aligned horizontally.
Segmentation builds a per-column "bandness" profile from two cues -- distance
from the resistor body color, and excess specular texture -- then extracts the
four bands as connected runs above an adaptive threshold, falling back to
greedy peak claiming for bands the threshold misses.  Classification
returns a score for every color rather than a hard label, so the decoder in
``decode.py`` can search over color hypotheses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import cv2
import numpy as np

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
    name: cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)
    for name, rgb in COLOR_RGB.items()
}


def _segmentation_cfg(config: dict[str, Any]) -> dict[str, Any]:
    seg = config.get("segmentation", {}) or {}
    k = int(seg.get("band_smooth_window", 7))
    if k % 2 == 0:
        k += 1
    k = max(1, k)
    return {
        "band_smooth_window": k,
        "min_band_width_px": max(1, int(seg.get("min_band_width_px", 5))),
        "edge_margin": max(0, int(seg.get("edge_margin", 4))),
        "max_band_width_ratio": float(seg.get("max_band_width_ratio", 0.35)),
        "strip_top": float(seg.get("strip_top", 0.28)),
        "strip_bottom": float(seg.get("strip_bottom", 0.74)),
        "matte_keep_ratio": float(seg.get("matte_keep_ratio", 0.70)),
        "texture_weight": float(seg.get("texture_weight", 1.0)),
        "texture_cap": float(seg.get("texture_cap", 25.0)),
        "highlight_ratio": float(seg.get("highlight_ratio", 0.15)),
        "chroma_gate_low": float(seg.get("chroma_gate_low", 70.0)),
        "chroma_gate_high": float(seg.get("chroma_gate_high", 110.0)),
        "min_band_separation_px": max(1, int(seg.get("min_band_separation_px", 9))),
        "thr_frac_min": float(seg.get("thr_frac_min", 0.20)),
        "thr_frac_max": float(seg.get("thr_frac_max", 0.75)),
        "thr_frac_step": float(seg.get("thr_frac_step", 0.025)),
        "peak_extent_frac": float(seg.get("peak_extent_frac", 0.45)),
        "peak_rise_tol": float(seg.get("peak_rise_tol", 0.15)),
        "min_signal": float(seg.get("min_signal", 5.0)),
        "end_pin_ratio": float(seg.get("end_pin_ratio", 0.04)),
        "upsample": max(1, int(seg.get("upsample", 4))),
    }


def _classification_cfg(config: dict[str, Any]) -> dict[str, Any]:
    cls = config.get("classification", {}) or {}
    return {
        "strip_top": float(cls.get("strip_top", 0.25)),
        "strip_bottom": float(cls.get("strip_bottom", 0.75)),
        "matte_keep_ratio": float(cls.get("matte_keep_ratio", 0.70)),
        "metallic_gain": float(cls.get("metallic_gain", 26.0)),
        "metallic_offset": float(cls.get("metallic_offset", 34.0)),
        "metallic_scale": float(cls.get("metallic_scale", 22.0)),
        "metallic_min_value": float(cls.get("metallic_min_value", 70.0)),
        "highlight_ratio": float(cls.get("highlight_ratio", 0.15)),
        "chroma_gate_low": float(cls.get("chroma_gate_low", 70.0)),
        "chroma_gate_high": float(cls.get("chroma_gate_high", 110.0)),
        "metallic_max_hue": float(cls.get("metallic_max_hue", 28.0)),
        "silver_max_sat": float(cls.get("silver_max_sat", 70.0)),
    }


def _debug_dir_from_config(config: dict[str, Any]) -> Path:
    return Path(config.get("runtime", {}).get("debug", {}).get("dir", "logs"))


def _save_matplotlib_plot(
    curves,
    titles,
    image=None,
    peaks=None,
    segments=None,
    threshold=None,
    out_path="segmentation_debug.png",
):
    """Save a stacked plot of the segmentation profile for interactive tuning.

    curves: list of (y_values, label) where y_values is 1D numpy array
    titles: list of subtitles for each curve panel
    image:  optional RGB image to show at top
    peaks:  optional 1D array of marker x positions on the last curve
    segments: optional list of (L, R) to shade on the last curve
    threshold: optional y value to draw as a horizontal line on the last curve
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
        if row == n_rows:
            if segments is not None:
                for L, R in segments:
                    ax.axvspan(L, R, alpha=0.2, color="tab:orange")
            if threshold is not None:
                ax.axhline(threshold, color="tab:green", ls="--", lw=1, label="threshold")
            if peaks is not None and len(peaks):
                ax.scatter(peaks, y[peaks], s=20, color="tab:red", zorder=3, label="centers")
            ax.legend(loc="upper right")
        row += 1

    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------


def _strip_bounds(height: int, top: float, bottom: float) -> tuple[int, int]:
    y0 = int(height * top)
    y1 = int(height * bottom)
    if y1 - y0 < 3:
        y0, y1 = 0, height
    return y0, y1


def _matte_mean(values: np.ndarray, order: np.ndarray) -> np.ndarray:
    """Mean over the rows selected by ``order`` for each column."""
    return np.take_along_axis(values, order, axis=0).mean(axis=0)


def _band_profile(
    image: np.ndarray, body_mask: np.ndarray, cfg: dict[str, Any]
) -> dict[str, Any]:
    """Build the per-column bandness signal plus the body color reference."""
    h, w = image.shape[:2]
    if body_mask.shape != (h, w):
        raise ValueError("body_mask must match image HxW")

    col_sum = (body_mask > 0).sum(axis=0)
    xs = np.where(col_sum > 0)[0]
    if xs.size == 0:
        raise ValueError("empty body mask")
    em = int(cfg["edge_margin"])
    xl = int(xs.min()) + em
    xr = int(xs.max()) - em
    if xl >= xr:
        raise ValueError("edge margin too large for body mask")

    y0, y1 = _strip_bounds(h, cfg["strip_top"], cfg["strip_bottom"])
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB).astype(np.float32)[y0:y1]
    sat = cv2.cvtColor(image, cv2.COLOR_RGB2HSV).astype(np.float32)[y0:y1, :, 1]
    lum = lab[:, :, 0]
    rows = lum.shape[0]

    # Column color from the darkest rows only: specular highlights sit on top of
    # every band and would otherwise drag the mean toward white.
    keep = max(1, round(cfg["matte_keep_ratio"] * rows))
    order = np.argsort(lum, axis=0)
    prof = np.stack([_matte_mean(lab[:, :, c], order[:keep]) for c in range(3)], axis=1)

    # Texture: metallic (gold/silver) bands sparkle, matte bands do not.  Plain
    # body glare sparkles just as hard, so gate the texture on the highlight
    # being chromatic -- a metallic sparkle stays saturated gold, a specular
    # reflection off the beige body washes out to near-white.
    tex = np.percentile(lum, 92, axis=0) - np.percentile(lum, 50, axis=0)
    n_hi = max(1, round(cfg["highlight_ratio"] * rows))
    sat_hi = _matte_mean(sat, order[-n_hi:])
    gate = np.clip(
        (sat_hi - cfg["chroma_gate_low"])
        / max(1e-6, cfg["chroma_gate_high"] - cfg["chroma_gate_low"]),
        0.0,
        1.0,
    )
    tex = tex * gate

    sub = prof[xl : xr + 1]
    med = np.median(sub, axis=0)
    spread = np.linalg.norm(sub - med, axis=1)
    inner = sub[spread <= np.percentile(spread, 50)]
    body_lab = np.median(inner if len(inner) else sub, axis=0)
    body_tex = float(np.median(tex[xl : xr + 1]))

    dist = np.linalg.norm(prof - body_lab, axis=1)
    # Cap the metallic boost: it exists to make a gold band visible at all, not
    # to let it tower over the others and drag the detection threshold with it.
    boost = np.minimum(np.maximum(0.0, tex - body_tex), cfg["texture_cap"])
    signal = dist + cfg["texture_weight"] * boost
    signal = cv2.GaussianBlur(
        signal[None, :].astype(np.float32), (1, int(cfg["band_smooth_window"])), 0
    ).ravel()
    signal[:xl] = 0.0
    signal[xr + 1 :] = 0.0

    return {
        "signal": signal,
        "xl": xl,
        "xr": xr,
        "body_lab": body_lab,
        "body_tex": body_tex,
        "dist": dist,
        "tex": tex,
    }


def _runs_above(on: np.ndarray, min_width: int) -> list[tuple[int, int]]:
    """Return ``(start, end)`` half-open runs of True at least ``min_width`` wide."""
    flags = np.concatenate(([0], on.astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(flags))
    return [
        (int(s), int(e))
        for s, e in zip(edges[0::2], edges[1::2])
        if e - s >= min_width
    ]


def _expand_peak(
    signal: np.ndarray,
    centre: int,
    taken: np.ndarray,
    lo: int,
    hi: int,
    frac: float,
    rise_tol: float,
) -> tuple[int, int]:
    """Grow a band outward from ``centre`` down to ``frac`` of its own height.

    Growth also stops once the signal climbs back up by more than ``rise_tol``
    of the peak above the lowest point seen so far -- that upturn is the near
    edge of the neighbouring band.  Tracking the running minimum rather than
    demanding a monotonic descent lets a band with a flat or noisy top expand to
    its full width instead of leaving a shoulder behind for the next iteration
    to claim as a phantom band.
    """
    peak = float(signal[centre])
    level = frac * peak
    rise = rise_tol * peak
    bounds = []
    for step, limit in ((-1, lo), (1, hi)):
        edge = centre
        run_min = peak
        j = centre
        while True:
            nxt = j + step
            if step < 0 and nxt < limit:
                break
            if step > 0 and nxt > limit:
                break
            if taken[nxt]:
                break
            value = float(signal[nxt])
            if value <= level or value > run_min + rise:
                break
            run_min = min(run_min, value)
            j = nxt
            edge = j
        bounds.append(edge)
    return bounds[0], bounds[1]


def _claim_peak(
    signal: np.ndarray,
    taken: np.ndarray,
    lo: int,
    hi: int,
    cfg: dict[str, Any],
    min_w: int,
) -> tuple[int, int] | None:
    """Claim the strongest unclaimed peak as a band, or ``None`` if none is left."""
    free = np.where(~taken)[0]
    if free.size == 0:
        return None
    centre = int(free[np.argmax(signal[free])])
    if float(signal[centre]) < cfg["min_signal"]:
        return None
    left, right = _expand_peak(
        signal, centre, taken, lo, hi, cfg["peak_extent_frac"], cfg["peak_rise_tol"]
    )
    if right - left + 1 < min_w:
        half = min_w // 2
        left = max(lo, centre - half)
        right = min(hi, left + min_w - 1)
    return left, right + 1


def _extract_bands(
    signal: np.ndarray, xl: int, xr: int, cfg: dict[str, Any], scale: int
) -> tuple[list[tuple[int, int]], float]:
    """Return four column runs covering the bands, and the signal level used.

    Thresholding the signal finds cleanly separated bands well, but no single
    cut-off spans the dynamic range: a metallic band scores several times higher
    than a gray band sitting next to the beige body, so a threshold low enough to
    keep the weak one merges the strong one with its neighbours.  So sweep for a
    threshold that yields exactly four runs, and when none does, keep the runs
    the sweep did find and fill the remainder by claiming the strongest peaks in
    the columns left over.  Filling never subdivides a run that was already
    found, which is what keeps two boxes from landing on the same band.
    """
    min_w = max(1, round(cfg["min_band_width_px"] * scale))
    guard = max(1, round(cfg["min_band_separation_px"] * scale))
    pin = round(cfg["end_pin_ratio"] * (xr - xl + 1))
    lo, hi = xl + pin, xr - pin
    if hi - lo < 4 * min_w:
        lo, hi = xl, xr

    fracs = np.arange(cfg["thr_frac_min"], cfg["thr_frac_max"], cfg["thr_frac_step"])
    peak97 = float(np.percentile(signal[lo : hi + 1], 97))
    partial: list[tuple[int, int]] = []
    partial_level = cfg["min_signal"]
    crowded: list[tuple[int, int]] | None = None
    crowded_level = cfg["min_signal"]
    for frac in fracs:
        mask = signal > max(frac * peak97, cfg["min_signal"])
        mask[:lo] = False
        mask[hi + 1 :] = False
        runs = _runs_above(mask, min_w)
        level = max(float(frac) * peak97, cfg["min_signal"])
        if len(runs) == 4:
            return runs, level
        if len(runs) < 4:
            if len(runs) > len(partial):
                partial, partial_level = runs, level
        elif crowded is None:
            crowded, crowded_level = runs, level

    if not partial and crowded is not None:
        # Every threshold over-segments: keep the strongest four runs.
        runs = sorted(crowded, key=lambda r: float(signal[r[0] : r[1]].sum()))[-4:]
        return sorted(runs), crowded_level

    runs = list(partial)
    taken = np.zeros(signal.shape[0], dtype=bool)
    taken[:lo] = True
    taken[hi + 1 :] = True
    for a, b in runs:
        taken[max(0, a - guard) : b + guard] = True
    while len(runs) < 4:
        claimed = _claim_peak(signal, taken, lo, hi, cfg, min_w)
        if claimed is None:
            raise ValueError(f"expected 4 bands, found {len(runs)}")
        a, b = claimed
        runs.append((a, b))
        taken[max(0, a - guard) : b + guard] = True
    runs.sort()
    return runs, partial_level


def _segment_columns(
    image: np.ndarray,
    body_mask: np.ndarray,
    cfg: dict[str, Any],
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    """Return column ranges ``(start, end)`` with ``end`` exclusive; plus debug arrays."""
    prof = _band_profile(image, body_mask, cfg)
    signal, xl, xr = prof["signal"], prof["xl"], prof["xr"]
    w = signal.shape[0]

    # Sub-pixel boundaries: the ROI is only ~160px wide, so a band edge lands
    # between samples.  Interpolating before thresholding recovers that.
    up = int(cfg["upsample"])
    if up > 1:
        grid = np.linspace(0.0, w - 1.0, (w - 1) * up + 1)
        sig_up = np.interp(grid, np.arange(w, dtype=np.float64), signal)
        runs_up, thr = _extract_bands(sig_up, xl * up, xr * up, cfg, up)
        runs = [
            (int(np.floor(s / up)), max(int(np.ceil(e / up)), int(np.floor(s / up)) + 1))
            for s, e in runs_up
        ]
    else:
        runs, thr = _extract_bands(signal, xl, xr, cfg, 1)
        sig_up = signal

    # Cap absurdly wide bands around their center of mass.
    max_w = max(1, int(cfg["max_band_width_ratio"] * (xr - xl + 1)))
    capped: list[tuple[int, int]] = []
    for s, e in runs:
        if e - s > max_w:
            weights = signal[s:e]
            centre = s + round(float(np.average(np.arange(e - s), weights=weights)))
            half = max_w // 2
            s = max(xl, centre - half)
            e = min(xr + 1, s + max_w)
        capped.append((int(s), int(e)))
    capped.sort()

    centers = np.array([(s + e) // 2 for s, e in capped], dtype=np.int32)
    debug_info: dict[str, Any] = {
        "signal": signal,
        "signal_up": sig_up,
        "threshold": thr,
        "upsample": up,
        "xl": xl,
        "xr": xr,
        "peaks_selected": centers,
        "body_lab": prof["body_lab"],
        "body_tex": prof["body_tex"],
    }
    return capped, debug_info


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _band_scores(
    segment: np.ndarray, body_tex: float, cfg: dict[str, Any]
) -> tuple[dict[ColorsEnum, float], dict[str, float]]:
    """Return a score per color (higher is better) plus the raw band features."""
    h = segment.shape[0]
    y0, y1 = _strip_bounds(h, cfg["strip_top"], cfg["strip_bottom"])
    central = segment[y0:y1]
    pixels = central.reshape(-1, 3)
    if pixels.shape[0] == 0:
        pixels = segment.reshape(-1, 3)

    px = pixels.reshape(-1, 1, 3).astype(np.uint8)
    lab = cv2.cvtColor(px, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    hsv = cv2.cvtColor(px, cv2.COLOR_RGB2HSV).reshape(-1, 3).astype(np.float32)
    hue, sat, val = hsv[:, 0], hsv[:, 1], hsv[:, 2]

    order = np.argsort(val)
    keep = max(1, round(cfg["matte_keep_ratio"] * len(val)))
    mean_lab = np.median(lab[order[:keep]], axis=0)

    n_hi = max(1, round(cfg["highlight_ratio"] * len(val)))
    sat_hi = float(np.mean(sat[order[-n_hi:]]))
    gate = float(
        np.clip(
            (sat_hi - cfg["chroma_gate_low"])
            / max(1e-6, cfg["chroma_gate_high"] - cfg["chroma_gate_low"]),
            0.0,
            1.0,
        )
    )
    features = {
        "spread": gate * float(np.percentile(val, 95) - np.percentile(val, 50)),
        "sat_hi": sat_hi,
        "hue": float(np.median(hue)),
        "sat": float(np.median(sat)),
        "value": float(np.median(val)),
    }

    scores = {
        name: -float(np.linalg.norm(mean_lab - ref)) for name, ref in _REF_LAB.items()
    }

    # Metallic cue.  Gold and silver carry their identity in the specular
    # sparkle, which the matte median above deliberately discards; without this
    # term a gold band is indistinguishable from brown.
    excess = features["spread"] - body_tex - cfg["metallic_offset"]
    metallic = cfg["metallic_gain"] * float(
        np.clip(excess / cfg["metallic_scale"], -1.0, 1.0)
    )
    bright = features["value"] >= cfg["metallic_min_value"]
    warm = features["hue"] <= cfg["metallic_max_hue"] or features["hue"] >= 170.0
    if bright and warm:
        scores[ColorsEnum.GOLD] += metallic
    else:
        scores[ColorsEnum.GOLD] -= abs(metallic)
    if bright and features["sat"] <= cfg["silver_max_sat"]:
        scores[ColorsEnum.SILVER] += metallic
    else:
        scores[ColorsEnum.SILVER] -= abs(metallic)

    return scores, features


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
        return SegmentationOutput(error=ErrorCodeEnum.E03, error_msg=str(exc))

    # ``_extract_bands`` returns exactly four runs or raises, so reaching here
    # means four boxes.
    h = image.shape[0]
    boxes: list[BandBoundingBox] = [(int(s), 0, int(e), int(h)) for s, e in segments]
    metadata: dict[str, object] = {
        "raw_segments": segments,
        "body_lab": [float(v) for v in dbg_cols["body_lab"]],
        "threshold": float(dbg_cols["threshold"]),
    }

    overlay: np.ndarray | None = None
    dbg = debug and stage_input.config.get("segmentation", {}).get("debug_image", False)
    if dbg:
        overlay = _annotate(
            image, segments, [f"band_{i + 1}" for i in range(len(segments))]
        )
        debug_path = save_image(
            overlay, "segmentation", debug=True, config=stage_input.config, ts=ts
        )
        metadata["debug_image_path"] = str(debug_path) if debug_path else None

    plot_cfg = stage_input.config.get("segmentation", {}) or {}
    if debug and bool(plot_cfg.get("create_plot", False)) and ts is not None:
        sig = dbg_cols["signal"]
        xl = int(dbg_cols["xl"])
        xr = int(dbg_cols["xr"])
        plot_dir = _debug_dir_from_config(stage_input.config)
        plot_dir.mkdir(parents=True, exist_ok=True)
        plot_path = plot_dir / f"{ts}_segmentation_plot.png"
        tw, th = min(600, image.shape[1]), min(400, image.shape[0])
        _save_matplotlib_plot(
            [(sig[xl : xr + 1], "bandness")],
            ["LAB distance from body + specular texture"],
            image=cv2.resize(image, (tw, th)),
            peaks=dbg_cols["peaks_selected"] - xl,
            segments=[(s - xl, e - xl) for s, e in segments],
            threshold=dbg_cols["threshold"],
            out_path=str(plot_path),
        )
        metadata["segmentation_plot_path"] = str(plot_path)

    return SegmentationOutput(
        bounding_boxes=boxes,
        body_tex=float(dbg_cols["body_tex"]),
        debug_overlay=overlay,
        _metadata=metadata,
    )


def _annotate(
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


def classify_bands(
    stage_input: ClassificationInput,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> ClassificationOutput:
    """Score each band against every reference color.

    Returns one score per color per band, in left-to-right image order.  No hard
    label and no orientation fix is applied here -- ``decode.decode_best``
    chooses both the band order and the labels from the full score matrix
    together with the resistor color code rules.
    """
    image = stage_input.image
    boxes = stage_input.bounding_boxes
    if len(boxes) != 4:
        return ClassificationOutput(
            error=ErrorCodeEnum.E03,
            error_msg=f"Expected 4 bounding boxes, found {len(boxes)}",
        )

    cfg = _classification_cfg(stage_input.config)
    body_tex = float(stage_input.body_tex)

    segments: list[tuple[int, int]] = []
    scores: list[dict[ColorsEnum, float]] = []
    features: list[dict[str, float]] = []
    for x0, y0, x1, y1 in boxes:
        x0c, y0c = max(0, x0), max(0, y0)
        x1c, y1c = min(image.shape[1], x1), min(image.shape[0], y1)
        if x1c <= x0c or y1c <= y0c:
            return ClassificationOutput(
                error=ErrorCodeEnum.E04,
                error_msg="Invalid bounding box dimensions.",
            )
        band_scores, band_feats = _band_scores(image[y0c:y1c, x0c:x1c], body_tex, cfg)
        segments.append((x0c, x1c))
        scores.append(band_scores)
        features.append(band_feats)

    metadata: dict[str, object] = {"segments": segments, "features": features}

    overlay: np.ndarray | None = None
    dbg = debug and stage_input.config.get("classification", {}).get(
        "debug_image", False
    )
    if dbg:
        # The arg-max label is the decoder's starting point, not its answer, but
        # it is the useful thing to draw on a debug overlay.
        labels = [max(s, key=s.get).value for s in scores]
        overlay = _annotate(image, segments, labels)
        debug_path = save_image(
            overlay, "classification", debug=True, config=stage_input.config, ts=ts
        )
        metadata["debug_image_path"] = str(debug_path) if debug_path else None

    return ClassificationOutput(
        scores=scores, debug_overlay=overlay, _metadata=metadata
    )
