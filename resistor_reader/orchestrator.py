"""Orchestrator agent coordinating the resistor reading pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import yaml

from . import bands, preprocess, resolve, roi
from .models import (
    ClassificationInput,
    ErrorCodeEnum,
    PipelineResult,
    PreprocessInput,
    ResolveInput,
    RoIInput,
    SegmentationInput,
)


def read_pipeline(
    array: np.ndarray,
    config: dict[str, Any] | None = None,
) -> PipelineResult:
    """Execute full pipeline and return structured result contract."""

    config = config or {}
    debug = config.get("runtime", {}).get("debug", {}).get("enabled", False)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S%f")

    pre_out = preprocess.preprocess(
        PreprocessInput(image=array, config=config), debug=debug, ts=ts
    )
    if not pre_out.success:
        return PipelineResult(
            failure=ErrorCodeEnum.E01,
            error_msg=str(pre_out._metadata.get("error_msg", "Preprocess failed.")),
            debug_image=None,
            bands=None,
            colors=None,
            resistance=None,
            _metadata={"preprocess": pre_out._metadata},
        )

    roi_out = roi.detect_resistor_roi(
        RoIInput(image=pre_out.image, config=config), debug=debug, ts=ts
    )
    if not roi_out.success:
        return PipelineResult(
            failure=ErrorCodeEnum.E02,
            error_msg=str(roi_out._metadata.get("error_msg", "No resistor found.")),
            debug_image=roi_out.image,
            bands=None,
            colors=None,
            resistance=None,
            _metadata={"preprocess": pre_out._metadata, "roi": roi_out._metadata},
        )

    seg_out = bands.segment_bands(
        SegmentationInput(image=roi_out.image, config=config), debug=debug, ts=ts
    )
    if not seg_out.success:
        return PipelineResult(
            failure=ErrorCodeEnum.E03,
            error_msg=str(seg_out._metadata.get("error_msg", "Segmentation failed.")),
            debug_image=roi_out.image,
            bands=seg_out.bounding_boxes,
            colors=None,
            resistance=None,
            _metadata={
                "preprocess": pre_out._metadata,
                "roi": roi_out._metadata,
                "segmentation": seg_out._metadata,
            },
        )

    cls_out = bands.classify_bands(
        ClassificationInput(
            image=roi_out.image,
            bounding_boxes=seg_out.bounding_boxes,
            config=config,
        ),
        debug=debug,
        ts=ts,
    )
    if not cls_out.success or cls_out.colors is None:
        return PipelineResult(
            failure=ErrorCodeEnum.E04,
            error_msg=str(cls_out._metadata.get("error_msg", "Classification failed.")),
            debug_image=roi_out.image,
            bands=seg_out.bounding_boxes,
            colors=None,
            resistance=None,
            _metadata={
                "preprocess": pre_out._metadata,
                "roi": roi_out._metadata,
                "segmentation": seg_out._metadata,
                "classification": cls_out._metadata,
            },
        )

    res_out = resolve.resolve_value(ResolveInput(colors=cls_out.colors, config=config))
    if not res_out.success or res_out.resistance is None:
        return PipelineResult(
            failure=ErrorCodeEnum.E04,
            error_msg=str(res_out._metadata.get("error_msg", "Resolve failed.")),
            debug_image=roi_out.image,
            bands=seg_out.bounding_boxes,
            colors=cls_out.colors,
            resistance=None,
            _metadata={
                "preprocess": pre_out._metadata,
                "roi": roi_out._metadata,
                "segmentation": seg_out._metadata,
                "classification": cls_out._metadata,
                "resolve": res_out._metadata,
            },
        )

    return PipelineResult(
        failure=None,
        error_msg="",
        debug_image=roi_out.image,
        bands=seg_out.bounding_boxes,
        colors=cls_out.colors,
        resistance=res_out.resistance,
        _metadata={
            "preprocess": pre_out._metadata,
            "roi": roi_out._metadata,
            "segmentation": seg_out._metadata,
            "classification": cls_out._metadata,
            "resolve": res_out._metadata,
        },
    )


def read_resistor(array: np.ndarray, config: dict[str, Any] | None = None) -> float:
    """Backward-compatible convenience API returning resistance only."""
    result = read_pipeline(array, config=config)
    if result.failure is not None or result.resistance is None:
        raise ValueError(result.error_msg or "Pipeline failed")
    return result.resistance


def load_config(config_file: str | None) -> dict[str, Any]:
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
