#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from poster_vision_utils import clean_space, read_json, write_json


ALLOWED_GLOBAL = {
    "card_style": {"radius", "stroke_width", "shadow_opacity"},
    "typography": {"title", "section_title", "body", "caption", "line_height_ratio"},
    "decorations": {"header_rounded", "accent_rule"},
}
ALLOWED_SECTION = {"title_font_size", "body_font_size", "line_height_ratio"}
NUMERIC_LIMITS: dict[tuple[str, str], tuple[float, float, float]] = {
    ("card_style", "radius"): (2.0, 16.0, 2.0),
    ("card_style", "stroke_width"): (0.5, 2.0, 0.3),
    ("card_style", "shadow_opacity"): (0.0, 0.3, 0.06),
    ("typography", "title"): (25.0, 38.0, 2.0),
    ("typography", "section_title"): (14.0, 21.0, 1.0),
    ("typography", "body"): (8.8, 12.0, 0.6),
    ("typography", "caption"): (6.8, 9.0, 0.5),
    ("typography", "line_height_ratio"): (1.18, 1.5, 0.05),
    ("section", "title_font_size"): (14.0, 21.0, 1.0),
    ("section", "body_font_size"): (8.8, 12.0, 0.6),
    ("section", "line_height_ratio"): (1.18, 1.5, 0.05),
}


def safe_numeric_change(target: str, parameter: str, previous: Any, value: Any) -> bool:
    key = ("section" if target.startswith("section:") else target, parameter)
    bounds = NUMERIC_LIMITS.get(key)
    if not bounds or isinstance(previous, bool) or isinstance(value, bool):
        return False
    try:
        previous_number = float(previous)
        value_number = float(value)
    except (TypeError, ValueError):
        return False
    low, high, max_delta = bounds
    return low <= value_number <= high and abs(value_number - previous_number) <= max_delta + 1e-6


def section_by_id(design: dict[str, Any], section_id: str) -> dict[str, Any] | None:
    for section in design.get("sections", []):
        if isinstance(section, dict) and clean_space(section.get("section_id")) == section_id:
            return section
    return None


def apply_patch(design: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any] | None:
    target = clean_space(patch.get("target")).lower()
    parameter = clean_space(patch.get("parameter")).lower()
    value = patch.get("value")
    if target in ALLOWED_GLOBAL:
        if parameter not in ALLOWED_GLOBAL[target]:
            return None
        parent = design.get(target)
        if not isinstance(parent, dict):
            parent = {}
            design[target] = parent
        previous = parent.get(parameter)
        if target == "decorations":
            if not isinstance(value, bool):
                return None
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            recorded_previous = patch.get("previous_value")
            if isinstance(previous, (int, float)) and isinstance(recorded_previous, (int, float)):
                if abs(float(previous) - float(recorded_previous)) > 0.01:
                    return None
            if not safe_numeric_change(target, parameter, previous, value):
                return None
        parent[parameter] = value
        return {"target": target, "parameter": parameter, "previous_value": previous, "value": value}

    if not target.startswith("section:") or parameter not in ALLOWED_SECTION:
        return None
    section_id = target.split(":", 1)[1]
    section = section_by_id(design, section_id)
    if section is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    style_key = "title_style" if parameter == "title_font_size" else "body_style"
    field = "font_size" if parameter.endswith("font_size") else parameter
    style = section.get(style_key)
    if not isinstance(style, dict):
        style = {}
        section[style_key] = style
    previous = style.get(field)
    recorded_previous = patch.get("previous_value")
    if isinstance(previous, (int, float)) and isinstance(recorded_previous, (int, float)):
        if abs(float(previous) - float(recorded_previous)) > 0.01:
            return None
    if not safe_numeric_change(target, parameter, previous, value):
        return None
    style[field] = value
    return {"target": target, "parameter": parameter, "previous_value": previous, "value": value}


def apply_review_repairs(
    design: dict[str, Any],
    review: dict[str, Any],
    iteration: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if review.get("scientific_content_influence") != "none" or review.get("visible_text_retained") is not False:
        return design, []
    art_direction = design.get("art_direction") if isinstance(design.get("art_direction"), dict) else {}
    expected_sha256 = clean_space(art_direction.get("reference_sha256")).lower()
    review_sha256 = clean_space(review.get("reference_sha256")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or review_sha256 != expected_sha256:
        return design, []
    patches = review.get("approved_patches")
    if not isinstance(patches, list):
        return design, []

    actions: list[dict[str, Any]] = []
    for raw in patches[:8]:
        if not isinstance(raw, dict):
            continue
        action = apply_patch(design, raw)
        if action:
            action["iteration"] = iteration
            actions.append(action)

    history = design.get("visual_review_repair")
    if not isinstance(history, dict):
        history = {"iterations": []}
        design["visual_review_repair"] = history
    iterations = history.get("iterations")
    if not isinstance(iterations, list):
        iterations = []
        history["iterations"] = iterations
    iterations.append({
        "iteration": iteration,
        "review_preview_sha256": review.get("preview_sha256"),
        "actions": actions,
    })
    history["status"] = "repaired" if actions else "no_action"
    history["last_iteration"] = iteration
    history["scientific_content_influence"] = "none"
    return design, actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply only allowlisted bounded visual-review patches to a poster design specification.")
    parser.add_argument("--design-json", default="outputs/poster_design_spec.json")
    parser.add_argument("--review-json", default="outputs/poster_visual_review.json")
    parser.add_argument("--output-json", default=None, help="Defaults to overwriting --design-json.")
    parser.add_argument("--report-json", default="outputs/poster_visual_repair_report.json")
    parser.add_argument("--iteration", type=int, default=1)
    args = parser.parse_args()

    design_path = Path(args.design_json)
    output_path = Path(args.output_json) if args.output_json else design_path
    try:
        design = read_json(design_path)
        review = read_json(Path(args.review_json))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    repaired, actions = apply_review_repairs(design, review, max(1, args.iteration))
    write_json(output_path, repaired)
    report = {
        "version": 1,
        "status": "repaired" if actions else "no_action",
        "iteration": max(1, args.iteration),
        "source_review_status": review.get("status"),
        "source_preview_sha256": review.get("preview_sha256"),
        "actions": actions,
        "scientific_content_influence": "none",
    }
    write_json(Path(args.report_json), report)
    print(f"Wrote {output_path}")
    print(f"Wrote {args.report_json}")
    print(f"Visual-review repair actions: {len(actions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
