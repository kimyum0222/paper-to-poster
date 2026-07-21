#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from openai_response_utils import json_object_from_text, response_output_text


DEFAULT_MODEL = os.environ.get("OPENAI_NARRATIVE_MODEL", "gpt-5.6-terra")
SECTION_IDS = (
    "problem",
    "motivation",
    "core_idea",
    "method",
    "results",
    "contribution",
    "conclusion",
    "limitations",
)
SECTION_HEADINGS = {
    "problem": "Problem",
    "motivation": "Motivation",
    "core_idea": "Core Idea",
    "method": "Method",
    "results": "Results",
    "contribution": "Contributions",
    "conclusion": "Conclusion",
    "limitations": "Limitations",
}
SECTION_PURPOSES = {
    "problem": "Establish the research problem and why it is difficult.",
    "motivation": "Explain why the problem matters and why existing approaches are insufficient.",
    "core_idea": "State the central insight and the paper's take-home idea.",
    "method": "Explain the method or system at a poster-readable level.",
    "results": "Present the strongest verified evidence and comparisons.",
    "contribution": "Summarize the paper's distinct contributions without overstating novelty.",
    "conclusion": "Close with the verified implication of the work.",
    "limitations": "State important verified limitations or scope boundaries.",
}
PAPER_TYPES = {
    "empirical_result_centered",
    "method_centered",
    "conceptual",
    "theoretical",
    "survey_or_review",
    "other",
}
STORY_ARCS = {
    "problem_method_evidence_implication",
    "problem_insight_method_evidence",
    "question_argument_evidence_conclusion",
    "context_synthesis_implications",
}
TEXT_DENSITIES = {"short", "medium", "long"}
VISUAL_ROLES = {"hero", "primary", "supporting", "compact"}


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


def positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value > 0 else None
    if isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        number = int(value.strip())
        return number if number > 0 else None
    return None


def verified_refs(item: dict[str, Any]) -> list[dict[str, Any]]:
    refs = item.get("source_refs", [])
    if not isinstance(refs, list):
        return []
    result: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict) or ref.get("verification_status") != "verified":
            continue
        quote = clean_space(ref.get("quote", ""))
        page = positive_integer(ref.get("page"))
        if not quote or page is None:
            continue
        result.append({
            "page": page,
            "quote": quote,
            "bbox": ref.get("bbox"),
            "verification_status": "verified",
        })
    return result


