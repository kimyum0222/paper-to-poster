#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def intersection_over_union(first: dict[str, Any], second: dict[str, Any]) -> float:
    ax, ay, aw, ah = (float(first.get(key, 0)) for key in ["x", "y", "width", "height"])
    bx, by, bw, bh = (float(second.get(key, 0)) for key in ["x", "y", "width", "height"])
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def build_report(analysis: dict[str, Any], design: dict[str, Any], layout: dict[str, Any]) -> dict[str, Any]:
    derived = analysis.get("derived_design_tokens") if isinstance(analysis.get("derived_design_tokens"), dict) else {}
    expected_sections = {
        str(item.get("section_id", "")): item
        for item in derived.get("sections", [])
        if isinstance(item, dict) and str(item.get("section_id", ""))
    }
    actual_boxes = layout.get("section_bounding_boxes") if isinstance(layout.get("section_bounding_boxes"), dict) else {}
    section_scores = {
        section_id: round(intersection_over_union(expected, actual_boxes.get(section_id, {})), 4)
        for section_id, expected in expected_sections.items()
    }
    geometry_score = sum(section_scores.values()) / len(section_scores) if section_scores else 0.0
    expected_palette = derived.get("color_palette") if isinstance(derived.get("color_palette"), dict) else {}
    actual_palette = design.get("color_palette") if isinstance(design.get("color_palette"), dict) else {}
    palette_keys = ["background", "panel", "header_background", "accent_primary", "accent_secondary", "accent_result"]
    palette_matches = [expected_palette.get(key) == actual_palette.get(key) for key in palette_keys if expected_palette.get(key)]
    palette_score = sum(palette_matches) / len(palette_matches) if palette_matches else 0.0
    sections = [item for item in design.get("sections", []) if isinstance(item, dict)]
    hero_sections = [item for item in sections if item.get("visual_role") == "hero"]
    hero_score = 0.0
    if len(hero_sections) == 1 and sections:
        hero_area = float(hero_sections[0].get("width", 0)) * float(hero_sections[0].get("height", 0))
        hero_score = 1.0 if hero_area >= max(float(item.get("width", 0)) * float(item.get("height", 0)) for item in sections) else 0.0
    decorations = design.get("decorative_assets") if isinstance(design.get("decorative_assets"), list) else []
    included = [item for item in decorations if isinstance(item, dict) and item.get("included")]
    decoration_score = min(1.0, len(included) / 2)
    overall = geometry_score * 0.55 + palette_score * 0.20 + hero_score * 0.15 + decoration_score * 0.10
    return {
        "report_kind": "structural_token_conformance",
        "status": "passed" if overall >= 0.80 and geometry_score >= 0.80 else "needs_revision",
        "conformance_scope": "Checks whether analyzed geometry, palette, hero priority, and declared decorations reached the executable design. It does not compare final-preview pixels with the reference image.",
        "pixel_similarity_measured": False,
        "panel_geometry_score": round(geometry_score, 4),
        "section_geometry_scores": section_scores,
        "palette_score": round(palette_score, 4),
        "hero_area_score": round(hero_score, 4),
        "decoration_score": round(decoration_score, 4),
        "overall_score": round(overall, 4),
        "reference_analysis_status": analysis.get("status"),
        "layout_source": design.get("layout_source"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check deterministic poster conformance to analyzed style tokens.")
    parser.add_argument("--analysis-json", default="outputs/poster_style_analysis.json")
    parser.add_argument("--design-json", default="outputs/poster_design_spec.json")
    parser.add_argument("--layout-json", default="outputs/poster_layout.json")
    parser.add_argument("--output-json", default="outputs/poster_style_conformance_report.json")
    args = parser.parse_args()
    try:
        report = build_report(
            read_json(Path(args.analysis_json)),
            read_json(Path(args.design_json)),
            read_json(Path(args.layout_json)),
        )
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {args.output_json}")
    print(f"Style-token conformance: {report['status']} ({report['overall_score']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
