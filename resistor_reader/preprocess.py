import numpy as np
import PIL.Image


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


