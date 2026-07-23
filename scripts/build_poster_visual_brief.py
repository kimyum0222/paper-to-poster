#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

from plan_poster_narrative_with_openai import PAPER_TYPES, STORY_ARCS, claim_catalog, figure_catalog


PROMPT_VERSION = "rightcode-content-aware-layout-reference-v2"
SECTION_IDS = {
    "problem",
    "motivation",
    "core_idea",
    "method",
    "results",
    "contribution",
    "conclusion",
    "limitations",
}
SECTION_LABELS = {
    "problem": "problem framing",
    "motivation": "motivation",
    "core_idea": "core idea",
    "method": "method",
    "results": "results",
    "contribution": "contributions",
    "conclusion": "conclusion",
    "limitations": "limitations",
}
TEXT_DENSITIES = {"short", "medium", "long"}
VISUAL_ROLES = {"hero", "primary", "supporting", "compact"}
SOURCE_FIGURE_ROLE_LABELS = {
    "method_overview": "method-overview image",
    "result_evidence": "result-evidence image",
    "qualitative_example": "qualitative-example image",
    "supporting_figure": "supporting source image",
}
PROHIBITED_CONTENT = [
    "final poster title, author names, affiliations, citations, or body text",
    "legible words, letters, numbers, formulas, metrics, or benchmark values",
    "scientific plots, tables, axes, legends, error bars, or result graphics",
    "invented architecture, causal relationships, evidence, or conclusions",
    "a finished raster poster intended to replace the editable SVG",
]

DEFAULT_PALETTE = {
    "background": "#eef3f8",
    "panel": "#ffffff",
    "panel_stroke": "#cbd7e6",
    "text": "#172033",
    "muted": "#5c687a",
    "accent_primary": "#3157c8",
    "accent_secondary": "#0f766e",
    "accent_result": "#d15b32",
    "accent_neutral": "#526176",
    "accent_idea": "#7656b5",
    "accent_contribution": "#1686a0",
    "header_rule": "#9eb6d3",
    "header_background": "#172a46",
    "header_text": "#ffffff",
    "header_muted": "#d7e4f2",
    "highlight_background": "#fff4eb",
    "figure_background": "#f7f9fc",
}


