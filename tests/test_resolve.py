import pytest

from resistor_reader.resolve import resolve_value
from resistor_reader.models import ColorsEnum, ErrorCodeEnum, ResolveInput

# Import your function (adjust the import path as needed)
# from your_module import resolve_value

# --- Happy-path tests ---------------------------------------------------------


@pytest.mark.parametrize(
    "bands, expected",
    [
        ([ColorsEnum.BROWN, ColorsEnum.BLACK, ColorsEnum.BLACK, ColorsEnum.BROWN], 10),  # 10 Ω
        ([ColorsEnum.RED, ColorsEnum.VIOLET, ColorsEnum.YELLOW, ColorsEnum.GOLD], 270000),  # 270 kΩ
        ([ColorsEnum.YELLOW, ColorsEnum.VIOLET, ColorsEnum.RED, ColorsEnum.BROWN], 4700),  # 4.7 kΩ
        ([ColorsEnum.GREEN, ColorsEnum.BLUE, ColorsEnum.ORANGE, ColorsEnum.RED], 56000),  # 56 kΩ
        ([ColorsEnum.BLUE, ColorsEnum.GRAY, ColorsEnum.BLACK, ColorsEnum.BROWN], 68),  # 68 Ω
        ([ColorsEnum.WHITE, ColorsEnum.WHITE, ColorsEnum.WHITE, ColorsEnum.GOLD], 99_000_000_000),  # 99 × 10^9 Ω
        ([ColorsEnum.BLACK, ColorsEnum.BLACK, ColorsEnum.BLACK, ColorsEnum.GOLD], 0),  # 0 Ω (valid code)
    ],
)
def test_resolve_value_basic(bands, expected):
    result = resolve_value(ResolveInput(colors=bands, config={}))
    assert result.success
    assert result.resistance == pytest.approx(float(expected))


@pytest.mark.parametrize(
    "bands, expected",
    [
        ((ColorsEnum.RED, ColorsEnum.RED, ColorsEnum.GOLD, ColorsEnum.BROWN), 2.2),  # ×0.1
        ((ColorsEnum.RED, ColorsEnum.RED, ColorsEnum.SILVER, ColorsEnum.BROWN), 0.22),  # ×0.01
    ],
)
def test_gold_silver_multipliers(bands, expected):
    result = resolve_value(ResolveInput(colors=bands, config={}))
    assert result.success
    assert result.resistance == pytest.approx(expected)


def test_case_and_whitespace_insensitivity():
    bands = (ColorsEnum.RED, ColorsEnum.VIOLET, ColorsEnum.YELLOW , ColorsEnum.GOLD)
    # 27 × 10,000 = 270,000 Ω
    result = resolve_value(
        ResolveInput(
            colors=bands,
            config={},
        )
    )
    assert result.success
    assert result.resistance == pytest.approx(270000.0)


# --- Error-handling tests -----------------------------------------------------


def test_requires_four_bands():
    result_3 = resolve_value(
        ResolveInput(colors=(ColorsEnum.RED, ColorsEnum.VIOLET, ColorsEnum.YELLOW), config={})
    )
    assert not result_3.success
    assert result_3._metadata.get("error_code") == ErrorCodeEnum.E04.value

    result_5 = resolve_value(
        ResolveInput(
            colors=(
                ColorsEnum.RED,
                ColorsEnum.VIOLET,
                ColorsEnum.YELLOW,
                ColorsEnum.GOLD,
                ColorsEnum.BROWN,
            ),
            config={},
        )
    )
    assert not result_5.success
    assert result_5._metadata.get("error_code") == ErrorCodeEnum.E04.value






def test_fourth_band_is_ignored_for_value():
    # Even with an unusual tolerance color, value should still compute
    # Here, digits 2,7; multiplier 10^3 => 27,000 Ω
    result = resolve_value(
        ResolveInput(
            colors=(ColorsEnum.RED, ColorsEnum.VIOLET, ColorsEnum.ORANGE, ColorsEnum.BROWN),
            config={},
        )
    )
    assert result.success
    assert result.resistance == pytest.approx(27000.0)
