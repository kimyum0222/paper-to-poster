#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


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


def safe_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def section_summary(content: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ["problem", "motivation", "core_idea", "method", "results", "contribution", "conclusion", "limitations"]:
        section = content.get(key)
        if not isinstance(section, dict):
            continue
        bullets = section.get("bullets", [])
        if not isinstance(bullets, list):
            bullets = []
        summary[key] = {
            "heading": clean_space(section.get("heading", key)),
            "bullet_count": len(bullets),
            "total_chars": sum(len(str(bullet)) for bullet in bullets),
            "sample_bullets": [clean_space(bullet) for bullet in bullets[:3]],
        }
    figures = content.get("figures_to_use", [])
    callouts = content.get("result_callouts", [])
    summary["figures_to_use"] = len(figures) if isinstance(figures, list) else 0
    summary["result_callouts"] = len(callouts) if isinstance(callouts, list) else 0
    summary["take_home_message"] = clean_space(content.get("take_home_message", ""))
    return summary


def compact_boxes(raw: Any) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict):
        return {}
    boxes: dict[str, dict[str, float]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            boxes[str(key)] = {
                "x": round(float(value.get("x", 0)), 1),
                "y": round(float(value.get("y", 0)), 1),
                "width": round(float(value.get("width", 0)), 1),
                "height": round(float(value.get("height", 0)), 1),
            }
        except (TypeError, ValueError):
            continue
    return boxes


def layout_metrics(layout: dict[str, Any]) -> dict[str, Any]:
    boxes = compact_boxes(layout.get("section_bounding_boxes", {}))
    canvas_h = float(layout.get("canvas_height", 841) or 841)
    canvas_w = float(layout.get("canvas_width", 1189) or 1189)
    area_by_section = {
        key: round((box["width"] * box["height"]) / max(1.0, canvas_w * canvas_h), 4)
        for key, box in boxes.items()
    }
    columns: dict[str, float] = {}
    for key, box in boxes.items():
        if key in {"header", "footer"}:
            continue
        column_key = str(round(box["x"], 1))
        columns[column_key] = columns.get(column_key, 0.0) + box["height"]
    return {
        "area_by_section": area_by_section,
        "column_height_totals": {key: round(value, 1) for key, value in columns.items()},
        "canvas": {"width": canvas_w, "height": canvas_h},
    }


def build_review_payload(content: dict[str, Any], design: dict[str, Any], layout: dict[str, Any], overflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "rubric": {
            "visual_balance": "Are columns and cards proportioned without awkward crowding or emptiness?",
            "hierarchy": "Are title, take-home, results, figures, and supporting sections visually prioritized appropriately?",
            "readability": "Are text density, component sizes, and typography likely readable?",
            "white_space": "Is there enough breathing room without wasting too much canvas?",
            "figure_text_balance": "Is figure space balanced against text and evidence callouts?",
            "academic_poster_style": "Does the layout feel like a clear academic poster rather than a random card stack?",
        },
        "section_summary": section_summary(content),
        "design": {
            "template": design.get("template"),
            "template_rationale": design.get("template_rationale"),
            "visual_hierarchy": design.get("visual_hierarchy", {}),
            "typography": design.get("typography", {}),
            "grid": design.get("grid", {}),
            "card_variants": design.get("card_variants", {}),
            "callout_style": design.get("callout_style", {}),
            "layout_repair": design.get("layout_repair", {}),
        },
        "layout": {
            "template": layout.get("template"),
            "section_bounding_boxes": compact_boxes(layout.get("section_bounding_boxes", {})),
            "component_bounding_boxes": compact_boxes(layout.get("component_bounding_boxes", {})),
            "typography_scale": layout.get("typography_scale", {}),
            "metrics": layout_metrics(layout),
        },
        "overflow_report": {
            "status": overflow.get("status"),
            "overflow_line_count": overflow.get("overflow_line_count"),
            "overflow_count_by_section": overflow.get("overflow_count_by_section", {}),
        },
    }


def call_model(client: Any, model: str, payload: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""
You are reviewing a generated academic poster layout from structured JSON only. You do not see a screenshot.

Judge whether the layout is likely visually balanced, readable, and appropriate for an academic poster. Focus on layout rules and proportions, not scientific correctness.

Input JSON:
{json.dumps(payload, ensure_ascii=False, indent=2)}

Return only JSON with this exact shape:
{{
  "status": "passed | needs_revision | failed",
  "summary": "one concise sentence",
  "scores": {{
    "visual_balance": 0.0,
    "hierarchy": 0.0,
    "readability": 0.0,
    "white_space": 0.0,
    "figure_text_balance": 0.0,
    "academic_poster_style": 0.0
  }},
  "issues": [
    {{
      "severity": "low | medium | high",
      "section": "section id or overall",
      "issue": "specific layout/aesthetic concern",
      "suggested_rule_change": "concrete change to typography, sizing, spacing, or component layout"
    }}
  ],
  "approved_rules": ["specific layout choices that should be kept"]
}}

Rules:
- Be strict about cramped results/callout areas, weak hierarchy, tiny figure areas, and uneven columns.
- Do not ask for manual redesign; suggest rule-level changes.
- If overflow_report is not passed, status must not be passed.
- Prefer concrete changes such as increasing a section height, reducing body font, reducing callout value size, increasing figure panel height, or moving a component.
"""
    response = client.responses.create(
        model=model,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
    )
    raw = getattr(response, "output_text", "") or ""
    data = safe_json_object(raw)
    if not data:
        return {
            "status": "failed",
            "summary": "Aesthetic review returned no parseable JSON.",
            "scores": {},
            "issues": [],
            "approved_rules": [],
            "raw_response": raw[:2000],
        }
    return data


def normalize_report(raw: dict[str, Any], model: str, payload: dict[str, Any]) -> dict[str, Any]:
    status = clean_space(raw.get("status", "")).lower()
    if status not in {"passed", "needs_revision", "failed"}:
        status = "needs_revision"
    issues = raw.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    normalized_issues: list[dict[str, str]] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        severity = clean_space(item.get("severity", "medium")).lower()
        if severity not in {"low", "medium", "high"}:
            severity = "medium"
        normalized_issues.append({
            "severity": severity,
            "section": clean_space(item.get("section", "overall")) or "overall",
            "issue": clean_space(item.get("issue", "")),
            "suggested_rule_change": clean_space(item.get("suggested_rule_change", "")),
        })
    high = [item for item in normalized_issues if item["severity"] == "high"]
    medium = [item for item in normalized_issues if item["severity"] == "medium"]
    if high:
        status = "failed"
    elif medium and status == "passed":
        status = "needs_revision"
    scores = raw.get("scores", {})
    if not isinstance(scores, dict):
        scores = {}
    return {
        "status": status,
        "model": model,
        "summary": clean_space(raw.get("summary", "")),
        "scores": scores,
        "high_risk_count": len(high),
        "medium_risk_count": len(medium),
        "issues": normalized_issues,
        "approved_rules": raw.get("approved_rules", []) if isinstance(raw.get("approved_rules", []), list) else [],
        "review_payload": payload,
        "notes": [
            "This review uses structured layout JSON only, not a rendered screenshot.",
            "It evaluates likely visual balance and readability, not scientific correctness.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Review poster layout aesthetics from JSON using an OpenAI text model.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--design-json", default="outputs/poster_design_spec.json")
    parser.add_argument("--layout-json", default="outputs/poster_layout.json")
    parser.add_argument("--overflow-json", default="outputs/poster_overflow_report.json")
    parser.add_argument("--output-json", default="outputs/poster_aesthetic_report.json")
    parser.add_argument("--model", default=os.environ.get("OPENAI_AESTHETIC_MODEL", "gpt-4.1-mini"))
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is required for aesthetic review.", file=sys.stderr)
        return 2
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("Error: Python package 'openai' is required for aesthetic review.", file=sys.stderr)
        return 2

    content = read_json(Path(args.content_json))
    design = read_json(Path(args.design_json))
    layout = read_json(Path(args.layout_json))
    overflow = read_json(Path(args.overflow_json))
    payload = build_review_payload(content, design, layout, overflow)

    client = OpenAI()
    raw = call_model(client, args.model, payload)
    report = normalize_report(raw, args.model, payload)
    write_json(Path(args.output_json), report)
    print(f"Wrote {args.output_json}")
    print(f"Aesthetic review status: {report.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
