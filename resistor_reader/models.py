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

    One code space, one owner per code.  ``E01`` and ``E05``-``E06`` are raised
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


@dataclass
class PipelineResult:
    failure: ErrorCodeEnum | None
    error_msg: str
    debug_image: np.ndarray | None
    bands: list[BandBoundingBox] | None
    colors: BandColorTuple | None
    resistance: float | None
    _metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreprocessInput:
    image: np.ndarray
    config: dict[str, Any]


@dataclass
class PreprocessOutput:
    image: np.ndarray
    success: bool
    _metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoIInput:
    image: np.ndarray
    config: dict[str, Any]


@dataclass
class RoIOutput:
    image: np.ndarray
    success: bool
    body_mask: np.ndarray | None
    _metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SegmentationInput:
    image: np.ndarray
    body_mask: np.ndarray
    config: dict[str, Any]


@dataclass
class SegmentationOutput:
    bounding_boxes: list[BandBoundingBox]
    success: bool
    _metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClassificationInput:
    image: np.ndarray
    bounding_boxes: list[BandBoundingBox]
    config: dict[str, Any]
    # Median specular spread of the bare resistor body, measured during
    # segmentation.  Metallic bands are scored relative to it.
    body_tex: float = 0.0


@dataclass
class ClassificationOutput:
    colors: BandColorTuple | None
    success: bool
    _metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolveInput:
    colors: BandColorTuple
    config: dict[str, Any]


@dataclass
class ResolveOutput:
    resistance: float | None
    success: bool
    _metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DecodeInput:
    # One score per color, per band, in left-to-right image order.
    scores: list[dict[ColorsEnum, float]]
    config: dict[str, Any]


@dataclass
class DecodeOutput:
    resistance: float | None
    colors: BandColorTuple | None
    # True when the winning sequence reads right-to-left in the image.
    reversed_: bool
    # Score margin over the best alternative resistance value.
    confidence: float
    success: bool
    _metadata: dict[str, Any] = field(default_factory=dict)
