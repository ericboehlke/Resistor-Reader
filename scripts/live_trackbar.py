#!/usr/bin/env python3
"""Interactive trackbar tool for live pipeline tuning."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from resistor_reader import orchestrator

CONTROL_WINDOW = "Resistor Reader Controls"
PREVIEW_WINDOW = "Resistor Reader Preview"


def _read_image(path: str) -> np.ndarray:
    bgr = cv2.imread(path)
    if bgr is None:
        raise ValueError(f"Unable to read image: {path}")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _set_nested(config: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node: dict[str, Any] = config
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[path[-1]] = value


def _get_nested(config: dict[str, Any], path: tuple[str, ...], default: Any) -> Any:
    node: Any = config
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
        if node is None:
            return default
    return node


def _bool_to_slider(value: bool) -> int:
    return 1 if value else 0


def _slider_to_bool(value: int) -> bool:
    return value > 0


TRACKBARS: list[tuple[str, tuple[str, ...], int, int]] = [
    ("runtime_debug", ("runtime", "debug", "enabled"), 0, 1),
    ("proc_debug", ("processing", "debug_image"), 0, 1),
    ("roi_debug", ("region_of_interest", "debug_image"), 0, 1),
    ("seg_debug", ("segmentation", "debug_image"), 0, 1),
    ("cls_debug", ("classification", "debug_image"), 0, 1),
    ("seg_smooth", ("segmentation", "band_smooth_window"), 9, 31),
    ("seg_min_band", ("segmentation", "min_band_width_px"), 6, 30),
]


def _build_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for name, path, _, _ in TRACKBARS:
        val = cv2.getTrackbarPos(name, CONTROL_WINDOW)
        if path[-1].endswith("debug") or path[-1] == "enabled" or path[-1] == "debug_image":
            _set_nested(overrides, path, _slider_to_bool(val))
        else:
            _set_nested(overrides, path, val)
    return overrides


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _init_trackbars(base_config: dict[str, Any]) -> None:
    cv2.namedWindow(CONTROL_WINDOW, cv2.WINDOW_NORMAL)
    cv2.namedWindow(PREVIEW_WINDOW, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(CONTROL_WINDOW, 360, 420)
    cv2.resizeWindow(PREVIEW_WINDOW, 900, 700)
    cv2.moveWindow(CONTROL_WINDOW, 30, 60)
    cv2.moveWindow(PREVIEW_WINDOW, 420, 60)
    for name, path, default, max_value in TRACKBARS:
        raw = _get_nested(base_config, path, default)
        if isinstance(raw, bool):
            initial = _bool_to_slider(raw)
        else:
            try:
                initial = int(raw)
            except Exception:
                initial = int(default)
        initial = max(0, min(max_value, initial))
        cv2.createTrackbar(name, CONTROL_WINDOW, initial, max_value, lambda _: None)


def _reset_trackbars(base_config: dict[str, Any]) -> None:
    for name, path, default, max_value in TRACKBARS:
        raw = _get_nested(base_config, path, default)
        if isinstance(raw, bool):
            val = _bool_to_slider(raw)
        else:
            try:
                val = int(raw)
            except Exception:
                val = int(default)
        cv2.setTrackbarPos(name, CONTROL_WINDOW, max(0, min(max_value, val)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Live trackbar tuning for resistor pipeline")
    parser.add_argument("--image", required=True, help="Image file to process repeatedly")
    parser.add_argument("--config", default="config.yaml", help="Base pipeline YAML config")
    parser.add_argument("--save-config", default=None, help="Optional path to save tuned YAML")
    parser.add_argument(
        "--stage",
        default="all",
        choices=["all", "preprocess", "roi", "segmentation", "classification"],
        help="Reserved for stage-focused views",
    )
    parser.add_argument("--debug", action="store_true", help="Force runtime.debug.enabled=true")
    parser.add_argument("--debug-dir", default=None, help="Override runtime.debug.dir")
    args = parser.parse_args()

    image = _read_image(args.image)
    base_config = orchestrator.load_config(args.config)
    if args.debug:
        _set_nested(base_config, ("runtime", "debug", "enabled"), True)
    if args.debug_dir:
        _set_nested(base_config, ("runtime", "debug", "dir"), args.debug_dir)

    _init_trackbars(base_config)
    last_signature = ""
    preview = np.zeros((300, 640, 3), dtype=np.uint8)

    while True:
        overrides = _build_overrides()
        config = _deep_merge(base_config, overrides)
        signature = str(overrides)
        if signature != last_signature:
            result = orchestrator.read_pipeline(image, config)
            montage = result.debug_image
            if montage is None:
                preview = np.full((220, 640, 3), 245, dtype=np.uint8)
                cv2.putText(
                    preview,
                    result.error_msg or "Pipeline failed",
                    (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 255),
                    1,
                    cv2.LINE_AA,
                )
            else:
                preview = montage.copy()

            status = (
                f"failure={result.failure.name if result.failure else 'none'} "
                f"ohms={result.resistance if result.resistance is not None else 'n/a'}"
            )
            cv2.putText(
                preview,
                status,
                (10, 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (10, 10, 10),
                1,
                cv2.LINE_AA,
            )
            last_signature = signature

        bgr_preview = cv2.cvtColor(preview, cv2.COLOR_RGB2BGR)
        cv2.imshow(PREVIEW_WINDOW, bgr_preview)
        key = cv2.waitKey(60) & 0xFF
        if key in (27, ord("q")):
            break
        if key == ord("r"):
            _reset_trackbars(base_config)
            last_signature = ""
        if key == ord("s"):
            if args.save_config is None:
                continue
            out_cfg = _deep_merge(base_config, _build_overrides())
            out_path = Path(args.save_config)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w") as f:
                yaml.safe_dump(out_cfg, f, sort_keys=False)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
