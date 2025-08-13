"""Orchestrator agent coordinating the resistor reading pipeline."""
from __future__ import annotations

import numpy as np
from . import preprocess


def run_once(array: np.ndarray, config: dict | None = None) -> int:
    """Return the resistor value in ohms for a given image array.

    This placeholder implementation only exercises the preprocessing step
    and returns a constant value. It exists so the rest of the pipeline can
    be developed incrementally.
    """
    _ = preprocess.auto_white_balance(array)
    return 100


