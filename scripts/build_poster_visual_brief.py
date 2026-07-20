#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


PROMPT_VERSION = "rightcode-style-reference-v1"
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


def source_asset_roles(content: dict[str, Any]) -> list[dict[str, Any]]:
    roles: list[dict[str, Any]] = []
    for figure in selected_figures(content)[:3]:
        roles.append({
            "id": clean_space(figure.get("id")) or "figure",
            "asset_class": "source_evidence",
            "role": clean_space(figure.get("role")) or "supporting_figure",
            "page": figure.get("page"),
            "intended_placement": "unchanged evidence figure in a deterministic SVG slot",
        })
    return roles


def style_prompt(title: str, paper_type: str) -> str:
    topic = visual_topic_phrase(title)
    return clean_space(f"""
        Create a 16:9 style-reference mood board for an A0 landscape academic
        research poster about {topic}. This is visual art direction only, not
        the final poster. Use a deep indigo header band, quiet blue-gray
        background, white editorial cards, teal method accents, restrained
        coral result accents, generous whitespace, precise alignment, subtle
        reasoning-to-action flow motifs, and a polished conference-poster
        aesthetic. The content profile is {paper_type}. Represent all content
        with blank blocks, neutral placeholder lines, and abstract geometric
        shapes. Do not render any legible text, letters, numbers, formulas,
        citations, tables, charts, plots, axes, metrics, logos, or scientific
        evidence. Do not imitate or redraw source figures. Keep the composition
        clean, high-contrast, flat, and feasible to reproduce with editable SVG
        geometry. No photographic mockup, frame, wall, hands, or perspective.
    """)


def build_visual_brief(
    content: dict[str, Any],
    model: str,
    style_reference_path: str = "outputs/poster_style_reference.png",
) -> dict[str, Any]:
    title = clean_space(content.get("title")) or "Untitled academic paper"
    paper_type = infer_paper_type(content)
    figures = source_asset_roles(content)
    result_callouts = content.get("result_callouts", [])
    result_count = len(result_callouts) if isinstance(result_callouts, list) else 0
    return {
        "version": 1,
        "status": "planned",
        "provider": "rightcode",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "visual_goal": "Produce a non-authoritative style reference for deterministic SVG implementation.",
        "paper_type": paper_type,
        "topic": compact_topic(title),
        "hierarchy": {
            "title": "dominant dark header band rendered later as exact SVG text",
            "take_home": "single high-contrast message zone rendered later as exact SVG text",
            "main_figure": "largest unchanged source-evidence figure slot" if figures else "no required figure slot",
            "main_result": "warm-accent result card with deterministic callouts" if result_count else "standard result card",
            "supporting_sections": "three-column editorial card system",
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
            "canvas": "16:9 landscape reference corresponding to A0 landscape",
            "grid": "three columns with a full-width header and restrained footer",
            "rhythm": "alternating compact text cards and one larger evidence-figure region",
            "result_emphasis": "use coral only for the strongest verified result area",
        },
        "source_asset_roles": figures,
        "generated_asset_requests": [{
            "id": "poster_style_reference",
            "asset_class": "style_reference_only",
            "prompt_purpose": "visualize palette, card language, spacing, and composition",
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
        "prompt": style_prompt(title, paper_type),
        "failure_or_fallback_notes": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a safe visual brief for image-model poster art direction.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--output-json", default="outputs/poster_visual_brief.json")
    parser.add_argument("--style-reference-path", default="outputs/poster_style_reference.png")
    parser.add_argument("--model", default=os.environ.get("RIGHTCODE_IMAGE_MODEL", "gpt-image-2"))
    args = parser.parse_args()

    try:
        content = read_json(Path(args.content_json))
        brief = build_visual_brief(
            content,
            clean_space(args.model) or "gpt-image-2",
            args.style_reference_path,
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
