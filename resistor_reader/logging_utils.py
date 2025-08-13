from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import PIL.Image


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

    debug_dir = Path(config.get("runtime", {}).get("debug_dir", "logs"))
    debug_dir.mkdir(parents=True, exist_ok=True)

    if ts is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S%f")

    if isinstance(image, np.ndarray):
        image = PIL.Image.fromarray(image)

    path = debug_dir / f"{ts}_{suffix}.jpg"
    image.save(path)
    return path
