#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 2)


def ensure_dict(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def overflow_sides(item: dict[str, Any]) -> set[str]:
    raw = item.get("overflow", {})
    if not isinstance(raw, dict):
        return set()
    return {str(side) for side, flagged in raw.items() if flagged}


def repair_design(design: dict[str, Any], overflow: dict[str, Any], iteration: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    items = overflow.get("overflow_items", [])
    if not isinstance(items, list) or not items:
        return design, []

    typography = ensure_dict(design, "typography")
    grid = ensure_dict(design, "grid")
    image_placement = ensure_dict(design, "image_placement")
    callout_style = ensure_dict(design, "callout_style")
    explicit_sections = design.get("sections") if isinstance(design.get("sections"), list) else []
    sections_by_id = {
        str(section.get("section_id", "")).replace("-", "_"): section
        for section in explicit_sections
        if isinstance(section, dict) and section.get("section_id")
    }

    actions: list[dict[str, Any]] = []

    def add_action(target: str, problem: str, action: str) -> None:
        actions.append({
            "iteration": iteration,
            "target": target,
            "problem": problem,
            "action": action,
        })

    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        target = str(raw_item.get("section", "unknown"))
        sides = overflow_sides(raw_item)
        problem = ", ".join(sorted(sides)) or "unknown overflow"

        if target.startswith("result-callout"):
            if "right" in sides or "left" in sides:
                old_min = float(callout_style.get("value_min_font_size", 7.4) or 7.4)
                old_max = float(callout_style.get("value_max_font_size", 18.0) or 18.0)
                callout_style["value_min_font_size"] = clamp(old_min - 0.8, 5.8, 10.0)
                callout_style["value_max_font_size"] = clamp(old_max - 1.4, 9.0, 18.0)
                add_action(target, problem, "reduced callout value font size bounds")
            if "bottom" in sides or "top" in sides:
                old_height = float(callout_style.get("height", 74) or 74)
                callout_style["height"] = clamp(old_height + 10, 74, 112)
                old_scale = float(callout_style.get("detail_font_scale", 1.0) or 1.0)
                callout_style["detail_font_scale"] = clamp(old_scale - 0.08, 0.72, 1.0)
                add_action(target, problem, "increased callout height and reduced detail text scale")
            continue

        if target == "header":
            if "bottom" in sides or "top" in sides:
                if explicit_sections:
                    old_title = float(typography.get("title", 34) or 34)
                    typography["title"] = clamp(old_title - 1.5, 25, 38)
                    add_action(target, problem, "reduced title size while preserving explicit section coordinates")
                else:
                    old_header = float(grid.get("header_height", 116) or 116)
                    grid["header_height"] = clamp(old_header + 12, 96, 160)
                    add_action(target, problem, "increased header height")
            if "right" in sides or "left" in sides:
                old_title = float(typography.get("title", 34) or 34)
                typography["title"] = clamp(old_title - 1.5, 25, 38)
                add_action(target, problem, "reduced title font size")
            old_authors = float(typography.get("authors", 12.5) or 12.5)
            typography["authors"] = clamp(old_authors - 0.4, 9.5, 13)
            continue

        if target in {"key-figure", "primary-figure", "secondary-figure"} or target.startswith("figure-slot-") or "caption" in str(raw_item.get("text", "")).lower():
            old_caption = float(typography.get("caption", 8.2) or 8.2)
            typography["caption"] = clamp(old_caption - 0.4, 6.8, 9.0)
            old_lines = int(image_placement.get("caption_lines", 3) or 3)
            image_placement["caption_lines"] = min(5, old_lines + 1)
            add_action(target, problem, "reduced caption font size and allowed more caption lines")
            continue

        normalized_target = target.replace("-", "_")
        if normalized_target in sections_by_id:
            section = sections_by_id[normalized_target]
            body_style = ensure_dict(section, "body_style")
            old_body = float(body_style.get("font_size", typography.get("body", 10.8)) or 10.8)
            body_style["font_size"] = clamp(old_body - (0.5 if "bottom" in sides or "top" in sides else 0.35), 8.8, 12.0)
            old_line = float(body_style.get("line_height_ratio", typography.get("line_height_ratio", 1.34)) or 1.34)
            if "bottom" in sides or "top" in sides:
                body_style["line_height_ratio"] = clamp(old_line - 0.03, 1.18, 1.5)
            add_action(target, problem, "reduced the explicit section body size without changing verified text or geometry")
            continue

        if target in {"problem", "core_idea", "method", "results", "contribution", "conclusion"}:
            if "bottom" in sides or "top" in sides:
                old_body = float(typography.get("body", 10.8) or 10.8)
                typography["body"] = clamp(old_body - 0.45, 8.8, 11.5)
                old_line = float(typography.get("line_height_ratio", 1.34) or 1.34)
                typography["line_height_ratio"] = clamp(old_line - 0.03, 1.18, 1.38)
                add_action(target, problem, "reduced body font size and line height")
            if "right" in sides or "left" in sides:
                old_body = float(typography.get("body", 10.8) or 10.8)
                typography["body"] = clamp(old_body - 0.35, 8.8, 11.5)
                add_action(target, problem, "reduced body font size for horizontal fit")
            continue

        old_body = float(typography.get("body", 10.8) or 10.8)
        typography["body"] = clamp(old_body - 0.3, 8.8, 11.5)
        add_action(target, problem, "applied conservative global body font reduction")

    history = ensure_dict(design, "layout_repair")
    iterations = history.get("iterations")
    if not isinstance(iterations, list):
        iterations = []
        history["iterations"] = iterations
    iterations.append({
        "iteration": iteration,
        "overflow_line_count": overflow.get("overflow_line_count", len(items)),
        "actions": actions,
    })
    history["last_iteration"] = iteration
    history["status"] = "repaired" if actions else "no_action"
    return design, actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair poster design parameters after text overflow validation.")
    parser.add_argument("--design-json", default="outputs/poster_design_spec.json")
    parser.add_argument("--overflow-json", default="outputs/poster_overflow_report.json")
    parser.add_argument("--output-json", default=None, help="Defaults to overwriting --design-json.")
    parser.add_argument("--repair-report", default="outputs/layout_repair_report.json")
    parser.add_argument("--iteration", type=int, default=1)
    args = parser.parse_args()

    design_path = Path(args.design_json)
    overflow_path = Path(args.overflow_json)
    output_path = Path(args.output_json) if args.output_json else design_path
    report_path = Path(args.repair_report)

    design = read_json(design_path)
    overflow = read_json(overflow_path)
    if not design:
        print(f"Error: design JSON could not be read: {design_path}")
        return 1
    if not overflow:
        print(f"Error: overflow report could not be read: {overflow_path}")
        return 1

    if overflow.get("status") == "passed":
        report = {
            "status": "no_repair_needed",
            "iteration": args.iteration,
            "actions": [],
        }
        write_json(report_path, report)
        print(f"Wrote {report_path}")
        print("No layout repair needed.")
        return 0

    repaired, actions = repair_design(design, overflow, args.iteration)
    write_json(output_path, repaired)
    report = {
        "status": "repaired" if actions else "no_action",
        "iteration": args.iteration,
        "actions": actions,
        "source_overflow_status": overflow.get("status"),
        "source_overflow_line_count": overflow.get("overflow_line_count", 0),
    }
    write_json(report_path, report)
    print(f"Wrote {output_path}")
    print(f"Wrote {report_path}")
    print(f"Repair actions: {len(actions)}")
    return 0 if actions else 1


if __name__ == "__main__":
    raise SystemExit(main())
