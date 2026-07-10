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
    "结果", "比较", "误差", "分布", "拟合", "诊断", "实验", "试验", "算法",
]

METHOD_FIGURE_KEYWORDS = [
    "framework", "architecture", "pipeline", "overview", "method", "approach",
    "model", "system", "workflow", "comparison of", "prompting methods",
    "reason", "act", "react", "algorithm", "示意", "框架", "流程", "方法", "模型",
]

RESULT_FIGURE_KEYWORDS = [
    "result", "results", "performance", "accuracy", "success rate", "evaluation",
    "experiment", "benchmark", "baseline", "baselines", "scaling", "ablation",
    "hotpotqa", "fever", "alfworld", "webshop", "结果", "性能", "准确率", "对比",
    "实验", "消融",
]

CASE_FIGURE_KEYWORDS = [
    "example", "qualitative", "case", "trajectory", "human-in-the-loop",
    "failure", "behavior", "示例", "案例", "轨迹",
]


def keyword_score(text: str, keywords: list[str]) -> int:
    lowered = text.lower()
    score = 0
    for index, keyword in enumerate(keywords):
        if keyword in lowered:
            score += max(1, len(keywords) - index)
    return score


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def clean_source_text(text: str) -> str:
    lines = []
    for raw_line in str(text).splitlines():
        line = clean_space(raw_line)
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("published as "):
            continue
        if re.fullmatch(r"\d{1,3}", line):
            continue
        if re.match(r"^\d+\s*(human feedback|work during|project page|projet page)", lowered):
            continue
        if lowered.startswith(("project page", "projet page", "∗work during")):
            continue
        if re.fullmatch(r"(method|score|sr|act|react|human|expert|all|pick|clean|heat|cool|look|pick 2)", lowered):
            continue
        lines.append(line)
    return "\n".join(lines)


def split_sentences(text: str) -> list[str]:
    text = clean_space(clean_source_text(text))
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
    return clean_source_text(data.get(key, ""))


def first_nonempty(*values: str) -> str:
    for value in values:
        value = clean_space(value)
        if value:
            return value
    return ""


def looks_noisy_for_summary(text: str) -> bool:
    cleaned = clean_source_text(text)
    if not cleaned:
        return True
    lowered = cleaned.lower()
    bad_fragments = [
        "published as a conference paper",
        "project page",
        "projet page",
        "work during google internship",
        "prompt methoda",
        "hotpotqa fever",
        "table ",
        "figure ",
        "we thank the support",
        "human feedback can also be incorporated",
    ]
    if any(fragment in lowered for fragment in bad_fragments):
        return True
    tokens = cleaned.split()
    numeric_tokens = [token for token in tokens if re.search(r"\d", token)]
    if tokens and len(numeric_tokens) / len(tokens) > 0.22:
        return True
    return False


def clean_or_empty(text: str) -> str:
    return "" if looks_noisy_for_summary(text) else clean_source_text(text)


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


def section_text_by_keys(data: dict[str, Any], keys: set[str], min_chars: int = 180) -> str:
    sections = data.get("sections") or []
    candidates: list[tuple[int, str]] = []
    if not isinstance(sections, list):
        return ""
    for section in sections:
        if not isinstance(section, dict):
            continue
        normalized = str(section.get("normalized_heading", ""))
        heading = clean_space(section.get("heading", ""))
        text = clean_source_text(section.get("text", ""))
        if len(text) < min_chars:
            continue
        if normalized in keys:
            priority = 10000
        elif any(key in heading.lower() for key in keys):
            priority = 5000
        else:
            continue
        if heading.lower().startswith(("table", "figure")):
            priority -= 4000
        candidates.append((priority + len(text), text))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def score_figure(record: dict[str, Any]) -> int:
    text = clean_space(record.get("caption", "") or record.get("text", ""))
    score = int(float(record.get("quality_score", 0) or 0))
    score += keyword_score(text, FIGURE_KEYWORDS)
    if record.get("asset_path"):
        score += 4
    if record.get("width_px", 0) and record.get("height_px", 0):
        width = int(record.get("width_px") or 0)
        height = int(record.get("height_px") or 0)
        if width >= 300 and height >= 180:
            score += 2
    return score