def claim_catalog(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    claims = content.get("poster_claims", [])
    if not isinstance(claims, list):
        return {}
    catalog: dict[str, dict[str, Any]] = {}
    for item in claims:
        if not isinstance(item, dict) or item.get("evidence_status") != "verified":
            continue
        claim_id = clean_space(item.get("id", ""))
        claim = clean_space(item.get("claim", ""))
        refs = verified_refs(item)
        if not claim_id or not claim or not refs or claim_id in catalog:
            continue
        catalog[claim_id] = {
            "id": claim_id,
            "section": clean_space(item.get("section", "")),
            "claim": claim,
            "source": clean_space(item.get("source", "")),
            "source_text": clean_space(item.get("source_text", "")),
            "source_refs": refs,
            "evidence_status": "verified",
        }
    return catalog


def safe_dimension(value: Any) -> int | None:
    return positive_integer(value)


def is_generated_or_non_evidence_figure(item: dict[str, Any], asset_path: str) -> bool:
    classification = clean_space(
        item.get("asset_class", "")
        or item.get("evidence_class", "")
        or item.get("generation_role", "")
    ).lower()
    if any(marker in classification for marker in ("generated", "non_evidence", "style_reference", "decorative")):
        return True
    normalized_path = asset_path.replace("\\", "/").lower()
    path_parts = {part for part in normalized_path.split("/") if part}
    return (
        "generated" in path_parts
        or "style_reference" in normalized_path
        or normalized_path.startswith(("http://", "https://", "data:"))
    )


def figure_catalog(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: list[Any] = []
    for key in ("figures_to_use", "figure_candidates"):
        values = content.get(key, [])
        if isinstance(values, list):
            candidates.extend(values)
    catalog: dict[str, dict[str, Any]] = {}
    selected_ids = {
        clean_space(item.get("id", ""))
        for item in content.get("figures_to_use", [])
        if isinstance(item, dict)
    }
    for item in candidates:
        if not isinstance(item, dict):
            continue
        figure_id = clean_space(item.get("id", ""))
        if not figure_id or figure_id in catalog:
            continue
        page = positive_integer(item.get("page"))
        asset_path = clean_space(item.get("asset_path", ""))
        if page is None or not asset_path or is_generated_or_non_evidence_figure(item, asset_path):
            continue
        width = safe_dimension(item.get("width_px"))
        height = safe_dimension(item.get("height_px"))
        aspect_ratio = round(width / height, 3) if width and height else None
        catalog[figure_id] = {
            "id": figure_id,
            "role": clean_space(item.get("role", "")) or "supporting_figure",
            "page": page,
            "caption": clean_space(item.get("caption", "") or item.get("text", ""))[:500],
            "asset_path": asset_path,
            "width_px": width,
            "height_px": height,
            "aspect_ratio": aspect_ratio,
            "selected_by_evidence_stage": figure_id in selected_ids,
            "importance_score": item.get("importance_score"),
            "readability_score": item.get("readability_score"),
            "asset_class": "source_evidence",
            "upstream_asset_class": clean_space(item.get("asset_class", "")) or None,
        }
    return catalog


def narrative_plan_schema() -> dict[str, Any]:
    section_enum = list(SECTION_IDS)
    return {
        "type": "object",
        "properties": {
            "paper_type": {"type": "string", "enum": sorted(PAPER_TYPES)},
            "story_arc": {"type": "string", "enum": sorted(STORY_ARCS)},
            "hero_section": {"type": "string", "enum": section_enum},
            "reading_order": {
                "type": "array",
                "items": {"type": "string", "enum": section_enum},
            },
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": section_enum},
                        "heading": {"type": "string"},
                        "purpose": {"type": "string"},
                        "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                        "text_density": {"type": "string", "enum": sorted(TEXT_DENSITIES)},
                        "bullet_budget": {"type": "integer", "minimum": 1, "maximum": 5},
                        "visual_role": {"type": "string", "enum": sorted(VISUAL_ROLES)},
                        "claim_ids": {"type": "array", "items": {"type": "string"}},
                        "figure_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "id", "heading", "purpose", "priority", "text_density",
                        "bullet_budget", "visual_role", "claim_ids", "figure_ids",
                    ],
                    "additionalProperties": False,
                },
            },
            "core_figure_ids": {"type": "array", "items": {"type": "string"}},
            "omitted_sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": section_enum},
                        "reason": {"type": "string"},
                    },
                    "required": ["id", "reason"],
                    "additionalProperties": False,
                },
            },
            "planning_notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "paper_type", "story_arc", "hero_section", "reading_order", "sections",
            "core_figure_ids", "omitted_sections", "planning_notes",
        ],
        "additionalProperties": False,
    }


def map_claim_section(source_section: str) -> str:
    source = clean_space(source_section)
    if source == "take_home_message":
        return "core_idea"
    if source == "result_callouts":
        return "results"
    return source if source in SECTION_IDS else "core_idea"


def target_section_for_figure(figure: dict[str, Any]) -> str:
    role = clean_space(figure.get("role", ""))
    if role == "method_overview":
        return "method"
    if role in {"result_evidence", "qualitative_example"}:
        return "results"
    return "core_idea"


