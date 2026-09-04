from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from .logging_utils import save_image
from .models import ErrorCodeEnum, PreprocessInput, PreprocessOutput

# Tray interior for the appliance's 640x480 capture: everything outside is the
# MDF frame, which is neither white nor part of the scene.
DEFAULT_CROP = (64, 36, 480, 598)  # top, left, bottom, right


def _crop_box(config: dict[str, Any]) -> tuple[int, int, int, int]:
    raw = (config.get("processing", {}) or {}).get("crop")
    if raw is None:
        return DEFAULT_CROP
    if len(raw) != 4:
        raise ValueError(f"processing.crop needs 4 values, got {len(raw)}")
    return tuple(int(v) for v in raw)  # type: ignore[return-value]


def auto_white_balance(array: np.ndarray) -> np.ndarray:
    """Return a white balanced copy of an RGB image array.

    A simple gray-world algorithm is used where each color channel is
    scaled so that their averages are equal. The result is clipped to the
    valid 0-255 range and returned as ``uint8``.

    Parameters
    ----------
    array:
        numpy array of shape ``(H, W, 3)`` with dtype ``uint8``

    Returns
    -------
    numpy.ndarray
        White-balanced array of the same shape and dtype.
    """
    avg_rgb = np.asarray(cv2.mean(array)[:3], dtype=np.float32)
    scale = avg_rgb.mean() / avg_rgb
    # The transform is a per-channel gain on an 8-bit image, so a 256-entry
    # lookup per channel reproduces ``clip(image * scale, 0, 255)`` exactly at a
    # fraction of the cost of the full-frame float multiply.
    ramp = np.arange(256, dtype=np.float32)
    lut = np.clip(ramp[:, None] * scale, 0, 255).astype(np.uint8)
    channels = [cv2.LUT(array[:, :, c], lut[:, c]) for c in range(3)]
    return cv2.merge(channels)


def preprocess(
    stage_input: PreprocessInput,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> PreprocessOutput:
    """Crop to the tray interior and white balance.

    Fails with ``E07`` rather than silently mis-cropping when the frame is not
    the size the crop rectangle was measured for -- a capture at a different
    resolution used to produce a truncated image and a nonsense reading.
    """
    image = stage_input.image
    if image.ndim != 3 or image.shape[2] != 3:
        return PreprocessOutput(
            image=image,
            error=ErrorCodeEnum.E07,
            error_msg=f"Expected an HxWx3 RGB image, got shape {image.shape}.",
        )

    try:
        top, left, bottom, right = _crop_box(stage_input.config)
    except (TypeError, ValueError) as exc:
        return PreprocessOutput(
            image=image, error=ErrorCodeEnum.E07, error_msg=str(exc)
        )

    h, w = image.shape[:2]
    if not (0 <= top < bottom <= h and 0 <= left < right <= w):
        return PreprocessOutput(
            image=image,
            error=ErrorCodeEnum.E07,
            error_msg=(
                f"Crop {(top, left, bottom, right)} does not fit a {w}x{h} frame."
            ),
        )

    processed = auto_white_balance(image[top:bottom, left:right])
    debug = debug and stage_input.config.get("processing", {}).get("debug_image", False)
    pre_path = save_image(
        processed,
        "pre",
        debug=debug,
        config=stage_input.config,
        ts=ts,
    )
    return PreprocessOutput(
        image=processed,
        _metadata={"debug_image_path": str(pre_path) if pre_path else None},
    )
