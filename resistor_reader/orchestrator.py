"""Orchestrator agent coordinating the resistor reading pipeline."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import numpy as np

from . import preprocess


def run_once(array: np.ndarray, config: Dict[str, Any] | None = None) -> int:
    """Return the resistor value in ohms for a given image array.

    This placeholder implementation only exercises the preprocessing step
    and returns a constant value. It exists so the rest of the pipeline can
    be developed incrementally.
    """

    config = config or {}
    debug = config.get("runtime", {}).get("debug", {}).get("enabled", False)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S%f")
    preprocess.preprocess(array, config=config, debug=debug, ts=ts)
    return 100