def build_local_raw_plan(content: dict[str, Any]) -> dict[str, Any]:
    claims = claim_catalog(content)
    figures = figure_catalog(content)
    claims_by_section: dict[str, list[str]] = {section_id: [] for section_id in SECTION_IDS}
    for claim_id, claim in claims.items():
        claims_by_section[map_claim_section(claim.get("section", ""))].append(claim_id)
    figures_by_section: dict[str, list[str]] = {section_id: [] for section_id in SECTION_IDS}
    selected_figures = [figure for figure in figures.values() if figure.get("selected_by_evidence_stage")]
    for figure in selected_figures:
        figures_by_section[target_section_for_figure(figure)].append(str(figure["id"]))

    has_results = bool(claims_by_section["results"] or figures_by_section["results"])
    has_method = bool(claims_by_section["method"] or figures_by_section["method"])
    hero = "results" if has_results else "method" if has_method else "core_idea"
    paper_type = "empirical_result_centered" if has_results else "method_centered" if has_method else "conceptual"
    priorities = {
        "problem": 3,
        "motivation": 2,
        "core_idea": 4,
        "method": 4,
        "results": 5,
        "contribution": 3,
        "conclusion": 3,
        "limitations": 2,
    }
    sections: list[dict[str, Any]] = []
    for section_id in SECTION_IDS:
        claim_ids = claims_by_section[section_id]
        figure_ids = figures_by_section[section_id]
        if not claim_ids and not figure_ids:
            continue
        bullet_budget = max(1, min(5, len(claim_ids) or 1))
        density = "short" if bullet_budget <= 2 else "medium" if bullet_budget <= 4 else "long"
        sections.append({
            "id": section_id,
            "heading": SECTION_HEADINGS[section_id],
            "purpose": SECTION_PURPOSES[section_id],
            "priority": 5 if section_id == hero else priorities[section_id],
            "text_density": density,
            "bullet_budget": bullet_budget,
            "visual_role": "hero" if section_id == hero else "primary" if priorities[section_id] >= 4 else "supporting",
            "claim_ids": claim_ids[:5],
            "figure_ids": figure_ids[:2],
        })
    active_ids = [section["id"] for section in sections]
    return {
        "paper_type": paper_type,
        "story_arc": "problem_method_evidence_implication",
        "hero_section": hero,
        "reading_order": active_ids,
        "sections": sections,
        "core_figure_ids": [str(figure["id"]) for figure in selected_figures[:3]],
        "omitted_sections": [
            {"id": section_id, "reason": "No verified poster claim or selected source figure was available."}
            for section_id in SECTION_IDS
            if section_id not in active_ids
        ],
        "planning_notes": ["Deterministic evidence-preserving narrative fallback was used."],
    }


def planning_context(extracted: dict[str, Any], content: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": clean_space(content.get("title", "")),
        "extraction_method": extracted.get("extraction_method"),
        "extraction_verification": extracted.get("extraction_verification", {}),
        "verified_claims": list(claim_catalog(content).values()),
        "source_figures": list(figure_catalog(content).values()),
        "existing_section_headings": {
            section_id: clean_space((content.get(section_id) or {}).get("heading", ""))
            for section_id in SECTION_IDS
            if isinstance(content.get(section_id), dict)
        },
    }


SYSTEM_PROMPT = """
Plan the narrative structure of one academic research poster.

Return only the requested structured JSON. Do not write final poster prose and
do not invent claims, metrics, comparisons, methods, conclusions, or figure
content. Select scientific content only by the supplied verified claim IDs and
select images only by the supplied source figure IDs.

Plan 3 to 7 useful sections. Choose a clear reading order, one hero section,
relative priorities, text-density budgets, and figure assignments. A claim ID
may appear in only one section unless it is the take-home message. Use at most
5 claims and 2 figures per section. Omit weak or redundant sections. Planning
notes must be concise decisions, not hidden reasoning.
"""


def call_model(extracted: dict[str, Any], content: dict[str, Any], model: str) -> dict[str, Any]:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Python package 'openai' is not installed.") from exc
    context = planning_context(extracted, content)
    if len(context["verified_claims"]) < 3:
        raise RuntimeError("Fewer than three verified poster claims are available for narrative planning.")
    client = OpenAI()
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": "Build a content-driven poster narrative plan from this verified catalog:\n"
                    + json.dumps(context, ensure_ascii=False),
                }],
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "poster_narrative_plan",
                "strict": True,
                "schema": narrative_plan_schema(),
            }
        },
    )
    output_text = response_output_text(response)
    if not output_text:
        raise RuntimeError("The narrative model returned no structured output.")
    try:
        return json_object_from_text(output_text)
    except ValueError as exc:
        preview = clean_space(output_text)[:400]
        raise RuntimeError(f"The narrative model returned invalid JSON: {exc}. Preview: {preview!r}") from exc


