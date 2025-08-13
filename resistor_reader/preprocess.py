from __future__ import annotations

from typing import Any, Dict

import numpy as np
import PIL.Image

from .logging_utils import save_image


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


def rgb_to_lab(array: np.ndarray) -> np.ndarray:
    """Convert an RGB image array to LAB color space using Pillow."""
    image = PIL.Image.fromarray(array)
    return np.asarray(image.convert("LAB"))


def preprocess(
    array: np.ndarray,
    config: Dict[str, Any] | None = None,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> Dict[str, np.ndarray]:
    """Apply basic preprocessing and optionally log the result.

    Currently this performs automatic white balance and LAB conversion. The
    preprocessed RGB image is saved to ``logs`` when ``debug`` is ``True``.

    Parameters
    ----------
    array:
        Input RGB image as ``uint8`` numpy array.
    config:
        Optional configuration dictionary. Only ``runtime.debug_dir`` is used.
    debug:
        When ``True`` the preprocessed image is written to disk using the
        ``save_image`` helper.
    ts:
        Optional timestamp prefix to use for the saved image filename.

    Returns
    -------
    dict
        Dictionary containing at least the preprocessed RGB image under the
        ``"image"`` key and its LAB representation under ``"lab"``.
    """

    processed = auto_white_balance(array)
    lab = rgb_to_lab(processed)
    debug = debug and config.get("processing", {}).get("debug_image", False)
    save_image(processed, "pre", debug=debug, config=config, ts=ts)
    return {"image": processed, "lab": lab}


