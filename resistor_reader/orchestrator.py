"""Orchestrator agent coordinating the resistor reading pipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from . import bands, preprocess, resolve, roi
from .debug_montage import build_debug_montage, render_final_overlay
from .logging_utils import save_image
from .models import (
    BandBoundingBox,
    ClassificationInput,
    ColorsEnum,
    ErrorCodeEnum,
    PipelineResult,
    PreprocessInput,
    ResolveInput,
    RoIInput,
    SegmentationInput,
)


def _read_debug_image(path_value: object) -> np.ndarray | None:
    if not isinstance(path_value, str) or not path_value:
        return None
    if not Path(path_value).exists():
        return None
    bgr = cv2.imread(path_value)
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _finalize_pipeline_result(
    *,
    config: dict[str, Any],
    ts: str,
    input_image: np.ndarray,
    preprocessed_image: np.ndarray | None,
    roi_image: np.ndarray | None,
    failure: ErrorCodeEnum | None,
    error_msg: str,
    bounding_boxes: list[BandBoundingBox] | None,
    colors: tuple[ColorsEnum, ColorsEnum, ColorsEnum, ColorsEnum] | None,
    resistance: float | None,
    metadata: dict[str, Any],
) -> PipelineResult:
    final_overlay = render_final_overlay(
        roi_image=roi_image,
        bounding_boxes=bounding_boxes,
        colors=colors,
        resistance=resistance,
        failure=failure,
        error_msg=error_msg,
    )
    seg_img = _read_debug_image(metadata.get("segmentation", {}).get("debug_image_path"))
    cls_img = _read_debug_image(metadata.get("classification", {}).get("debug_image_path"))
    extra_panels = [
        ("Segmentation", seg_img, None),
        ("Classification", cls_img, None),
    ]
    montage = build_debug_montage(
        input_image=input_image,
        preprocessed_image=preprocessed_image,
        roi_image=roi_image,
        final_overlay=final_overlay,
        failure=failure,
        error_msg=error_msg,
        extra_panels=extra_panels,
    )

    montage_path: str | None = None
    explicit_path = config.get("debug_montage_path")
    if isinstance(explicit_path, str) and explicit_path:
        out_path = Path(explicit_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), cv2.cvtColor(montage, cv2.COLOR_RGB2BGR))
        montage_path = str(out_path)
    else:
        debug_enabled = config.get("runtime", {}).get("debug", {}).get("enabled", False)
        path = save_image(montage, "montage", debug=debug_enabled, config=config, ts=ts)
        montage_path = str(path) if path else None

    metadata["debug_montage_path"] = montage_path
    return PipelineResult(
        failure=failure,
        error_msg=error_msg,
        debug_image=montage,
        bands=bounding_boxes,
        colors=colors,
        resistance=resistance,
        _metadata=metadata,
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
        return _finalize_pipeline_result(
            config=config,
            ts=ts,
            input_image=array,
            preprocessed_image=None,
            roi_image=None,
            failure=ErrorCodeEnum.E01,
            error_msg=str(pre_out._metadata.get("error_msg", "Preprocess failed.")),
            bounding_boxes=None,
            colors=None,
            resistance=None,
            metadata={"preprocess": pre_out._metadata},
        )

    roi_out = roi.detect_resistor_roi(
        RoIInput(image=pre_out.image, config=config), debug=debug, ts=ts
    )
    if not roi_out.success:
        return _finalize_pipeline_result(
            config=config,
            ts=ts,
            input_image=array,
            preprocessed_image=pre_out.image,
            roi_image=roi_out.image,
            failure=ErrorCodeEnum.E02,
            error_msg=str(roi_out._metadata.get("error_msg", "No resistor found.")),
            bounding_boxes=None,
            colors=None,
            resistance=None,
            metadata={"preprocess": pre_out._metadata, "roi": roi_out._metadata},
        )

    assert roi_out.body_mask is not None
    seg_out = bands.segment_bands(
        SegmentationInput(
            image=roi_out.image, body_mask=roi_out.body_mask, config=config
        ),
        debug=debug,
        ts=ts,
    )
    if not seg_out.success:
        return _finalize_pipeline_result(
            config=config,
            ts=ts,
            input_image=array,
            preprocessed_image=pre_out.image,
            roi_image=roi_out.image,
            failure=ErrorCodeEnum.E03,
            error_msg=str(seg_out._metadata.get("error_msg", "Segmentation failed.")),
            bounding_boxes=seg_out.bounding_boxes,
            colors=None,
            resistance=None,
            metadata={
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
        return _finalize_pipeline_result(
            config=config,
            ts=ts,
            input_image=array,
            preprocessed_image=pre_out.image,
            roi_image=roi_out.image,
            failure=ErrorCodeEnum.E04,
            error_msg=str(cls_out._metadata.get("error_msg", "Classification failed.")),
            bounding_boxes=seg_out.bounding_boxes,
            colors=None,
            resistance=None,
            metadata={
                "preprocess": pre_out._metadata,
                "roi": roi_out._metadata,
                "segmentation": seg_out._metadata,
                "classification": cls_out._metadata,
            },
        )

    res_out = resolve.resolve_value(ResolveInput(colors=cls_out.colors, config=config))
    if not res_out.success or res_out.resistance is None:
        return _finalize_pipeline_result(
            config=config,
            ts=ts,
            input_image=array,
            preprocessed_image=pre_out.image,
            roi_image=roi_out.image,
            failure=ErrorCodeEnum.E04,
            error_msg=str(res_out._metadata.get("error_msg", "Resolve failed.")),
            bounding_boxes=seg_out.bounding_boxes,
            colors=cls_out.colors,
            resistance=None,
            metadata={
                "preprocess": pre_out._metadata,
                "roi": roi_out._metadata,
                "segmentation": seg_out._metadata,
                "classification": cls_out._metadata,
                "resolve": res_out._metadata,
            },
        )

    return _finalize_pipeline_result(
        config=config,
        ts=ts,
        input_image=array,
        preprocessed_image=pre_out.image,
        roi_image=roi_out.image,
        failure=None,
        error_msg="",
        bounding_boxes=seg_out.bounding_boxes,
        colors=cls_out.colors,
        resistance=res_out.resistance,
        metadata={
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