def bounded_integer(value: Any, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = fallback
    return max(low, min(high, number))


def normalize_plan(
    raw_plan: dict[str, Any],
    content: dict[str, Any],
    planning_method: str,
    model: str | None,
    fallback_notes: list[str] | None = None,
) -> dict[str, Any]:
    claims = claim_catalog(content)
    figures = figure_catalog(content)
    raw_sections = raw_plan.get("sections", [])
    if not isinstance(raw_sections, list):
        raise ValueError("Narrative plan sections must be an array")
    sections: list[dict[str, Any]] = []
    used_sections: set[str] = set()
    used_claims: set[str] = set()
    for raw_section in raw_sections:
        if not isinstance(raw_section, dict):
            continue
        section_id = clean_space(raw_section.get("id", ""))
        if section_id not in SECTION_IDS or section_id in used_sections:
            continue
        claim_ids: list[str] = []
        for value in raw_section.get("claim_ids", []):
            claim_id = clean_space(value)
            if claim_id in claims and claim_id not in used_claims:
                claim_ids.append(claim_id)
                used_claims.add(claim_id)
            if len(claim_ids) >= 5:
                break
        figure_ids: list[str] = []
        for value in raw_section.get("figure_ids", []):
            figure_id = clean_space(value)
            if figure_id in figures and figure_id not in figure_ids:
                figure_ids.append(figure_id)
            if len(figure_ids) >= 2:
                break
        if not claim_ids and not figure_ids:
            continue
        density = clean_space(raw_section.get("text_density", "medium"))
        visual_role = clean_space(raw_section.get("visual_role", "supporting"))
        heading_suggestion = clean_space(raw_section.get("heading", ""))[:60]
        purpose_suggestion = clean_space(raw_section.get("purpose", ""))[:280]
        section = {
            "id": section_id,
            "heading": SECTION_HEADINGS[section_id],
            "heading_suggestion": heading_suggestion or SECTION_HEADINGS[section_id],
            "purpose": SECTION_PURPOSES[section_id],
            "purpose_suggestion": purpose_suggestion or SECTION_PURPOSES[section_id],
            "priority": bounded_integer(raw_section.get("priority"), 1, 5, 3),
            "text_density": density if density in TEXT_DENSITIES else "medium",
            "bullet_budget": bounded_integer(raw_section.get("bullet_budget"), 1, 5, max(1, len(claim_ids))),
            "visual_role": visual_role if visual_role in VISUAL_ROLES else "supporting",
            "claim_ids": claim_ids,
            "figure_ids": figure_ids,
            "resolved_claims": [claims[claim_id] for claim_id in claim_ids],
            "resolved_figures": [figures[figure_id] for figure_id in figure_ids],
        }
        sections.append(section)
        used_sections.add(section_id)
        if len(sections) >= 7:
            break
    if len(sections) < 3:
        raise ValueError(f"Narrative plan resolved to only {len(sections)} evidence-bearing sections")

    section_ids = [section["id"] for section in sections]
    reading_order: list[str] = []
    for value in raw_plan.get("reading_order", []):
        section_id = clean_space(value)
        if section_id in section_ids and section_id not in reading_order:
            reading_order.append(section_id)
    reading_order.extend(section_id for section_id in section_ids if section_id not in reading_order)

    hero = clean_space(raw_plan.get("hero_section", ""))
    if hero not in section_ids:
        hero = max(sections, key=lambda section: (section["priority"], -section_ids.index(section["id"])))["id"]
    for section in sections:
        if section["id"] == hero:
            section["priority"] = 5
            section["visual_role"] = "hero"
        elif section["visual_role"] == "hero":
            section["visual_role"] = "primary"

    core_figure_ids: list[str] = []
    for value in raw_plan.get("core_figure_ids", []):
        figure_id = clean_space(value)
        if figure_id in figures and figure_id not in core_figure_ids:
            core_figure_ids.append(figure_id)
        if len(core_figure_ids) >= 3:
            break
    if not core_figure_ids:
        for section in sections:
            for figure_id in section["figure_ids"]:
                if figure_id not in core_figure_ids:
                    core_figure_ids.append(figure_id)
                if len(core_figure_ids) >= 3:
                    break

    omitted_sections: list[dict[str, str]] = []
    for item in raw_plan.get("omitted_sections", []):
        if not isinstance(item, dict):
            continue
        section_id = clean_space(item.get("id", ""))
        reason = clean_space(item.get("reason", ""))
        if section_id in SECTION_IDS and section_id not in section_ids and reason:
            omitted_sections.append({"id": section_id, "reason": reason[:280]})
    for section_id in SECTION_IDS:
        if section_id not in section_ids and not any(item["id"] == section_id for item in omitted_sections):
            omitted_sections.append({"id": section_id, "reason": "Not selected for the concise poster narrative."})

    paper_type = clean_space(raw_plan.get("paper_type", ""))
    story_arc = clean_space(raw_plan.get("story_arc", ""))
    notes = [
        clean_space(note)[:300]
        for note in raw_plan.get("planning_notes", [])
        if clean_space(note)
    ][:8]
    notes.extend(fallback_notes or [])
    content_bytes = json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "version": 1,
        "status": "planned",
        "planning_method": planning_method,
        "model": model,
        "source_policy": "verified_poster_claim_ids_and_source_figure_ids_only",
        "source_content_sha256": hashlib.sha256(content_bytes).hexdigest(),
        "paper_type": paper_type if paper_type in PAPER_TYPES else "other",
        "story_arc": story_arc if story_arc in STORY_ARCS else "problem_method_evidence_implication",
        "hero_section": hero,
        "reading_order": reading_order,
        "sections": sections,
        "core_figure_ids": core_figure_ids,
        "core_figures": [figures[figure_id] for figure_id in core_figure_ids],
        "omitted_sections": omitted_sections,
        "planning_notes": notes,
        "claim_selection_summary": {
            "available_verified_claim_count": len(claims),
            "selected_verified_claim_count": len(used_claims),
            "unverified_claims_allowed": False,
        },
        "figure_selection_summary": {
            "available_source_figure_count": len(figures),
            "selected_core_figure_count": len(core_figure_ids),
            "generated_figures_allowed": False,
        },
    }


