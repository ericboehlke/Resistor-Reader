"""Resolve the value of resistors given a list of 4 band colors."""

# Digit and multiplier color codes
DIGIT_MAP = {
    "black": 0,
    "brown": 1,
    "red": 2,
    "orange": 3,
    "yellow": 4,
    "green": 5,
    "blue": 6,
    "violet": 7,
    "grey": 8,
    "gray": 8,
    "white": 9,
}

MULTIPLIER_MAP = {
    "black": 1,
    "brown": 10,
    "red": 100,
    "orange": 1_000,
    "yellow": 10_000,
    "green": 100_000,
    "blue": 1_000_000,
    "violet": 10_000_000,
    "grey": 100_000_000,
    "gray": 100_000_000,
    "white": 1_000_000_000,
    "gold": 0.1,
    "silver": 0.01,
}


def resolve_value(band_colors: list[str]) -> float:
    """Use the standard 4-band color code to decode band colors to a resistance value in ohms."""

    # Tolerance is usually the 4th band, but here we just resolve value in ohms
    if len(band_colors) != 4:
        raise ValueError("Expected 4 color bands.")

    band_colors = [c.strip().lower() for c in band_colors]

    # First two bands are digits
    if band_colors[0] not in DIGIT_MAP or band_colors[1] not in DIGIT_MAP:
        raise ValueError("Invalid digit color.")

    first_digit = DIGIT_MAP[band_colors[0]]
    second_digit = DIGIT_MAP[band_colors[1]]

    # Third band is multiplier
    if band_colors[2] not in MULTIPLIER_MAP:
        raise ValueError("Invalid multiplier color.")
    multiplier = MULTIPLIER_MAP[band_colors[2]]

    # Calculate resistance value
    resistance = (first_digit * 10 + second_digit) * multiplier
    return resistance
