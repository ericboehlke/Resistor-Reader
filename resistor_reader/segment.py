"""Band segmentation: find the four colour bands on a cropped resistor.

The resistor is assumed to be already cropped and aligned horizontally.  A
per-column "bandness" profile is built from two cues -- distance from the
resistor body colour, and excess specular texture -- and the four bands are
extracted as connected runs above an adaptive threshold, falling back to greedy
peak claiming for bands the threshold misses.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from .imageops import annotate_bands, matte_mean, strip_bounds
from .logging_utils import save_image
from .models import (
    BandBoundingBox,
    ErrorCodeEnum,
    SegmentationInput,
    SegmentationOutput,
)


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

    y0, y1 = strip_bounds(h, cfg["strip_top"], cfg["strip_bottom"])
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB).astype(np.float32)[y0:y1]
    sat = cv2.cvtColor(image, cv2.COLOR_RGB2HSV).astype(np.float32)[y0:y1, :, 1]
    lum = lab[:, :, 0]
    rows = lum.shape[0]

    # Column color from the darkest rows only: specular highlights sit on top of
    # every band and would otherwise drag the mean toward white.
    keep = max(1, round(cfg["matte_keep_ratio"] * rows))
    order = np.argsort(lum, axis=0)
    prof = np.stack([matte_mean(lab[:, :, c], order[:keep]) for c in range(3)], axis=1)

    # Texture: metallic (gold/silver) bands sparkle, matte bands do not.  Plain
    # body glare sparkles just as hard, so gate the texture on the highlight
    # being chromatic -- a metallic sparkle stays saturated gold, a specular
    # reflection off the beige body washes out to near-white.
    tex = np.percentile(lum, 92, axis=0) - np.percentile(lum, 50, axis=0)
    n_hi = max(1, round(cfg["highlight_ratio"] * rows))
    sat_hi = matte_mean(sat, order[-n_hi:])
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
        overlay = annotate_bands(
            image, segments, [f"band_{i + 1}" for i in range(len(segments))]
        )
        debug_path = save_image(
            overlay, "segmentation", debug=True, config=stage_input.config, ts=ts
        )
        metadata["debug_image_path"] = str(debug_path) if debug_path else None

    return SegmentationOutput(
        bounding_boxes=boxes,
        body_tex=float(dbg_cols["body_tex"]),
        debug_overlay=overlay,
        _metadata=metadata,
    )

