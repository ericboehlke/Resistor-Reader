"""Debug image logging.

Writes are opt-in (``debug=False`` is a no-op) and the destination directory is
capped, because on the appliance ``logs/`` is a Log2Ram RAM disk: an unbounded
five-images-per-button-press would eventually fill it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import PIL.Image

# Roughly 30 reads' worth of per-stage images before the oldest are dropped.
DEFAULT_MAX_FILES = 200


def _debug_cfg(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("runtime", {}).get("debug", {}) or {}


def _prune(debug_dir: Path, max_files: int) -> None:
    """Drop the oldest images once the directory exceeds ``max_files``."""
    if max_files <= 0:
        return
    files = sorted(debug_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
    for stale in files[: max(0, len(files) - max_files)]:
        stale.unlink(missing_ok=True)


def save_image(
    image: np.ndarray | PIL.Image.Image,
    suffix: str,
    *,
    debug: bool,
    config: dict[str, Any] | None = None,
    ts: str | None = None,
) -> Path | None:
    """Save an image to the debug log directory and return its path.

    Parameters
    ----------
    image:
        Image to save. Can be a ``numpy`` array or ``PIL.Image`` instance.
    suffix:
        Suffix appended to the filename after the timestamp, e.g. ``"pre"``.
    debug:
        When ``False`` no file is written and ``None`` is returned.
    config:
        Optional configuration dictionary. ``runtime.debug.dir`` controls the
        destination directory (default ``"logs"``) and ``runtime.debug.max_files``
        how many images it keeps (default 200; 0 disables pruning).
    ts:
        Optional timestamp string to prefix the filename. When omitted, the
        current time is used.
    """

    if not debug:
        return None

    cfg = _debug_cfg(config or {})
    debug_dir = Path(cfg.get("dir") or "logs")
    debug_dir.mkdir(parents=True, exist_ok=True)

    if ts is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S%f")

    if isinstance(image, np.ndarray):
        image = PIL.Image.fromarray(image)

    prefix = cfg.get("filename_prefix")
    stem = prefix if isinstance(prefix, str) and prefix else ts
    path = debug_dir / f"{stem}_{suffix}.jpg"
    image.save(path)

    _prune(debug_dir, int(cfg.get("max_files", DEFAULT_MAX_FILES)))
    return path
