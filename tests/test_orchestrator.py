import csv
import math
import sys
from pathlib import Path

import yaml

# Ensure the project root is on the import path when tests are run directly
sys.path.append(str(Path(__file__).resolve().parents[1]))

import numpy
import PIL.Image
import pytest

from resistor_reader import orchestrator


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


# Load test.yaml as a dictionary
with open("tests/test.yaml", "r") as f:
    test_config = yaml.safe_load(f)


@pytest.mark.parametrize("fname,value", _load_cases())
def test_resistors(fname, value):
    """Validate that each example image is parsed to the expected value."""
    assert math.isclose(
        orchestrator.read_resistor(numpy.asarray(PIL.Image.open(fname)), test_config),
        value,
    )


def test_0():
    """Validate that each example image is parsed to the expected value."""
    assert (
        orchestrator.read_resistor(
            numpy.asarray(PIL.Image.open(Path("resistor_pictures") / "0000.jpg")),
            test_config,
        )
        == 100
    )


if __name__ == "__main__":
    pytest.main([__file__])
