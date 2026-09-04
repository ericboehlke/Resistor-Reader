import pytest

from resistor_reader.display import resistance_str, show_error, show_message
from resistor_reader.models import ErrorCodeEnum


@pytest.mark.parametrize(
    "value, expected",
    [
        (0.22, "0.22"),
        (4.7, "4.70"),
        (10, "10.0"),
        (68, "68.0"),
        (220, "220"),
        (4700, "4.70k"),
        (10_000, "10.0k"),
        (330_000, "330k"),
        (1_000_000, "1.00M"),
        (4_700_000, "4.70M"),
    ],
)
def test_resistance_str_fits_four_characters(value, expected):
    text = resistance_str(value)
    assert text == expected
    # The display has four digits; the multiplier suffix rides on the last one.
    assert len(text.replace(".", "")) <= 4


class _FakeDisplay:
    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.written: list[str] = []
        self.filled = 0

    def print(self, text: str) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("i2c write failed")
        self.written.append(text)

    def fill(self, value: int) -> None:
        self.filled += 1


def test_show_message_writes_through():
    display = _FakeDisplay()
    show_message(display, "4.70k")
    assert display.written == ["4.70k"]


def test_show_message_retries_then_gives_up_quietly():
    """A dead display must never take the read loop down with it."""
    display = _FakeDisplay(fail_times=1)
    show_message(display, "4.70k")
    assert display.filled == 1
    assert display.written == ["4.70"]

    dead = _FakeDisplay(fail_times=99)
    show_message(dead, "4.70k")
    assert dead.written == []


def test_show_error_displays_the_code_name(capsys):
    display = _FakeDisplay()
    show_error(display, ErrorCodeEnum.E02, "nothing on the tray")
    assert display.written == ["E02"]
    assert "no resistor found" in capsys.readouterr().out


@pytest.mark.parametrize("code", list(ErrorCodeEnum))
def test_every_error_code_fits_the_display(code):
    assert len(code.name) <= 4
