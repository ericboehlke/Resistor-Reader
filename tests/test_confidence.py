"""The confidence gate: refuse a reading the decoder could not separate.

`ARCHITECTURE.md` states that a wrong answer is worse than an error, so the
appliance drops readings whose score margin over the next-best value is thin.
"""

import numpy as np

from resistor_reader.models import ErrorCodeEnum, PipelineResult
from resistor_reader.orchestrator import is_confident


def _result(**kwargs) -> PipelineResult:
    defaults = {
        "failure": None,
        "error_msg": "",
        "debug_image": None,
        "bands": None,
        "colors": None,
        "resistance": 4700.0,
        "confidence": 10.0,
    }
    return PipelineResult(**{**defaults, **kwargs})


def test_a_clear_reading_passes():
    assert is_confident(_result(confidence=11.0), 1.0)


def test_a_thin_margin_is_refused():
    assert not is_confident(_result(confidence=0.22), 1.0)


def test_the_floor_is_inclusive():
    assert is_confident(_result(confidence=1.0), 1.0)


def test_a_zero_floor_accepts_anything_legal():
    assert is_confident(_result(confidence=0.0), 0.0)


def test_an_unbeaten_reading_always_passes():
    """No legal alternative at all means an infinite margin."""
    assert is_confident(_result(confidence=float("inf")), 1.0)


def test_a_failed_pipeline_is_never_confident():
    assert not is_confident(
        _result(failure=ErrorCodeEnum.E03, resistance=None, confidence=float("inf")),
        0.0,
    )


def test_debug_image_is_not_required():
    assert is_confident(_result(debug_image=np.zeros((4, 4, 3), np.uint8)), 1.0)
