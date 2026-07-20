#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openai_response_utils import json_object_from_text, response_output_text


DEFAULT_MODEL = os.environ.get("OPENAI_EXTRACTION_MODEL", "gpt-5.6-terra")
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_MODEL_TEXT_CHARS = 240_000


def clean_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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


def source_ref_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "page": {"type": "integer", "minimum": 1},
            "quote": {"type": "string"},
        },
        "required": ["page", "quote"],
        "additionalProperties": False,
    }


def evidence_field_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source_refs": {"type": "array", "items": source_ref_schema()},
        },
        "required": ["text", "confidence", "source_refs"],
        "additionalProperties": False,
    }


def extraction_schema() -> dict[str, Any]:
    evidence = evidence_field_schema()
    section = {
        "type": "object",
        "properties": {
            "heading": {"type": "string"},
            "normalized_heading": {"type": "string"},
            "page_start": {"type": "integer", "minimum": 1},
            "page_end": {"type": "integer", "minimum": 1},
            "text": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "source_refs": {"type": "array", "items": source_ref_schema()},
        },
        "required": [
            "heading",
            "normalized_heading",
            "page_start",
            "page_end",
            "text",
            "confidence",
            "source_refs",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "title": evidence,
            "authors": {"type": "array", "items": evidence},
            "affiliations": {"type": "array", "items": evidence},
            "abstract": evidence,
            "sections": {"type": "array", "items": section},
            "methods": evidence,
            "results": evidence,
            "conclusion": evidence,
            "research_question": evidence,
            "key_contributions": {"type": "array", "items": evidence},
            "key_results": {"type": "array", "items": evidence},
            "limitations": {"type": "array", "items": evidence},
            "paper_language": {"type": "string"},
            "paper_type": {"type": "string"},
            "extraction_notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "title",
            "authors",
            "affiliations",
            "abstract",
            "sections",
            "methods",
            "results",
            "conclusion",
            "research_question",
            "key_contributions",
            "key_results",
            "limitations",
            "paper_language",
            "paper_type",
            "extraction_notes",
        ],
        "additionalProperties": False,
    }


def compact_raw_context(raw: dict[str, Any]) -> dict[str, Any]:
    captions: list[dict[str, Any]] = []
    for item in raw.get("captions", [])[:30]:
        if not isinstance(item, dict):
            continue
        captions.append(
            {
                "id": item.get("id"),
                "type": item.get("type"),
                "page": item.get("page"),
                "text": clean_space(item.get("text", ""))[:500],
            }
        )
    return {
        "page_count": raw.get("page_count"),
        "local_title_candidates": raw.get("title_candidates", [])[:8],
        "local_section_heading_candidates": raw.get("section_headings", [])[:40],
        "local_caption_candidates": captions,
        "text_extraction_quality": raw.get("text_extraction_quality", {}),
    }


PDF_SYSTEM_PROMPT = """
Extract faithful, structured academic-paper content from the supplied PDF.

Treat the PDF as the source of truth. Use the local extraction context only as
candidate metadata. Read both the PDF text and its page images. Resolve reading
order, multi-column layouts, cover pages, section boundaries, figures, and
tables semantically.

Rules:
- Never invent authors, affiliations, claims, metrics, p-values, comparisons,
  novelty, limitations, or conclusions.
- Preserve uncertainty and exact numeric values.
- Use one-indexed PDF page numbers.
- Attach at least one source reference to every non-empty claim-bearing field.
- Each source quote must be a short, exact passage copied from the cited page.
- Return an empty string or empty list when content is not supported.
- Keep abstract, methods, results, and conclusion faithful and concise enough
  for downstream poster synthesis; do not turn them into promotional language.
- Do not treat bibliography entries, headers, footers, or table-of-contents
  lines as paper findings.
"""


TEXT_SYSTEM_PROMPT = """
Extract faithful, structured academic-paper content from page-numbered text.

Treat the supplied page text as the source of truth. It was extracted
deterministically from a PDF and may contain multi-column reading-order noise,
headers, footers, captions, or broken lines. Resolve semantic sections without
inventing missing content.

Rules:
- Never invent authors, affiliations, claims, metrics, p-values, comparisons,
  novelty, limitations, or conclusions.
- Preserve uncertainty and exact numeric values.
- PAGE markers are one-indexed PDF page numbers.
- Attach at least one source reference to every non-empty claim-bearing field.
- Each source quote must be a short, exact passage copied from the cited page.
- Return an empty string or empty list when content is not supported.
- Keep abstract, methods, results, and conclusion faithful and concise enough
  for downstream poster synthesis; do not turn them into promotional language.
- Do not treat bibliography entries, headers, footers, or table-of-contents
  lines as paper findings.
"""


