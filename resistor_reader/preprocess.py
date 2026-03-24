from __future__ import annotations

import numpy as np

from .logging_utils import save_image
from .models import PreprocessInput, PreprocessOutput


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
    image = array.astype(np.float32)
    avg_rgb = image.reshape(-1, 3).mean(axis=0)
    gray_value = avg_rgb.mean()
    scale = gray_value / avg_rgb
    balanced = image * scale
    return np.clip(balanced, 0, 255).astype(np.uint8)


def preprocess(
    stage_input: PreprocessInput,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> PreprocessOutput:
    """Apply preprocessing and return the stage contract output."""
    # Crop to tray interior before white balance.
    cropped = stage_input.image[64:480, 36:598]
    processed = auto_white_balance(cropped)
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
        success=True,
        _metadata={"debug_image_path": str(pre_path) if pre_path else None},
    )
    return output
