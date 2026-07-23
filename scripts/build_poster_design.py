#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


CANONICAL_HEADINGS = {
    "problem": "Problem / Motivation",
    "motivation": "Motivation",
    "core_idea": "Core Idea",
    "method": "Method",
    "theoretical_foundation": "Theory",
    "results": "Results",
    "conclusion": "Conclusion",
    "contribution": "Contributions",
    "innovation": "Innovation",
    "significance": "Significance",
    "limitations": "Limitations",
}

SAFE_DECORATIVE_CONCEPTS = {"reasoning", "observation", "tool", "action", "verification"}
DECORATIVE_VECTOR_TARGETS = {
    "header-process-icons": "header_process",
    "body-process-strip": "body_flow",
}


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


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def safe_hex_color(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", text) else fallback


def safe_generated_asset_path(value: Any) -> str | None:
    text = str(value or "").strip().replace("\\", "/")
    parts = [part for part in text.split("/") if part]
    if len(parts) == 3 and parts[:2] == ["assets", "generated"] and parts[-1].endswith(".svg"):
        return "/".join(parts)
    return None


def rectangles_overlap(first: dict[str, Any], second: dict[str, Any], tolerance: float = 0.1) -> bool:
    return not (
        float(first["x"]) + float(first["width"]) <= float(second["x"]) + tolerance
        or float(second["x"]) + float(second["width"]) <= float(first["x"]) + tolerance
        or float(first["y"]) + float(first["height"]) <= float(second["y"]) + tolerance
        or float(second["y"]) + float(second["height"]) <= float(first["y"]) + tolerance
    )


def sanitize_decorative_flow(
    raw: Any,
    canvas_width: float,
    canvas_height: float,
    sections: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not raw.get("enabled"):
        return None
    numbers = {key: finite_number(raw.get(key)) for key in ["x", "y", "width", "height"]}
    if any(value is None for value in numbers.values()):
        return None
    x, y, width, height = (float(numbers[key]) for key in ["x", "y", "width", "height"])
    if width < 120 or height < 32 or x < 0 or y < 0 or x + width > canvas_width or y + height > canvas_height:
        return None
    box = {"x": x, "y": y, "width": width, "height": height}
    if any(rectangles_overlap(box, section, tolerance=2.0) for section in sections):
        return None
    concepts = [
        str(value).strip() for value in raw.get("concepts", [])
        if str(value).strip() in SAFE_DECORATIVE_CONCEPTS
    ]
    if not concepts:
        concepts = ["reasoning", "observation", "tool", "action", "verification"]
    return {
        "enabled": True,
        "asset_class": "generated_decorative",
        "render_mode": "vector_substitute",
        "x": round(x, 2),
        "y": round(y, 2),
        "width": round(width, 2),
        "height": round(height, 2),
        "concepts": concepts[:5],
        "scientific_meaning": "none",
    }


def source_figure_catalog(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    figures: dict[str, dict[str, Any]] = {}
    for item in content.get("figures_to_use", []):
        if not isinstance(item, dict):
            continue
        figure_id = str(item.get("id", "")).strip()
        asset_path = str(item.get("asset_path", "")).strip().replace("\\", "/")
        asset_class = str(item.get("asset_class", "source_evidence") or "source_evidence")
        if figure_id and asset_class == "source_evidence" and not asset_path.startswith("assets/generated/"):
            figures[figure_id] = item
    return figures


def verified_claim_catalog(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    claims: dict[str, dict[str, Any]] = {}
    for item in content.get("poster_claims", []):
        if not isinstance(item, dict) or item.get("evidence_status") != "verified":
            continue
        claim_id = str(item.get("id", "")).strip()
        refs = item.get("source_refs", [])
        if claim_id and isinstance(refs, list) and any(
            isinstance(ref, dict) and ref.get("verification_status") == "verified" and ref.get("page")
            for ref in refs
        ):
            claims[claim_id] = item
    return claims


def sanitize_spatial_sections(
    derived: dict[str, Any],
    content: dict[str, Any],
    canvas_width: float,
    canvas_height: float,
) -> list[dict[str, Any]] | None:
    raw_sections = derived.get("sections")
    if not isinstance(raw_sections, list) or not 3 <= len(raw_sections) <= 7:
        return None
    claims = verified_claim_catalog(content)
    figures = source_figure_catalog(content)
    sanitized: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for raw in raw_sections:
        if not isinstance(raw, dict):
            return None
        section_id = str(raw.get("section_id", "")).strip()
        if section_id not in CANONICAL_HEADINGS or section_id in used_ids:
            return None
        used_ids.add(section_id)
        numbers = {key: finite_number(raw.get(key)) for key in ["x", "y", "width", "height"]}
        if any(value is None for value in numbers.values()):
            return None
        x, y, width, height = (float(numbers[key]) for key in ["x", "y", "width", "height"])
        if width < 150 or height < 100 or x < 0 or y < 0 or x + width > canvas_width or y + height > canvas_height:
            return None
        raw_claim_ids = raw.get("claim_ids", [])
        raw_figure_ids = raw.get("figure_ids", [])
        if not isinstance(raw_claim_ids, list) or not isinstance(raw_figure_ids, list):
            return None
        claim_ids = [str(value).strip() for value in raw_claim_ids if str(value).strip()]
        figure_ids = [str(value).strip() for value in raw_figure_ids if str(value).strip()]
        if any(claim_id not in claims for claim_id in claim_ids):
            return None
        if any(figure_id not in figures for figure_id in figure_ids):
            return None

        title_style = raw.get("title_style") if isinstance(raw.get("title_style"), dict) else {}
        body_style = raw.get("body_style") if isinstance(raw.get("body_style"), dict) else {}
        title_size = finite_number(title_style.get("font_size")) or 16.5
        body_size = finite_number(body_style.get("font_size")) or 10.6
        raw_slots = raw.get("figure_slots", [])
        if not isinstance(raw_slots, list):
            return None
        slots: list[dict[str, Any]] = []
        for raw_slot in raw_slots:
            if not isinstance(raw_slot, dict):
                return None
            figure_id = str(raw_slot.get("figure_id", "")).strip()
            slot_numbers = {key: finite_number(raw_slot.get(key)) for key in ["x", "y", "width", "height"]}
            if figure_id not in figures or any(value is None for value in slot_numbers.values()):
                return None
            sx, sy, sw, sh = (float(slot_numbers[key]) for key in ["x", "y", "width", "height"])
            if sw < 40 or sh < 40 or sx < x or sy < y or sx + sw > x + width or sy + sh > y + height:
                return None
            slots.append({
                "figure_id": figure_id,
                "asset_class": "source_evidence",
                "x": round(sx, 2),
                "y": round(sy, 2),
                "width": round(sw, 2),
                "height": round(sh, 2),
                "aspect_ratio": round(float(finite_number(raw_slot.get("aspect_ratio")) or 1.0), 4),
                "preserve_aspect_ratio": "xMidYMid meet",
            })
        if set(figure_ids) != {slot["figure_id"] for slot in slots}:
            return None
        sanitized.append({
            "section_id": section_id,
            "heading": CANONICAL_HEADINGS[section_id],
            "reading_order": int(finite_number(raw.get("reading_order")) or len(sanitized) + 1),
            "column": int(finite_number(raw.get("column")) or 1),
            "column_span": max(1, min(4, int(finite_number(raw.get("column_span")) or 1))),
            "reference_panel_confidence": round(max(0.0, min(1.0, float(finite_number(raw.get("reference_panel_confidence")) or 0.0))), 3),
            "x": round(x, 2),
            "y": round(y, 2),
            "width": round(width, 2),
            "height": round(height, 2),
            "background": safe_hex_color(raw.get("background"), "#fff7ed" if raw.get("visual_role") == "hero" else "#ffffff"),
            "accent": safe_hex_color(raw.get("accent"), "#1d4ed8"),
            "visual_role": str(raw.get("visual_role", "supporting")),
            "priority": max(1, min(5, int(finite_number(raw.get("priority")) or 3))),
            "text_density": str(raw.get("text_density", "medium")),
            "bullet_budget": max(1, min(5, int(finite_number(raw.get("bullet_budget")) or 3))),
            "claim_ids": claim_ids,
            "figure_ids": figure_ids,
            "title_style": {"font_size": max(14.0, min(21.0, title_size)), "font_weight": 700},
            "body_style": {
                "font_size": max(9.0, min(12.0, body_size)),
                "line_height_ratio": max(1.2, min(1.5, float(finite_number(body_style.get("line_height_ratio")) or 1.32))),
            },
            "figure_slots": slots,
        })
    for index, first in enumerate(sanitized):
        for second in sanitized[index + 1:]:
            if rectangles_overlap(first, second):
                return None
    return sorted(sanitized, key=lambda section: section["reading_order"])


def apply_reference_vision_adjustments(
    spec: dict[str, Any],
    vision_analysis: dict[str, Any],
    expected_sha256: str,
) -> bool:
    if not isinstance(vision_analysis, dict) or vision_analysis.get("status") != "passed":
        return False
    reference_sha256 = str(vision_analysis.get("reference_sha256", "") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", reference_sha256) or reference_sha256 != expected_sha256:
        return False
    if vision_analysis.get("scientific_content_influence") != "none":
        return False
    adjustments = vision_analysis.get("design_adjustments")
    if not isinstance(adjustments, dict):
        return False

    applied = False
    raw_card = adjustments.get("card_style") if isinstance(adjustments.get("card_style"), dict) else {}
    card_style = spec.get("card_style") if isinstance(spec.get("card_style"), dict) else {}
    for key, low, high in [
        ("radius", 2.0, 16.0),
        ("stroke_width", 0.5, 2.0),
        ("shadow_opacity", 0.0, 0.3),
    ]:
        value = finite_number(raw_card.get(key))
        if value is not None and low <= value <= high:
            card_style[key] = round(value, 3)
            applied = True
    spec["card_style"] = card_style

    raw_decorations = adjustments.get("decorations") if isinstance(adjustments.get("decorations"), dict) else {}
    decorations = spec.get("decorations") if isinstance(spec.get("decorations"), dict) else {}
    for key in ["header_rounded", "accent_rule"]:
        if isinstance(raw_decorations.get(key), bool):
            decorations[key] = raw_decorations[key]
            applied = True
    if decorations:
        decorations.setdefault("scientific_meaning", "none")
        spec["decorations"] = decorations

    spec["visual_semantics"] = {
        "status": vision_analysis.get("status"),
        "method": vision_analysis.get("method"),
        "model": vision_analysis.get("model"),
        "reference_hash_verified": True,
        "visual_language": vision_analysis.get("visual_language"),
        "reading_flow": vision_analysis.get("reading_flow"),
        "density_style": vision_analysis.get("density_style"),
        "background_treatment": vision_analysis.get("background_treatment"),
        "applied_to_design": applied,
        "scientific_content_influence": "none",
    }
    return applied


def apply_visual_brief(
    spec: dict[str, Any],
    visual_brief: dict[str, Any] | None,
    content: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(visual_brief, dict) or not visual_brief:
        return spec
    status = str(visual_brief.get("status", "unknown") or "unknown")
    generation = visual_brief.get("generation") if isinstance(visual_brief.get("generation"), dict) else {}
    analysis = visual_brief.get("visual_analysis") if isinstance(visual_brief.get("visual_analysis"), dict) else {}
    vision_analysis = visual_brief.get("vision_analysis") if isinstance(visual_brief.get("vision_analysis"), dict) else {}
    analysis_status = str(analysis.get("status", "not_run") or "not_run")
    generation_status = str(generation.get("status", "not_run") or "not_run")
    generation_sha256 = str(generation.get("sha256", "")).strip().lower()
    analysis_sha256 = str(analysis.get("source_sha256", "")).strip().lower()
    hash_matches = (
        re.fullmatch(r"[0-9a-f]{64}", generation_sha256) is not None
        and generation_sha256 == analysis_sha256
    )
    derived_tokens = analysis.get("derived_design_tokens")
    tokens_applied = (
        status == "generated"
        and generation_status == "generated"
        and analysis_status == "passed"
        and hash_matches
        and isinstance(derived_tokens, dict)
    )
    spatial_sections = (
        sanitize_spatial_sections(
            derived_tokens,
            content,
            float(spec["canvas"]["width"]),
            float(spec["canvas"]["height"]),
        )
        if tokens_applied else None
    )
    spatial_tokens_applied = bool(spatial_sections)
    spec["art_direction"] = {
        "status": status,
        "generation_status": generation_status,
        "analysis_status": analysis_status,
        "analysis_method": analysis.get("method"),
        "reference_hash_verified": hash_matches,
        "provider": visual_brief.get("provider", "rightcode"),
        "model": visual_brief.get("model"),
        "prompt_version": visual_brief.get("prompt_version"),
        "style_reference_path": generation.get("output_path") if status == "generated" else None,
        "reference_sha256": generation_sha256 if hash_matches else None,
        "asset_class": "style_reference_only",
        "embedded_in_final_svg": False,
        "tokens_applied": tokens_applied,
        "spatial_tokens_applied": spatial_tokens_applied,
        "vision_analysis_status": vision_analysis.get("status", "not_run"),
        "vision_analysis_model": vision_analysis.get("model"),
        "vision_analysis_applied": False,
        "influence": (
            "palette and guarded spatial geometry derived from hash-matched reference pixels; scientific content remains deterministic"
            if spatial_tokens_applied
            else "palette derived from analyzed and hash-matched reference pixels; scientific content remains deterministic"
            if tokens_applied
            else "none; deterministic design fallback retained"
        ),
        "failure_or_fallback_notes": visual_brief.get("failure_or_fallback_notes", []),
    }
    if not tokens_applied:
        return spec

    tokens = derived_tokens
    spec["theme"] = "model_art_directed_academic"

    palette = tokens.get("color_palette")
    if isinstance(palette, dict):
        accepted = spec["color_palette"]
        for key in list(accepted) + ["accent_idea", "accent_contribution"]:
            value = palette.get(key)
            if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                accepted[key] = value.lower()

    if spatial_sections:
        for section in spatial_sections:
            section["background"] = (
                spec["color_palette"]["highlight_background"]
                if section.get("visual_role") == "hero"
                else spec["color_palette"]["panel"]
            )

    if spatial_sections:
        spec["sections"] = spatial_sections
        spec["layout_source"] = "reference_pixels_plus_verified_narrative_constraints"
        grid = derived_tokens.get("grid") if isinstance(derived_tokens.get("grid"), dict) else {}
        for key, low, high in [
            ("columns", 2, 4),
            ("margin", 20, 60),
            ("gutter", 12, 40),
            ("header_height", 80, 160),
            ("footer_height", 24, 48),
            ("panel_gap", 10, 30),
        ]:
            value = finite_number(grid.get(key))
            if value is not None and low <= value <= high:
                spec["grid"][key] = int(value) if key == "columns" else round(value, 2)
        spec["grid"]["column_bounds"] = [
            {"x": section["x"], "width": section["width"], "column": section["column"]}
            for section in spatial_sections
            if not any(
                previous["column"] == section["column"]
                for previous in spatial_sections[:spatial_sections.index(section)]
            )
        ]
        spacing = derived_tokens.get("spacing") if isinstance(derived_tokens.get("spacing"), dict) else {}
        spec["spacing"] = {
            "panel_gap": round(float(finite_number(spacing.get("panel_gap")) or spec["grid"].get("panel_gap", 18)), 2),
            "panel_padding_x": round(max(14.0, min(24.0, float(finite_number(spacing.get("panel_padding_x")) or 18))), 2),
            "panel_padding_y": round(max(12.0, min(22.0, float(finite_number(spacing.get("panel_padding_y")) or 16))), 2),
        }
        card_tokens = derived_tokens.get("card_style") if isinstance(derived_tokens.get("card_style"), dict) else {}
        for key, low, high in [("radius", 2, 16), ("stroke_width", 0.5, 2), ("shadow_opacity", 0, 0.3)]:
            value = finite_number(card_tokens.get(key))
            if value is not None and low <= value <= high:
                spec["card_style"][key] = round(value, 3)
        decorations = derived_tokens.get("decorations") if isinstance(derived_tokens.get("decorations"), dict) else {}
        body_flow = sanitize_decorative_flow(
            decorations.get("body_flow"),
            float(spec["canvas"]["width"]),
            float(spec["canvas"]["height"]),
            spatial_sections,
        )
        header_process_raw = decorations.get("header_process") if isinstance(decorations.get("header_process"), dict) else {}
        header_concepts = [
            str(value).strip() for value in header_process_raw.get("concepts", [])
            if str(value).strip() in SAFE_DECORATIVE_CONCEPTS
        ] or ["reasoning", "observation", "tool", "action", "verification"]
        spec["decorations"] = {
            "header_band": bool(decorations.get("header_band", True)),
            "header_rounded": bool(decorations.get("header_rounded", False)),
            "accent_rule": bool(decorations.get("accent_rule", False)),
            "background_motif": "none",
            "scientific_meaning": "none",
            "header_process": {
                "enabled": bool(header_process_raw.get("enabled", False)),
                "asset_class": "generated_decorative",
                "render_mode": "vector_substitute",
                "concepts": header_concepts[:5],
                "scientific_meaning": "none",
            },
            "body_flow": body_flow,
        }
        spec["decorative_assets"] = [
            {
                "id": "header-process-icons",
                "asset_class": "generated_decorative",
                "render_mode": "vector_substitute",
                "included": bool(spec["decorations"]["header_process"]["enabled"]),
                "scientific_meaning": "none",
            },
            {
                "id": "body-process-strip",
                "asset_class": "generated_decorative",
                "render_mode": "vector_substitute",
                "included": body_flow is not None,
                "scientific_meaning": "none",
            },
        ]

    spec["art_direction"]["vision_analysis_applied"] = apply_reference_vision_adjustments(
        spec,
        vision_analysis,
        generation_sha256,
    )

    return spec


def apply_decorative_vectors(
    spec: dict[str, Any],
    vectorization: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(vectorization, dict) or not vectorization:
        return spec
    status = str(vectorization.get("status", "unknown") or "unknown")
    reference_sha256 = str(vectorization.get("reference_sha256", "") or "").strip().lower()
    expected_sha256 = str((spec.get("art_direction") or {}).get("reference_sha256", "") or "").strip().lower()
    hash_matches = bool(
        re.fullmatch(r"[0-9a-f]{64}", reference_sha256)
        and reference_sha256 == expected_sha256
    )
    summary = {
        "status": status,
        "vectorizer": str(vectorization.get("vectorizer", "vtracer")),
        "reference_hash_verified": hash_matches,
        "generated_asset_count": 0,
        "fallback": vectorization.get("fallback"),
        "reason": vectorization.get("reason") or vectorization.get("failure"),
    }
    spec["decorative_vectorization"] = summary
    decorations = spec.get("decorations") if isinstance(spec.get("decorations"), dict) else {}
    manifest = spec.get("decorative_assets") if isinstance(spec.get("decorative_assets"), list) else []
    if status not in {"generated", "partial"} or not hash_matches or not decorations:
        return spec

    applied = 0
    for asset in vectorization.get("assets", []):
        if not isinstance(asset, dict) or asset.get("status") != "generated":
            continue
        asset_id = str(asset.get("id", "")).strip()
        target = DECORATIVE_VECTOR_TARGETS.get(asset_id)
        vector_path = safe_generated_asset_path(asset.get("vector_path"))
        vector_sha256 = str(asset.get("vector_sha256", "") or "").strip().lower()
        if not target or not vector_path or not re.fullmatch(r"[0-9a-f]{64}", vector_sha256):
            continue
        config = decorations.get(target) if isinstance(decorations.get(target), dict) else None
        if not config or not config.get("enabled"):
            continue
        config.update({
            "render_mode": "vtracer_inline",
            "vector_path": vector_path,
            "vector_sha256": vector_sha256,
            "reference_crop_normalized": asset.get("reference_crop_normalized"),
            "vector_element_count": max(1, min(5000, int(finite_number(asset.get("element_count")) or 1))),
            "vectorizer": "vtracer",
        })
        for item in manifest:
            if isinstance(item, dict) and item.get("id") == asset_id:
                item.update({
                    "render_mode": "vtracer_inline",
                    "vector_path": vector_path,
                    "vector_sha256": vector_sha256,
                    "vectorizer": "vtracer",
                    "included": True,
                })
        applied += 1
    summary["generated_asset_count"] = applied
    if not applied:
        summary["fallback"] = "deterministic_vector_substitute"
    return spec


def build_design_spec(
    content: dict[str, Any],
    visual_brief: dict[str, Any] | None = None,
    decorative_vectors: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

    spec = {
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
            "accent_idea": "#7c3aed",
            "accent_contribution": "#0891b2",
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
    return apply_decorative_vectors(apply_visual_brief(spec, visual_brief, content), decorative_vectors)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build structured poster design/layout spec from poster_content.json.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--visual-brief-json", default=None)
    parser.add_argument("--decorative-vectors-json", default=None)
    parser.add_argument("--output-json", default="outputs/poster_design_spec.json")
    args = parser.parse_args()

    content_json = Path(args.content_json)
    output_json = Path(args.output_json)
    if not content_json.exists():
        print(f"Error: content JSON does not exist: {content_json}", file=sys.stderr)
        return 1

    try:
        content = json.loads(content_json.read_text(encoding="utf-8"))
        visual_brief = None
        if args.visual_brief_json:
            visual_brief_path = Path(args.visual_brief_json)
            if not visual_brief_path.exists():
                print(f"Error: visual brief JSON does not exist: {visual_brief_path}", file=sys.stderr)
                return 1
            visual_brief = json.loads(visual_brief_path.read_text(encoding="utf-8"))
        decorative_vectors = None
        if args.decorative_vectors_json:
            decorative_vectors_path = Path(args.decorative_vectors_json)
            if not decorative_vectors_path.exists():
                print(f"Error: decorative vectors JSON does not exist: {decorative_vectors_path}", file=sys.stderr)
                return 1
            decorative_vectors = json.loads(decorative_vectors_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: could not read design input JSON: {exc}", file=sys.stderr)
        return 1
    spec = build_design_spec(content, visual_brief, decorative_vectors)
    write_json(output_json, spec)
    print(f"Wrote {output_json}")
    print(f"Template: {spec.get('template')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
