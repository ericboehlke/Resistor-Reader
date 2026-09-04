"""Shared data contracts for the resistor reading pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeAlias

import numpy as np

# Reusable type aliases for clearer stage signatures.
BandBoundingBox: TypeAlias = tuple[int, int, int, int]
BandColorTuple: TypeAlias = tuple["ColorsEnum", "ColorsEnum", "ColorsEnum", "ColorsEnum"]


class ErrorCodeEnum(str, Enum):
    """Error codes for known failure modes, shown on the segment display.

    One code space, one owner per code.  ``E01``, ``E05`` and ``E06`` are raised
    by ``main.py`` around the pipeline; ``E02``-``E04`` and ``E07`` are raised by
    the stage that detected the problem and propagated unchanged by the
    orchestrator.  Names are three characters so they fit the four-digit
    display.
    """

    E01 = "camera failure"
    E02 = "no resistor found"
    E03 = "too many/few bands found"
    E04 = "invalid band set"
    E05 = "pipeline crashed"
    E06 = "low confidence"
    E07 = "bad input image"


class ColorsEnum(str, Enum):
    """Supported resistor band colors."""

    BLACK = "black"
    BROWN = "brown"
    RED = "red"
    ORANGE = "orange"
    YELLOW = "yellow"
    GREEN = "green"
    BLUE = "blue"
    VIOLET = "violet"
    GRAY = "gray"
    WHITE = "white"
    GOLD = "gold"
    SILVER = "silver"


@dataclass(kw_only=True)
class StageResult:
    """Failure reporting shared by every stage output.

    A stage that fails sets ``error`` to the code for *its own* failure mode;
    the orchestrator propagates it unchanged rather than re-deriving a code from
    the stage's position in the pipeline.  Fields are keyword-only so subclasses
    can declare required positional fields of their own.
    """

    error: ErrorCodeEnum | None = None
    error_msg: str = ""
    # Annotated view of this stage's work, populated only when debug is on.  The
    # orchestrator stacks these into the montage; keeping the array here means
    # it never has to read back a JPEG the same process just wrote.
    debug_overlay: np.ndarray | None = None
    # Diagnostics only -- timings, thresholds, debug image paths.  Anything the
    # next stage needs is a real field.
    _metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class PipelineResult:
    failure: ErrorCodeEnum | None
    error_msg: str
    debug_image: np.ndarray | None
    bands: list[BandBoundingBox] | None
    colors: BandColorTuple | None
    resistance: float | None
    # Score margin of the winning reading over the best alternative value.
    # ``inf`` when no alternative was legal.
    confidence: float = 0.0
    _metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreprocessInput:
    image: np.ndarray
    config: dict[str, Any]


@dataclass
class PreprocessOutput(StageResult):
    image: np.ndarray


@dataclass
class RoIInput:
    image: np.ndarray
    config: dict[str, Any]


@dataclass
class RoIOutput(StageResult):
    image: np.ndarray
    body_mask: np.ndarray | None = None


@dataclass
class SegmentationInput:
    image: np.ndarray
    body_mask: np.ndarray
    config: dict[str, Any]


@dataclass
class SegmentationOutput(StageResult):
    bounding_boxes: list[BandBoundingBox] = field(default_factory=list)
    # Median specular spread of the bare resistor body.  Classification scores
    # metallic bands relative to it.
    body_tex: float = 0.0


@dataclass
class ClassificationInput:
    image: np.ndarray
    bounding_boxes: list[BandBoundingBox]
    config: dict[str, Any]
    # Median specular spread of the bare resistor body, measured during
    # segmentation.  Metallic bands are scored relative to it.
    body_tex: float = 0.0


@dataclass
class ClassificationOutput(StageResult):
    # One score per color, per band, in left-to-right image order.  This is the
    # decoder's entire input.
    scores: list[dict[ColorsEnum, float]] = field(default_factory=list)


@dataclass
class DecodeInput:
    # One score per color, per band, in left-to-right image order.
    scores: list[dict[ColorsEnum, float]]
    config: dict[str, Any]


@dataclass
class DecodeOutput(StageResult):
    resistance: float | None = None
    colors: BandColorTuple | None = None
    # True when the winning sequence reads right-to-left in the image.
    reversed_: bool = False
    # Score margin over the best alternative resistance value.
    confidence: float = 0.0
