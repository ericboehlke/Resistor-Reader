"""Formatting and safe writes for the 4-character segment display.

Kept free of hardware imports (``board``, ``RPi.GPIO``, ``picamera2``) so it can
be exercised on a dev machine; ``main.py`` supplies the real device.
"""

from __future__ import annotations

from typing import Protocol

from .models import ErrorCodeEnum


class SegmentDisplay(Protocol):
    """The slice of ``adafruit_ht16k33.segments.Seg14x4`` used here."""

    def print(self, text: str) -> None: ...

    def fill(self, value: int) -> None: ...


def resistance_str(value: float) -> str:
    """Format a resistance value to fit the 4-character display.

    Keeps three significant figures at most so values like 10 kOhm render as
    ``10.0k`` rather than overflowing the four digits.
    """
    if value >= 1_000_000:
        scaled, suffix = value / 1_000_000, "M"
    elif value >= 1_000:
        scaled, suffix = value / 1_000, "k"
    else:
        scaled, suffix = float(value), ""
    if scaled >= 100:
        body = f"{scaled:.0f}"
    elif scaled >= 10:
        body = f"{scaled:.1f}"
    else:
        body = f"{scaled:.2f}"
    return f"{body}{suffix}"


def show_message(display: SegmentDisplay, text: str) -> None:
    """Write to the segment display without ever taking the loop down with it."""
    try:
        display.print(text)
    except Exception:
        try:
            display.fill(0)
            display.print(text[:4])
        except Exception:
            pass


def show_error(display: SegmentDisplay, code: ErrorCodeEnum, detail: str = "") -> None:
    """Report a failure on the console and surface its code on the display."""
    reason = f"{code.value}: {detail}" if detail else code.value
    print(f"[{code.name}] {reason}")
    show_message(display, code.name)
