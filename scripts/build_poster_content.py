#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SECTION_LIMITS = {
    "problem": 3,
    "core_idea": 3,
    "method": 4,
    "results": 5,
    "conclusion": 3,
    "contribution": 3,
    "limitations": 2,
}

FIGURE_KEYWORDS = [
    "result", "performance", "comparison", "experiment", "evaluation", "accuracy",
    "architecture", "framework", "pipeline", "overview", "method", "model",
    "ablation", "qualitative", "example",
]


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def split_sentences(text: str) -> list[str]:
    text = clean_space(text)
    if not text:
        return []
    # Simple sentence splitter. Good enough for a first MVP; it avoids requiring
    # any external NLP package.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [clean_space(part) for part in parts if len(clean_space(part)) >= 20]


def trim_words(text: str, max_words: int = 18) -> str:
    words = clean_space(text).split()
    if len(words) <= max_words:
        return clean_space(text)
    return " ".join(words[:max_words]).rstrip(",;:") + "…"


def make_bullets(text: str, max_bullets: int, max_words: int = 18) -> list[str]:
    sentences = split_sentences(text)
    bullets: list[str] = []
    seen: set[str] = set()

    for sentence in sentences:
        bullet = trim_words(sentence, max_words=max_words)
        key = re.sub(r"[^a-z0-9]", "", bullet.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        bullets.append(bullet)
        if len(bullets) >= max_bullets:
            break

    return bullets


def section_or_empty(data: dict[str, Any], key: str) -> str:
    return clean_space(data.get(key, ""))


def first_nonempty(*values: str) -> str:
    for value in values:
        value = clean_space(value)
        if value:
            return value
    return ""


def find_intro_text(data: dict[str, Any]) -> str:
    pages = data.get("pages") or []
    page_text = "\n".join(str(page.get("text", "")) for page in pages[:3])
    match = re.search(
        r"(?is)\b(?:1\.?\s*)?introduction\b\s*(.*?)(?=\n\s*(?:2\.?\s+|related work|background|method|methods|approach)\b)",
        page_text,
    )
    if match:
        return clean_space(match.group(1))
    return clean_space(page_text[:5000])


def score_figure(record: dict[str, Any]) -> int:
    text = clean_space(record.get("caption", "") or record.get("text", ""))
    lowered = text.lower()
    score = 0
    for index, keyword in enumerate(FIGURE_KEYWORDS):
        if keyword in lowered:
            score += max(1, len(FIGURE_KEYWORDS) - index)
    if record.get("asset_path"):
        score += 4
    if record.get("width_px", 0) and record.get("height_px", 0):
        width = int(record.get("width_px") or 0)
        height = int(record.get("height_px") or 0)
        if width >= 300 and height >= 180:
            score += 2
    return score


def select_figures(data: dict[str, Any], max_figures: int = 2) -> list[dict[str, Any]]:
    figures = data.get("figures") or []
    if not isinstance(figures, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, figure in enumerate(figures):
        if not isinstance(figure, dict):
            continue
        item = dict(figure)
        item.setdefault("id", f"figure_{index + 1}")
        item.setdefault("caption", item.get("text", ""))
        normalized.append(item)

    normalized.sort(key=score_figure, reverse=True)
    return normalized[:max_figures]


def build_poster_content(data: dict[str, Any]) -> dict[str, Any]:
    abstract = section_or_empty(data, "abstract")
    intro = find_intro_text(data)
    methods = section_or_empty(data, "methods")
    results = section_or_empty(data, "results")
    conclusion = section_or_empty(data, "conclusion")

    problem_source = first_nonempty(abstract, intro)
    core_idea_source = first_nonempty(abstract, methods, intro)
    method_source = first_nonempty(methods, abstract)
    results_source = first_nonempty(results, conclusion)
    conclusion_source = first_nonempty(conclusion, abstract)

    omitted_sections: list[str] = []
    for key in ["abstract", "methods", "results", "conclusion"]:
        if not section_or_empty(data, key):
            omitted_sections.append(key)

    content = {
        "title": clean_space(data.get("title", "")) or "Untitled Paper",
        "authors": data.get("authors", []) if isinstance(data.get("authors", []), list) else [],
        "affiliations": data.get("affiliations", []) if isinstance(data.get("affiliations", []), list) else [],
        "problem": {
            "heading": "Problem",
            "bullets": make_bullets(problem_source, SECTION_LIMITS["problem"]),
        },
        "motivation": {
            "heading": "Motivation",
            "bullets": make_bullets(intro, 2),
        },
        "core_idea": {
            "heading": "Core Idea",
            "bullets": make_bullets(core_idea_source, SECTION_LIMITS["core_idea"]),
        },
        "method": {
            "heading": "Method",
            "bullets": make_bullets(method_source, SECTION_LIMITS["method"]),
        },
        "theoretical_foundation": {
            "heading": "Theory",
            "bullets": [],
        },
        "results": {
            "heading": "Results",
            "bullets": make_bullets(results_source, SECTION_LIMITS["results"]),
        },
        "conclusion": {
            "heading": "Conclusion",
            "bullets": make_bullets(conclusion_source, SECTION_LIMITS["conclusion"]),
        },
        "contribution": {
            "heading": "Contributions",
            "bullets": make_bullets(first_nonempty(conclusion, abstract), SECTION_LIMITS["contribution"]),
        },
        "innovation": {
            "heading": "Novelty",
            "bullets": [],
        },
        "significance": {
            "heading": "Significance",
            "bullets": [],
        },
        "limitations": {
            "heading": "Limitations",
            "bullets": make_bullets(section_or_empty(data, "limitations"), SECTION_LIMITS["limitations"]),
        },
        "figures_to_use": select_figures(data, max_figures=2),
        "footer_metadata": {
            "source_pdf": data.get("source_pdf", ""),
            "page_count": data.get("page_count", 0),
            "backend_notes": data.get("extraction_notes", [])[:5],
        },
        "omitted_sections": omitted_sections,
    }

    # Fallbacks: keep the SVG from being empty when a paper has weak extraction.
    fallback_text = first_nonempty(abstract, intro, "\n".join(str(page.get("text", "")) for page in (data.get("pages") or [])[:2]))
    for key in ["problem", "core_idea", "method", "results", "conclusion", "contribution"]:
        if not content[key]["bullets"]:
            content[key]["bullets"] = make_bullets(fallback_text, 2)

    return content


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build poster-ready content from extracted_paper.json.")
    parser.add_argument("--input-json", default="outputs/extracted_paper.json")
    parser.add_argument("--output-json", default="outputs/poster_content.json")
    args = parser.parse_args()

    input_json = Path(args.input_json)
    output_json = Path(args.output_json)

    if not input_json.exists():
        print(f"Error: input JSON does not exist: {input_json}", file=sys.stderr)
        return 1

    data = json.loads(input_json.read_text(encoding="utf-8"))
    content = build_poster_content(data)
    write_json(output_json, content)

    print(f"Wrote {output_json}")
    print(f"Title: {content.get('title')}")
    print(f"Figures selected: {len(content.get('figures_to_use', []))}")
    print(f"Omitted source sections: {', '.join(content.get('omitted_sections', [])) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
