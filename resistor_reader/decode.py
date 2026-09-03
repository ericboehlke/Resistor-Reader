"""Constrained decoding of band color scores into a resistance value.

``bands.classify_bands`` produces a score for every color on every band instead
of a hard label.  This module searches over band order and the top few color
candidates per band, keeps only sequences that form a legal 4-band resistor
code, and returns the best-scoring one.

The structural rules are what make orientation work.  A photographed resistor
is just as likely to be tolerance-band-left as tolerance-band-right, and the
band colors themselves are the only cue to which end is which:

* the tolerance band is never black, orange, yellow or white (EIA-RS-279), so
  an end band confidently in that set cannot be the tolerance band;
* the first significant digit is never black (no leading-zero resistors);
* real parts come from the E24 preferred-value series, applied here as a bonus
  rather than a filter so an unusual part still decodes.
"""

from __future__ import annotations

from itertools import product
from typing import Any, Iterable

from .models import (
    BandColorTuple,
    ColorsEnum,
    DecodeInput,
    DecodeOutput,
    ErrorCodeEnum,
    ResolveInput,
)
from .resolve import resolve_value

# EIA-RS-279 tolerance band colors.  Black, orange, yellow and white never
# appear as a tolerance.
TOLERANCE_COLORS: frozenset[ColorsEnum] = frozenset(
    {
        ColorsEnum.GOLD,
        ColorsEnum.SILVER,
        ColorsEnum.BROWN,
        ColorsEnum.RED,
        ColorsEnum.GREEN,
        ColorsEnum.BLUE,
        ColorsEnum.VIOLET,
        ColorsEnum.GRAY,
    }
)

# E24 preferred significant-figure pairs (IEC 60063).
E24_PAIRS: frozenset[int] = frozenset(
    {
        10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30,
        33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91,
    }
)

_DIGITS = [
    ColorsEnum.BLACK,
    ColorsEnum.BROWN,
    ColorsEnum.RED,
    ColorsEnum.ORANGE,
    ColorsEnum.YELLOW,
    ColorsEnum.GREEN,
    ColorsEnum.BLUE,
    ColorsEnum.VIOLET,
    ColorsEnum.GRAY,
    ColorsEnum.WHITE,
]
_DIGIT_OF = {c: i for i, c in enumerate(_DIGITS)}


def _decode_cfg(config: dict[str, Any]) -> dict[str, Any]:
    cfg = config.get("decode", {}) or {}
    return {
        "top_k": max(1, int(cfg.get("top_k", 3))),
        "gold_tolerance_bonus": float(cfg.get("gold_tolerance_bonus", 10.0)),
        "e24_bonus": float(cfg.get("e24_bonus", 8.0)),
        "min_resistance": float(cfg.get("min_resistance", 0.1)),
        "max_resistance": float(cfg.get("max_resistance", 1e8)),
    }


def _top_candidates(
    scores: dict[ColorsEnum, float], k: int
) -> list[tuple[ColorsEnum, float]]:
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]


def _sequence_prior(colors: BandColorTuple, cfg: dict[str, Any]) -> float | None:
    """Return the prior score for a band sequence, or ``None`` if illegal."""
    if colors[3] not in TOLERANCE_COLORS:
        return None
    if colors[0] not in _DIGIT_OF or colors[1] not in _DIGIT_OF:
        return None
    if colors[0] == ColorsEnum.BLACK:
        return None
    prior = 0.0
    if colors[3] == ColorsEnum.GOLD:
        prior += cfg["gold_tolerance_bonus"]
    pair = _DIGIT_OF[colors[0]] * 10 + _DIGIT_OF[colors[1]]
    if pair in E24_PAIRS:
        prior += cfg["e24_bonus"]
    return prior


def _hypotheses(
    scores: list[dict[ColorsEnum, float]], cfg: dict[str, Any]
) -> Iterable[tuple[float, BandColorTuple, bool]]:
    """Yield ``(score, colors, reversed_)`` for every legal band assignment."""
    for reversed_ in (False, True):
        ordered = list(reversed(scores)) if reversed_ else list(scores)
        per_band = [_top_candidates(s, cfg["top_k"]) for s in ordered]
        for combo in product(*per_band):
            colors = tuple(c for c, _ in combo)
            prior = _sequence_prior(colors, cfg)
            if prior is None:
                continue
            total = sum(v for _, v in combo) + prior
            yield total, colors, reversed_


def decode_best(stage_input: DecodeInput) -> DecodeOutput:
    """Pick the highest-scoring legal band sequence and resolve its value."""
    scores = stage_input.scores
    if len(scores) != 4:
        return DecodeOutput(
            resistance=None,
            colors=None,
            reversed_=False,
            confidence=0.0,
            success=False,
            _metadata={
                "error_code": ErrorCodeEnum.E04.value,
                "error_msg": f"Expected 4 band scores, found {len(scores)}",
            },
        )

    cfg = _decode_cfg(stage_input.config)
    best: tuple[float, BandColorTuple, bool, float] | None = None
    runner_up = float("-inf")

    for total, colors, reversed_ in _hypotheses(scores, cfg):
        resolved = resolve_value(ResolveInput(colors=colors, config=stage_input.config))
        if not resolved.success or resolved.resistance is None:
            continue
        value = resolved.resistance
        if not (cfg["min_resistance"] <= value <= cfg["max_resistance"]):
            continue
        if best is None or total > best[0]:
            if best is not None and best[3] != value:
                runner_up = max(runner_up, best[0])
            best = (total, colors, reversed_, value)
        elif value != best[3]:
            runner_up = max(runner_up, total)

    if best is None:
        return DecodeOutput(
            resistance=None,
            colors=None,
            reversed_=False,
            confidence=0.0,
            success=False,
            _metadata={
                "error_code": ErrorCodeEnum.E04.value,
                "error_msg": "No valid band sequence.",
            },
        )

    total, colors, reversed_, value = best
    confidence = float(total - runner_up) if runner_up > float("-inf") else float("inf")
    return DecodeOutput(
        resistance=value,
        colors=colors,
        reversed_=reversed_,
        confidence=confidence,
        success=True,
        _metadata={"score": total, "runner_up": runner_up},
    )
