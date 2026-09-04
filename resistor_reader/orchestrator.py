"""Orchestrator coordinating the resistor reading pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from . import classify, decode, preprocess, roi, segment
from .debug_montage import build_debug_montage, render_final_overlay
from .logging_utils import save_image
from .models import (
    BandBoundingBox,
    BandColorTuple,
    ClassificationInput,
    DecodeInput,
    PipelineResult,
    PreprocessInput,
    RoIInput,
    SegmentationInput,
    StageResult,
)


@dataclass
class _Run:
    """State accumulated as the pipeline advances.

    Every stage records itself here, so a failure return is one call that knows
    everything gathered so far -- rather than repeating the whole result
    construction at each of the five places a stage can fail.
    """

    config: dict[str, Any]
    input_image: np.ndarray
    ts: str
    debug: bool
    preprocessed_image: np.ndarray | None = None
    roi_image: np.ndarray | None = None
    bounding_boxes: list[BandBoundingBox] | None = None
    colors: BandColorTuple | None = None
    resistance: float | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    # (panel title, image) for stages that produced a debug overlay.
    overlays: list[tuple[str, np.ndarray]] = field(default_factory=list)

    def record(self, name: str, out: StageResult, *, panel: str | None = None) -> None:
        """Fold a finished stage's diagnostics into the run."""
        self.metadata[name] = out._metadata
        if panel is not None and out.debug_overlay is not None:
            self.overlays.append((panel, out.debug_overlay))

    def finish(self, failed: StageResult | None = None) -> PipelineResult:
        """Build the final result, with the montage if anyone wants it."""
        failure = failed.error if failed is not None else None
        error_msg = failed.error_msg if failed is not None else ""

        debug_cfg = self.config.get("runtime", {}).get("debug", {})
        explicit_path = debug_cfg.get("montage_path")
        has_explicit_path = isinstance(explicit_path, str) and bool(explicit_path)

        montage: np.ndarray | None = None
        montage_path: str | None = None
        # Assembling the montage means an overlay render and a multi-panel
        # composite -- skip all of it unless someone actually wants the picture.
        if self.debug or has_explicit_path:
            montage = build_debug_montage(
                input_image=self.input_image,
                preprocessed_image=self.preprocessed_image,
                roi_image=self.roi_image,
                final_overlay=render_final_overlay(
                    roi_image=self.roi_image,
                    bounding_boxes=self.bounding_boxes,
                    colors=self.colors,
                    resistance=self.resistance,
                    failure=failure,
                    error_msg=error_msg,
                ),
                failure=failure,
                error_msg=error_msg,
                extra_panels=[(title, img, None) for title, img in self.overlays],
            )

            if has_explicit_path:
                out_path = Path(explicit_path)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(out_path), cv2.cvtColor(montage, cv2.COLOR_RGB2BGR))
                montage_path = str(out_path)
            else:
                path = save_image(
                    montage, "montage", debug=self.debug, config=self.config, ts=self.ts
                )
                montage_path = str(path) if path else None

        self.metadata["debug_montage_path"] = montage_path
        return PipelineResult(
            failure=failure,
            error_msg=error_msg,
            debug_image=montage,
            bands=self.bounding_boxes,
            colors=self.colors,
            resistance=self.resistance,
            confidence=self.confidence,
            _metadata=self.metadata,
        )


def read_pipeline(
    array: np.ndarray,
    config: dict[str, Any] | None = None,
) -> PipelineResult:
    """Execute the full pipeline and return the structured result contract."""

    config = config or {}
    run = _Run(
        config=config,
        input_image=array,
        ts=datetime.now().strftime("%Y%m%d_%H%M%S%f"),
        debug=config.get("runtime", {}).get("debug", {}).get("enabled", False),
    )
    # Mutated in place as stages run, so the timings survive an early return.
    timings: dict[str, float] = {}
    run.metadata["timings_ms"] = timings

    def timed(name: str, call, panel: str | None = None):
        start = time.perf_counter()
        out = call()
        timings[name] = (time.perf_counter() - start) * 1000.0
        run.record(name, out, panel=panel)
        return out

    pre_out = timed(
        "preprocess",
        lambda: preprocess.preprocess(
            PreprocessInput(image=array, config=config), debug=run.debug, ts=run.ts
        ),
    )
    if not pre_out.success:
        return run.finish(pre_out)
    run.preprocessed_image = pre_out.image

    roi_out = timed(
        "roi",
        lambda: roi.detect_resistor_roi(
            RoIInput(image=pre_out.image, config=config), debug=run.debug, ts=run.ts
        ),
    )
    if not roi_out.success:
        return run.finish(roi_out)
    run.roi_image = roi_out.image
    assert roi_out.body_mask is not None

    seg_out = timed(
        "segmentation",
        lambda: segment.segment_bands(
            SegmentationInput(
                image=roi_out.image, body_mask=roi_out.body_mask, config=config
            ),
            debug=run.debug,
            ts=run.ts,
        ),
        panel="Segmentation",
    )
    run.bounding_boxes = seg_out.bounding_boxes or None
    if not seg_out.success:
        return run.finish(seg_out)

    cls_out = timed(
        "classification",
        lambda: classify.classify_bands(
            ClassificationInput(
                image=roi_out.image,
                bounding_boxes=seg_out.bounding_boxes,
                config=config,
                body_tex=seg_out.body_tex,
            ),
            debug=run.debug,
            ts=run.ts,
        ),
        panel="Classification",
    )
    if not cls_out.success:
        return run.finish(cls_out)

    dec_out = timed(
        "decode",
        lambda: decode.decode_best(
            DecodeInput(scores=cls_out.scores, config=config)
        ),
    )
    if not dec_out.success or dec_out.resistance is None:
        return run.finish(dec_out)

    if dec_out.reversed_:
        run.bounding_boxes = list(reversed(seg_out.bounding_boxes))
    run.colors = dec_out.colors
    run.resistance = dec_out.resistance
    run.confidence = dec_out.confidence
    return run.finish()


def is_confident(result: PipelineResult, min_confidence: float) -> bool:
    """Whether a successful reading clears the confidence floor.

    Deliberately *not* applied inside ``read_pipeline``: the pipeline reports
    what it saw and how sure it was, and the caller decides what to do about it.
    That keeps the test suite measuring raw algorithm accuracy rather than the
    accuracy-after-policy number the appliance shows.
    """
    if result.failure is not None or result.resistance is None:
        return False
    return result.confidence >= min_confidence


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
