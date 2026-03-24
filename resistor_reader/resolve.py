"""Resolve the value of resistors given a list of 4 band colors."""

from __future__ import annotations

from .models import ColorsEnum, ErrorCodeEnum, ResolveInput, ResolveOutput

DIGIT_MAP = {
    ColorsEnum.BLACK: 0,
    ColorsEnum.BROWN: 1,
    ColorsEnum.RED: 2,
    ColorsEnum.ORANGE: 3,
    ColorsEnum.YELLOW: 4,
    ColorsEnum.GREEN: 5,
    ColorsEnum.BLUE: 6,
    ColorsEnum.VIOLET: 7,
    ColorsEnum.GRAY: 8,
    ColorsEnum.WHITE: 9,
}

MULTIPLIER_MAP = {
    ColorsEnum.BLACK: 1,
    ColorsEnum.BROWN: 10,
    ColorsEnum.RED: 100,
    ColorsEnum.ORANGE: 1_000,
    ColorsEnum.YELLOW: 10_000,
    ColorsEnum.GREEN: 100_000,
    ColorsEnum.BLUE: 1_000_000,
    ColorsEnum.VIOLET: 10_000_000,
    ColorsEnum.GRAY: 100_000_000,
    ColorsEnum.WHITE: 1_000_000_000,
    ColorsEnum.GOLD: 0.1,
    ColorsEnum.SILVER: 0.01,
}


def resolve_value(stage_input: ResolveInput) -> ResolveOutput:
    """Decode 4-band colors to resistance in ohms."""
    band_colors = stage_input.colors
    if len(band_colors) != 4:
        return ResolveOutput(
            resistance=None,
            success=False,
            _metadata={
                "error_code": ErrorCodeEnum.E04.value,
                "error_msg": "Expected 4 color bands.",
            },
        )

    if band_colors[0] not in DIGIT_MAP or band_colors[1] not in DIGIT_MAP:
        return ResolveOutput(
            resistance=None,
            success=False,
            _metadata={
                "error_code": ErrorCodeEnum.E04.value,
                "error_msg": "Invalid digit color.",
            },
        )
    if band_colors[2] not in MULTIPLIER_MAP:
        return ResolveOutput(
            resistance=None,
            success=False,
            _metadata={
                "error_code": ErrorCodeEnum.E04.value,
                "error_msg": "Invalid multiplier color.",
            },
        )

    first_digit = DIGIT_MAP[band_colors[0]]
    second_digit = DIGIT_MAP[band_colors[1]]
    multiplier = MULTIPLIER_MAP[band_colors[2]]
    resistance = float((first_digit * 10 + second_digit) * multiplier)
    return ResolveOutput(
        resistance=resistance,
        success=True,
        _metadata={},
    )