def local_plan(content: dict[str, Any], reason: str) -> dict[str, Any]:
    return normalize_plan(
        build_local_raw_plan(content),
        content,
        "deterministic_evidence_preserving_fallback",
        None,
        [reason],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan an evidence-grounded academic-poster narrative with an OpenAI-compatible text model.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--extracted-json", default="outputs/extracted_paper.json")
    parser.add_argument("--output-json", default="outputs/poster_narrative_plan.json")
    parser.add_argument("--mode", choices=["auto", "model", "local"], default="auto")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    content_path = Path(args.content_json)
    extracted_path = Path(args.extracted_json)
    output_path = Path(args.output_json)
    if not content_path.exists() or not extracted_path.exists():
        print("Error: poster content and extracted paper JSON are both required.", file=sys.stderr)
        return 1
    try:
        content = read_json(content_path)
        extracted = read_json(extracted_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.mode == "local":
        try:
            plan = local_plan(content, "Local narrative-planning mode was explicitly selected.")
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        write_json(output_path, plan)
        print(f"Wrote {output_path} using deterministic narrative fallback.")
        return 0

    if not os.environ.get("OPENAI_API_KEY"):
        reason = "OPENAI_API_KEY is not configured for narrative planning."
        if args.mode == "model":
            print(f"Error: {reason}", file=sys.stderr)
            return 2
        try:
            plan = local_plan(content, reason)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        write_json(output_path, plan)
        print(f"Wrote {output_path} using deterministic narrative fallback.")
        return 0

    try:
        raw_plan = call_model(extracted, content, args.model)
        plan = normalize_plan(raw_plan, content, "openai_compatible_structured_planning", args.model)
    except Exception as exc:
        if args.mode == "model":
            print(f"Error: narrative planning failed: {exc}", file=sys.stderr)
            return 2
        print(f"Warning: narrative planning failed; using deterministic fallback: {exc}", file=sys.stderr)
        try:
            plan = local_plan(content, f"Model narrative planning failed: {clean_space(exc)}")
        except ValueError as fallback_exc:
            print(f"Error: {fallback_exc}", file=sys.stderr)
            return 1

    write_json(output_path, plan)
    print(f"Wrote {output_path}")
    print(f"Narrative planning method: {plan.get('planning_method')}")
    print(f"Planned sections: {len(plan.get('sections', []))}")
    print(f"Hero section: {plan.get('hero_section')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