def resolve_model_input_mode(requested: str) -> str:
    if requested in {"pdf", "text"}:
        return requested
    base_url = clean_space(os.environ.get("OPENAI_BASE_URL", ""))
    if not base_url:
        return "pdf"
    hostname = (urlparse(base_url).hostname or "").casefold()
    return "pdf" if hostname == "api.openai.com" else "text"


def page_text_context(raw: dict[str, Any], max_chars: int = MAX_MODEL_TEXT_CHARS) -> tuple[str, bool]:
    chunks: list[str] = []
    used = 0
    truncated = False
    for index, page in enumerate(raw.get("pages", []), start=1):
        if not isinstance(page, dict):
            continue
        try:
            page_number = int(page.get("page_number", index) or index)
        except (TypeError, ValueError):
            page_number = index
        text = str(page.get("text", "") or "").strip()
        if not text:
            continue
        chunk = f"\n\n===== PAGE {page_number} =====\n{text}"
        remaining = max_chars - used
        if remaining <= 0:
            truncated = True
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            truncated = True
            break
        chunks.append(chunk)
        used += len(chunk)
    return "".join(chunks).strip(), truncated


def model_payload_stats(model_data: dict[str, Any]) -> dict[str, int]:
    evidence_items: list[dict[str, Any]] = []
    for field in ("title", "abstract", "methods", "results", "conclusion", "research_question"):
        item = model_data.get(field)
        if isinstance(item, dict) and clean_space(item.get("text", "")):
            evidence_items.append(item)
    for field in ("authors", "affiliations", "key_contributions", "key_results", "limitations"):
        values = model_data.get(field, [])
        if not isinstance(values, list):
            continue
        evidence_items.extend(
            item for item in values
            if isinstance(item, dict) and clean_space(item.get("text", ""))
        )
    sections = [
        item for item in model_data.get("sections", [])
        if isinstance(item, dict) and clean_space(item.get("heading", "")) and clean_space(item.get("text", ""))
    ]
    source_ref_count = sum(
        len(item.get("source_refs", []))
        for item in [*evidence_items, *sections]
        if isinstance(item.get("source_refs", []), list)
    )
    return {
        "nonempty_evidence_fields": len(evidence_items),
        "nonempty_sections": len(sections),
        "source_ref_count": source_ref_count,
    }


def validate_model_payload(model_data: dict[str, Any]) -> dict[str, int]:
    stats = model_payload_stats(model_data)
    semantic_count = stats["nonempty_evidence_fields"] + stats["nonempty_sections"]
    if semantic_count < 2:
        raise RuntimeError(
            "The model returned an effectively empty semantic extraction "
            f"(semantic_fields={semantic_count}, source_refs={stats['source_ref_count']})."
        )
    if stats["source_ref_count"] < 2:
        raise RuntimeError(
            "The model extraction did not include enough source references "
            f"(semantic_fields={semantic_count}, source_refs={stats['source_ref_count']})."
        )
    return stats


def call_model(
    pdf_path: Path,
    raw: dict[str, Any],
    model: str,
    detail: str,
    input_mode: str,
) -> dict[str, Any]:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Python package 'openai' is not installed.") from exc

    local_context = json.dumps(compact_raw_context(raw), ensure_ascii=False)
    prompt_prefix = (
        "Extract the paper into the required schema. Here is deterministic local "
        "evidence metadata to help align page count, candidate headings, and captions:\n"
        + local_context
    )
    if input_mode == "pdf":
        encoded_pdf = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
        system_prompt = PDF_SYSTEM_PROMPT
        user_content = [
            {
                "type": "input_file",
                "filename": pdf_path.name,
                "file_data": f"data:application/pdf;base64,{encoded_pdf}",
                "detail": detail,
            },
            {"type": "input_text", "text": prompt_prefix},
        ]
    else:
        page_text, truncated = page_text_context(raw)
        if not page_text:
            raise RuntimeError("Deterministic PDF extraction produced no page text for model input.")
        system_prompt = TEXT_SYSTEM_PROMPT
        truncation_note = (
            "\nThe page text was truncated at the configured character limit."
            if truncated else ""
        )
        user_content = [{
            "type": "input_text",
            "text": f"{prompt_prefix}{truncation_note}\n\nPAGE-NUMBERED PAPER TEXT:\n{page_text}",
        }]
    client = OpenAI()
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_content,
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "academic_paper_extraction",
                "strict": True,
                "schema": extraction_schema(),
            }
        },
    )
    output_text = response_output_text(response)
    if not output_text:
        raise RuntimeError("The model returned no structured output.")
    try:
        model_data = json_object_from_text(output_text)
    except ValueError as exc:
        preview = clean_space(output_text)[:400]
        raise RuntimeError(
            f"The model returned invalid JSON: {exc}. Response preview: {preview!r}"
        ) from exc
    validate_model_payload(model_data)
    return model_data


