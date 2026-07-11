#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def section_bullet_count(content: dict[str, Any], key: str) -> int:
    section = content.get(key)
    if not isinstance(section, dict):
        return 0
    bullets = section.get("bullets", [])
    return len(bullets) if isinstance(bullets, list) else 0


def selected_figure_roles(content: dict[str, Any]) -> set[str]:
    figures = content.get("figures_to_use", [])
    if not isinstance(figures, list):
        return set()
    return {str(figure.get("role", "")) for figure in figures if isinstance(figure, dict)}


def choose_template(content: dict[str, Any]) -> tuple[str, str]:
    roles = selected_figure_roles(content)
    result_bullets = section_bullet_count(content, "results")
    method_bullets = section_bullet_count(content, "method")
    if "result_evidence" in roles and result_bullets >= method_bullets:
        return "result_centered", "Selected because a result evidence figure is present and the results section is at least as dense as method."
    if "method_overview" in roles:
        return "method_centered", "Selected because a method overview figure is present and method needs visual support."
    if "qualitative_example" in roles:
        return "case_study", "Selected because qualitative example figures are the strongest visual evidence."
    return "text_fallback", "Selected because no strong extracted figure role was available."


def build_design_spec(content: dict[str, Any]) -> dict[str, Any]:
    template, template_rationale = choose_template(content)
    result_callouts = content.get("result_callouts", [])
    if not isinstance(result_callouts, list):
        result_callouts = []
    take_home_message = str(content.get("take_home_message", "") or content.get("title", ""))
    if template == "result_centered":
        section_order = [
            "problem",
            "core_idea",
            "method",
            "key_figures",
            "results",
            "contribution",
            "conclusion",
        ]
        emphasis = {"results": "hero", "key_figures": "large", "method": "medium"}
    elif template == "method_centered":
        section_order = [
            "problem",
            "core_idea",
            "method",
            "key_figures",
            "results",
            "contribution",
            "conclusion",
        ]
        emphasis = {"method": "hero", "key_figures": "large", "results": "medium"}
    elif template == "case_study":
        section_order = [
            "problem",
            "core_idea",
            "key_figures",
            "method",
            "results",
            "contribution",
            "conclusion",
        ]
        emphasis = {"key_figures": "hero", "results": "medium", "method": "compact"}
    else:
        section_order = [
            "problem",
            "core_idea",
            "method",
            "results",
            "contribution",
            "conclusion",
            "key_figures",
        ]
        emphasis = {"core_idea": "large", "results": "medium", "key_figures": "compact"}

    density = {}
    for key in ["problem", "core_idea", "method", "results", "contribution", "conclusion"]:
        count = section_bullet_count(content, key)
        density[key] = "compact" if count <= 2 else "medium" if count <= 4 else "dense"

    return {
        "version": 1,
        "theme": "modern_academic_evidence",
        "template": template,
        "template_rationale": template_rationale,
        "hero_message": take_home_message,
        "callouts": result_callouts[:3],
        "canvas": {
            "width": 1189,
            "height": 841,
            "unit": "mm-like viewBox units",
        },
        "grid": {
            "columns": 3,
            "margin": 36,
            "gutter": 24,
            "header_height": 116,
            "footer_height": 34,
        },
        "visual_hierarchy": {
            "main_message": content.get("title", "Untitled Paper"),
            "take_home_message": take_home_message,
            "section_order": section_order,
            "emphasis": emphasis,
            "hero_sections": [key for key, value in emphasis.items() if value == "hero"],
            "callout_sections": ["results"] if result_callouts else [],
            "primary_figure_role": "method_overview",
            "secondary_figure_role": "result_evidence",
        },
        "typography": {
            "font_family": "Arial, Helvetica, sans-serif",
            "title": 34,
            "authors": 12.5,
            "section_title": 16.5,
            "body": 10.8,
            "caption": 8.2,
            "footer": 8.2,
            "line_height_ratio": 1.34,
        },
        "color_palette": {
            "background": "#eef3f8",
            "panel": "#ffffff",
            "panel_stroke": "#d3dce8",
            "text": "#162033",
            "muted": "#5f6b7a",
            "accent_primary": "#1d4ed8",
            "accent_secondary": "#0f766e",
            "accent_result": "#c2410c",
            "accent_neutral": "#475569",
            "header_rule": "#9bb5d6",
            "header_background": "#12233f",
            "header_text": "#ffffff",
            "header_muted": "#d7e3f3",
            "highlight_background": "#fff7ed",
            "figure_background": "#f8fafc",
        },
        "card_style": {
            "radius": 8,
            "padding_x": 20,
            "padding_y": 18,
            "accent_bar_width": 6,
            "stroke_width": 1.1,
            "shadow_opacity": 0.22,
        },
        "card_variants": {
            "problem": "standard",
            "core_idea": "idea",
            "method": "standard",
            "key_figures": "visual",
            "results": "hero" if result_callouts or template == "result_centered" else "standard",
            "contribution": "compact",
            "conclusion": "compact",
        },
        "image_placement": {
            "max_figures": 2,
            "primary_slot": "key_figures.primary",
            "secondary_slot": "key_figures.secondary",
            "caption_lines": 3,
            "preserve_aspect_ratio": "xMidYMid meet",
        },
        "section_density": density,
        "overflow_rules": [
            "wrap_text_to_box",
            "drop_extra_bullets_after_box_is_full",
            "prefer_reducing_bullets_before_reducing_font",
            "keep_images_inside_figure_slots",
            "never_allow_panel_overlap",
        ],
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build structured poster design/layout spec from poster_content.json.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--output-json", default="outputs/poster_design_spec.json")
    args = parser.parse_args()

    content_json = Path(args.content_json)
    output_json = Path(args.output_json)
    if not content_json.exists():
        print(f"Error: content JSON does not exist: {content_json}", file=sys.stderr)
        return 1

    content = json.loads(content_json.read_text(encoding="utf-8"))
    spec = build_design_spec(content)
    write_json(output_json, spec)
    print(f"Wrote {output_json}")
    print(f"Template: {spec.get('template')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
