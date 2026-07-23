#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from openai_response_utils import json_object_from_text, response_output_text
from poster_vision_utils import clamp_float, clean_space, image_data_uri, read_json, sha256_file, write_json


SCORE_KEYS = {"composition", "hierarchy", "spacing", "style_similarity", "readability"}
SEVERITIES = {"low", "medium", "high"}
ISSUE_CATEGORIES = {"hierarchy", "spacing", "density", "typography", "card_style", "decoration", "color", "figure_balance"}
GLOBAL_PATCHES: dict[str, dict[str, tuple[float, float, float]]] = {
    "card_style": {
        "radius": (2.0, 16.0, 2.0),
        "stroke_width": (0.5, 2.0, 0.3),
        "shadow_opacity": (0.0, 0.3, 0.06),
    },
    "typography": {
        "title": (25.0, 38.0, 2.0),
        "section_title": (14.0, 21.0, 1.0),
        "body": (8.8, 12.0, 0.6),
        "caption": (6.8, 9.0, 0.5),
        "line_height_ratio": (1.18, 1.5, 0.05),
    },
}
SECTION_PATCHES: dict[str, tuple[float, float, float]] = {
    "title_font_size": (14.0, 21.0, 1.0),
    "body_font_size": (8.8, 12.0, 0.6),
    "line_height_ratio": (1.18, 1.5, 0.05),
}
BOOLEAN_PATCHES = {"header_rounded", "accent_rule"}


def compact_box(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    result = {
        key: clamp_float(value.get(key), 0, 2000, 0)
        for key in ["x", "y", "width", "height"]
    }
    return result if result["width"] > 0 and result["height"] > 0 else None


def allowed_section_ids(design: dict[str, Any], layout: dict[str, Any]) -> list[str]:
    ids = [
        clean_space(section.get("section_id"))
        for section in design.get("sections", [])
        if isinstance(section, dict) and clean_space(section.get("section_id"))
    ]
    if ids:
        return ids
    boxes = layout.get("section_bounding_boxes") if isinstance(layout.get("section_bounding_boxes"), dict) else {}
    return [
        clean_space(key).replace("-", "_")
        for key in boxes
        if clean_space(key) not in {"header", "footer", "key-figure"}
    ]


def build_review_context(design: dict[str, Any], layout: dict[str, Any], overflow: dict[str, Any]) -> dict[str, Any]:
    boxes = layout.get("section_bounding_boxes") if isinstance(layout.get("section_bounding_boxes"), dict) else {}
    compact_boxes = {
        clean_space(key): box
        for key, value in boxes.items()
        if (box := compact_box(value)) is not None
    }
    sections: list[dict[str, Any]] = []
    for raw in design.get("sections", []):
        if not isinstance(raw, dict):
            continue
        sections.append({
            "section_id": clean_space(raw.get("section_id")),
            "visual_role": clean_space(raw.get("visual_role")),
            "priority": int(clamp_float(raw.get("priority"), 1, 5, 3)),
            "text_density": clean_space(raw.get("text_density")),
            "bullet_budget": int(clamp_float(raw.get("bullet_budget"), 1, 6, 3)),
            "figure_slot_count": len(raw.get("figure_slots", [])) if isinstance(raw.get("figure_slots"), list) else 0,
        })
    return {
        "contract": {
            "reference_is_style_only": True,
            "do_not_transcribe_visible_text": True,
            "do_not_modify_scientific_content": True,
            "only_allow_bounded_design_parameter_patches": True,
        },
        "canvas": {
            "width": layout.get("canvas_width", 1189),
            "height": layout.get("canvas_height", 841),
        },
        "layout_source": layout.get("layout_source"),
        "section_boxes": compact_boxes,
        "section_roles": sections,
        "typography": design.get("typography", {}),
        "card_style": design.get("card_style", {}),
        "decorations": {
            key: (design.get("decorations") or {}).get(key)
            for key in ["header_rounded", "accent_rule"]
        },
        "overflow_status": overflow.get("status"),
        "allowed_patch_targets": {
            "card_style": sorted(GLOBAL_PATCHES["card_style"]),
            "typography": sorted(GLOBAL_PATCHES["typography"]),
            "decorations": sorted(BOOLEAN_PATCHES),
            "section": sorted(SECTION_PATCHES),
        },
    }


def call_model(
    client: Any,
    model: str,
    reference_path: Path,
    preview_path: Path,
    context: dict[str, Any],
) -> dict[str, Any]:
    prompt = f"""
Compare two academic-poster images. Image 1 is a non-authoritative style reference. Image 2 is the deterministic SVG render containing verified paper content.

Evaluate composition, visual hierarchy, spacing, style similarity, and readability. Do not OCR, quote, transcribe, summarize, correct, or return any title, author, number, claim, caption, chart label, or other visible text. Do not judge scientific correctness. Do not generate SVG or arbitrary code.

Structured design context:
{json.dumps(context, ensure_ascii=False, indent=2)}

Return only JSON:
{{
  "status": "passed | needs_revision | failed",
  "scores": {{
    "composition": 0.0,
    "hierarchy": 0.0,
    "spacing": 0.0,
    "style_similarity": 0.0,
    "readability": 0.0
  }},
  "issues": [
    {{
      "severity": "low | medium | high",
      "target": "overall or an allowed section_id",
      "category": "hierarchy | spacing | density | typography | card_style | decoration | color | figure_balance"
    }}
  ],
  "patches": [
    {{
      "target": "card_style | typography | decorations | section:<allowed section_id>",
      "parameter": "one allowed parameter from the context",
      "value": 0.0,
      "confidence": 0.0
    }}
  ]
}}

Suggest at most eight patches. Never suggest coordinates, panel dimensions, colors, content changes, rewritten text, figure replacement, image cropping, new sections, or generated scientific graphics. Use absolute numeric values, not prose operations. A patch is only advisory and will be clamped and revalidated locally.
"""
    response = client.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_text", "text": "Image 1: style reference."},
                {"type": "input_image", "image_url": image_data_uri(reference_path)},
                {"type": "input_text", "text": "Image 2: rendered deterministic SVG preview."},
                {"type": "input_image", "image_url": image_data_uri(preview_path)},
            ],
        }],
    )
    return json_object_from_text(response_output_text(response))


