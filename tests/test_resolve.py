import pytest
from resistor_reader.resolve import resolve_value

import pytest

# Import your function (adjust the import path as needed)
# from your_module import resolve_value

# --- Happy-path tests ---------------------------------------------------------


@pytest.mark.parametrize(
    "bands, expected",
    [
        (["brown", "black", "black", "brown"], 10),  # 10 Ω
        (["red", "violet", "yellow", "gold"], 270000),  # 270 kΩ
        (["yellow", "violet", "red", "brown"], 4700),  # 4.7 kΩ
        (["green", "blue", "orange", "red"], 56000),  # 56 kΩ
        (["blue", "grey", "black", "brown"], 68),  # 68 Ω (grey spelling)
        (["blue", "gray", "black", "brown"], 68),  # 68 Ω (gray spelling)
        (["white", "white", "white", "gold"], 99_000_000_000),  # 99 × 10^9 Ω
        (["black", "black", "black", "gold"], 0),  # 0 Ω (valid code)
    ],
)
def test_resolve_value_basic(bands, expected):
    assert resolve_value(bands) == pytest.approx(float(expected))


@pytest.mark.parametrize(
    "bands, expected",
    [
        (["red", "red", "gold", "brown"], 2.2),  # ×0.1
        (["red", "red", "silver", "brown"], 0.22),  # ×0.01
    ],
)
def test_gold_silver_multipliers(bands, expected):
    assert resolve_value(bands) == pytest.approx(expected)


def test_case_and_whitespace_insensitivity():
    bands = ["  ReD ", "  VIOLET", " yElLoW ", " GoLd "]
    # 27 × 10,000 = 270,000 Ω
    assert resolve_value(bands) == pytest.approx(270000.0)


# --- Error-handling tests -----------------------------------------------------


def test_requires_four_bands():
    with pytest.raises(ValueError):
        resolve_value(["red", "violet", "yellow"])  # only 3

    with pytest.raises(ValueError):
        resolve_value(["red", "violet", "yellow", "gold", "brown"])  # 5 bands


@pytest.mark.parametrize(
    "bad_first_two",
    [
        ["pink", "violet", "yellow", "gold"],  # invalid first
        ["red", "pink", "yellow", "gold"],  # invalid second
        ["pink", "pink", "yellow", "gold"],  # both invalid
    ],
)
def test_invalid_digit_colors(bad_first_two):
    with pytest.raises(ValueError):
        resolve_value(bad_first_two)


def test_invalid_multiplier_color():
    with pytest.raises(ValueError):
        resolve_value(["red", "violet", "pink", "gold"])  # invalid 3rd band


def test_fourth_band_is_ignored_for_value():
    # Even with an unusual tolerance color, value should still compute
    # Here, digits 2,7; multiplier 10^3 => 27,000 Ω
    assert resolve_value(["red", "violet", "orange", "brown"]) == pytest.approx(27000.0)