def normalized_evidence(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"text": "", "confidence": 0.0, "source_refs": []}
    refs = item.get("source_refs", [])
    return {
        "text": clean_space(item.get("text", "")),
        "confidence": round(max(0.0, min(float(item.get("confidence", 0.0) or 0.0), 1.0)), 2),
        "source_refs": refs if isinstance(refs, list) else [],
    }


def normalized_evidence_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        evidence = normalized_evidence(item)
        if evidence["text"]:
            result.append(evidence)
    return result


def merge_model_extraction(
    raw: dict[str, Any],
    model_data: dict[str, Any],
    raw_json: Path,
    model: str,
    detail: str,
    input_mode: str,
) -> dict[str, Any]:
    result = copy.deepcopy(raw)
    title = normalized_evidence(model_data.get("title"))
    authors = normalized_evidence_list(model_data.get("authors"))
    affiliations = normalized_evidence_list(model_data.get("affiliations"))
    abstract = normalized_evidence(model_data.get("abstract"))
    methods = normalized_evidence(model_data.get("methods"))
    results = normalized_evidence(model_data.get("results"))
    conclusion = normalized_evidence(model_data.get("conclusion"))

    source_label = "openai_pdf_semantic_extraction" if input_mode == "pdf" else "model_page_text_semantic_extraction"
    model_sections: list[dict[str, Any]] = []
    for item in model_data.get("sections", []):
        if not isinstance(item, dict):
            continue
        heading = clean_space(item.get("heading", ""))
        text = clean_space(item.get("text", ""))
        if not heading or not text:
            continue
        model_sections.append(
            {
                "heading": heading,
                "normalized_heading": clean_space(item.get("normalized_heading", "")),
                "page_start": int(item.get("page_start", 1) or 1),
                "page_end": int(item.get("page_end", 1) or 1),
                "text": text,
                "line_count": 0,
                "confidence": round(float(item.get("confidence", 0.0) or 0.0), 2),
                "source_refs": item.get("source_refs", []),
                "source": source_label,
            }
        )

    if title["text"]:
        result["title"] = title["text"]
        result["title_confidence"] = title["confidence"]
        candidates = list(result.get("title_candidates", []))
        candidates.insert(
            0,
            {
                "text": title["text"],
                "source": source_label,
                "page": title["source_refs"][0].get("page") if title["source_refs"] else None,
                "score": round(title["confidence"] * 24, 2),
            },
        )
        result["title_candidates"] = candidates[:12]
    if authors:
        result["authors"] = [item["text"] for item in authors if item["text"]]
    if affiliations:
        result["affiliations"] = [item["text"] for item in affiliations if item["text"]]
    if abstract["text"]:
        result["abstract"] = abstract["text"]
    if methods["text"]:
        result["methods"] = methods["text"]
    if results["text"]:
        result["results"] = results["text"]
    if conclusion["text"]:
        result["conclusion"] = conclusion["text"]
    if model_sections:
        result["sections"] = model_sections
        result["section_headings"] = [item["heading"] for item in model_sections]

    result["field_evidence"] = {
        "title": title,
        "authors": authors,
        "affiliations": affiliations,
        "abstract": abstract,
        "methods": methods,
        "results": results,
        "conclusion": conclusion,
    }
    result["semantic_extraction"] = {
        "research_question": normalized_evidence(model_data.get("research_question")),
        "key_contributions": normalized_evidence_list(model_data.get("key_contributions")),
        "key_results": normalized_evidence_list(model_data.get("key_results")),
        "limitations": normalized_evidence_list(model_data.get("limitations")),
        "paper_language": clean_space(model_data.get("paper_language", "")),
        "paper_type": clean_space(model_data.get("paper_type", "")),
    }
    result["extraction_stage"] = "semantic_paper_extraction"
    result["extraction_method"] = (
        "openai_pdf_input_hybrid" if input_mode == "pdf"
        else "openai_compatible_page_text_hybrid"
    )
    result["extraction_model"] = model
    result["model_input_mode"] = input_mode
    result["pdf_detail"] = detail if input_mode == "pdf" else None
    result["model_payload_stats"] = model_payload_stats(model_data)
    if input_mode == "text":
        page_text, truncated = page_text_context(raw)
        result["model_input_char_count"] = len(page_text)
        result["model_input_truncated"] = truncated
    result["raw_extraction_path"] = str(raw_json)
    notes = list(raw.get("extraction_notes", []))
    notes.extend(clean_space(note) for note in model_data.get("extraction_notes", []) if clean_space(note))
    if input_mode == "pdf":
        notes.append(f"Semantic PDF extraction used model {model} with detail={detail}.")
    else:
        notes.append(
            f"Semantic extraction used model {model} with page-numbered deterministic PDF text "
            f"({result['model_input_char_count']} characters; truncated={result['model_input_truncated']})."
        )
    result["extraction_notes"] = notes
    return result


