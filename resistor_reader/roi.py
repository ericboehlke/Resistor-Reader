from __future__ import annotations

from typing import Any, Dict

import numpy as np
import PIL.Image
import PIL.ImageOps


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
                        if (
                            0 <= ny < height
                            and 0 <= nx < width
                            and mask[ny, nx]
                            and not visited[ny, nx]
                        ):
                            visited[ny, nx] = True
                            stack.append((ny, nx))
                if len(coords) > best_size:
                    best_size = len(coords)
                    best_coords = coords
    if best_coords is None:
        raise ValueError("no connected component found")
    xs, ys = zip(*best_coords)
    return np.asarray(xs), np.asarray(ys)


# --- Fast 1D squared EDT (Felzenszwalb & Huttenlocher) ---
def _edt_1d(f: np.ndarray) -> np.ndarray:
    """
    f: 1D array of non-negative floats; 0 at 'features', +inf elsewhere.
    returns: 1D array of squared distances to nearest feature.
    """
    n = f.shape[0]
    v = np.zeros(n, dtype=np.int32)  # locations of parabolas in lower envelope
    z = np.zeros(n + 1, dtype=np.float64)  # locations of boundaries between parabolas
    g = np.empty(n, dtype=np.float64)

    k = 0
    v[0] = 0
    z[0] = -np.inf
    z[1] = +np.inf

    for q in range(1, n):
        # intersection with parabola from v[k]
        s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2.0 * q - 2.0 * v[k])
        while s <= z[k]:
            k -= 1
            s = ((f[q] + q * q) - (f[v[k]] + v[k] * v[k])) / (2.0 * q - 2.0 * v[k])
        k += 1
        v[k] = q
        z[k] = s
        z[k + 1] = +np.inf

    k = 0
    for q in range(n):
        while z[k + 1] < q:
            k += 1
        dq = q - v[k]
        g[q] = dq * dq + f[v[k]]
    return g


def _edt_2d(f: np.ndarray) -> np.ndarray:
    """
    2D squared Euclidean distance transform by applying 1D EDT
    to columns, then to rows (separable).
    """
    # columns
    tmp = np.empty_like(f, dtype=np.float64)
    for x in range(f.shape[1]):
        tmp[:, x] = _edt_1d(f[:, x])
    # rows
    out = np.empty_like(tmp, dtype=np.float64)
    for y in range(tmp.shape[0]):
        out[y, :] = _edt_1d(tmp[y, :])
    return out


def distance_transform(mask: np.ndarray) -> np.ndarray:
    """
    Euclidean distance *inside* the foreground (True) to the nearest background (False).
    mask: boolean array (True = resistor+leads foreground)
    returns: float64 array of distances in pixels.
    """
    mask = mask.astype(bool)
    # Build feature map: distance to nearest background -> features are background pixels
    INF = 1e12
    f = np.where(~mask, 0.0, INF)
    dist2 = _edt_2d(f)
    return np.sqrt(dist2)


# --- Lead removal + crop ---
def crop_resistor_body(mask: np.ndarray, dist_thresh_px: float = 3.0, pad: int = 8):
    """
    Keep only 'thick' foreground (distance >= dist_thresh_px) to remove thin leads,
    then return a padded crop bbox around the remaining body.

    mask: boolean array (True = resistor + leads)
    dist_thresh_px: choose slightly > half the lead thickness (in pixels)
    pad: padding (pixels) added around the final bbox
    returns: (minr, minc, maxr, maxc), cropped_mask (original mask cropped to bbox)
    """
    if mask.ndim != 2:
        raise ValueError("mask must be 2D")
    mask = mask.astype(bool)

    dist = distance_transform(mask)  # distance to background, inside foreground
    thick = mask & (dist >= float(dist_thresh_px))

    ys, xs = np.where(thick)
    if ys.size == 0:
        raise ValueError(
            "Nothing left after thickness filter. "
            "Lower dist_thresh_px or ensure your working resolution is high enough."
        )

    minr, maxr = int(ys.min()), int(ys.max())
    minc, maxc = int(xs.min()), int(xs.max())

    H, W = mask.shape
    minr = max(0, minr - pad)
    minc = max(0, minc - pad)
    maxr = min(H, maxr + pad + 1)
    maxc = min(W, maxc + pad + 1)

    return (minr, minc, maxr, maxc), mask[minr:maxr, minc:maxc]


