"""Orchestrator agent coordinating the resistor reading pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import numpy as np
import yaml

from . import bands, preprocess, resolve, roi


def read_resistor(array: np.ndarray, config: Dict[str, Any] | None = None) -> int:
    """Return the resistor value in ohms for a given image array.

    This placeholder implementation only exercises the preprocessing step
    and returns a constant value. It exists so the rest of the pipeline can
    be developed incrementally.
    """

    config = config or {}
    debug = config.get("runtime", {}).get("debug", {}).get("enabled", False)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S%f")
    artifacts = preprocess.preprocess(array, config=config, debug=debug, ts=ts)
    crop = roi.detect_resistor_roi(artifacts, config=config, debug=debug, ts=ts)
    band_colors = bands.segment_and_classify_bands(
        crop, config=config, debug=debug, ts=ts
    )
    return resolve.resolve_value(band_colors)


def load_config(config_file: str | None) -> Dict[str, Any]:
    """Load a configuration file for the image processing pipeline.

    The configuration file should be in yaml format

    Parameters
    ----------
    config_file:
        Path to the configuration file. If `None`, an empty dictionary is returned.

    Returns
    -------
    dict
        Configuration dictionary.
    """

    if config_file is None:
        return {}

    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    return config
