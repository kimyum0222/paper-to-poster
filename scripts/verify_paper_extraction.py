#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any


CRITICAL_FIELDS = ("title", "abstract", "methods", "results", "conclusion")
MODEL_EXTRACTION_METHODS = {
    "openai_pdf_input_hybrid",
    "openai_compatible_page_text_hybrid",
}


def clean_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("‐", "-").replace("‑", "-").replace("–", "-").replace("—", "-")
    return clean_space(text).casefold()


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_bboxes(boxes: list[Any]) -> list[float] | None:
    valid: list[list[float]] = []
    for box in boxes:
        if not isinstance(box, list) or len(box) != 4:
            continue
        try:
            valid.append([float(value) for value in box])
        except (TypeError, ValueError):
            continue
    if not valid:
        return None
    return [
        round(min(box[0] for box in valid), 2),
        round(min(box[1] for box in valid), 2),
        round(max(box[2] for box in valid), 2),
        round(max(box[3] for box in valid), 2),
    ]


def page_map(raw: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for page in raw.get("pages", []):
        if not isinstance(page, dict):
            continue
        try:
            number = int(page.get("page_number", 0) or 0)
        except (TypeError, ValueError):
            continue
        if number > 0:
            result[number] = page
    return result


def find_quote_bbox(page: dict[str, Any], quote: str) -> list[float] | None:
    quote_norm = normalized(quote)
    if len(quote_norm) < 4:
        return None
    lines = [line for line in page.get("lines", []) if isinstance(line, dict)]
    for window_size in range(1, min(8, len(lines)) + 1):
        for start in range(0, len(lines) - window_size + 1):
            window = lines[start : start + window_size]
            window_text = normalized(" ".join(clean_space(line.get("text", "")) for line in window))
            if quote_norm in window_text:
                return merge_bboxes([line.get("bbox") for line in window])
    return None


def verify_source_ref(raw_pages: dict[int, dict[str, Any]], ref: Any) -> dict[str, Any]:
    if not isinstance(ref, dict):
        return {
            "page": 0,
            "quote": "",
            "verification_status": "invalid_reference",
            "reason": "source reference is not an object",
        }
    try:
        page_number = int(ref.get("page", 0) or 0)
    except (TypeError, ValueError):
        page_number = 0
    quote = clean_space(ref.get("quote", ""))
    verified = dict(ref)
    verified["page"] = page_number
    verified["quote"] = quote
    if page_number not in raw_pages:
        verified["verification_status"] = "page_not_found"
        verified["reason"] = "cited page is not present in raw extraction"
        return verified
    if len(normalized(quote)) < 4:
        verified["verification_status"] = "quote_missing"
        verified["reason"] = "source quote is empty or too short"
        return verified

    page = raw_pages[page_number]
    page_text = normalized(page.get("text", ""))
    quote_norm = normalized(quote)
    if quote_norm not in page_text:
        line_text = normalized(" ".join(clean_space(line.get("text", "")) for line in page.get("lines", [])))
        if quote_norm not in line_text:
            verified["verification_status"] = "quote_not_found"
            verified["reason"] = "quoted evidence was not found on the cited page"
            return verified

    verified["verification_status"] = "verified"
    bbox = find_quote_bbox(page, quote)
    if bbox:
        verified["bbox"] = bbox
    return verified


def verify_evidence(
    name: str,
    evidence: dict[str, Any],
    raw_pages: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = copy.deepcopy(evidence)
    refs = updated.get("source_refs", [])
    if not isinstance(refs, list):
        refs = []
    verified_refs = [verify_source_ref(raw_pages, ref) for ref in refs]
    verified_count = sum(ref.get("verification_status") == "verified" for ref in verified_refs)
    text = clean_space(updated.get("text", ""))
    if verified_count:
        status = "verified"
    elif not text:
        status = "empty"
    elif not refs:
        status = "missing_evidence"
    else:
        status = "unverified"
    updated["source_refs"] = verified_refs
    updated["verification_status"] = status
    if status not in {"verified", "empty"}:
        try:
            updated["confidence"] = round(min(float(updated.get("confidence", 0.0) or 0.0), 0.25), 2)
        except (TypeError, ValueError):
            updated["confidence"] = 0.0
    report = {
        "field": name,
        "status": status,
        "source_ref_count": len(refs),
        "verified_ref_count": verified_count,
    }
    return updated, report


def fallback_critical_fields(
    raw: dict[str, Any],
    extracted: dict[str, Any],
    reports: list[dict[str, Any]],
) -> list[str]:
    by_name = {str(item.get("field")): item for item in reports}
    fallback_fields: list[str] = []
    for field in CRITICAL_FIELDS:
        status = str(by_name.get(field, {}).get("status", "missing_evidence"))
        if status == "verified":
            continue
        raw_value = raw.get(field)
        if clean_space(raw_value):
            extracted[field] = raw_value
            fallback_fields.append(field)
            if field == "title":
                extracted["title_confidence"] = raw.get("title_confidence", 0.0)
                extracted["title_candidates"] = raw.get("title_candidates", [])
        else:
            extracted[field] = ""

    for field in ("authors", "affiliations"):
        evidence_list = extracted.get("field_evidence", {}).get(field, [])
        model_values = extracted.get(field, [])
        verified_values: list[str] = []
        if isinstance(evidence_list, list) and isinstance(model_values, list):
            for index, item in enumerate(evidence_list):
                if (
                    isinstance(item, dict)
                    and item.get("verification_status") == "verified"
                    and index < len(model_values)
                    and clean_space(model_values[index])
                ):
                    verified_values.append(clean_space(model_values[index]))
        if verified_values:
            extracted[field] = verified_values
        elif isinstance(raw.get(field), list):
            extracted[field] = raw.get(field, [])
            if model_values:
                fallback_fields.append(field)
    return fallback_fields


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify model source references against deterministic PDF text and coordinates."
    )
    parser.add_argument("--raw-json", default="outputs/raw_pdf_extraction.json")
    parser.add_argument("--extracted-json", default="outputs/extracted_paper.json")
    parser.add_argument("--output-json", default=None, help="Verified extraction path; defaults to --extracted-json.")
    parser.add_argument("--report-json", default="outputs/extraction_verification.json")
    args = parser.parse_args()

    raw_path = Path(args.raw_json)
    extracted_path = Path(args.extracted_json)
    output_path = Path(args.output_json) if args.output_json else extracted_path
    report_path = Path(args.report_json)
    try:
        raw = read_json(raw_path)
        extracted = read_json(extracted_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if extracted.get("extraction_method") not in MODEL_EXTRACTION_METHODS:
        report = {
            "status": "skipped_local_fallback",
            "extraction_method": extracted.get("extraction_method", "unknown"),
            "model": extracted.get("extraction_model"),
            "field_count": 0,
            "verified_count": 0,
            "unverified_count": 0,
            "fallback_fields": [],
            "fields": [],
        }
        extracted["extraction_verification"] = report
        write_json(output_path, extracted)
        write_json(report_path, report)
        print(f"Wrote {report_path}; verification skipped for local fallback.")
        return 0

    raw_pages = page_map(raw)
    reports: list[dict[str, Any]] = []
    field_evidence = extracted.get("field_evidence", {})
    if not isinstance(field_evidence, dict):
        field_evidence = {}

    for name, value in list(field_evidence.items()):
        if isinstance(value, dict):
            field_evidence[name], report = verify_evidence(name, value, raw_pages)
            reports.append(report)
        elif isinstance(value, list):
            updated_items: list[dict[str, Any]] = []
            for index, item in enumerate(value):
                if not isinstance(item, dict):
                    continue
                updated, report = verify_evidence(f"{name}[{index}]", item, raw_pages)
                updated_items.append(updated)
                reports.append(report)
            field_evidence[name] = updated_items
    extracted["field_evidence"] = field_evidence

    semantic = extracted.get("semantic_extraction", {})
    if isinstance(semantic, dict):
        for name, value in list(semantic.items()):
            if isinstance(value, dict):
                semantic[name], report = verify_evidence(f"semantic.{name}", value, raw_pages)
                reports.append(report)
            elif isinstance(value, list):
                updated_items = []
                for index, item in enumerate(value):
                    if not isinstance(item, dict):
                        continue
                    updated, report = verify_evidence(f"semantic.{name}[{index}]", item, raw_pages)
                    updated_items.append(updated)
                    reports.append(report)
                semantic[name] = updated_items
        extracted["semantic_extraction"] = semantic

    sections = extracted.get("sections", [])
    if isinstance(sections, list):
        for index, section in enumerate(sections):
            if not isinstance(section, dict) or section.get("source") not in {
                "openai_pdf_semantic_extraction",
                "model_page_text_semantic_extraction",
            }:
                continue
            evidence = {
                "text": section.get("text", ""),
                "confidence": section.get("confidence", 0.0),
                "source_refs": section.get("source_refs", []),
            }
            updated, report = verify_evidence(f"sections[{index}]", evidence, raw_pages)
            section["source_refs"] = updated["source_refs"]
            section["verification_status"] = updated["verification_status"]
            section["confidence"] = updated["confidence"]
            reports.append(report)

    fallback_fields = fallback_critical_fields(raw, extracted, reports)
    verified_count = sum(item["status"] == "verified" for item in reports)
    unverified_count = sum(item["status"] not in {"verified", "empty"} for item in reports)
    if fallback_fields or unverified_count:
        status = "partial" if verified_count else "fallback"
    else:
        status = "passed"
    report = {
        "status": status,
        "extraction_method": extracted.get("extraction_method"),
        "model": extracted.get("extraction_model"),
        "field_count": len(reports),
        "verified_count": verified_count,
        "unverified_count": unverified_count,
        "fallback_fields": fallback_fields,
        "fields": reports,
    }
    extracted["extraction_verification"] = report
    if fallback_fields:
        extracted.setdefault("extraction_notes", []).append(
            "Replaced unverified model fields with deterministic local extraction: "
            + ", ".join(fallback_fields)
        )
    write_json(output_path, extracted)
    write_json(report_path, report)
    print(f"Wrote {output_path}")
    print(f"Wrote {report_path}")
    print(f"Verification status: {status}; verified={verified_count}; unverified={unverified_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
