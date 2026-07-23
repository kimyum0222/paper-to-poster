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
from poster_vision_utils import (
    clamp_float,
    clean_space,
    image_data_uri,
    read_json,
    sha256_file,
    write_json,
)


VISUAL_LANGUAGES = {
    "minimal_academic",
    "technical_editorial",
    "modular_cards",
    "diagrammatic",
    "bold_conference",
    "soft_editorial",
}
READING_FLOWS = {"left_to_right", "top_to_bottom", "z_pattern", "hero_then_supporting"}
DENSITY_STYLES = {"airy", "balanced", "compact"}
CORNER_STYLES = {"sharp", "soft", "rounded"}
BORDER_STYLES = {"none", "hairline", "defined"}
SHADOW_STYLES = {"none", "subtle", "pronounced"}
HEADER_SHAPES = {"straight", "rounded"}
BACKGROUND_TREATMENTS = {"flat", "soft_gradient", "subtle_texture"}
VISUAL_WEIGHTS = {"hero", "primary", "supporting"}
ALIGNMENTS = {"left", "center", "mixed"}
DECORATION_KINDS = {"abstract_icon", "flow_line", "geometric_motif", "texture", "accent_shape"}


def reference_hashes(brief: dict[str, Any], style_analysis: dict[str, Any]) -> tuple[str, str]:
    generation = brief.get("generation") if isinstance(brief.get("generation"), dict) else {}
    expected = clean_space(generation.get("sha256")).lower()
    analyzed = clean_space(style_analysis.get("source_sha256")).lower()
    return expected, analyzed


def compact_reference_context(
    brief: dict[str, Any],
    style_analysis: dict[str, Any],
    narrative_plan: dict[str, Any],
) -> dict[str, Any]:
    requirements = brief.get("layout_requirements") if isinstance(brief.get("layout_requirements"), dict) else {}
    planned_sections: list[dict[str, Any]] = []
    for raw in requirements.get("sections", []):
        if not isinstance(raw, dict):
            continue
        slots = raw.get("figure_slots", []) if isinstance(raw.get("figure_slots"), list) else []
        planned_sections.append({
            "section_id": clean_space(raw.get("id")),
            "reading_order": int(clamp_float(raw.get("order"), 1, 7, len(planned_sections) + 1)),
            "visual_role": clean_space(raw.get("visual_role")),
            "priority": int(clamp_float(raw.get("priority"), 1, 5, 3)),
            "text_density": clean_space(raw.get("text_density")),
            "bullet_budget": int(clamp_float(raw.get("bullet_budget"), 1, 6, 3)),
            "relative_area_weight": clamp_float(raw.get("relative_area_weight"), 0.05, 0.8, 0.2),
            "figure_slot_aspect_ratios": [
                clamp_float(slot.get("aspect_ratio"), 0.2, 6.0, 1.0)
                for slot in slots[:3]
                if isinstance(slot, dict)
            ],
        })

    derived = style_analysis.get("derived_design_tokens") if isinstance(style_analysis.get("derived_design_tokens"), dict) else {}
    measured_sections: list[dict[str, Any]] = []
    for index, raw in enumerate(derived.get("sections", []), start=1):
        if not isinstance(raw, dict):
            continue
        measured_sections.append({
            "panel_index": index,
            "section_id": clean_space(raw.get("section_id")),
            "x": clamp_float(raw.get("x"), 0, 1189, 0),
            "y": clamp_float(raw.get("y"), 0, 841, 0),
            "width": clamp_float(raw.get("width"), 0, 1189, 0),
            "height": clamp_float(raw.get("height"), 0, 841, 0),
            "visual_role": clean_space(raw.get("visual_role")),
            "reference_panel_confidence": clamp_float(raw.get("reference_panel_confidence"), 0, 1, 0),
        })
    return {
        "contract": {
            "reference_is_style_only": True,
            "ocr_or_transcription_allowed": False,
            "scientific_content_allowed": False,
            "coordinates_are_measured_locally": True,
        },
        "paper_type": clean_space(requirements.get("paper_type") or narrative_plan.get("paper_type")),
        "story_arc": clean_space(requirements.get("story_arc") or narrative_plan.get("story_arc")),
        "canvas_aspect_ratio": clean_space(requirements.get("canvas_aspect_ratio")),
        "hero_section": clean_space(requirements.get("hero_section")),
        "reading_order": [clean_space(item) for item in requirements.get("reading_order", []) if clean_space(item)],
        "planned_sections": planned_sections,
        "local_measurements": {
            "grid": derived.get("grid", {}),
            "card_style": derived.get("card_style", {}),
            "decorations": derived.get("decorations", {}),
            "measured_sections": measured_sections,
        },
    }