def current_patch_value(design: dict[str, Any], target: str, parameter: str) -> Any:
    if target in GLOBAL_PATCHES:
        value = design.get(target)
        return value.get(parameter) if isinstance(value, dict) else None
    if target == "decorations":
        value = design.get("decorations")
        return value.get(parameter) if isinstance(value, dict) else None
    if target.startswith("section:"):
        section_id = target.split(":", 1)[1]
        for section in design.get("sections", []):
            if not isinstance(section, dict) or clean_space(section.get("section_id")) != section_id:
                continue
            style_key = "title_style" if parameter == "title_font_size" else "body_style"
            style = section.get(style_key) if isinstance(section.get(style_key), dict) else {}
            field = "font_size" if parameter.endswith("font_size") else parameter
            return style.get(field)
    return None


def normalize_patch(
    item: dict[str, Any],
    design: dict[str, Any],
    section_ids: set[str],
) -> dict[str, Any] | None:
    target = clean_space(item.get("target")).lower()
    parameter = clean_space(item.get("parameter")).lower()
    confidence = clamp_float(item.get("confidence"), 0, 1, 0)
    if confidence < 0.7:
        return None

    if target == "decorations":
        if parameter not in BOOLEAN_PATCHES or not isinstance(item.get("value"), bool):
            return None
        return {"target": target, "parameter": parameter, "value": item["value"], "confidence": confidence}

    if target.startswith("section:"):
        section_id = target.split(":", 1)[1]
        if section_id not in section_ids or parameter not in SECTION_PATCHES:
            return None
        bounds = SECTION_PATCHES[parameter]
    elif target in GLOBAL_PATCHES and parameter in GLOBAL_PATCHES[target]:
        bounds = GLOBAL_PATCHES[target][parameter]
    else:
        return None

    current = current_patch_value(design, target, parameter)
    if isinstance(current, bool):
        return None
    try:
        current_number = float(current)
        requested = float(item.get("value"))
    except (TypeError, ValueError):
        return None
    low, high, max_delta = bounds
    bounded_low = max(low, current_number - max_delta)
    bounded_high = min(high, current_number + max_delta)
    value = round(max(bounded_low, min(bounded_high, requested)), 3)
    if abs(value - current_number) < 0.0005:
        return None
    return {
        "target": target,
        "parameter": parameter,
        "value": value,
        "previous_value": round(current_number, 3),
        "confidence": confidence,
    }


def normalize_report(
    raw: dict[str, Any],
    *,
    model: str,
    reference_path: Path,
    preview_path: Path,
    design: dict[str, Any],
    layout: dict[str, Any],
) -> dict[str, Any]:
    sections = set(allowed_section_ids(design, layout))
    scores_raw = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    scores = {key: clamp_float(scores_raw.get(key), 0, 1, 0) for key in sorted(SCORE_KEYS)}

    issues: list[dict[str, str]] = []
    high_count = 0
    medium_count = 0
    raw_issues = raw.get("issues", [])
    if isinstance(raw_issues, list):
        for item in raw_issues[:20]:
            if not isinstance(item, dict):
                continue
            severity = clean_space(item.get("severity")).lower()
            category = clean_space(item.get("category")).lower()
            target = clean_space(item.get("target")).lower().replace("-", "_")
            if severity not in SEVERITIES or category not in ISSUE_CATEGORIES:
                continue
            if target != "overall" and target not in sections:
                continue
            issues.append({"severity": severity, "target": target, "category": category})
            high_count += int(severity == "high")
            medium_count += int(severity == "medium")

    patches: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    raw_patches = raw.get("patches", [])
    if isinstance(raw_patches, list):
        for item in raw_patches:
            if not isinstance(item, dict):
                continue
            normalized = normalize_patch(item, design, sections)
            if not normalized:
                continue
            key = (normalized["target"], normalized["parameter"])
            if key in seen:
                continue
            seen.add(key)
            patches.append(normalized)
            if len(patches) >= 8:
                break

    requested_status = clean_space(raw.get("status")).lower()
    if high_count:
        status = "failed"
    elif medium_count or patches:
        status = "needs_revision"
    elif requested_status == "passed":
        status = "passed"
    else:
        status = "needs_revision"
    return {
        "version": 1,
        "status": status,
        "method": "multimodal_reference_vs_render_review",
        "model": model,
        "reference_path": str(reference_path),
        "reference_sha256": sha256_file(reference_path),
        "preview_path": str(preview_path),
        "preview_sha256": sha256_file(preview_path),
        "scores": scores,
        "high_risk_count": high_count,
        "medium_risk_count": medium_count,
        "issues": issues,
        "approved_patches": patches,
        "visible_text_retained": False,
        "scientific_content_influence": "none",
        "provider_received_rendered_preview": True,
        "review_scope": "composition, hierarchy, spacing, style similarity, and visual readability only",
    }


