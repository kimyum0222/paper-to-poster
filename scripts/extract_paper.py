#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


COMMON_SECTION_NAMES = {
    "abstract",
    "keywords",
    "introduction",
    "background",
    "related work",
    "preliminaries",
    "method",
    "methods",
    "methodology",
    "approach",
    "model",
    "framework",
    "experiments",
    "experiment",
    "evaluation",
    "results",
    "discussion",
    "limitations",
    "conclusion",
    "conclusions",
    "acknowledgments",
    "acknowledgements",
    "references",
    "bibliography",
}

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
ARXIV_RE = re.compile(r"\barXiv:\s*(?:[a-z\-]+/)?\d{4}\.\d{4,5}(?:v\d+)?", re.IGNORECASE)
CAPTION_START_RE = re.compile(r"^(fig(?:ure)?\.?|table)\s*\d+[a-z]?\s*[:.]", re.IGNORECASE)
AFFILIATION_KEYWORDS = {
    "university",
    "institute",
    "department",
    "school",
    "laboratory",
    "laboratories",
    "lab",
    "college",
    "research",
    "group",
    "team",
    "center",
    "centre",
    "company",
    "google",
    "microsoft",
    "openai",
    "meta",
}
NOISY_HEADING_FRAGMENTS = {
    "published as",
    "pack of",
    "ounce",
    "total results",
    "back to search",
    "instruction:",
}


def clean_space(text: str) -> str:
    """Collapse repeated whitespace while keeping text readable."""
    return re.sub(r"\s+", " ", text).strip()


def clean_lines(text: str) -> list[str]:
    return [clean_space(line) for line in text.splitlines() if clean_space(line)]


def compact_alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def normalize_extracted_title(text: str) -> str:
    """Repair common PDF title extraction artifacts without inventing content."""
    title = clean_space(text)
    if not title:
        return ""

    title = re.sub(r"\s+([:;,])", r"\1", title)

    # Some PDFs expose display-letterspaced titles as "R E A CT" or
    # "S YNERGIZING". Repair those only when the title has enough single-letter
    # tokens to suggest letterspacing rather than ordinary prose.
    single_letter_tokens = re.findall(r"\b[A-Z]\b", title)
    if len(single_letter_tokens) >= 2:
        title = re.sub(
            r"\b((?:[A-Z]\s+){2,}[A-Z]{1,4})\b",
            lambda match: match.group(1).replace(" ", ""),
            title,
        )
        title = re.sub(r"\b([A-Z])\s+([A-Z]{2,})\b", r"\1\2", title)
        title = re.sub(r"\s+([:;,])", r"\1", title)

    return clean_space(title)


def clean_extracted_page_text(text: str) -> str:
    cleaned_lines: list[str] = []
    for line in clean_lines(text):
        lowered = line.lower()
        if re.fullmatch(r"\d{1,4}", line):
            continue
        if lowered.startswith("published as "):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def load_optional_pdf_tools() -> tuple[Any | None, Any | None]:
    """Load local PDF libraries if the environment already has them installed."""
    try:
        import fitz  # type: ignore
    except ImportError:
        fitz = None

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        PdfReader = None

    return fitz, PdfReader