def _normalize_angle_deg(angle: float) -> float:
    # Map angle to [-180, 180)
    a = ((angle + 180.0) % 360.0) - 180.0
    # Choose the smaller rotation to horizontal: [-90, 90]
    if a > 90.0:
        a -= 180.0
    elif a < -90.0:
        a += 180.0
    return a


def _quad_warp_xy(
    img_np: np.ndarray, quad_src_xy, out_w: int, out_h: int, *, resample=PIL.Image.BILINEAR
) -> np.ndarray:
    """
    quad_src_xy: iterable of 4 points in SOURCE image coords, as (x, y):
                 [UL, UR, LR, LL] (clockwise, starting at upper-left)
    out_w, out_h: output size in pixels (width, height)
    """
    pil = PIL.Image.fromarray(img_np)
    data = [
        float(quad_src_xy[0][0]),
        float(quad_src_xy[0][1]),  # UL (x,y)
        float(quad_src_xy[1][0]),
        float(quad_src_xy[1][1]),  # UR
        float(quad_src_xy[2][0]),
        float(quad_src_xy[2][1]),  # LR
        float(quad_src_xy[3][0]),
        float(quad_src_xy[3][1]),  # LL
    ]
    out = pil.transform((int(out_w), int(out_h)), PIL.Image.QUAD, data, resample=resample)
    return np.asarray(out)


def _rotate_np_image(arr: np.ndarray, angle_deg: float, *, mask: bool = False) -> np.ndarray:
    img = PIL.Image.fromarray(arr)
    if mask:
        # Keep labels/binary crisp
        img = img.convert("L")
        img = img.rotate(-angle_deg, resample=PIL.Image.NEAREST, expand=True, fillcolor=0)
        return np.asarray(img) > 127
    else:
        if arr.ndim == 2:
            img = img.convert("L")
        elif arr.ndim == 3 and arr.shape[2] == 3:
            pass
        else:
            # Fall back to L
            img = img.convert("L")
        img = img.rotate(
            -angle_deg,
            resample=PIL.Image.BILINEAR,
            expand=True,
            fillcolor=(255 if arr.ndim == 2 else (255, 255, 255)),
        )
        return np.asarray(img)


