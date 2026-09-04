import pytest

from resistor_reader.decode import decode_best, resolve_value
from resistor_reader.models import ColorsEnum, DecodeInput, ErrorCodeEnum

# --- resolve_value ------------------------------------------------------------


@pytest.mark.parametrize(
    "bands, expected",
    [
        ([ColorsEnum.BROWN, ColorsEnum.BLACK, ColorsEnum.BLACK, ColorsEnum.BROWN], 10),
        (
            [ColorsEnum.RED, ColorsEnum.VIOLET, ColorsEnum.YELLOW, ColorsEnum.GOLD],
            270000,
        ),
        ([ColorsEnum.YELLOW, ColorsEnum.VIOLET, ColorsEnum.RED, ColorsEnum.BROWN], 4700),
        ([ColorsEnum.GREEN, ColorsEnum.BLUE, ColorsEnum.ORANGE, ColorsEnum.RED], 56000),
        ([ColorsEnum.BLUE, ColorsEnum.GRAY, ColorsEnum.BLACK, ColorsEnum.BROWN], 68),
        (
            [ColorsEnum.WHITE, ColorsEnum.WHITE, ColorsEnum.WHITE, ColorsEnum.GOLD],
            99_000_000_000,
        ),
        ([ColorsEnum.BLACK, ColorsEnum.BLACK, ColorsEnum.BLACK, ColorsEnum.GOLD], 0),
        ([ColorsEnum.ORANGE, ColorsEnum.ORANGE, ColorsEnum.BLACK, ColorsEnum.GOLD], 33),
    ],
)
def test_resolve_value_basic(bands, expected):
    assert resolve_value(bands) == pytest.approx(float(expected))


@pytest.mark.parametrize(
    "bands, expected",
    [
        ((ColorsEnum.RED, ColorsEnum.RED, ColorsEnum.GOLD, ColorsEnum.BROWN), 2.2),
        ((ColorsEnum.RED, ColorsEnum.RED, ColorsEnum.SILVER, ColorsEnum.BROWN), 0.22),
    ],
)
def test_gold_silver_multipliers(bands, expected):
    assert resolve_value(bands) == pytest.approx(expected)


def test_resolve_requires_four_bands():
    assert resolve_value((ColorsEnum.RED, ColorsEnum.VIOLET, ColorsEnum.YELLOW)) is None
    assert (
        resolve_value(
            (
                ColorsEnum.RED,
                ColorsEnum.VIOLET,
                ColorsEnum.YELLOW,
                ColorsEnum.GOLD,
                ColorsEnum.BROWN,
            )
        )
        is None
    )


def test_resolve_rejects_metallic_digits():
    """Gold is a legal multiplier and tolerance, but never a significant digit."""
    assert (
        resolve_value(
            (ColorsEnum.GOLD, ColorsEnum.VIOLET, ColorsEnum.RED, ColorsEnum.BROWN)
        )
        is None
    )


def test_fourth_band_is_ignored_for_value():
    # Even with an unusual tolerance color, value should still compute:
    # digits 2,7; multiplier 10^3 => 27,000 Ω
    value = resolve_value(
        (ColorsEnum.RED, ColorsEnum.VIOLET, ColorsEnum.ORANGE, ColorsEnum.BROWN)
    )
    assert value == pytest.approx(27000.0)


# --- decode_best --------------------------------------------------------------


def _scores(*winners: ColorsEnum) -> list[dict[ColorsEnum, float]]:
    """Score matrix where each band's named color wins by a wide margin."""
    return [
        {color: (10.0 if color is winner else 0.0) for color in ColorsEnum}
        for winner in winners
    ]


def test_decode_best_reads_unambiguous_bands():
    out = decode_best(
        DecodeInput(
            scores=_scores(
                ColorsEnum.YELLOW, ColorsEnum.VIOLET, ColorsEnum.RED, ColorsEnum.GOLD
            ),
            config={},
        )
    )
    assert out.success
    assert out.resistance == pytest.approx(4700.0)
    assert out.reversed_ is False


def test_decode_best_flips_a_reversed_resistor():
    """Tolerance-band-left must decode to the same value, flagged reversed."""
    out = decode_best(
        DecodeInput(
            scores=_scores(
                ColorsEnum.GOLD, ColorsEnum.RED, ColorsEnum.VIOLET, ColorsEnum.YELLOW
            ),
            config={},
        )
    )
    assert out.success
    assert out.resistance == pytest.approx(4700.0)
    assert out.reversed_ is True


def test_decode_best_requires_four_bands():
    out = decode_best(
        DecodeInput(scores=_scores(ColorsEnum.RED, ColorsEnum.RED), config={})
    )
    assert not out.success
    assert out.error == ErrorCodeEnum.E04


def test_decode_best_rejects_an_illegal_sequence():
    """No legal reading has a tolerance-only color at both ends."""
    out = decode_best(
        DecodeInput(
            scores=_scores(
                ColorsEnum.BLACK, ColorsEnum.BLACK, ColorsEnum.BLACK, ColorsEnum.BLACK
            ),
            config={"decode": {"top_k": 1}},
        )
    )
    assert not out.success
    assert out.error == ErrorCodeEnum.E04
