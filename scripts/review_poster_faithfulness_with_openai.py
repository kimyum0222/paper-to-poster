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


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def build_paper_context(extracted: dict[str, Any], max_chars: int = 5000) -> str:
    parts = [
        f"Title: {clean_space(extracted.get('title', ''))}",
        f"Abstract: {clean_space(extracted.get('abstract', ''))}",
        f"Methods: {clean_space(extracted.get('methods', ''))[:1200]}",
        f"Results: {clean_space(extracted.get('results', ''))[:1400]}",
        f"Conclusion: {clean_space(extracted.get('conclusion', ''))[:900]}",
    ]
    sections = extracted.get("sections")
    if isinstance(sections, list):
        selected = []
        for section in sections[:8]:
            if not isinstance(section, dict):
                continue
            heading = clean_space(section.get("heading", ""))
            body = clean_space(section.get("text", ""))[:600]
            if heading and body:
                selected.append(f"{heading}: {body}")
        if selected:
            parts.append("Selected sections:\n" + "\n".join(selected))
    return "\n".join(part for part in parts if part.strip())[:max_chars]


def normalize_claims(content: dict[str, Any], max_claims: int) -> list[dict[str, Any]]:
    raw_claims = content.get("poster_claims", [])
    if not isinstance(raw_claims, list):
        raw_claims = []
    claims: list[dict[str, Any]] = []
    for item in raw_claims:
        if not isinstance(item, dict):
            continue
        claim = clean_space(item.get("claim", ""))
        evidence = clean_space(item.get("evidence_text", ""))
        if not claim:
            continue
        claims.append({
            "id": clean_space(item.get("id", "")) or f"claim_{len(claims) + 1}",
            "section": clean_space(item.get("section", "")),
            "claim": claim,
            "source": clean_space(item.get("source", "")),
            "evidence_text": evidence,
        })
        if len(claims) >= max_claims:
            break
    return claims


def review_claims(client: Any, model: str, paper_context: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = f"""
You are auditing a generated academic poster for faithfulness to a source paper.

Your job is not to judge whether the paper is correct. Judge only whether each poster claim is supported by the provided evidence and paper context.

Paper context:
{paper_context}

Poster claims to audit:
{json.dumps(claims, ensure_ascii=False, indent=2)}

Return only JSON with this shape:
{{
  "overall_status": "passed | needs_revision | failed",
  "summary": "one concise sentence",
  "reviews": [
    {{
      "claim_id": "string",
      "status": "supported | partially_supported | unsupported | unclear",
      "risk": "low | medium | high",
      "support_score": 0.0,
      "issue": "concise explanation; empty string when supported",
      "suggested_revision": "more faithful replacement, or null"
    }}
  ]
}}

Rules:
- Be strict about unsupported numbers, benchmarks, methods, and causal claims.
- Do not use external knowledge.
- Do not strengthen claims beyond the evidence.
- Prefer "partially_supported" when a claim is directionally right but too broad.
- Preserve scientific caution in suggested revisions.
"""
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
    )
    raw_text = getattr(response, "output_text", "") or ""
    data = safe_json_object(raw_text)
    if not data:
        return {
            "overall_status": "failed",
            "summary": "Faithfulness review returned no parseable JSON.",
            "reviews": [],
            "raw_response": raw_text[:2000],
        }
    return data


def normalize_review_report(raw: dict[str, Any], claims: list[dict[str, Any]], model: str) -> dict[str, Any]:
    reviews = raw.get("reviews", [])
    if not isinstance(reviews, list):
        reviews = []

    normalized_reviews: list[dict[str, Any]] = []
    claim_ids = {str(claim["id"]) for claim in claims}
    for item in reviews:
        if not isinstance(item, dict):
            continue
        claim_id = clean_space(item.get("claim_id", ""))
        status = clean_space(item.get("status", "")).lower() or "unclear"
        risk = clean_space(item.get("risk", "")).lower() or "medium"
        if status not in {"supported", "partially_supported", "unsupported", "unclear"}:
            status = "unclear"
        if risk not in {"low", "medium", "high"}:
            risk = "medium"
        normalized_reviews.append({
            "claim_id": claim_id,
            "status": status,
            "risk": risk,
            "support_score": clamp_score(item.get("support_score"), default=0.0),
            "issue": clean_space(item.get("issue", "")),
            "suggested_revision": item.get("suggested_revision"),
        })

    reviewed_ids = {review["claim_id"] for review in normalized_reviews}
    for claim_id in sorted(claim_ids - reviewed_ids):
        normalized_reviews.append({
            "claim_id": claim_id,
            "status": "unclear",
            "risk": "medium",
            "support_score": 0.0,
            "issue": "The model did not return a review for this claim.",
            "suggested_revision": None,
        })

    high_risk = [review for review in normalized_reviews if review["risk"] == "high" or review["status"] == "unsupported"]
    medium_risk = [review for review in normalized_reviews if review["risk"] == "medium" or review["status"] in {"partially_supported", "unclear"}]
    if high_risk:
        status = "failed"
    elif medium_risk:
        status = "needs_revision"
    else:
        status = "passed"

    if clean_space(raw.get("overall_status", "")) in {"passed", "needs_revision", "failed"}:
        model_status = clean_space(raw.get("overall_status", ""))
        if status == "passed" or model_status == "failed":
            status = model_status

    return {
        "status": status,
        "model": model,
        "summary": clean_space(raw.get("summary", "")),
        "claim_count": len(claims),
        "review_count": len(normalized_reviews),
        "high_risk_count": len(high_risk),
        "medium_risk_count": len(medium_risk),
        "reviews": normalized_reviews,
        "claims": claims,
        "notes": [
            "This is a grounded semantic review against extracted source evidence.",
            "It does not prove scientific correctness; it checks whether poster wording is faithful to the extracted paper text.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Use an OpenAI text model to review poster claim faithfulness against extracted paper evidence.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--extracted-json", default="outputs/extracted_paper.json")
    parser.add_argument("--output-json", default="outputs/poster_faithfulness_report.json")
    parser.add_argument("--model", default=os.environ.get("OPENAI_FAITHFULNESS_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--max-claims", type=int, default=28)
    args = parser.parse_args()

    content_json = Path(args.content_json)
    extracted_json = Path(args.extracted_json)
    output_json = Path(args.output_json)

    if not content_json.exists():
        print(f"Error: content JSON does not exist: {content_json}", file=sys.stderr)
        return 1
    if not extracted_json.exists():
        print(f"Error: extracted JSON does not exist: {extracted_json}", file=sys.stderr)
        return 1
    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY is required for faithfulness review.", file=sys.stderr)
        return 2

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("Error: Python package 'openai' is required for faithfulness review.", file=sys.stderr)
        return 2

    content = read_json(content_json)
    extracted = read_json(extracted_json)
    claims = normalize_claims(content, max(1, args.max_claims))
    if not claims:
        report = {
            "status": "failed",
            "model": args.model,
            "summary": "No poster claims with evidence were available to review.",
            "claim_count": 0,
            "review_count": 0,
            "high_risk_count": 0,
            "medium_risk_count": 0,
            "reviews": [],
            "claims": [],
        }
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {output_json}")
        print("Faithfulness status: failed")
        return 1

    client = OpenAI()
    paper_context = build_paper_context(extracted)
    raw_report = review_claims(client, args.model, paper_context, claims)
    report = normalize_review_report(raw_report, claims, args.model)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {output_json}")
    print(f"Faithfulness status: {report.get('status')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