def clean_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read JSON from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def content_sha256(content: dict[str, Any]) -> str:
    payload = json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def bounded_integer(value: Any, low: int, high: int, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Narrative plan {field} must be an integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        number = int(value.strip())
    else:
        raise ValueError(f"Narrative plan {field} must be an integer")
    if number < low or number > high:
        raise ValueError(f"Narrative plan {field} must be between {low} and {high}")
    return number


def source_figure_ratio(figure: dict[str, Any]) -> float:
    value = figure.get("aspect_ratio")
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        try:
            ratio = float(figure.get("width_px")) / float(figure.get("height_px"))
        except (TypeError, ValueError, ZeroDivisionError):
            ratio = 1.0
    if not math.isfinite(ratio) or ratio <= 0:
        ratio = 1.0
    return round(ratio, 3)


def ratio_orientation(ratio: float) -> str:
    if ratio >= 1.45:
        return "wide"
    if ratio <= 0.72:
        return "tall"
    return "near_square"


def safe_figure_role(value: Any) -> str:
    role = clean_space(value)
    return role if role in SOURCE_FIGURE_ROLE_LABELS else "supporting_figure"


def validate_narrative_layout(content: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("status") != "planned":
        raise ValueError("Narrative plan status must be planned before building a visual brief")
    expected_hash = content_sha256(content)
    if clean_space(plan.get("source_content_sha256")).lower() != expected_hash:
        raise ValueError("Narrative plan does not match the supplied poster content")
    paper_type = clean_space(plan.get("paper_type"))
    story_arc = clean_space(plan.get("story_arc"))
    if paper_type not in PAPER_TYPES or story_arc not in STORY_ARCS:
        raise ValueError("Narrative plan contains an invalid paper type or story arc")

    claims = claim_catalog(content)
    figures = figure_catalog(content)
    raw_sections = plan.get("sections", [])
    if not isinstance(raw_sections, list) or not 3 <= len(raw_sections) <= 7:
        raise ValueError("Narrative plan must contain three to seven sections")

    sections_by_id: dict[str, dict[str, Any]] = {}
    hero_roles: list[str] = []
    used_claim_ids: set[str] = set()
    used_figure_ids: set[str] = set()
    for raw_section in raw_sections:
        if not isinstance(raw_section, dict):
            raise ValueError("Narrative plan sections must be JSON objects")
        section_id = clean_space(raw_section.get("id"))
        if section_id not in SECTION_IDS or section_id in sections_by_id:
            raise ValueError(f"Narrative plan contains an invalid or duplicate section: {section_id or '[empty]'}")
        density = clean_space(raw_section.get("text_density"))
        visual_role = clean_space(raw_section.get("visual_role"))
        if density not in TEXT_DENSITIES or visual_role not in VISUAL_ROLES:
            raise ValueError(f"Narrative plan section {section_id} has invalid density or visual role")
        priority = bounded_integer(raw_section.get("priority"), 1, 5, f"{section_id}.priority")
        bullet_budget = bounded_integer(raw_section.get("bullet_budget"), 1, 5, f"{section_id}.bullet_budget")

        raw_claim_ids = raw_section.get("claim_ids", [])
        raw_figure_ids = raw_section.get("figure_ids", [])
        if not isinstance(raw_claim_ids, list) or not isinstance(raw_figure_ids, list):
            raise ValueError(f"Narrative plan section {section_id} must contain claim and figure ID arrays")
        claim_ids = [clean_space(value) for value in raw_claim_ids]
        figure_ids = [clean_space(value) for value in raw_figure_ids]
        if len(claim_ids) != len(set(claim_ids)) or any(claim_id not in claims for claim_id in claim_ids):
            raise ValueError(f"Narrative plan section {section_id} contains unknown or duplicate claim IDs")
        if len(figure_ids) != len(set(figure_ids)) or any(figure_id not in figures for figure_id in figure_ids):
            raise ValueError(f"Narrative plan section {section_id} contains unknown or duplicate source-figure IDs")
        if used_claim_ids.intersection(claim_ids):
            raise ValueError(f"Narrative plan repeats a claim ID across sections at {section_id}")
        if used_figure_ids.intersection(figure_ids):
            raise ValueError(f"Narrative plan repeats a source-figure ID across sections at {section_id}")
        used_claim_ids.update(claim_ids)
        used_figure_ids.update(figure_ids)
        if not claim_ids and not figure_ids:
            raise ValueError(f"Narrative plan section {section_id} contains no verified content")

        figure_slots = []
        for figure_id in figure_ids:
            figure = figures[figure_id]
            ratio = source_figure_ratio(figure)
            figure_slots.append({
                "figure_id": figure_id,
                "asset_class": "source_evidence",
                "role": safe_figure_role(figure.get("role")),
                "aspect_ratio": ratio,
                "orientation": ratio_orientation(ratio),
                "source_page": figure.get("page"),
                "asset_path": figure.get("asset_path"),
            })

        density_factor = {"short": 0.82, "medium": 1.0, "long": 1.22}[density]
        raw_weight = (priority * density_factor) + (bullet_budget * 0.32) + (len(figure_slots) * 1.7)
        if visual_role == "hero":
            raw_weight *= 1.28
            hero_roles.append(section_id)
        sections_by_id[section_id] = {
            "id": section_id,
            "semantic_role": SECTION_LABELS[section_id],
            "priority": priority,
            "visual_role": visual_role,
            "text_density": density,
            "bullet_budget": bullet_budget,
            "claim_placeholder_count": len(claim_ids),
            "figure_slots": figure_slots,
            "raw_area_weight": raw_weight,
        }

    reading_order = plan.get("reading_order", [])
    if not isinstance(reading_order, list):
        raise ValueError("Narrative plan reading_order must be an array")
    ordered_ids = [clean_space(value) for value in reading_order]
    if len(ordered_ids) != len(sections_by_id) or set(ordered_ids) != set(sections_by_id):
        raise ValueError("Narrative plan reading_order must contain every planned section exactly once")
    hero_section = clean_space(plan.get("hero_section"))
    if hero_section not in sections_by_id or hero_roles != [hero_section]:
        raise ValueError("Narrative plan must contain exactly one visual hero matching hero_section")

    ordered_sections = [sections_by_id[section_id] for section_id in ordered_ids]
    total_weight = sum(section["raw_area_weight"] for section in ordered_sections)
    for index, section in enumerate(ordered_sections, start=1):
        section["order"] = index
        section["relative_area_weight"] = round(section.pop("raw_area_weight") / total_weight, 3)

    figure_slot_count = sum(len(section["figure_slots"]) for section in ordered_sections)
    return {
        "source": "validated_poster_narrative_plan",
        "validated": True,
        "source_content_sha256": expected_hash,
        "paper_type": paper_type,
        "story_arc": story_arc,
        "canvas_aspect_ratio": "16:9",
        "section_count": len(ordered_sections),
        "preferred_column_count": 3 if len(ordered_sections) >= 4 else 2,
        "reading_order": ordered_ids,
        "hero_section": hero_section,
        "figure_slot_count": figure_slot_count,
        "sections": ordered_sections,
        "layout_rules": [
            "reserve a full-width header and a restrained footer outside the body-section count",
            "give the hero section the largest clear visual region",
            "scale blank text-line groups according to text density and bullet budget",
            "preserve every source-image placeholder aspect ratio",
            "show source-image slots as blank neutral frames without recreating their contents",
        ],
    }


def selected_figures(content: dict[str, Any]) -> list[dict[str, Any]]:
    figures = content.get("figures_to_use", [])
    return [item for item in figures if isinstance(item, dict)] if isinstance(figures, list) else []


def infer_paper_type(content: dict[str, Any]) -> str:
    roles = {clean_space(item.get("role")) for item in selected_figures(content)}
    callouts = content.get("result_callouts", [])
    if "result_evidence" in roles or (isinstance(callouts, list) and callouts):
        return "empirical_result_centered"
    if "method_overview" in roles:
        return "method_centered"
    return "conceptual_or_text_centered"


def compact_topic(title: str, max_words: int = 18) -> str:
    words = clean_space(title).split()
    return " ".join(words[:max_words]) or "an academic research project"


def visual_topic_phrase(title: str) -> str:
    lowered = clean_space(title).casefold()
    if any(term in lowered for term in ["agent", "reason", "language model", "llm", "tool"]):
        return "language-model agents, reasoning, tools, and interactive decision making"
    if any(term in lowered for term in ["robot", "vision", "image", "detection", "segmentation"]):
        return "perception, embodied systems, and structured computational workflows"
    if any(term in lowered for term in ["protein", "gene", "cell", "clinical", "medical", "disease"]):
        return "biological mechanisms and experimental research"
    if any(term in lowered for term in ["climate", "energy", "carbon", "environment"]):
        return "environmental systems, energy, and measured change"
    return "the paper's research domain represented through neutral abstract systems motifs"


def source_asset_roles(content: dict[str, Any], layout: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if isinstance(layout, dict) and layout.get("validated"):
        roles: list[dict[str, Any]] = []
        seen: set[str] = set()
        for section in layout.get("sections", []):
            if not isinstance(section, dict):
                continue
            for slot in section.get("figure_slots", []):
                if not isinstance(slot, dict):
                    continue
                figure_id = clean_space(slot.get("figure_id"))
                if not figure_id or figure_id in seen:
                    continue
                seen.add(figure_id)
                roles.append({
                    "id": figure_id,
                    "asset_class": "source_evidence",
                    "role": slot.get("role", "supporting_figure"),
                    "page": slot.get("source_page"),
                    "asset_path": slot.get("asset_path"),
                    "assigned_section": section.get("id"),
                    "aspect_ratio": slot.get("aspect_ratio"),
                    "orientation": slot.get("orientation"),
                    "intended_placement": "blank aspect-ratio-matched placeholder in the reference; unchanged source image in final SVG",
                })
        return roles

    roles: list[dict[str, Any]] = []
    safe_figures = figure_catalog(content)
    for figure in selected_figures(content)[:3]:
        figure_id = clean_space(figure.get("id"))
        safe_figure = safe_figures.get(figure_id)
        if not safe_figure:
            continue
        roles.append({
            "id": figure_id,
            "asset_class": "source_evidence",
            "role": safe_figure_role(safe_figure.get("role")),
            "page": safe_figure.get("page"),
            "asset_path": safe_figure.get("asset_path"),
            "aspect_ratio": source_figure_ratio(safe_figure),
            "intended_placement": "unchanged evidence figure in a deterministic SVG slot",
        })
    return roles


def layout_prompt(layout: dict[str, Any] | None) -> str:
    if not isinstance(layout, dict) or not layout.get("validated"):
        return "Use a balanced three-column body with several generic blank editorial cards."
    descriptions: list[str] = []
    for section in layout.get("sections", []):
        if not isinstance(section, dict):
            continue
        slots = section.get("figure_slots", [])
        slot_descriptions = []
        for slot in slots if isinstance(slots, list) else []:
            if not isinstance(slot, dict):
                continue
            role = SOURCE_FIGURE_ROLE_LABELS.get(str(slot.get("role")), "supporting source image")
            slot_descriptions.append(
                f"one blank {role} frame at approximately {slot.get('aspect_ratio', 1.0)} to 1 aspect ratio"
            )
        slot_text = "; reserve " + ", ".join(slot_descriptions) if slot_descriptions else "; no image frame"
        descriptions.append(
            f"zone {section.get('order')}: {section.get('semantic_role')}, "
            f"{section.get('visual_role')} role, priority {section.get('priority')} of 5, "
            f"{section.get('text_density')} placeholder-text density with "
            f"{section.get('bullet_budget')} blank line groups, approximately "
            f"{section.get('relative_area_weight')} of body area{slot_text}"
        )
    return clean_space(
        f"Use exactly {layout.get('section_count')} body content zones in this reading order: "
        + "; ".join(descriptions)
        + f". Make the {SECTION_LABELS.get(str(layout.get('hero_section')), 'primary')} zone the single largest hero. "
        + "Section descriptions are layout instructions only; do not draw their names, priorities, ratios, or labels."
    )


def style_prompt(title: str, paper_type: str, layout: dict[str, Any] | None = None, aspect_ratio: str = "4:3") -> str:
    topic = visual_topic_phrase(title)
    structure = layout_prompt(layout)
    return clean_space(f"""
        Create a {aspect_ratio} content-aware but text-free layout reference for an A0
        landscape academic research poster about {topic}. This is visual art
        direction only, not the final poster. {structure} Use a deep indigo
        header band, quiet blue-gray
        background, white editorial cards, teal method accents, restrained
        coral result accents, generous whitespace, precise alignment, subtle
        reasoning-to-action flow motifs, and a polished conference-poster
        aesthetic. The content profile is {paper_type}. Represent every text
        region with blank blocks or neutral placeholder lines and every source
        image with an empty neutral frame at the requested aspect ratio. Do not
        render any legible text, section label, priority, ratio, letters,
        numbers, formulas,
        citations, tables, charts, plots, axes, metrics, logos, or scientific
        evidence. Do not imitate or redraw source figures. Keep the composition
        clean, high-contrast, flat, and feasible to reproduce with editable SVG
        geometry. No photographic mockup, frame, wall, hands, or perspective.
    """)


def build_visual_brief(
    content: dict[str, Any],
    model: str,
    style_reference_path: str = "outputs/poster_style_reference.png",
    narrative_plan: dict[str, Any] | None = None,
    narrative_plan_path: str | None = None,
    aspect_ratio: str = "4:3",
) -> dict[str, Any]:
    title = clean_space(content.get("title")) or "Untitled academic paper"
    layout = validate_narrative_layout(content, narrative_plan) if narrative_plan is not None else None
    if layout is not None:
        layout["canvas_aspect_ratio"] = aspect_ratio
    paper_type = clean_space(layout.get("paper_type")) if layout else infer_paper_type(content)
    figures = source_asset_roles(content, layout)
    result_callouts = content.get("result_callouts", [])
    result_count = len(result_callouts) if isinstance(result_callouts, list) else 0
    return {
        "version": 2,
        "status": "planned",
        "provider": "rightcode",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "visual_goal": "Produce a content-aware, text-free, non-authoritative layout reference for deterministic SVG implementation.",
        "paper_type": paper_type,
        "topic": compact_topic(title),
        "narrative_plan_linkage": {
            "consumed": layout is not None,
            "validation_status": "passed" if layout is not None else "not_provided",
            "source_path": narrative_plan_path,
            "source_content_sha256": layout.get("source_content_sha256") if layout else None,
        },
        "layout_requirements": layout or {
            "source": "content_heuristic_fallback",
            "validated": False,
            "canvas_aspect_ratio": aspect_ratio,
            "preferred_column_count": 3,
        },
        "hierarchy": {
            "title": "dominant dark header band rendered later as exact SVG text",
            "take_home": "single high-contrast message zone rendered later as exact SVG text",
            "main_figure": "largest unchanged source-evidence figure slot" if figures else "no required figure slot",
            "main_result": "warm-accent result card with deterministic callouts" if result_count else "standard result card",
            "supporting_sections": (
                f"{layout.get('section_count')} planned blank body zones in validated reading order"
                if layout else "three-column editorial card system"
            ),
        },
        "style_keywords": [
            "modern academic editorial",
            "precise modular grid",
            "indigo teal coral palette",
            "subtle reasoning-action flow motifs",
            "generous whitespace",
            "flat vector-feasible surfaces",
        ],
        "avoid_keywords": [
            "legible text",
            "scientific chart",
            "data visualization",
            "photorealistic poster mockup",
            "perspective scene",
            "heavy gradients",
            "decorative clutter",
        ],
        "palette_direction": {
            "name": "indigo_teal_coral_evidence",
            "contrast_requirement": "dark-on-light body text and white-on-indigo header text",
        },
        "composition_direction": {
            "canvas": f"{aspect_ratio} landscape reference corresponding closely to A0 landscape",
            "grid": (
                f"prefer {layout.get('preferred_column_count')} columns while preserving the planned reading order"
                if layout else "three columns with a full-width header and restrained footer"
            ),
            "rhythm": "planned text-density blocks and aspect-ratio-matched blank source-image slots" if layout else "alternating compact text cards and one larger evidence-figure region",
            "result_emphasis": "use coral only for the strongest verified result area",
        },
        "source_asset_roles": figures,
        "generated_asset_requests": [{
            "id": "poster_style_reference",
            "asset_class": "style_reference_only",
            "prompt_purpose": "visualize palette, card language, spacing, and the validated content-aware blank layout",
            "output_path": style_reference_path,
            "inclusion_decision": "never embed as the poster canvas or scientific evidence",
        }],
        "prohibited_content": list(PROHIBITED_CONTENT),
        "design_tokens": {
            "theme": "model_art_directed_academic",
            "color_palette": dict(DEFAULT_PALETTE),
            "card_style": {
                "radius": 10,
                "padding_x": 20,
                "padding_y": 18,
                "accent_bar_width": 6,
                "stroke_width": 1.0,
                "shadow_opacity": 0.16,
            },
        },
        "prompt": style_prompt(title, paper_type, layout, aspect_ratio),
        "failure_or_fallback_notes": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a safe visual brief for image-model poster art direction.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--narrative-plan-json", default=None)
    parser.add_argument("--output-json", default="outputs/poster_visual_brief.json")
    parser.add_argument("--style-reference-path", default="outputs/poster_style_reference.png")
    parser.add_argument("--model", default=os.environ.get("RIGHTCODE_IMAGE_MODEL", "gpt-image-2"))
    parser.add_argument("--aspect-ratio", choices=["1:1", "16:9", "9:16", "4:3"], default="4:3")
    args = parser.parse_args()

    try:
        content = read_json(Path(args.content_json))
        narrative_plan = read_json(Path(args.narrative_plan_json)) if args.narrative_plan_json else None
        brief = build_visual_brief(
            content,
            clean_space(args.model) or "gpt-image-2",
            args.style_reference_path,
            narrative_plan,
            args.narrative_plan_json,
            args.aspect_ratio,
        )
        write_json(Path(args.output_json), brief)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {args.output_json}")
    print(f"Visual brief status: {brief['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
