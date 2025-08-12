import csv
from pathlib import Path

import numpy
import pytest
import rreader
import PIL.Image


def _load_cases():
    """Return (filename, value) tuples for each sample resistor image."""
    cases = []
    with open("resistor_pictures/resistors.csv", "r") as csvfile:
        reader = csv.reader(csvfile, delimiter=",", quotechar="|")
        for number, value in reader:
            fname = Path("resistor_pictures") / f"{int(number):04d}.jpg"
            if fname.exists():
                cases.append((str(fname), float(value)))
    return cases


@pytest.mark.parametrize("fname,value", _load_cases())
def test_resistors(fname, value):
    """Validate that each example image is parsed to the expected value."""
    assert rreader.rread(numpy.asarray(PIL.Image.open(fname))) == value


if __name__ == "__main__":
    pytest.main([__file__])