def local_fallback(raw: dict[str, Any], raw_json: Path, reason: str) -> dict[str, Any]:
    result = copy.deepcopy(raw)
    result["extraction_stage"] = "semantic_paper_extraction"
    result["extraction_method"] = "local_pdf_tools_fallback"
    result["extraction_model"] = None
    result["raw_extraction_path"] = str(raw_json)
    result["field_evidence"] = {}
    result["semantic_extraction"] = {}
    result.setdefault("extraction_notes", []).append(f"Model semantic extraction skipped: {reason}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Use an OpenAI multimodal model to structure PDF content while preserving local evidence."
    )
    parser.add_argument("pdf_path", help="Path to the source academic PDF.")
    parser.add_argument("--raw-json", default="outputs/raw_pdf_extraction.json")
    parser.add_argument("--output-json", default="outputs/extracted_paper.json")
    parser.add_argument("--mode", choices=["auto", "model", "local"], default="auto")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--detail", choices=["auto", "low", "high"], default="auto")
    parser.add_argument(
        "--input-mode",
        choices=["auto", "pdf", "text"],
        default="auto",
        help="auto uses direct PDF input for api.openai.com and page-numbered text for custom base URLs.",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    raw_json = Path(args.raw_json)
    output_json = Path(args.output_json)
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        print(f"Error: source PDF does not exist or is not a PDF: {pdf_path}", file=sys.stderr)
        return 1
    if not raw_json.exists():
        print(f"Error: raw extraction JSON does not exist: {raw_json}", file=sys.stderr)
        return 1

    try:
        raw = read_json(raw_json)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.mode == "local":
        data = local_fallback(raw, raw_json, "local mode was explicitly selected")
        write_json(output_json, data)
        print(f"Wrote {output_json} using local fallback.")
        return 0

    input_mode = resolve_model_input_mode(args.input_mode)
    unavailable_reason = ""
    if not os.environ.get("OPENAI_API_KEY"):
        unavailable_reason = "OPENAI_API_KEY is not configured"
    elif input_mode == "pdf" and pdf_path.stat().st_size >= MAX_PDF_BYTES:
        unavailable_reason = "the PDF is 50 MB or larger and cannot be sent as one file input"

    if unavailable_reason:
        if args.mode == "model":
            print(f"Error: {unavailable_reason}.", file=sys.stderr)
            return 2
        data = local_fallback(raw, raw_json, unavailable_reason)
        write_json(output_json, data)
        print(f"Wrote {output_json} using local fallback: {unavailable_reason}.")
        return 0

    try:
        model_data = call_model(pdf_path, raw, args.model, args.detail, input_mode)
        data = merge_model_extraction(raw, model_data, raw_json, args.model, args.detail, input_mode)
    except Exception as exc:
        if args.mode == "model":
            print(f"Error: model semantic extraction failed: {exc}", file=sys.stderr)
            return 2
        data = local_fallback(raw, raw_json, f"model call failed: {exc}")
        print(f"Warning: model semantic extraction failed; using local fallback: {exc}", file=sys.stderr)

    write_json(output_json, data)
    print(f"Wrote {output_json}")
    print(f"Extraction method: {data.get('extraction_method')}")
    print(f"Model: {data.get('extraction_model') or '[not used]'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
