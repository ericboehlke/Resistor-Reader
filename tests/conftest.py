"""Shared test fixtures.

Paths are resolved from this file rather than the working directory, so the
suite runs the same from anywhere.  There is one pipeline config -- the
appliance's ``config.yaml`` -- and tests override the debug switches in code;
a second copy of the tunables under ``tests/`` only ever drifts.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config.yaml"
IMAGE_DIR = REPO_ROOT / "resistor_pictures"
GROUND_TRUTH = IMAGE_DIR / "resistors.csv"


def load_pipeline_config(*, debug: bool = False) -> dict[str, Any]:
    """The appliance config, with debug forced on or off."""
    config = yaml.safe_load(CONFIG_PATH.read_text())
    runtime = config.setdefault("runtime", {}).setdefault("debug", {})
    runtime["enabled"] = debug
    # Tests write a whole run's images at once; pruning would delete the ones
    # the failure report links to.
    runtime["max_files"] = 0
    return config


@pytest.fixture
def pipeline_config() -> dict[str, Any]:
    return copy.deepcopy(load_pipeline_config())
