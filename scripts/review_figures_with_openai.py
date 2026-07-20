#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
from pathlib import Path
from typing import Any

from openai_response_utils import response_output_text


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def image_data_uri(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


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


def clamp_score(value: Any, default: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return round(max(0.0, min(score, 1.0)), 2)


def review_one_figure(client: Any, model: str, paper_context: str, figure: dict[str, Any], image_url: str) -> dict[str, Any]:
    caption = clean_space(figure.get("caption", "") or figure.get("text", ""))
    prompt = f"""
You are selecting figures for a concise academic poster.

Paper context:
{paper_context}

Figure metadata:
- id: {figure.get("id", "")}
- page: {figure.get("page", "")}
- caption: {caption}

Judge this figure visually and semantically. Return only JSON:
{{
  "figure_id": "{figure.get("id", "")}",
  "role": "method_overview | result_evidence | qualitative_example | table_evidence | background | unusable",
  "importance_score": 0.0,
  "readability_score": 0.0,
  "selection_reason": "one concise sentence grounded in the figure and caption"
}}

Do not invent claims, metrics, or results not visible in the figure/caption/context.
"""
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
    )
    raw_text = response_output_text(response)
    data = safe_json_object(raw_text)
    if not data:
        data = {
            "figure_id": figure.get("id", ""),
            "role": "unusable",
            "importance_score": 0.0,
            "readability_score": 0.0,
            "selection_reason": "Vision review returned no parseable JSON.",
        }
    data["figure_id"] = clean_space(data.get("figure_id", "")) or figure.get("id", "")
    data["role"] = clean_space(data.get("role", "")) or "unusable"
    data["importance_score"] = clamp_score(data.get("importance_score"))
    data["readability_score"] = clamp_score(data.get("readability_score"))
    data["selection_reason"] = clean_space(data.get("selection_reason", ""))
    return data


def build_paper_context(data: dict[str, Any], max_chars: int = 3500) -> str:
    parts = [
        f"Title: {clean_space(data.get('title', ''))}",
        f"Abstract: {clean_space(data.get('abstract', ''))}",
        f"Methods: {clean_space(data.get('methods', ''))[:900]}",
        f"Results: {clean_space(data.get('results', ''))[:900]}",
        f"Conclusion: {clean_space(data.get('conclusion', ''))[:700]}",
    ]
    return "\n".join(part for part in parts if part.strip())[:max_chars]


def main() -> int:
    parser = argparse.ArgumentParser(description="Use an OpenAI vision model to review extracted figure candidates.")
    parser.add_argument("--input-json", default="outputs/extracted_paper.json")
    parser.add_argument("--output-json", default="outputs/extracted_paper.json")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--model", default=os.environ.get("OPENAI_VISION_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--max-figures", type=int, default=8)
    args = parser.parse_args()

    input_json = Path(args.input_json)
    output_json = Path(args.output_json)
    outputs_dir = Path(args.outputs_dir)
    if not input_json.exists():
        print(f"Error: input JSON does not exist: {input_json}", file=sys.stderr)
        return 1

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is required for vision review.", file=sys.stderr)
        return 2

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("Error: Python package 'openai' is required for vision review.", file=sys.stderr)
        return 2

    data = json.loads(input_json.read_text(encoding="utf-8"))
    figures = data.get("figures") or []
    if not isinstance(figures, list):
        figures = []

    client = OpenAI()
    paper_context = build_paper_context(data)
    reviews: list[dict[str, Any]] = []
    for figure in figures[: max(0, args.max_figures)]:
        if not isinstance(figure, dict):
            continue
        asset = clean_space(figure.get("asset_path", ""))
        image_url = image_data_uri(outputs_dir / asset) if asset else None
        if not image_url:
            continue
        try:
            reviews.append(review_one_figure(client, args.model, paper_context, figure, image_url))
        except Exception as exc:
            reviews.append(
                {
                    "figure_id": figure.get("id", ""),
                    "role": "unusable",
                    "importance_score": 0.0,
                    "readability_score": 0.0,
                    "selection_reason": f"Vision review failed: {exc}",
                }
            )

    data["figure_reviews"] = reviews
    data.setdefault("extraction_notes", []).append(f"Vision figure review: {len(reviews)} figures reviewed with {args.model}.")
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output_json}")
    print(f"Vision-reviewed figures: {len(reviews)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