def figure_number(record: dict[str, Any]) -> int | None:
    text = clean_space(record.get("caption", "") or record.get("text", ""))
    match = re.search(r"\b(?:fig(?:ure)?\.?|图)\s*([0-9]+)", text, re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def readability_score(record: dict[str, Any]) -> float:
    width = int(record.get("width_px", 0) or 0)
    height = int(record.get("height_px", 0) or 0)
    area = float(record.get("area_ratio", 0.0) or 0.0)
    score = 0.2
    if width >= 900 and height >= 300:
        score += 0.35
    elif width >= 500 and height >= 220:
        score += 0.25
    elif width >= 300 and height >= 180:
        score += 0.15
    if 0.06 <= area <= 0.45:
        score += 0.25
    elif 0.02 <= area <= 0.6:
        score += 0.15
    if record.get("caption"):
        score += 0.15
    if not record.get("asset_path"):
        score -= 0.25
    return round(max(0.0, min(score, 1.0)), 2)


def apply_visual_review(record: dict[str, Any], reviews: dict[str, dict[str, Any]]) -> None:
    review = reviews.get(str(record.get("id", ""))) or reviews.get(str(record.get("caption_id", "")))
    if not review:
        return
    role = clean_space(review.get("role", ""))
    if role:
        record["role"] = role
    for key in ["importance_score", "readability_score"]:
        if key in review:
            try:
                record[key] = round(float(review[key]), 2)
            except (TypeError, ValueError):
                pass
    reason = clean_space(review.get("selection_reason", "") or review.get("reason", ""))
    if reason:
        record["selection_reason"] = reason
    record["selection_source"] = "vision_review"


def visual_reviews_by_id(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_reviews = data.get("figure_reviews") or data.get("vision_figure_reviews") or []
    if not isinstance(raw_reviews, list):
        return {}
    reviews: dict[str, dict[str, Any]] = {}
    for review in raw_reviews:
        if not isinstance(review, dict):
            continue
        for key in ["id", "figure_id", "caption_id"]:
            value = clean_space(review.get(key, ""))
            if value:
                reviews[value] = review
    return reviews


def annotate_figure(record: dict[str, Any], reviews: dict[str, dict[str, Any]]) -> dict[str, Any]:
    item = dict(record)
    caption = clean_space(item.get("caption", "") or item.get("text", ""))
    base = score_figure(item)
    role_scores = {
        "method_overview": base + keyword_score(caption, METHOD_FIGURE_KEYWORDS),
        "result_evidence": base + keyword_score(caption, RESULT_FIGURE_KEYWORDS),
        "qualitative_example": base + keyword_score(caption, CASE_FIGURE_KEYWORDS),
    }

    # Early figures often introduce the method; later figures are more likely to
    # carry experimental evidence. Keep this weak so captions still dominate.
    number = figure_number(item)
    if number is not None:
        if number <= 1:
            role_scores["method_overview"] += 6
        if number >= 3:
            role_scores["result_evidence"] += 5

    role = max(role_scores, key=role_scores.get)
    item["role_scores"] = role_scores
    item["role"] = role
    item["importance_score"] = round(max(0.0, min(max(role_scores.values()) / 150, 1.0)), 2)
    item["readability_score"] = readability_score(item)
    item["selection_source"] = "caption_layout_heuristic"
    item["selection_reason"] = item.get("selection_reason") or f"Selected as {role.replace('_', ' ')} from caption, size, and page context."
    apply_visual_review(item, reviews)
    return item


def best_by_role(candidates: list[dict[str, Any]], role: str, excluded_ids: set[str]) -> dict[str, Any] | None:
    pool = [candidate for candidate in candidates if str(candidate.get("id", "")) not in excluded_ids]
    if not pool:
        return None
    return max(
        pool,
        key=lambda item: (
            float(item.get("role_scores", {}).get(role, 0) or 0),
            float(item.get("importance_score", 0) or 0),
            float(item.get("readability_score", 0) or 0),
        ),
    )


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

    reviews = visual_reviews_by_id(data)
    candidates = [annotate_figure(item, reviews) for item in normalized]
    if not candidates:
        return []

    selected: list[dict[str, Any]] = []
    excluded: set[str] = set()
    for role in ["method_overview", "result_evidence", "qualitative_example"]:
        if len(selected) >= max_figures:
            break
        candidate = best_by_role(candidates, role, excluded)
        if not candidate:
            continue
        candidate = dict(candidate)
        candidate["poster_slot"] = "primary" if not selected else "secondary"
        selected.append(candidate)
        excluded.add(str(candidate.get("id", "")))

    if len(selected) < max_figures:
        for candidate in sorted(candidates, key=score_figure, reverse=True):
            if str(candidate.get("id", "")) in excluded:
                continue
            candidate = dict(candidate)
            candidate["poster_slot"] = "primary" if not selected else "secondary"
            selected.append(candidate)
            excluded.add(str(candidate.get("id", "")))
            if len(selected) >= max_figures:
                break

    return selected[:max_figures]


def figure_candidates(data: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    figures = data.get("figures") or []
    if not isinstance(figures, list):
        return []
    reviews = visual_reviews_by_id(data)
    candidates = []
    for index, figure in enumerate(figures):
        if not isinstance(figure, dict):
            continue
        item = dict(figure)
        item.setdefault("id", f"figure_{index + 1}")
        item.setdefault("caption", item.get("text", ""))
        candidates.append(annotate_figure(item, reviews))
    candidates.sort(
        key=lambda item: (
            float(item.get("importance_score", 0) or 0),
            float(item.get("readability_score", 0) or 0),
            score_figure(item),
        ),
        reverse=True,
    )
    return candidates[:limit]


def build_poster_content(data: dict[str, Any]) -> dict[str, Any]:
    abstract = section_or_empty(data, "abstract")
    intro = clean_or_empty(find_intro_text(data))
    methods = first_nonempty(
        clean_or_empty(section_text_by_keys(data, {"methods"}, min_chars=180)),
        clean_or_empty(section_or_empty(data, "methods")),
    )
    results = first_nonempty(
        clean_or_empty(section_text_by_keys(data, {"results"}, min_chars=180)),
        clean_or_empty(section_or_empty(data, "results")),
    )
    conclusion = first_nonempty(
        clean_or_empty(section_text_by_keys(data, {"conclusion"}, min_chars=120)),
        clean_or_empty(section_or_empty(data, "conclusion")),
    )

    problem_source = first_nonempty(abstract, intro)
    core_idea_source = first_nonempty(abstract, methods, intro)
    method_source = first_nonempty(methods, abstract)
    results_source = first_nonempty(results, abstract, conclusion)
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
        "figure_candidates": figure_candidates(data, limit=8),
        "figure_selection_policy": {
            "strategy": "caption_layout_heuristic_with_optional_vision_review",
            "roles": ["method_overview", "result_evidence", "qualitative_example"],
            "vision_review_field": "figure_reviews",
            "note": "If extracted_paper.json includes figure_reviews, those visual model judgments override heuristic role and scores.",
        },
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
