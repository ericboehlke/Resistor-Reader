import numpy as np

from resistor_reader.debug_montage import build_debug_montage, render_final_overlay
from resistor_reader.models import ColorsEnum, ErrorCodeEnum


def _img(h: int, w: int, value: int) -> np.ndarray:
    return np.full((h, w, 3), value, dtype=np.uint8)


def test_render_final_overlay_success() -> None:
    roi = _img(60, 140, 180)
    overlay = render_final_overlay(
        roi_image=roi,
        bounding_boxes=[(10, 0, 30, 60), (35, 0, 50, 60), (60, 0, 80, 60), (95, 0, 115, 60)],
        colors=(ColorsEnum.BROWN, ColorsEnum.BLACK, ColorsEnum.RED, ColorsEnum.GOLD),
        resistance=1_000.0,
        failure=None,
        error_msg="",
    )
    assert overlay is not None
    assert overlay.shape == roi.shape


def test_build_debug_montage_stacks_panels() -> None:
    montage = build_debug_montage(
        input_image=_img(120, 160, 220),
        preprocessed_image=_img(90, 120, 200),
        roi_image=_img(60, 100, 180),
        final_overlay=_img(70, 110, 160),
        failure=ErrorCodeEnum.E03,
        error_msg="too many/few bands found",
        panel_width=320,
        extra_panels=[("Segmentation", _img(70, 100, 150), None)],
    )
    assert montage.ndim == 3
    assert montage.shape[1] == 320
    assert montage.shape[0] > 300
