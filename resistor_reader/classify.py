"""Colour classification: score each band against every reference colour.

Scores rather than hard labels, so ``decode.decode_best`` can search over colour
hypotheses with the resistor colour-code rules in hand.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from .imageops import annotate_bands, strip_bounds
from .logging_utils import save_image
from .models import (
    ClassificationInput,
    ClassificationOutput,
    ColorsEnum,
    ErrorCodeEnum,
)

COLOR_RGB: dict[ColorsEnum, tuple[int, int, int]] = {
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


def _band_scores(
    segment: np.ndarray, body_tex: float, cfg: dict[str, Any]
) -> tuple[dict[ColorsEnum, float], dict[str, float]]:
    """Return a score per color (higher is better) plus the raw band features."""
    h = segment.shape[0]
    y0, y1 = strip_bounds(h, cfg["strip_top"], cfg["strip_bottom"])
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
        overlay = annotate_bands(image, segments, labels)
        debug_path = save_image(
            overlay, "classification", debug=True, config=stage_input.config, ts=ts
        )
        metadata["debug_image_path"] = str(debug_path) if debug_path else None

    return ClassificationOutput(
        scores=scores, debug_overlay=overlay, _metadata=metadata
    )