def detect_resistor_roi(
    artifacts: Dict[str, np.ndarray],
    config: Dict[str, Any] | None = None,
    *,
    debug: bool = False,
    ts: str | None = None,
) -> Dict[str, Any]:
    """Locate the resistor region and return a cropped, horizontally aligned image + mask,
    with no blank corners (uses OBB quad warp instead of rotating pixels)."""
    config = config or {}
    dbg_flag = debug and config.get("region_of_interest", {}).get("debug_image", False)

    image = artifacts["image"]  # HxWx3 uint8
    hsv = artifacts["hsv"]  # HxWx3
    h, s = hsv[:, :, 0], hsv[:, :, 1]

    # Coarse foreground mask (against white background)
    border = np.concatenate([h[0, :], h[-1, :], h[:, 0], h[:, -1]])
    bg_hue = float(np.median(border))
    mask = (_hue_difference(h, bg_hue) > 15) & (s > 30)
    v = hsv[:, :, 2]
    mask &= v < 220

    save_image(mask.astype(np.uint8) * 255, "roi_mask", debug=dbg_flag, config=config, ts=ts)

    # Preview thickness (optional)
    dist = distance_transform(mask)
    thick_preview = mask & (dist >= 7.0)
    save_image(
        thick_preview.astype(np.uint8) * 255, "thick_mask", debug=dbg_flag, config=config, ts=ts
    )

    # Tight crop around body using your distance-based body extractor
    bbox, crop_mask = crop_resistor_body(mask, dist_thresh_px=10.0, pad=8)
    save_image(crop_mask.astype(np.uint8) * 255, "crop_mask", debug=dbg_flag, config=config, ts=ts)

    # Unpack bbox correctly: (minr, minc, maxr, maxc)
    y0, x0, y1, x1 = bbox
    crop_img = image[y0:y1, x0:x1]
    save_image(crop_img, "cropped", debug=dbg_flag, config=config, ts=ts)

    # --- PCA on crop_mask to get principal axis in *XY* (x=col, y=row) space ---
    xs, ys = _largest_component(crop_mask)  # xs: x/col, ys: y/row
    if xs.size < 2:
        save_image(crop_img, "roi", debug=dbg_flag, config=config, ts=ts)
        return {"bbox": bbox, "crop": crop_img, "mask": crop_mask, "angle": 0.0}

    coords_xy = np.column_stack((xs, ys)).astype(np.float64)  # shape (N, 2) as (x, y)
    mean_xy = coords_xy.mean(axis=0)
    coords_c = coords_xy - mean_xy

    # SVD for stability → principal direction u = (ux, uy) in XY
    try:
        _, _, vh = np.linalg.svd(coords_c, full_matrices=False)
        u = vh[0]
    except np.linalg.LinAlgError:
        cov = np.cov(coords_c, rowvar=False)
        eig_vals, eig_vecs = np.linalg.eigh(cov)
        u = eig_vecs[:, np.argmax(eig_vals)]

    u = u / (np.linalg.norm(u) + 1e-12)  # ensure unit
    v = -np.array([-u[1], u[0]])  # perpendicular (also unit)

    # Project points onto (u, v) axes
    t_u = coords_c @ u
    t_v = coords_c @ v
    umin, umax = float(t_u.min()), float(t_u.max())
    vmin, vmax = float(t_v.min()), float(t_v.max())

    # Angle only for logging/QA (not used in warp)
    angle = _normalize_angle_deg(-np.degrees(np.arctan2(u[1], u[0])))

    # Reconstruct OBB corners in *XY* (x,y) coords of the crop
    # UL: (umin, vmin), UR: (umax, vmin), LR: (umax, vmax), LL: (umin, vmax)
    UL = mean_xy + u * umin + v * vmin
    UR = mean_xy + u * umax + v * vmin
    LR = mean_xy + u * umax + v * vmax
    LL = mean_xy + u * umin + v * vmax

    # Output rectangle size (width along u, height along v)
    out_w = max(1, int(round(umax - umin)))
    out_h = max(1, int(round(vmax - vmin)))

    # Warp from the ORIGINAL crop without rotating pixels → no blank corners
    roi_img = _quad_warp_xy(crop_img, (UL, UR, LR, LL), out_w, out_h, resample=PIL.Image.BILINEAR)
    # Warp the mask using nearest to keep it crisp
    src_mask = crop_mask.astype(np.uint8) * 255
    roi_mask = (
        _quad_warp_xy(src_mask, (UL, UR, LR, LL), out_w, out_h, resample=PIL.Image.NEAREST) > 127
    )

    # Debug
    save_image(roi_img, "roi", debug=dbg_flag, config=config, ts=ts)
    save_image(
        (roi_mask.astype(np.uint8) * 255), "roi_mask_aligned", debug=dbg_flag, config=config, ts=ts
    )

    return {
        "bbox": bbox,  # bbox in original image coords (pre-OBB)
        "crop": roi_img,  # axis-aligned, tightly warped RGB (no blank corners)
        "mask": roi_mask,  # aligned binary mask
        "angle": angle,  # principal axis angle (for logs/QA)
    }