def skipped_report(mode: str, model: str, reason: str, reference_path: Path, preview_path: Path) -> dict[str, Any]:
    return {
        "version": 1,
        "status": "skipped",
        "mode": mode,
        "method": "not_run",
        "model": model,
        "reference_path": str(reference_path),
        "reference_sha256": sha256_file(reference_path) if reference_path.is_file() else None,
        "preview_path": str(preview_path),
        "preview_sha256": sha256_file(preview_path) if preview_path.is_file() else None,
        "reason": clean_space(reason)[:500],
        "approved_patches": [],
        "visible_text_retained": False,
        "scientific_content_influence": "none",
        "provider_received_rendered_preview": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a style reference with the rendered SVG preview using a multimodal model.")
    parser.add_argument("--reference", default="outputs/poster_style_reference.png")
    parser.add_argument("--preview", default="outputs/poster_render_preview.png")
    parser.add_argument("--design-json", default="outputs/poster_design_spec.json")
    parser.add_argument("--layout-json", default="outputs/poster_layout.json")
    parser.add_argument("--overflow-json", default="outputs/poster_overflow_report.json")
    parser.add_argument("--output-json", default="outputs/poster_visual_review.json")
    parser.add_argument("--mode", choices=["off", "auto", "required"], default="auto")
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_POSTER_VISION_MODEL") or os.environ.get("OPENAI_VISION_MODEL") or "gpt-4.1-mini",
    )
    args = parser.parse_args()

    reference_path = Path(args.reference)
    preview_path = Path(args.preview)
    output_path = Path(args.output_json)
    model = clean_space(args.model)
    if args.mode == "off":
        write_json(output_path, skipped_report(args.mode, model, "Rendered-preview vision review is disabled.", reference_path, preview_path))
        return 0
    if not os.environ.get("OPENAI_API_KEY"):
        report = skipped_report(args.mode, model, "OPENAI_API_KEY is not configured.", reference_path, preview_path)
        write_json(output_path, report)
        print("Rendered-preview vision review skipped: OPENAI_API_KEY is not configured.", file=sys.stderr)
        return 0 if args.mode == "auto" else 2
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        report = skipped_report(args.mode, model, "Python package 'openai' is not installed.", reference_path, preview_path)
        write_json(output_path, report)
        print("Rendered-preview vision review skipped: Python package 'openai' is not installed.", file=sys.stderr)
        return 0 if args.mode == "auto" else 2

    try:
        if not reference_path.is_file() or not preview_path.is_file():
            raise ValueError("Reference and rendered-preview images must both exist")
        design = read_json(Path(args.design_json))
        layout = read_json(Path(args.layout_json))
        overflow = read_json(Path(args.overflow_json))
        art_direction = design.get("art_direction") if isinstance(design.get("art_direction"), dict) else {}
        if art_direction.get("tokens_applied") is not True:
            raise ValueError("The final design did not apply hash-matched reference tokens")
        expected_sha256 = clean_space(art_direction.get("reference_sha256")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or expected_sha256 != sha256_file(reference_path):
            raise ValueError("Reference hash does not match the applied design specification")
        if overflow.get("status") != "passed":
            raise ValueError("Structural overflow validation must pass before visual review")
        context = build_review_context(design, layout, overflow)
        raw = call_model(OpenAI(), model, reference_path, preview_path, context)
        report = normalize_report(
            raw,
            model=model,
            reference_path=reference_path,
            preview_path=preview_path,
            design=design,
            layout=layout,
        )
    except Exception as exc:
        report = skipped_report(args.mode, model, str(exc), reference_path, preview_path)
        report["status"] = "failed"
        report["failure_stage"] = "rendered_preview_vision_review"
        write_json(output_path, report)
        print(f"Rendered-preview vision review failed: {clean_space(exc)[:500]}", file=sys.stderr)
        return 0 if args.mode == "auto" else 2

    write_json(output_path, report)
    print(f"Wrote {output_path}")
    print(f"Rendered-preview vision review: {report['status']}; approved patches: {len(report['approved_patches'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