def call_model(client: Any, model: str, reference_path: Path, context: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""
You are a visual-design analyst examining a text-free academic-poster style reference.

The image is non-authoritative design guidance. Do not OCR, quote, transcribe, infer, or return any visible text, title, author, number, metric, caption, scientific claim, or figure content. Do not generate SVG code or paths. Local computer-vision measurements in the context are authoritative for numeric geometry; your job is to classify visual intent and styling.

Context JSON:
{json.dumps(context, ensure_ascii=False, indent=2)}

Return only one JSON object with this shape:
{{
  "status": "passed | degraded",
  "confidence": 0.0,
  "visual_language": "minimal_academic | technical_editorial | modular_cards | diagrammatic | bold_conference | soft_editorial",
  "reading_flow": "left_to_right | top_to_bottom | z_pattern | hero_then_supporting",
  "density_style": "airy | balanced | compact",
  "background_treatment": "flat | soft_gradient | subtle_texture",
  "card_style": {{
    "corner_style": "sharp | soft | rounded",
    "border_emphasis": "none | hairline | defined",
    "shadow_emphasis": "none | subtle | pronounced"
  }},
  "header_style": {{
    "shape": "straight | rounded",
    "accent_rule": true
  }},
  "panel_observations": [
    {{
      "panel_index": 1,
      "visual_weight": "hero | primary | supporting",
      "content_alignment": "left | center | mixed",
      "confidence": 0.0
    }}
  ],
  "decorative_regions": [
    {{
      "kind": "abstract_icon | flow_line | geometric_motif | texture | accent_shape",
      "bbox": [0.0, 0.0, 0.1, 0.1],
      "safe_to_vectorize": true,
      "confidence": 0.0
    }}
  ],
  "notes": ["short design-only observation"]
}}

Use normalized [x, y, width, height] boxes for decorative regions. Mark a region safe_to_vectorize only when it is clearly decoration and contains no text, chart, table, axis, caption, number, or scientific figure. Return no extra keys containing visible textual content.
"""
    response = client.responses.create(
        model=model,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_data_uri(reference_path)},
            ],
        }],
    )
    return json_object_from_text(response_output_text(response))


def normalized_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x, y, width, height = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > 1 or y + height > 1:
        return None
    if width * height > 0.3:
        return None
    return [round(x, 4), round(y, 4), round(width, 4), round(height, 4)]


def normalize_report(
    raw: dict[str, Any],
    *,
    model: str,
    reference_path: Path,
    reference_sha256: str,
    expected_panel_count: int,
) -> dict[str, Any]:
    confidence = clamp_float(raw.get("confidence"), 0, 1, 0)
    requested_status = clean_space(raw.get("status")).lower()
    status = "passed" if requested_status == "passed" and confidence >= 0.6 else "degraded"

    def enum_value(value: Any, allowed: set[str], default: str) -> str:
        candidate = clean_space(value).lower()
        return candidate if candidate in allowed else default

    card = raw.get("card_style") if isinstance(raw.get("card_style"), dict) else {}
    header = raw.get("header_style") if isinstance(raw.get("header_style"), dict) else {}
    corner = enum_value(card.get("corner_style"), CORNER_STYLES, "soft")
    border = enum_value(card.get("border_emphasis"), BORDER_STYLES, "hairline")
    shadow = enum_value(card.get("shadow_emphasis"), SHADOW_STYLES, "subtle")
    header_shape = enum_value(header.get("shape"), HEADER_SHAPES, "straight")

    observations: list[dict[str, Any]] = []
    used_indices: set[int] = set()
    raw_observations = raw.get("panel_observations", [])
    if isinstance(raw_observations, list):
        for item in raw_observations:
            if not isinstance(item, dict):
                continue
            try:
                panel_index = int(item.get("panel_index"))
            except (TypeError, ValueError):
                continue
            if panel_index < 1 or panel_index > max(1, expected_panel_count) or panel_index in used_indices:
                continue
            item_confidence = clamp_float(item.get("confidence"), 0, 1, 0)
            if item_confidence < 0.5:
                continue
            used_indices.add(panel_index)
            observations.append({
                "panel_index": panel_index,
                "visual_weight": enum_value(item.get("visual_weight"), VISUAL_WEIGHTS, "supporting"),
                "content_alignment": enum_value(item.get("content_alignment"), ALIGNMENTS, "left"),
                "confidence": item_confidence,
            })

    decorative_regions: list[dict[str, Any]] = []
    raw_regions = raw.get("decorative_regions", [])
    if isinstance(raw_regions, list):
        for item in raw_regions:
            if not isinstance(item, dict):
                continue
            box = normalized_bbox(item.get("bbox"))
            item_confidence = clamp_float(item.get("confidence"), 0, 1, 0)
            if not box or item_confidence < 0.65 or item.get("safe_to_vectorize") is not True:
                continue
            kind = enum_value(item.get("kind"), DECORATION_KINDS, "accent_shape")
            decorative_regions.append({
                "kind": kind,
                "bbox": box,
                "safe_to_vectorize": True,
                "confidence": item_confidence,
            })
            if len(decorative_regions) >= 8:
                break

    adjustments: dict[str, Any] = {}
    if status == "passed":
        adjustments = {
            "card_style": {
                "radius": {"sharp": 3.0, "soft": 8.0, "rounded": 14.0}[corner],
                "stroke_width": {"none": 0.5, "hairline": 0.9, "defined": 1.4}[border],
                "shadow_opacity": {"none": 0.0, "subtle": 0.12, "pronounced": 0.24}[shadow],
            },
            "decorations": {
                "header_rounded": header_shape == "rounded",
                "accent_rule": header.get("accent_rule") is True,
            },
        }

    return {
        "version": 1,
        "status": status,
        "method": "multimodal_reference_semantic_analysis",
        "model": model,
        "reference_path": str(reference_path),
        "reference_sha256": reference_sha256,
        "confidence": confidence,
        "visual_language": enum_value(raw.get("visual_language"), VISUAL_LANGUAGES, "minimal_academic"),
        "reading_flow": enum_value(raw.get("reading_flow"), READING_FLOWS, "left_to_right"),
        "density_style": enum_value(raw.get("density_style"), DENSITY_STYLES, "balanced"),
        "background_treatment": enum_value(raw.get("background_treatment"), BACKGROUND_TREATMENTS, "flat"),
        "card_style_classification": {
            "corner_style": corner,
            "border_emphasis": border,
            "shadow_emphasis": shadow,
        },
        "header_style_classification": {
            "shape": header_shape,
            "accent_rule": header.get("accent_rule") is True,
        },
        "panel_observations": observations,
        "decorative_regions": decorative_regions,
        "design_adjustments": adjustments,
        "scientific_content_influence": "none",
        "visible_text_retained": False,
        "free_form_response_retained": False,
        "provider_received_style_reference": True,
        "geometry_authority": "local_pixel_analysis",
    }


def update_brief(brief: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    updated = dict(brief)
    updated["vision_analysis"] = report
    return updated


def skipped_report(mode: str, model: str, reason: str, reference_path: Path) -> dict[str, Any]:
    return {
        "version": 1,
        "status": "skipped",
        "mode": mode,
        "method": "not_run",
        "model": model,
        "reference_path": str(reference_path),
        "reference_sha256": sha256_file(reference_path) if reference_path.is_file() else None,
        "reason": clean_space(reason)[:500],
        "scientific_content_influence": "none",
        "visible_text_retained": False,
        "provider_received_style_reference": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Use a multimodal model to classify non-authoritative poster-reference design semantics.")
    parser.add_argument("--reference", default="outputs/poster_style_reference.png")
    parser.add_argument("--style-analysis-json", default="outputs/poster_style_analysis.json")
    parser.add_argument("--visual-brief-json", default="outputs/poster_visual_brief.json")
    parser.add_argument("--narrative-plan-json", default="outputs/poster_narrative_plan.json")
    parser.add_argument("--output-json", default="outputs/poster_reference_vision_analysis.json")
    parser.add_argument("--mode", choices=["off", "auto", "required"], default="auto")
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_POSTER_VISION_MODEL") or os.environ.get("OPENAI_VISION_MODEL") or "gpt-4.1-mini",
    )
    args = parser.parse_args()

    reference_path = Path(args.reference)
    output_path = Path(args.output_json)
    brief_path = Path(args.visual_brief_json)
    model = clean_space(args.model)
    try:
        brief = read_json(brief_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.mode == "off":
        report = skipped_report(args.mode, model, "Reference vision analysis is disabled.", reference_path)
        write_json(output_path, report)
        write_json(brief_path, update_brief(brief, report))
        return 0

    if not os.environ.get("OPENAI_API_KEY"):
        report = skipped_report(args.mode, model, "OPENAI_API_KEY is not configured.", reference_path)
        write_json(output_path, report)
        write_json(brief_path, update_brief(brief, report))
        print("Reference vision analysis skipped: OPENAI_API_KEY is not configured.", file=sys.stderr)
        return 0 if args.mode == "auto" else 2

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        report = skipped_report(args.mode, model, "Python package 'openai' is not installed.", reference_path)
        write_json(output_path, report)
        write_json(brief_path, update_brief(brief, report))
        print("Reference vision analysis skipped: Python package 'openai' is not installed.", file=sys.stderr)
        return 0 if args.mode == "auto" else 2

    try:
        if not reference_path.is_file():
            raise ValueError(f"Reference image does not exist: {reference_path}")
        style_analysis = read_json(Path(args.style_analysis_json))
        narrative_plan = read_json(Path(args.narrative_plan_json), required=False)
        reference_sha256 = sha256_file(reference_path)
        generation = brief.get("generation") if isinstance(brief.get("generation"), dict) else {}
        if brief.get("status") != "generated" or generation.get("status") != "generated":
            raise ValueError("Visual brief does not record a successfully generated style reference")
        expected_sha256, analyzed_sha256 = reference_hashes(brief, style_analysis)
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or expected_sha256 != reference_sha256:
            raise ValueError("Reference hash does not match the recorded generated style reference")
        if analyzed_sha256 != reference_sha256 or style_analysis.get("status") != "passed":
            raise ValueError("Reference hash/status does not match successful local pixel analysis")
        context = compact_reference_context(brief, style_analysis, narrative_plan)
        raw = call_model(OpenAI(), model, reference_path, context)
        report = normalize_report(
            raw,
            model=model,
            reference_path=reference_path,
            reference_sha256=reference_sha256,
            expected_panel_count=len(context["local_measurements"]["measured_sections"]),
        )
    except Exception as exc:
        report = skipped_report(args.mode, model, str(exc), reference_path)
        report["status"] = "failed"
        report["failure_stage"] = "reference_vision_analysis"
        write_json(output_path, report)
        write_json(brief_path, update_brief(brief, report))
        print(f"Reference vision analysis failed: {clean_space(exc)[:500]}", file=sys.stderr)
        return 0 if args.mode == "auto" else 2

    write_json(output_path, report)
    write_json(brief_path, update_brief(brief, report))
    print(f"Wrote {output_path}")
    print(f"Reference vision analysis: {report['status']}")
    return 0 if report.get("status") == "passed" or args.mode == "auto" else 2


if __name__ == "__main__":
    raise SystemExit(main())
