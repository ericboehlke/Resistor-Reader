from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import PIL.Image


def _resolve_debug_dir(config: Dict[str, Any]) -> Path:
    runtime_cfg = config.get("runtime", {})
    # Support both runtime.debug.dir and legacy runtime.debug_dir.
    nested = runtime_cfg.get("debug", {}).get("dir")
    flat = runtime_cfg.get("debug_dir")
    debug_dir_value = nested or flat or "logs"
    return Path(debug_dir_value)


def save_image(
    image: np.ndarray | PIL.Image.Image,
    suffix: str,
    *,
    debug: bool,
    config: Dict[str, Any] | None = None,
    ts: Optional[str] = None,
) -> Optional[Path]:
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
        Optional configuration dictionary. ``runtime.debug_dir`` controls the
        destination directory. Defaults to ``"logs"``.
    ts:
        Optional timestamp string to prefix the filename. When omitted, the
        current time is used.
    """

    if not debug:
        return None

    if config is None:
        config = {}

    debug_dir = _resolve_debug_dir(config)
    debug_dir.mkdir(parents=True, exist_ok=True)

    if ts is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S%f")

    if isinstance(image, np.ndarray):
        image = PIL.Image.fromarray(image)

    filename_prefix = (
        config.get("runtime", {}).get("debug", {}).get("filename_prefix")
        if isinstance(config, dict)
        else None
    )
    if isinstance(filename_prefix, str) and filename_prefix:
        filename = f"{filename_prefix}_{suffix}.jpg"
    else:
        filename = f"{ts}_{suffix}.jpg"

    path = debug_dir / filename
    image.save(path)
    return path
