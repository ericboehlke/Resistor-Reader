import csv
from pathlib import Path
import sys
import yaml 


# Ensure the project root is on the import path when tests are run directly
sys.path.append(str(Path(__file__).resolve().parents[1]))

import numpy
import pytest
from resistor_reader import orchestrator
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

# Load test.yaml as a dictionary
with open("tests/test.yaml", "r") as f:
    test_config = yaml.safe_load(f)

@pytest.mark.parametrize("fname,value", _load_cases())
def test_resistors(fname, value):
    """Validate that each example image is parsed to the expected value."""
    assert orchestrator.run_once(numpy.asarray(PIL.Image.open(fname)), test_config) == value


if __name__ == "__main__":
    pytest.main([__file__])
