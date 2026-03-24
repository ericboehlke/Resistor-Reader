import csv
import copy
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Ensure the project root is on the import path when tests are run directly
sys.path.append(str(Path(__file__).resolve().parents[1]))

import numpy
import PIL.Image
import pytest

from resistor_reader import orchestrator
from resistor_reader.models import ErrorCodeEnum

def _load_cases():
    """Return (filename, value) tuples for each sample resistor image."""
    cases = []
    with open("resistor_pictures/resistors.csv", "r") as csvfile:
        reader = csv.reader(csvfile, delimiter=",", quotechar="|")
        for number, value in reader:
            fname = Path("resistor_pictures") / f"{int(number):04d}.jpg"
            if fname.exists():
                cases.append((str(fname), float(value)))
    return cases


# Load test.yaml as a dictionary
with open("tests/test.yaml", "r") as f:
    test_config = yaml.safe_load(f)


def _short_commit_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _infer_failed_stage(result, expected_value: float) -> str:
    if result.failure == ErrorCodeEnum.E01:
        return "preprocess"
    if result.failure == ErrorCodeEnum.E02:
        return "roi"
    if result.failure == ErrorCodeEnum.E03:
        return "segmentation"
    if result.failure == ErrorCodeEnum.E04:
        if result._metadata.get("resolve"):
            return "resolve"
        return "classification"
    if result.resistance is None or not math.isclose(result.resistance, expected_value):
        return "result"
    return ""


def _best_debug_path(result) -> str:
    meta = result._metadata
    if result.failure == ErrorCodeEnum.E03:
        return (
            meta.get("segmentation", {}).get("debug_image_path")
            or meta.get("roi", {}).get("debug_roi_path")
            or meta.get("preprocess", {}).get("debug_image_path")
            or meta.get("debug_montage_path")
            or ""
        )
    if result.failure == ErrorCodeEnum.E04:
        return (
            meta.get("classification", {}).get("debug_image_path")
            or meta.get("segmentation", {}).get("debug_image_path")
            or meta.get("roi", {}).get("debug_roi_path")
            or meta.get("debug_montage_path")
            or ""
        )
    return (
        meta.get("classification", {}).get("debug_image_path")
        or meta.get("segmentation", {}).get("debug_image_path")
        or meta.get("roi", {}).get("debug_roi_path")
        or meta.get("debug_montage_path")
        or ""
    )


def _append_report(rows: list[dict[str, str]], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    commit = _short_commit_hash()
    with open(report_path, "w") as f:
        f.write(f"# Test Failures\n\n")
        f.write(f"- datetime: `{now}`\n")
        f.write(f"- commit: `{commit}`\n\n")
        f.write(
            "| filename | failed stage | error message | segmentation bounding boxes (optional) | classification colors (optional) | resistance (optional) | debug image path |\n"
        )
        f.write("| --- | --- | --- | --- | --- | --- | --- |\n")
        for row in rows:
            f.write(
                f"| {row['filename']} | {row['failed_stage']} | {row['error_message']} | {row['segmentation_bounding_boxes']} | {row['classification_colors']} | {row['resistance']} | {row['debug_image_path']} |\n"
            )


def test_resistors():
    """Run all images, append markdown failure report, and fail if regressions remain."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path("logs") / run_id
    report_path = run_dir / "test_failures.md"
    rows: list[dict[str, str]] = []
    for fname, expected in _load_cases():
        image_name = Path(fname).stem
        case_config = copy.deepcopy(test_config)
        case_config.setdefault("runtime", {}).setdefault("debug", {})["enabled"] = True
        case_config["runtime"]["debug"]["dir"] = str(run_dir)
        case_config["runtime"]["debug"]["filename_prefix"] = image_name
        case_config["debug_montage_path"] = str(run_dir / f"{image_name}_montage.jpg")

        result = orchestrator.read_pipeline(
            numpy.asarray(PIL.Image.open(fname)),
            case_config,
        )
        failed_stage = _infer_failed_stage(result, expected)
        if not failed_stage:
            continue

        if failed_stage == "result":
            err = f"incorrect resistance: expected={expected:g}, got={result.resistance!s}"
        else:
            err = result.error_msg or "pipeline failure"

        colors = ""
        if result.colors is not None:
            colors = ", ".join(c.value for c in result.colors)

        debug_path = _best_debug_path(result)

        rows.append(
            {
                "filename": Path(fname).name,
                "failed_stage": failed_stage,
                "error_message": err,
                "segmentation_bounding_boxes": str(result.bands) if result.bands else "",
                "classification_colors": colors,
                "resistance": "" if result.resistance is None else f"{result.resistance:g}",
                "debug_image_path": debug_path,
            }
        )

    _append_report(rows, report_path)
    assert not rows, f"{len(rows)} failures logged to {report_path}"


def test_0():
    """Validate that each example image is parsed to the expected value."""
    result = orchestrator.read_pipeline(
        numpy.asarray(PIL.Image.open(Path("resistor_pictures") / "0000.jpg")),
        test_config,
    )
    assert result.failure is None
    assert result.resistance == 100


if __name__ == "__main__":
    pytest.main([__file__])
