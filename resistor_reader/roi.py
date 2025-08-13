from __future__ import annotations

from typing import Any, Dict

import numpy as np
import PIL.Image

from .logging_utils import save_image


def _hue_difference(h: np.ndarray, ref: float) -> np.ndarray:
    """Return circular hue distance between ``h`` and ``ref``."""
    return np.abs(((h.astype(int) - ref + 128) % 256) - 128)


def _largest_component(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return x and y coordinates for the largest connected component."""
    height, width = mask.shape
    visited = np.zeros((height, width), dtype=bool)
    best_coords: list[tuple[int, int]] | None = None
    best_size = 0
    for y in range(height):
        for x in range(width):
            if mask[y, x] and not visited[y, x]:
                stack = [(y, x)]
                visited[y, x] = True
                coords: list[tuple[int, int]] = []
                while stack:
                    cy, cx = stack.pop()
                    coords.append((cx, cy))
                    for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                        if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                            visited[ny, nx] = True
                            stack.append((ny, nx))
                if len(coords) > best_size:
                    best_size = len(coords)
                    best_coords = coords
    if best_coords is None:
        raise ValueError("no connected component found")
    xs, ys = zip(*best_coords)
    return np.asarray(xs), np.asarray(ys)


def detect_resistor_roi(
    artifacts: Dict[str, np.ndarray],
    config: Dict[str, Any] | None = None,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> Dict[str, Any]:
    """Locate the resistor region and return a cropped, horizontal image."""

    config = config or {}
    image = artifacts["image"]

    hsv = np.asarray(PIL.Image.fromarray(image).convert("HSV"))
    h, s = hsv[:, :, 0], hsv[:, :, 1]
    border = np.concatenate([h[0, :], h[-1, :], h[:, 0], h[:, -1]])
    bg_hue = float(np.median(border))
    mask = (_hue_difference(h, bg_hue) > 15) & (s > 30)
    xs, ys = _largest_component(mask)

    x0, x1 = xs.min(), xs.max() + 1
    y0, y1 = ys.min(), ys.max() + 1
    pad = 10
    x0 = max(x0 - pad, 0)
    y0 = max(y0 - pad, 0)
    x1 = min(x1 + pad, image.shape[1])
    y1 = min(y1 + pad, image.shape[0])
    crop = image[y0:y1, x0:x1]

    coords = np.column_stack((xs - x0, ys - y0))
    eig_vals, eig_vecs = np.linalg.eigh(np.cov(coords, rowvar=False))
    principal = eig_vecs[:, np.argmax(eig_vals)]
    angle = float(np.degrees(np.arctan2(principal[1], principal[0])))

    rotated_pil = PIL.Image.fromarray(crop).rotate(
        -angle, resample=PIL.Image.BILINEAR, expand=True, fillcolor=(255, 255, 255)
    )
    rotated = np.asarray(rotated_pil)

    hsv2 = np.asarray(rotated_pil.convert("HSV"))
    h2, s2 = hsv2[:, :, 0], hsv2[:, :, 1]
    border2 = np.concatenate([h2[0, :], h2[-1, :], h2[:, 0], h2[:, -1]])
    bg_hue2 = float(np.median(border2))
    mask2 = (_hue_difference(h2, bg_hue2) > 15) & (s2 > 30)
    xs2, ys2 = _largest_component(mask2)
    x0r, x1r = xs2.min(), xs2.max() + 1
    y0r, y1r = ys2.min(), ys2.max() + 1
    final_crop = rotated[y0r:y1r, x0r:x1r]

    if final_crop.shape[0] > final_crop.shape[1]:
        final_crop = np.asarray(
            PIL.Image.fromarray(final_crop).rotate(
                -90, resample=PIL.Image.BILINEAR, expand=True, fillcolor=(255, 255, 255)
            )
        )
        bbox = (0, 0, final_crop.shape[1], final_crop.shape[0])
    else:
        bbox = (int(x0r), int(y0r), int(x1r - x0r), int(y1r - y0r))

    save_image(
        final_crop,
        "roi",
        debug=debug and config.get("region_of_interest", {}).get("debug_image", False),
        config=config,
        ts=ts,
    )
    return {"bbox": bbox, "crop": final_crop, "angle": angle}