def looks_like_bad_title(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered or len(lowered) < 5:
        return True
    bad_fragments = [
        "microsoft word",
        "untitled",
        "arxiv",
        "proceedings of",
        "conference on",
        "transactions on",
        "journal of",
        "doi",
        "http",
        "www.",
    ]
    return any(fragment in lowered for fragment in bad_fragments)


def infer_title_from_metadata(metadata: dict[str, Any]) -> str:
    title = normalize_extracted_title(str(metadata.get("title") or ""))
    if title and not looks_like_bad_title(title):
        return title
    return ""


def infer_title_from_first_page_text(first_page_text: str) -> str:
    lines = clean_lines(first_page_text)
    for line in lines[:20]:
        if looks_like_bad_title(line):
            continue
        if line.lower() in COMMON_SECTION_NAMES:
            continue
        if 5 <= len(line) <= 180:
            return normalize_extracted_title(line)
    return ""


def infer_title_from_pymupdf_page(page: Any, metadata: dict[str, Any]) -> str:
    """Use font sizes on page 1 to guess the paper title when PyMuPDF is available."""
    metadata_title = infer_title_from_metadata(metadata)
    if metadata_title:
        return metadata_title

    try:
        page_dict = page.get_text("dict")
        page_height = float(page.rect.height)
    except Exception:
        return infer_title_from_first_page_text(page.get_text("text"))

    candidates: list[tuple[float, float, str]] = []
    for block in page_dict.get("blocks", []):
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = normalize_extracted_title(" ".join(str(span.get("text", "")) for span in spans))
            if not text or looks_like_bad_title(text):
                continue
            bbox = line.get("bbox", [0, 0, 0, 0])
            y0 = float(bbox[1])
            if y0 > page_height * 0.45:
                continue
            max_size = max(float(span.get("size", 0)) for span in spans)
            if 5 <= len(text) <= 180:
                candidates.append((y0, max_size, text))

    if not candidates:
        return infer_title_from_first_page_text(page.get_text("text"))

    largest_size = max(size for _, size, _ in candidates)
    title_lines = [
        text
        for y0, size, text in sorted(candidates, key=lambda item: item[0])
        if size >= largest_size * 0.85
    ]

    title = normalize_extracted_title(" ".join(title_lines[:3]))
    if title:
        return title
    return infer_title_from_first_page_text(page.get_text("text"))


def is_heading_line(line: str) -> bool:
    stripped = clean_space(line).strip(".: ")
    lowered = stripped.lower()

    if not stripped or len(stripped) > 120:
        return False

    if any(fragment in lowered for fragment in NOISY_HEADING_FRAGMENTS):
        return False

    if lowered in COMMON_SECTION_NAMES:
        return True

    if re.match(r"^\d+(?:\.\d+)*\s+[A-Z][A-Za-z0-9 ,/&()\-:]{2,}$", stripped):
        return True

    if re.match(r"^[IVX]+\.\s+[A-Z][A-Za-z0-9 ,/&()\-:]{2,}$", stripped):
        return True

    return False


def normalize_heading(heading: str) -> str:
    heading = clean_space(heading).strip(".: ")
    heading = re.sub(r"^\d+(?:\.\d+)*\s+", "", heading)
    heading = re.sub(r"^[IVX]+\.\s+", "", heading)
    return heading


def extract_sections(full_text: str) -> dict[str, str]:
    lines = clean_lines(full_text)
    heading_positions: list[tuple[int, str]] = []

    for index, line in enumerate(lines):
        if is_heading_line(line):
            heading_positions.append((index, normalize_heading(line)))

    sections: dict[str, str] = {}
    for position, (line_index, heading) in enumerate(heading_positions):
        next_index = heading_positions[position + 1][0] if position + 1 < len(heading_positions) else len(lines)
        body = "\n".join(lines[line_index + 1 : next_index]).strip()
        if body:
            sections[heading] = body

    return sections


def is_affiliation_line(line: str) -> bool:
    lowered = line.lower()
    if "@" in line:
        return True
    if any(keyword in lowered for keyword in AFFILIATION_KEYWORDS):
        return True
    if re.match(r"^\d+\s*[A-Z].*(research|team|group|lab|department|university|institute)", line, re.IGNORECASE):
        return True
    return False


def find_section_text(sections: dict[str, str], keywords: list[str], max_chars: int = 7000) -> str:
    for heading, body in sections.items():
        heading_l = heading.lower()
        if any(keyword in heading_l for keyword in keywords):
            return body[:max_chars]
    return ""


def extract_abstract(full_text: str, sections: dict[str, str]) -> str:
    for heading, body in sections.items():
        if heading.lower().strip() == "abstract":
            return body[:5000]

    match = re.search(
        r"(?is)\babstract\b\s*[:.\-]?\s*(.*?)(?=\n\s*(?:keywords|index terms|1\.?\s*introduction|introduction)\b)",
        full_text,
    )
    if match:
        return clean_space(match.group(1))[:5000]
    return ""


def extract_authors_and_affiliations(first_page_text: str, title: str) -> tuple[list[str], list[str]]:
    """A cautious heuristic. It is better to return little than to invent authors."""
    lines = clean_lines(first_page_text)
    authors: list[str] = []
    affiliations: list[str] = []

    start_index = 0
    if title:
        title_first_words = clean_space(title).split()[:5]
        for index, line in enumerate(lines[:30]):
            title_prefix = compact_alnum(" ".join(title_first_words[:3]))
            line_compact = compact_alnum(line)
            if title_prefix and title_prefix in line_compact:
                start_index = index + 1
                break

    candidate_lines = lines[start_index : start_index + 12]
    for line in candidate_lines:
        lowered = line.lower()
        if lowered in COMMON_SECTION_NAMES or lowered.startswith("abstract"):
            break
        if is_affiliation_line(line):
            affiliations.append(line)
            continue
        if re.search(r"[A-Z][a-z]+\s+[A-Z][a-z]+", line) and len(line) <= 220:
            authors.append(line)

    return authors[:5], affiliations[:5]


def extract_captions_from_pages(
    pages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    captions: list[dict[str, Any]] = []
    figures_from_captions: list[dict[str, Any]] = []
    tables_from_captions: list[dict[str, Any]] = []

    for page in pages:
        page_number = page.get("page_number")
        lines = clean_lines(str(page.get("text", "")))
        index = 0
        while index < len(lines):
            line = lines[index]
            if not CAPTION_START_RE.match(line):
                index += 1
                continue

            caption_parts = [line]
            lookahead = index + 1
            while lookahead < len(lines) and len(" ".join(caption_parts)) < 500:
                next_line = lines[lookahead]
                if CAPTION_START_RE.match(next_line) or is_heading_line(next_line):
                    break
                if len(next_line) > 220:
                    break
                caption_parts.append(next_line)
                lookahead += 1

            caption_text = clean_space(" ".join(caption_parts))
            caption_id = f"caption_{len(captions) + 1}"
            caption_type = "table" if caption_text.lower().startswith("table") else "figure"
            caption_record = {
                "id": caption_id,
                "type": caption_type,
                "page": page_number,
                "text": caption_text,
            }
            captions.append(caption_record)

            caption_ref = {"id": caption_id, "page": page_number, "caption": caption_text}
            if caption_type == "figure":
                figures_from_captions.append(caption_ref)
            else:
                tables_from_captions.append(caption_ref)

            index = max(lookahead, index + 1)

    return captions, figures_from_captions, tables_from_captions


def attach_captions_to_images(
    image_records: list[dict[str, Any]],
    figures_from_captions: list[dict[str, Any]],
) -> None:
    used_caption_ids: set[str] = set()
    for image_record in image_records:
        page = image_record.get("page")
        matching_caption = next(
            (
                caption
                for caption in figures_from_captions
                if caption.get("page") == page and caption.get("id") not in used_caption_ids
            ),
            None,
        )
        if matching_caption:
            image_record["caption"] = matching_caption.get("caption", "")
            image_record["caption_id"] = matching_caption.get("id", "")
            used_caption_ids.add(str(matching_caption.get("id", "")))


def extract_reference_metadata(full_text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    dois = sorted(set(match.group(0).rstrip(".,;)])") for match in DOI_RE.finditer(full_text)))
    arxiv_ids = sorted(set(clean_space(match.group(0)) for match in ARXIV_RE.finditer(full_text)))

    return {
        "pdf_metadata": {key: value for key, value in metadata.items() if value},
        "doi_candidates": dois[:10],
        "arxiv_candidates": arxiv_ids[:10],
    }


def extract_with_pymupdf(pdf_path: Path, outputs_dir: Path) -> dict[str, Any]:
    import fitz  # type: ignore

    assets_dir = outputs_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    notes: list[str] = []
    pages: list[dict[str, Any]] = []
    image_records: list[dict[str, Any]] = []
    seen_xrefs: set[int] = set()

    doc = fitz.open(str(pdf_path))
    if doc.is_encrypted:
        notes.append("PDF is encrypted. Attempted empty-password authentication.")
        if not doc.authenticate(""):
            return {
                "title": "",
                "authors": [],
                "affiliations": [],
                "abstract": "",
                "section_headings": [],
                "methods": "",
                "results": "",
                "conclusion": "",
                "figures": [],
                "tables": [],
                "captions": [],
                "references_or_citation_metadata": {},
                "extraction_notes": notes + ["Could not read encrypted PDF."],
                "source_pdf": str(pdf_path),
            }

    metadata = dict(doc.metadata or {})
    first_page = doc[0] if len(doc) else None
    title = infer_title_from_pymupdf_page(first_page, metadata) if first_page else infer_title_from_metadata(metadata)

    for page_index, page in enumerate(doc):
        page_number = page_index + 1
        page_text = clean_extracted_page_text(page.get_text("text") or "")
        pages.append({"page_number": page_number, "text": page_text})

        for image_index, image in enumerate(page.get_images(full=True), start=1):
            xref = int(image[0])
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                image_info = doc.extract_image(xref)
            except Exception as exc:
                notes.append(f"Could not extract image xref {xref} on page {page_number}: {exc}")
                continue

            image_bytes = image_info.get("image")
            ext = image_info.get("ext", "bin")
            width = int(image_info.get("width", 0) or 0)
            height = int(image_info.get("height", 0) or 0)

            if not image_bytes:
                continue

            # Skip tiny decorative images in the first MVP.
            if width < 120 or height < 80:
                notes.append(f"Skipped small image on page {page_number}: {width}x{height}")
                continue

            filename = f"figure_p{page_number}_{image_index}.{ext}"
            asset_path = assets_dir / filename
            asset_path.write_bytes(image_bytes)

            image_records.append(
                {
                    "id": f"image_{len(image_records) + 1}",
                    "page": page_number,
                    "asset_path": str(asset_path.relative_to(outputs_dir)),
                    "width_px": width,
                    "height_px": height,
                    "extension": ext,
                    "caption": "",
                }
            )

    full_text = "\n\n".join(page["text"] for page in pages)
    sections = extract_sections(full_text)
    captions, figures_from_captions, tables_from_captions = extract_captions_from_pages(pages)

    attach_captions_to_images(image_records, figures_from_captions)

    first_page_text = pages[0]["text"] if pages else ""
    authors, affiliations = extract_authors_and_affiliations(first_page_text, title)

    if len(clean_space(full_text)) < 500:
        notes.append("Very little text was extracted. The PDF may be scanned or image-only.")

    return {
        "title": title,
        "authors": authors,
        "affiliations": affiliations,
        "abstract": extract_abstract(full_text, sections),
        "section_headings": list(sections.keys()),
        "methods": find_section_text(sections, ["method", "approach", "model", "framework"]),
        "results": find_section_text(sections, ["result", "experiment", "evaluation"]),
        "conclusion": find_section_text(sections, ["conclusion", "discussion"]),
        "figures": image_records or figures_from_captions,
        "tables": tables_from_captions,
        "captions": captions,
        "references_or_citation_metadata": extract_reference_metadata(full_text, metadata),
        "extraction_notes": notes,
        "source_pdf": str(pdf_path),
        "page_count": len(pages),
        "pages": pages,
    }


def extract_with_pypdf(pdf_path: Path) -> dict[str, Any]:
    from pypdf import PdfReader  # type: ignore

    notes: list[str] = ["Used pypdf fallback. Image extraction is not available in this mode."]
    reader = PdfReader(str(pdf_path))

    if reader.is_encrypted:
        notes.append("PDF is encrypted. Attempted empty-password decryption.")
        try:
            decrypt_result = reader.decrypt("")
        except Exception as exc:
            decrypt_result = 0
            notes.append(f"Could not decrypt PDF: {exc}")
        if decrypt_result == 0:
            return {
                "title": "",
                "authors": [],
                "affiliations": [],
                "abstract": "",
                "section_headings": [],
                "methods": "",
                "results": "",
                "conclusion": "",
                "figures": [],
                "tables": [],
                "captions": [],
                "references_or_citation_metadata": {},
                "extraction_notes": notes + ["Could not read encrypted PDF."],
                "source_pdf": str(pdf_path),
            }

    metadata_raw = reader.metadata or {}
    metadata = {str(key).lstrip("/"): str(value) for key, value in metadata_raw.items() if value}

    pages: list[dict[str, Any]] = []
    for page_index, page in enumerate(reader.pages):
        try:
            page_text = clean_extracted_page_text(page.extract_text() or "")
        except Exception as exc:
            page_text = ""
            notes.append(f"Could not extract text from page {page_index + 1}: {exc}")
        pages.append({"page_number": page_index + 1, "text": page_text})

    full_text = "\n\n".join(page["text"] for page in pages)
    sections = extract_sections(full_text)
    captions, figures_from_captions, tables_from_captions = extract_captions_from_pages(pages)
    first_page_text = pages[0]["text"] if pages else ""
    title = infer_title_from_metadata(metadata) or infer_title_from_first_page_text(first_page_text)
    authors, affiliations = extract_authors_and_affiliations(first_page_text, title)

    if len(clean_space(full_text)) < 500:
        notes.append("Very little text was extracted. The PDF may be scanned or image-only.")

    return {
        "title": title,
        "authors": authors,
        "affiliations": affiliations,
        "abstract": extract_abstract(full_text, sections),
        "section_headings": list(sections.keys()),
        "methods": find_section_text(sections, ["method", "approach", "model", "framework"]),
        "results": find_section_text(sections, ["result", "experiment", "evaluation"]),
        "conclusion": find_section_text(sections, ["conclusion", "discussion"]),
        "figures": figures_from_captions,
        "tables": tables_from_captions,
        "captions": captions,
        "references_or_citation_metadata": extract_reference_metadata(full_text, metadata),
        "extraction_notes": notes,
        "source_pdf": str(pdf_path),
        "page_count": len(pages),
        "pages": pages,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract paper content into outputs/extracted_paper.json.")
    parser.add_argument("pdf_path", help="Path to one academic paper PDF.")
    parser.add_argument("--outputs-dir", default="outputs", help="Directory for generated outputs.")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    outputs_dir = Path(args.outputs_dir)
    output_json = outputs_dir / "extracted_paper.json"

    if not pdf_path.exists():
        print(f"Error: PDF file does not exist: {pdf_path}", file=sys.stderr)
        return 1

    if pdf_path.suffix.lower() != ".pdf":
        print(f"Error: input file is not a PDF: {pdf_path}", file=sys.stderr)
        return 1

    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "assets").mkdir(parents=True, exist_ok=True)

    fitz, PdfReader = load_optional_pdf_tools()

    if fitz is not None:
        data = extract_with_pymupdf(pdf_path, outputs_dir)
        data.setdefault("extraction_notes", []).append("Extraction backend: PyMuPDF.")
    elif PdfReader is not None:
        data = extract_with_pypdf(pdf_path)
        data.setdefault("extraction_notes", []).append("Extraction backend: pypdf.")
    else:
        print(
            "Error: no supported local PDF library found. Install PyMuPDF or pypdf first.\n"
            "Recommended for this skill: pip install pymupdf",
            file=sys.stderr,
        )
        return 1

    write_json(output_json, data)

    print(f"Wrote {output_json}")
    print(f"Title: {data.get('title') or '[not detected]'}")
    print(f"Pages: {data.get('page_count', 0)}")
    print(f"Figures/images: {len(data.get('figures', []))}")
    print(f"Captions: {len(data.get('captions', []))}")
    if data.get("extraction_notes"):
        print("Notes:")
        for note in data["extraction_notes"][:8]:
            print(f"- {note}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
