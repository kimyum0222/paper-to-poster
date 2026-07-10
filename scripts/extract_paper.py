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
    "summary",
    "keywords",
    "index terms",
    "contents",
    "table of contents",
    "introduction",
    "background",
    "related work",
    "literature review",
    "preliminaries",
    "method",
    "methods",
    "methodology",
    "approach",
    "model",
    "framework",
    "implementation",
    "experiments",
    "experiment",
    "experimental setup",
    "evaluation",
    "results",
    "analysis",
    "discussion",
    "limitations",
    "conclusion",
    "conclusions",
    "future work",
    "acknowledgments",
    "acknowledgements",
    "references",
    "bibliography",
    "appendix",
    "摘要",
    "关键词",
    "目录",
    "引言",
    "绪论",
    "背景",
    "相关工作",
    "文献综述",
    "方法",
    "研究方法",
    "模型",
    "框架",
    "实验",
    "实验结果",
    "结果",
    "分析",
    "讨论",
    "局限性",
    "结论",
    "总结",
    "展望",
    "致谢",
    "参考文献",
}

DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
ARXIV_RE = re.compile(r"\barXiv:\s*(?:[a-z\-]+/)?\d{4}\.\d{4,5}(?:v\d+)?", re.IGNORECASE)
CAPTION_START_RE = re.compile(
    r"^(?:(fig(?:ure)?\.?|table)\s*\d+[a-z]?\s*[:.]\s*|([图表])\s*\d+(?:[-—–.]\d+)?[a-zA-Z]?\s+)",
    re.IGNORECASE,
)
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
    "conference paper",
    "pack of",
    "ounce",
    "total results",
    "back to search",
    "instruction:",
}
COVER_OR_TEMPLATE_TITLE_FRAGMENTS = {
    "本科毕业论文",
    "毕业论文",
    "毕业设计",
    "硕士学位论文",
    "博士学位论文",
    "学位论文",
    "专业名称",
    "专业班级",
    "学生姓名",
    "学 生",
    "指导教师",
    "所在学院",
    "学院名称",
    "授权书",
    "原创性声明",
    "研究成果",
    "共同工作",
    "教育机构",
    "填写阿拉伯数字",
    "graduation thesis",
    "classification",
    "student name",
    "supervisor",
    "thesis submitted",
}
KNOWN_SECTION_KEYS = {
    "abstract",
    "introduction",
    "background",
    "related_work",
    "methods",
    "results",
    "conclusion",
    "limitations",
    "references",
    "contents",
}
REFERENCE_HEADINGS = {"references", "bibliography", "参考文献"}
ABSTRACT_HEADINGS = {"abstract", "summary", "摘要"}
METHOD_KEYWORDS = ["method", "approach", "model", "framework", "methodology", "方法", "模型", "框架"]
RESULT_KEYWORDS = ["result", "experiment", "evaluation", "analysis", "结果", "实验", "分析"]
CONCLUSION_KEYWORDS = ["conclusion", "discussion", "future work", "结论", "总结", "展望", "讨论"]


def clean_space(text: str) -> str:
    """Collapse repeated whitespace while keeping text readable."""
    return re.sub(r"\s+", " ", text).strip()


def clean_line_text(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(text))
    text = clean_space(text)
    text = re.sub(r"\s+([,.;:!?，。；：！？])", r"\1", text)
    text = re.sub(r"([（(])\s+", r"\1", text)
    text = re.sub(r"\s+([）)])", r"\1", text)
    return clean_space(text)


def clean_lines(text: str) -> list[str]:
    return [clean_line_text(line) for line in text.splitlines() if clean_line_text(line)]


def compact_alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def compact_heading_key(text: str) -> str:
    return re.sub(r"[\s:：.。_\-—–]+", "", text.lower())


def round_box(raw_box: Any) -> list[float]:
    try:
        return [round(float(value), 2) for value in raw_box]
    except Exception:
        return [0.0, 0.0, 0.0, 0.0]


def merge_bboxes(boxes: list[Any]) -> list[float] | None:
    normalized = [round_box(box) for box in boxes if box]
    if not normalized:
        return None
    return [
        round(min(box[0] for box in normalized), 2),
        round(min(box[1] for box in normalized), 2),
        round(max(box[2] for box in normalized), 2),
        round(max(box[3] for box in normalized), 2),
    ]


def bbox_center(box: Any) -> tuple[float, float] | None:
    if not box:
        return None
    x0, y0, x1, y1 = round_box(box)
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def bbox_area(box: Any) -> float:
    if not box:
        return 0.0
    x0, y0, x1, y1 = round_box(box)
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


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
        if lowered.startswith("arxiv preprint"):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def looks_like_template_or_cover_text(text: str) -> bool:
    lowered = text.lower()
    return any(fragment in lowered for fragment in COVER_OR_TEMPLATE_TITLE_FRAGMENTS)


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
    if looks_like_template_or_cover_text(text):
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
        "keywords",
        "abstract",
    ]
    return any(fragment in lowered for fragment in bad_fragments)


def title_candidate_score(text: str, page_number: int, font_size: float = 0.0, y0: float = 9999.0) -> float:
    title = normalize_extracted_title(text)
    if looks_like_bad_title(title):
        return -100.0
    if re.fullmatch(r"[\d\s年月日./-]+", title):
        return -100.0
    if any(mark in title for mark in ["□", "___", "：", ":"]) and not re.search(r"\b[A-Za-z]+:\s+[A-Za-z]", title):
        return -20.0
    if len(title) > 35 and re.search(r"[，。；；,.;]", title):
        return -20.0
    if title.endswith(("。", "，", ",", ";", "；")):
        return -20.0
    word_count = len(title.split())
    score = 0.0
    if 8 <= len(title) <= 180:
        score += 10
    if 3 <= word_count <= 24 or re.search(r"[\u4e00-\u9fff]", title):
        score += 4
    if page_number <= 2:
        score += 4
    if page_number == 1:
        score += 2
    if font_size:
        score += min(font_size, 30) / 3
    if y0 < 250:
        score += 2
    if re.search(r"\b(abstract|introduction|keywords|references)\b", title, re.IGNORECASE):
        score -= 8
    if re.search(r"(摘要|关键词|参考文献)", title):
        score -= 8
    return score


def infer_title_from_metadata(metadata: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    title = normalize_extracted_title(str(metadata.get("title") or ""))
    if title and not looks_like_bad_title(title):
        candidate = {
            "text": title,
            "source": "pdf_metadata",
            "page": None,
            "score": title_candidate_score(title, 1),
        }
        return title, [candidate]
    return "", []


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


def choose_title_from_candidates(candidates: list[dict[str, Any]]) -> tuple[str, float]:
    valid = [item for item in candidates if clean_space(str(item.get("text", ""))) and item.get("score", -100) > 0]
    if not valid:
        return "", 0.0
    valid.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    best = valid[0]
    return str(best["text"]), min(1.0, max(0.0, float(best.get("score", 0.0)) / 24.0))


def expand_title_from_layout(title: str, candidates: list[dict[str, Any]], pages: list[dict[str, Any]]) -> str:
    if not title or not candidates:
        return title

    best = max(candidates, key=lambda item: float(item.get("score", 0.0)))
    if best.get("source") != "layout_line" or not best.get("bbox") or not best.get("page"):
        return title

    page_number = int(best.get("page") or 0)
    page = next((item for item in pages if int(item.get("page_number", 0) or 0) == page_number), None)
    if not page:
        return title

    best_box = round_box(best["bbox"])
    best_y1 = best_box[3]
    best_x0 = best_box[0]
    best_size = float(best.get("font_size", 0.0) or 0.0)
    continuation: list[str] = []

    for line in page.get("lines", []):
        text = normalize_extracted_title(str(line.get("text", "")))
        if not text or text == title or looks_like_bad_title(text):
            continue
        box = round_box(line.get("bbox", [0, 9999, 0, 9999]))
        font_size = float(line.get("font_size", 0.0) or 0.0)
        if box[1] <= best_y1 or box[1] - best_y1 > 45:
            continue
        if abs(box[0] - best_x0) > 60:
            continue
        if best_size and font_size < best_size * 0.75:
            continue
        if len(text.split()) > 8:
            continue
        if re.search(r"[a-z]", text) and text.upper() != text:
            continue
        continuation.append(text)

    if continuation:
        return normalize_extracted_title(" ".join([title] + continuation[:2]))
    return title


def collect_title_candidates_from_pages(
    pages: list[dict[str, Any]],
    metadata: dict[str, Any],
    max_pages: int = 4,
) -> tuple[str, list[dict[str, Any]], float]:
    metadata_title, candidates = infer_title_from_metadata(metadata)
    if metadata_title:
        return metadata_title, candidates, 0.9

    for page in pages[:max_pages]:
        page_number = int(page.get("page_number", 0) or 0)
        for line in page.get("lines", [])[:80]:
            text = normalize_extracted_title(str(line.get("text", "")))
            if not text or len(text) > 180:
                continue
            bbox = line.get("bbox") or [0, 9999, 0, 9999]
            font_size = float(line.get("font_size", 0.0) or 0.0)
            score = title_candidate_score(text, page_number, font_size, float(bbox[1]))
            if score <= 0:
                continue
            candidates.append(
                {
                    "text": text,
                    "source": "layout_line",
                    "page": page_number,
                    "bbox": bbox,
                    "font_size": font_size,
                    "score": round(score, 2),
                }
            )

        lines = clean_lines(str(page.get("text", "")))
        for line in lines[:30]:
            title = normalize_extracted_title(line)
            score = title_candidate_score(title, page_number)
            if score > 0:
                candidates.append(
                    {
                        "text": title,
                        "source": "plain_text",
                        "page": page_number,
                        "score": round(score, 2),
                    }
                )

    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = compact_heading_key(str(candidate.get("text", "")))
        if not key:
            continue
        if key not in deduped or float(candidate.get("score", 0)) > float(deduped[key].get("score", 0)):
            deduped[key] = candidate

    title_candidates = sorted(deduped.values(), key=lambda item: float(item.get("score", 0)), reverse=True)[:12]
    title, confidence = choose_title_from_candidates(title_candidates)
    title = expand_title_from_layout(title, title_candidates, pages)
    return title, title_candidates, confidence


def is_heading_line(line: str) -> bool:
    stripped = clean_space(line).strip(".: ")
    lowered = stripped.lower()
    compact = compact_heading_key(stripped)

    if not stripped or len(stripped) > 120:
        return False

    if any(fragment in lowered for fragment in NOISY_HEADING_FRAGMENTS):
        return False

    if re.match(r"^(?:19|20)\d{2}\s*年", stripped):
        return False

    if len(stripped) > 35 and re.search(r"[，。；；,.;]", stripped):
        return False

    if re.search(r"\.{4,}|…{2,}|\.{2,}\s*\d+$", stripped):
        return False

    if lowered in COMMON_SECTION_NAMES or compact in {compact_heading_key(name) for name in COMMON_SECTION_NAMES}:
        return True

    if re.match(r"^\d+(?:\.\d+)*\s+[A-Z][A-Za-z0-9 ,/&()\-:]{2,}$", stripped):
        return True

    if re.match(r"^[IVX]+\.\s+[A-Z][A-Za-z0-9 ,/&()\-:]{2,}$", stripped):
        return True

    if re.match(r"^(chapter|section)\s+\d+(?:\.\d+)*[:.\s]+", stripped, re.IGNORECASE):
        return True

    if re.match(r"^第[一二三四五六七八九十\d]+[章节]\s*[\u4e00-\u9fffA-Za-z0-9 ]{2,}$", stripped):
        return True

    if re.match(r"^\d+(?:\.\d+)+\s*[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9 、：:（）()/-]{1,}$", stripped):
        return True

    if re.match(r"^\d+\s+[\u4e00-\u9fff][\u4e00-\u9fffA-Za-z0-9 、：:（）()/-]{1,20}$", stripped):
        return True

    letters = re.sub(r"[^A-Za-z]", "", stripped)
    if len(letters) >= 4 and letters.isupper() and len(stripped.split()) <= 8:
        return True

    return False


def normalize_heading(heading: str) -> str:
    heading = clean_space(heading).strip(".: ")
    heading = re.sub(r"^(chapter|section)\s+\d+(?:\.\d+)*[:.\s]+", "", heading, flags=re.IGNORECASE)
    heading = re.sub(r"^第[一二三四五六七八九十\d]+[章节]\s*", "", heading)
    heading = re.sub(r"^\d+(?:\.\d+)*\s+", "", heading)
    heading = re.sub(r"^\d+(?:\.\d+)*", "", heading)
    heading = re.sub(r"^[IVX]+\.\s+", "", heading)
    return clean_space(heading).strip(".:：。 ")


def normalize_section_key(heading: str) -> str:
    normalized = normalize_heading(heading).lower()
    compact = compact_heading_key(normalized)
    aliases = {
        "summary": "abstract",
        "摘要": "abstract",
        "contents": "contents",
        "tableofcontents": "contents",
        "目录": "contents",
        "introduction": "introduction",
        "引言": "introduction",
        "绪论": "introduction",
        "background": "background",
        "相关工作": "related_work",
        "文献综述": "related_work",
        "relatedwork": "related_work",
        "literaturereview": "related_work",
        "method": "methods",
        "methods": "methods",
        "methodology": "methods",
        "approach": "methods",
        "model": "methods",
        "framework": "methods",
        "方法": "methods",
        "研究方法": "methods",
        "模型": "methods",
        "框架": "methods",
        "experiments": "results",
        "experiment": "results",
        "experimentalsetup": "results",
        "evaluation": "results",
        "results": "results",
        "analysis": "results",
        "实验": "results",
        "实验结果": "results",
        "结果": "results",
        "分析": "results",
        "discussion": "conclusion",
        "conclusion": "conclusion",
        "conclusions": "conclusion",
        "futurework": "conclusion",
        "讨论": "conclusion",
        "结论": "conclusion",
        "总结": "conclusion",
        "展望": "conclusion",
        "limitations": "limitations",
        "局限性": "limitations",
        "references": "references",
        "bibliography": "references",
        "参考文献": "references",
    }
    if compact in aliases:
        return aliases[compact]
    if any(fragment in compact for fragment in ["数值试验", "试验结果", "实验结果", "结果分析", "矩误差", "分布分析", "接受拒绝诊断"]):
        return "results"
    if any(fragment in compact for fragment in ["总结", "展望", "结论"]):
        return "conclusion"
    if any(fragment in compact for fragment in ["朗之万采样", "采样基础", "采样方法"]):
        return "methods"
    return compact or normalized


def line_looks_like_heading_record(line: dict[str, Any], body_font_size: float) -> bool:
    text = clean_line_text(str(line.get("text", "")))
    lowered = text.lower().strip(".:： ")
    compact = compact_heading_key(text)
    if any(fragment in lowered for fragment in NOISY_HEADING_FRAGMENTS):
        return False
    if is_heading_line(text):
        return True
    if len(text) > 100 or len(text) < 3:
        return False
    if looks_like_template_or_cover_text(text):
        return False
    if re.search(r"\.{4,}|…{2,}|\.{2,}\s*\d+$", text):
        return False
    if text.endswith(("。", "，", ",", ";", "；")):
        return False
    if len(text) > 35 and re.search(r"[，。；；,.;]", text):
        return False
    symbol_count = len(re.findall(r"[^A-Za-z0-9\u4e00-\u9fff\s]", text))
    if len(text) >= 10 and symbol_count / max(len(text), 1) > 0.28:
        return False
    if lowered in COMMON_SECTION_NAMES or compact in {compact_heading_key(name) for name in COMMON_SECTION_NAMES}:
        return True
    font_size = float(line.get("font_size", 0.0) or 0.0)
    is_bold = bool(line.get("is_bold"))
    word_count = len(text.split())
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    if cjk_count and cjk_count > 16:
        return False
    if (is_bold or (body_font_size and font_size >= body_font_size * 1.2)) and word_count <= 10:
        if re.search(r"[A-Za-z\u4e00-\u9fff]", text) and not text.endswith((".", ",")):
            return True
    return False


def repeated_layout_line_keys(pages: list[dict[str, Any]], min_pages: int = 3) -> set[str]:
    page_sets: dict[str, set[int]] = {}
    for page in pages:
        page_number = int(page.get("page_number", 0) or 0)
        for line in page.get("lines", []):
            text = clean_line_text(str(line.get("text", "")))
            if not text or len(text) > 90:
                continue
            key = compact_heading_key(text)
            if not key:
                continue
            page_sets.setdefault(key, set()).add(page_number)
    return {key for key, page_numbers in page_sets.items() if len(page_numbers) >= min_pages}


def looks_like_table_or_numeric_fragment(text: str) -> bool:
    stripped = clean_space(text)
    if not stripped:
        return True
    numeric_tokens = re.findall(r"\b\d+(?:\.\d+)?%?\b", stripped)
    tokens = stripped.split()
    if tokens and len(numeric_tokens) / max(len(tokens), 1) >= 0.45:
        return True
    if len(stripped) <= 18 and re.fullmatch(r"[A-Za-z0-9+\-().% ]+", stripped):
        return True
    if re.search(r"^\d+(?:\.\d+)?$", stripped):
        return True
    return False


def truncate_caption_text(text: str, max_chars: int = 260) -> str:
    text = clean_space(text)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    sentence_end = max(cut.rfind(". "), cut.rfind("。"), cut.rfind("; "))
    if sentence_end >= 80:
        return clean_space(cut[: sentence_end + 1])
    return clean_space(cut).rstrip(",;:") + "..."


def extract_lines_from_pymupdf_page(page: Any, page_number: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    page_dict = page.get_text("dict")
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    line_records: list[dict[str, Any]] = []
    block_records: list[dict[str, Any]] = []

    for block_index, block in enumerate(page_dict.get("blocks", [])):
        if block.get("type", 0) != 0:
            continue
        block_lines: list[dict[str, Any]] = []
        for line_index, line in enumerate(block.get("lines", [])):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = clean_line_text("".join(str(span.get("text", "")) for span in spans))
            if not text:
                continue
            bbox = round_box(line.get("bbox", [0, 0, 0, 0]))
            font_sizes = [float(span.get("size", 0.0) or 0.0) for span in spans]
            fonts = " ".join(str(span.get("font", "")) for span in spans).lower()
            flags = [int(span.get("flags", 0) or 0) for span in spans]
            font_size = max(font_sizes) if font_sizes else 0.0
            is_bold = "bold" in fonts or any(flag & 16 for flag in flags)
            record = {
                "page_number": page_number,
                "block_index": block_index,
                "line_index": line_index,
                "text": text,
                "bbox": bbox,
                "font_size": round(font_size, 2),
                "is_bold": is_bold,
            }
            block_lines.append(record)
            line_records.append(record)
        if block_lines:
            block_text = "\n".join(line["text"] for line in block_lines)
            block_records.append(
                {
                    "page_number": page_number,
                    "block_index": block_index,
                    "bbox": round_box(block.get("bbox", [0, 0, 0, 0])),
                    "text": block_text,
                    "lines": block_lines,
                }
            )

    ordered_lines = order_page_lines(line_records, page_width, page_height)
    return ordered_lines, block_records


def order_page_lines(lines: list[dict[str, Any]], page_width: float, page_height: float) -> list[dict[str, Any]]:
    if not lines:
        return []
    header_cutoff = page_height * 0.18
    full_width_min = page_width * 0.62

    top_full = []
    column_lines = []
    for line in lines:
        x0, y0, x1, _ = line.get("bbox", [0, 0, 0, 0])
        width = float(x1) - float(x0)
        if y0 <= header_cutoff or width >= full_width_min:
            top_full.append(line)
        else:
            column_lines.append(line)

    left_count = sum(1 for line in column_lines if ((line["bbox"][0] + line["bbox"][2]) / 2) < page_width * 0.5)
    right_count = len(column_lines) - left_count
    detected_two_col = left_count >= 8 and right_count >= 8

    def sort_key(line: dict[str, Any]) -> tuple[float, float, float]:
        x0, y0, x1, _ = line.get("bbox", [0, 0, 0, 0])
        center_x = (float(x0) + float(x1)) / 2
        if detected_two_col:
            column = 0 if center_x < page_width * 0.5 else 1
            return (column, float(y0), float(x0))
        return (float(y0), float(x0), 0.0)

    ordered = sorted(top_full, key=lambda line: (line["bbox"][1], line["bbox"][0]))
    ordered.extend(sorted(column_lines, key=sort_key))
    for index, line in enumerate(ordered):
        line["reading_order"] = index
        line["column"] = "left" if ((line["bbox"][0] + line["bbox"][2]) / 2) < page_width * 0.5 else "right"
    return ordered


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


def estimate_body_font_size(pages: list[dict[str, Any]]) -> float:
    sizes: list[float] = []
    for page in pages:
        for line in page.get("lines", []):
            size = float(line.get("font_size", 0.0) or 0.0)
            text = clean_line_text(str(line.get("text", "")))
            if size > 0 and len(text) >= 30:
                sizes.append(round(size, 1))
    if not sizes:
        return 0.0
    sizes.sort()
    return sizes[len(sizes) // 2]


def extract_structured_sections_from_lines(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    body_font_size = estimate_body_font_size(pages)
    repeated_keys = repeated_layout_line_keys(pages)
    flattened: list[dict[str, Any]] = []
    for page in pages:
        for line in page.get("lines", []):
            text = clean_line_text(str(line.get("text", "")))
            if not text:
                continue
            item = dict(line)
            item["text"] = text
            flattened.append(item)

    heading_positions: list[tuple[int, dict[str, Any]]] = []
    seen_positions: set[tuple[int, str]] = set()
    for index, line in enumerate(flattened):
        text = line["text"]
        if not line_looks_like_heading_record(line, body_font_size):
            continue
        bbox = line.get("bbox") or [0, 9999, 0, 9999]
        page_number = int(line.get("page_number", 0) or 0)
        font_size = float(line.get("font_size", 0.0) or 0.0)
        if page_number <= 2 and float(bbox[1]) < 220 and body_font_size and font_size >= body_font_size * 1.45:
            continue
        normalized = normalize_heading(text)
        if not normalized or looks_like_template_or_cover_text(normalized):
            continue
        if re.match(r"^(figure|fig\.?|table)\s+\d+", normalized, re.IGNORECASE):
            continue
        normalized_key = normalize_section_key(normalized)
        compact_key = compact_heading_key(normalized)
        if compact_key in repeated_keys:
            continue
        if any(fragment in normalized.lower() for fragment in NOISY_HEADING_FRAGMENTS):
            continue
        if normalized_key in {"methods", "results"} and normalized.lower() in {"method", "methods", "result", "results", "score", "act", "react", "human", "expert"}:
            if not line.get("is_bold") and body_font_size and font_size <= body_font_size * 1.15:
                continue
        if normalized_key not in KNOWN_SECTION_KEYS and looks_like_table_or_numeric_fragment(normalized):
            continue
        if page_number <= 3 and normalized_key not in {"abstract", "introduction"}:
            continue
        if re.search(r"\.{4,}|…{2,}|\.{2,}\s*\d+$", normalized):
            continue
        key = (page_number, compact_heading_key(normalized))
        if key in seen_positions:
            continue
        seen_positions.add(key)
        heading_positions.append((index, line))

    first_content_heading = next(
        (
            position
            for position, (_, line) in enumerate(heading_positions)
            if normalize_section_key(str(line.get("text", ""))) in {"abstract", "introduction"}
        ),
        None,
    )
    if first_content_heading is not None:
        heading_positions = heading_positions[first_content_heading:]

    sections: list[dict[str, Any]] = []
    for position, (line_index, heading_line) in enumerate(heading_positions):
        next_index = heading_positions[position + 1][0] if position + 1 < len(heading_positions) else len(flattened)
        heading = normalize_heading(str(heading_line.get("text", "")))
        body_lines = flattened[line_index + 1 : next_index]
        body_text = "\n".join(line["text"] for line in body_lines).strip()
        if not body_text:
            continue
        normalized_heading = normalize_section_key(heading)
        if normalized_heading == "references":
            break
        if normalized_heading not in KNOWN_SECTION_KEYS and len(body_text) < 160:
            continue
        if normalized_heading not in KNOWN_SECTION_KEYS and looks_like_table_or_numeric_fragment(body_text[:240]):
            continue
        page_start = int(heading_line.get("page_number", 0) or 0)
        page_end = int(body_lines[-1].get("page_number", page_start) or page_start) if body_lines else page_start
        confidence = 0.65
        if is_heading_line(str(heading_line.get("text", ""))):
            confidence += 0.15
        if body_font_size and float(heading_line.get("font_size", 0.0) or 0.0) >= body_font_size * 1.12:
            confidence += 0.1
        if heading_line.get("is_bold"):
            confidence += 0.1
        sections.append(
            {
                "heading": heading,
                "normalized_heading": normalized_heading,
                "page_start": page_start,
                "page_end": page_end,
                "text": body_text,
                "line_count": len(body_lines),
                "confidence": round(min(confidence, 1.0), 2),
            }
        )

    return sections


def sections_list_to_dict(sections: list[dict[str, Any]], fallback_text: str = "") -> dict[str, str]:
    mapped: dict[str, str] = {}
    for section in sections:
        heading = clean_space(str(section.get("heading", "")))
        body = str(section.get("text", "")).strip()
        if heading and body:
            mapped[heading] = body
    if mapped:
        return mapped
    return extract_sections(fallback_text)


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
        if re.match(r"^(figure|fig\.?|table)\s+\d+", heading, re.IGNORECASE):
            continue
        heading_l = heading.lower()
        heading_key = normalize_section_key(heading)
        if any(keyword in heading_l or keyword in heading_key for keyword in keywords):
            return body[:max_chars]
    return ""


def find_structured_section_text(
    structured_sections: list[dict[str, Any]],
    normalized_keys: set[str],
    max_chars: int = 7000,
    min_chars: int = 120,
) -> str:
    candidates: list[tuple[int, str]] = []
    for section in structured_sections:
        normalized = str(section.get("normalized_heading", ""))
        heading = str(section.get("heading", ""))
        if re.match(r"^(figure|fig\.?|table)\s+\d+", heading, re.IGNORECASE):
            continue
        if normalized in normalized_keys:
            text = str(section.get("text", "")).strip()
            if len(text) >= min_chars:
                priority = 0
                compact = compact_heading_key(heading)
                if "results" in normalized_keys and any(term in compact for term in ["数值试验", "试验结果", "实验结果", "结果分析"]):
                    priority += 10000
                if "conclusion" in normalized_keys and any(term in compact for term in ["总结", "结论", "展望"]):
                    priority += 10000
                if "methods" in normalized_keys and any(term in compact for term in ["采样", "方法", "模型", "框架"]):
                    priority += 10000
                candidates.append((priority + len(text), text))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1][:max_chars]


def extract_abstract_from_pages(pages: list[dict[str, Any]]) -> str:
    def looks_like_title_line(line: str) -> bool:
        if re.search(r"[。.!?]", line):
            return False
        if re.search(r"[\u4e00-\u9fff]", line):
            return len(line) <= 28
        words = [word for word in re.split(r"\s+", line) if word]
        if not words:
            return True
        title_case_words = sum(1 for word in words if word[:1].isupper())
        return len(line) <= 85 and title_case_words / len(words) >= 0.45

    candidates: list[str] = []
    for page in pages[:8]:
        lines = clean_lines(str(page.get("text", "")))
        if not lines:
            continue
        keyword_index = next(
            (
                index
                for index, line in enumerate(lines)
                if re.match(r"^(关键词|key\s*words?|keywords)\b", line, re.IGNORECASE)
            ),
            None,
        )
        if keyword_index is None:
            continue
        before_keywords = [
            line
            for line in lines[:keyword_index]
            if normalize_section_key(line) not in {"abstract", "contents"}
            and not looks_like_template_or_cover_text(line)
        ]
        while before_keywords and looks_like_title_line(before_keywords[0]):
            before_keywords.pop(0)
        candidate = "\n".join(before_keywords).strip()
        if len(candidate) >= 120:
            candidates.append(candidate)
        continue

        # Unreachable by design after keyword handling; kept for readability of
        # the keyword-first branch above.

    if not candidates:
        for page in pages[:3]:
            lines = clean_lines(str(page.get("text", "")))
            abstract_index = next(
                (index for index, line in enumerate(lines) if line.lower().strip() == "abstract"),
                None,
            )
            if abstract_index is None:
                continue
            abstract_lines: list[str] = []
            for line in lines[abstract_index + 1 :]:
                lowered = line.lower().strip()
                if lowered in {"introduction", "references", "acknowledgements", "acknowledgments"}:
                    break
                if re.match(r"^(figure|fig\.?|table)\s+\d+", line, re.IGNORECASE):
                    break
                if len(abstract_lines) >= 24:
                    break
                abstract_lines.append(line)
            candidate = "\n".join(abstract_lines).strip()
            if len(candidate) >= 120:
                candidates.append(candidate)
    if not candidates:
        return ""
    candidates.sort(key=len, reverse=True)
    return candidates[0][:5000]


def extract_abstract(
    full_text: str,
    sections: dict[str, str],
    structured_sections: list[dict[str, Any]] | None = None,
    pages: list[dict[str, Any]] | None = None,
) -> str:
    if pages:
        page_abstract = extract_abstract_from_pages(pages)
        if page_abstract:
            return page_abstract

    if structured_sections:
        abstract = find_structured_section_text(structured_sections, {"abstract"}, max_chars=5000, min_chars=80)
        if abstract:
            return abstract

    for heading, body in sections.items():
        if normalize_section_key(heading) == "abstract":
            return body[:5000]

    match = re.search(
        r"(?is)(?:\babstract\b|摘要)\s*[:：.\-]?\s*(.*?)(?=\n\s*(?:keywords|关键词|index terms|1\.?\s*introduction|introduction|引言|绪论)\b)",
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
        raw_lines = page.get("lines") or [
            {"text": line, "bbox": None, "page_number": page_number}
            for line in clean_lines(str(page.get("text", "")))
        ]
        lines = [
            {
                "text": clean_line_text(str(line.get("text", ""))),
                "bbox": line.get("bbox"),
                "page_number": page_number,
            }
            for line in raw_lines
            if clean_line_text(str(line.get("text", "")))
        ]
        index = 0
        while index < len(lines):
            line = lines[index]
            line_text = str(line["text"])
            match = CAPTION_START_RE.match(line_text)
            if not match:
                index += 1
                continue
            is_chinese_caption = bool(match.group(2))
            caption_remainder = clean_space(line_text[match.end() :])
            if is_chinese_caption:
                if not caption_remainder:
                    index += 1
                    continue
                if caption_remainder.startswith(("中", "展示", "给出", "能够", "可以", "还", "（", "(")):
                    index += 1
                    continue
                if len(caption_remainder) > 80 and re.search(r"[。；;]", caption_remainder):
                    index += 1
                    continue

            caption_parts = [line_text]
            caption_boxes = [line.get("bbox")]
            lookahead = index + 1
            while not is_chinese_caption and lookahead < len(lines) and len(" ".join(caption_parts)) < 260:
                next_line = str(lines[lookahead]["text"])
                if CAPTION_START_RE.match(next_line) or is_heading_line(next_line):
                    break
                if re.match(r"^(we|this|the|on|in|as|for|to|also|due|table|figure)\b", next_line, re.IGNORECASE):
                    break
                if len(next_line) > 220:
                    break
                caption_parts.append(next_line)
                caption_boxes.append(lines[lookahead].get("bbox"))
                lookahead += 1

            caption_text = truncate_caption_text(clean_space(" ".join(caption_parts)))
            caption_id = f"caption_{len(captions) + 1}"
            caption_type = "table" if caption_text.lower().startswith("table") or caption_text.startswith("表") else "figure"
            bbox = merge_bboxes([box for box in caption_boxes if box])
            caption_record = {
                "id": caption_id,
                "type": caption_type,
                "page": page_number,
                "text": caption_text,
                "bbox": bbox,
            }
            captions.append(caption_record)

            caption_ref = {"id": caption_id, "page": page_number, "caption": caption_text, "bbox": bbox}
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
        image_box = image_record.get("bbox")
        image_center = bbox_center(image_box)
        candidates = [
            caption
            for caption in figures_from_captions
            if caption.get("page") == page and caption.get("id") not in used_caption_ids
        ]
        matching_caption = None
        if image_center and candidates:
            def caption_distance(caption: dict[str, Any]) -> float:
                caption_box = caption.get("bbox")
                caption_center = bbox_center(caption_box)
                if not caption_center:
                    return 100000.0
                _, image_y = image_center
                _, caption_y = caption_center
                vertical = abs(caption_y - image_y)
                if caption_box and image_box:
                    image_bottom = round_box(image_box)[3]
                    caption_top = round_box(caption_box)[1]
                    if caption_top >= image_bottom:
                        vertical *= 0.6
                return vertical

            matching_caption = min(candidates, key=caption_distance)
        elif candidates:
            matching_caption = candidates[0]

        if matching_caption:
            image_record["caption"] = matching_caption.get("caption", "")
            image_record["caption_id"] = matching_caption.get("id", "")
            image_record["caption_bbox"] = matching_caption.get("bbox")
            image_record["caption_confidence"] = 0.75 if matching_caption.get("bbox") else 0.45
            used_caption_ids.add(str(matching_caption.get("id", "")))


def extract_reference_metadata(full_text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    dois = sorted(set(match.group(0).rstrip(".,;)])") for match in DOI_RE.finditer(full_text)))
    arxiv_ids = sorted(set(clean_space(match.group(0)) for match in ARXIV_RE.finditer(full_text)))

    return {
        "pdf_metadata": {key: value for key, value in metadata.items() if value},
        "doi_candidates": dois[:10],
        "arxiv_candidates": arxiv_ids[:10],
    }


def score_image_record(record: dict[str, Any], page_width: float, page_height: float) -> float:
    width = int(record.get("width_px", 0) or 0)
    height = int(record.get("height_px", 0) or 0)
    bbox = record.get("bbox")
    score = 0.0
    if width >= 300 and height >= 180:
        score += 4
    elif width >= 180 and height >= 120:
        score += 2
    if bbox and page_width and page_height:
        area_ratio = bbox_area(bbox) / max(page_width * page_height, 1.0)
        if 0.04 <= area_ratio <= 0.55:
            score += 4
        elif 0.015 <= area_ratio <= 0.7:
            score += 2
        if area_ratio < 0.01:
            score -= 4
    if record.get("caption"):
        score += 3
    return round(score, 2)


def render_figure_crops_from_captions(
    doc: Any,
    figure_captions: list[dict[str, Any]],
    assets_dir: Path,
    outputs_dir: Path,
) -> list[dict[str, Any]]:
    crop_records: list[dict[str, Any]] = []
    for caption in figure_captions:
        page_number = int(caption.get("page", 0) or 0)
        bbox = caption.get("bbox")
        if not page_number or not bbox or page_number > len(doc):
            continue

        page = doc[page_number - 1]
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)
        caption_box = round_box(bbox)
        caption_top = caption_box[1]

        crop_bottom = max(60.0, caption_top - 6.0)
        crop_top = max(36.0, crop_bottom - min(300.0, page_height * 0.42))
        crop_left = max(36.0, min(caption_box[0] - 60.0, page_width * 0.12))
        crop_right = min(page_width - 36.0, max(caption_box[2] + 60.0, page_width * 0.88))

        if crop_bottom - crop_top < 80 or crop_right - crop_left < 120:
            continue

        try:
            import fitz  # type: ignore

            clip = fitz.Rect(crop_left, crop_top, crop_right, crop_bottom)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
        except Exception:
            continue

        filename = f"figure_crop_p{page_number}_{len(crop_records) + 1}.png"
        asset_path = assets_dir / filename
        pix.save(str(asset_path))

        crop_box = [round(crop_left, 2), round(crop_top, 2), round(crop_right, 2), round(crop_bottom, 2)]
        record = {
            "id": f"crop_{len(crop_records) + 1}",
            "page": page_number,
            "kind": "page_crop",
            "asset_path": str(asset_path.relative_to(outputs_dir)),
            "bbox": crop_box,
            "all_bboxes": [crop_box],
            "page_width": round(page_width, 2),
            "page_height": round(page_height, 2),
            "area_ratio": round(bbox_area(crop_box) / max(page_width * page_height, 1.0), 4),
            "width_px": int(pix.width),
            "height_px": int(pix.height),
            "extension": "png",
            "caption": caption.get("caption", ""),
            "caption_id": caption.get("id", ""),
            "caption_bbox": bbox,
            "caption_confidence": 0.85,
            "quality_score": 12.0,
            "selection_reason": "rendered page crop above matched figure caption",
        }
        crop_records.append(record)

    return crop_records


def detect_column_mode(pages: list[dict[str, Any]]) -> str:
    two_column_pages = 0
    checked_pages = 0
    for page in pages:
        lines = page.get("lines", [])
        if len(lines) < 16:
            continue
        checked_pages += 1
        left = sum(1 for line in lines if line.get("column") == "left")
        right = sum(1 for line in lines if line.get("column") == "right")
        if left >= 8 and right >= 8:
            two_column_pages += 1
    if checked_pages and two_column_pages >= max(1, checked_pages // 3):
        return "two-column"
    if checked_pages:
        return "single-column-or-mixed"
    return "unknown"


def build_text_extraction_quality(
    pages: list[dict[str, Any]],
    full_text: str,
    structured_sections: list[dict[str, Any]],
    title_confidence: float,
    title_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    pages_with_text = sum(1 for page in pages if clean_space(str(page.get("text", ""))))
    normalized_sections = {str(section.get("normalized_heading", "")) for section in structured_sections}
    missing_required_sections = [
        key
        for key in ["abstract", "methods", "results", "conclusion"]
        if key not in normalized_sections
    ]
    first_page_text = pages[0].get("text", "") if pages else ""
    likely_cover_page = looks_like_template_or_cover_text(first_page_text)
    return {
        "char_count": len(clean_space(full_text)),
        "page_count": len(pages),
        "pages_with_text": pages_with_text,
        "detected_columns": detect_column_mode(pages),
        "section_count": len(structured_sections),
        "section_headings": [section.get("heading", "") for section in structured_sections[:30]],
        "missing_required_sections": missing_required_sections,
        "title_confidence": round(title_confidence, 2),
        "title_candidate_count": len(title_candidates),
        "likely_cover_page": likely_cover_page,
        "body_font_size": round(estimate_body_font_size(pages), 2),
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
                "title_candidates": [],
                "title_confidence": 0.0,
                "authors": [],
                "affiliations": [],
                "abstract": "",
                "section_headings": [],
                "sections": [],
                "methods": "",
                "results": "",
                "conclusion": "",
                "figures": [],
                "tables": [],
                "captions": [],
                "references_or_citation_metadata": {},
                "text_extraction_quality": {
                    "char_count": 0,
                    "page_count": len(doc),
                    "pages_with_text": 0,
                    "detected_columns": "unknown",
                    "section_count": 0,
                    "section_headings": [],
                    "missing_required_sections": ["abstract", "methods", "results", "conclusion"],
                    "title_confidence": 0.0,
                    "title_candidate_count": 0,
                    "likely_cover_page": False,
                    "body_font_size": 0.0,
                },
                "extraction_notes": notes + ["Could not read encrypted PDF."],
                "source_pdf": str(pdf_path),
            }

    metadata = dict(doc.metadata or {})

    for page_index, page in enumerate(doc):
        page_number = page_index + 1
        try:
            layout_lines, layout_blocks = extract_lines_from_pymupdf_page(page, page_number)
            page_text = clean_extracted_page_text("\n".join(line["text"] for line in layout_lines))
        except Exception as exc:
            notes.append(f"Could not extract layout text from page {page_number}: {exc}")
            layout_lines = []
            layout_blocks = []
            page_text = clean_extracted_page_text(page.get_text("text") or "")
        pages.append(
            {
                "page_number": page_number,
                "width": round(float(page.rect.width), 2),
                "height": round(float(page.rect.height), 2),
                "text": page_text,
                "lines": layout_lines,
                "blocks": layout_blocks,
            }
        )

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
            image_rects = []
            try:
                image_rects = [round_box(rect) for rect in page.get_image_rects(xref)]
            except Exception:
                image_rects = []
            image_bbox = image_rects[0] if image_rects else None
            page_width = float(page.rect.width)
            page_height = float(page.rect.height)

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
                    "kind": "raster_xref",
                    "asset_path": str(asset_path.relative_to(outputs_dir)),
                    "bbox": image_bbox,
                    "all_bboxes": image_rects,
                    "page_width": round(page_width, 2),
                    "page_height": round(page_height, 2),
                    "area_ratio": round(bbox_area(image_bbox) / max(page_width * page_height, 1.0), 4) if image_bbox else 0.0,
                    "width_px": width,
                    "height_px": height,
                    "extension": ext,
                    "caption": "",
                    "caption_id": "",
                    "caption_confidence": 0.0,
                }
            )

    full_text = "\n\n".join(page["text"] for page in pages)
    title, title_candidates, title_confidence = collect_title_candidates_from_pages(pages, metadata)
    structured_sections = extract_structured_sections_from_lines(pages)
    sections = sections_list_to_dict(structured_sections, full_text)
    captions, figures_from_captions, tables_from_captions = extract_captions_from_pages(pages)

    crop_records = render_figure_crops_from_captions(doc, figures_from_captions, assets_dir, outputs_dir)
    attach_captions_to_images(image_records, figures_from_captions)
    image_records.extend(crop_records)
    for image_record in image_records:
        image_record["quality_score"] = score_image_record(
            image_record,
            float(image_record.get("page_width", 0.0) or 0.0),
            float(image_record.get("page_height", 0.0) or 0.0),
        )
        reasons: list[str] = []
        if image_record.get("caption"):
            reasons.append("matched caption")
        if image_record.get("area_ratio", 0) and float(image_record.get("area_ratio", 0)) >= 0.015:
            reasons.append("substantial page area")
        if int(image_record.get("width_px", 0) or 0) >= 300:
            reasons.append("adequate pixel width")
        image_record["selection_reason"] = image_record.get("selection_reason") or ("; ".join(reasons) if reasons else "extracted raster image")

    first_page_text = pages[0]["text"] if pages else ""
    authors, affiliations = extract_authors_and_affiliations(first_page_text, title)

    if len(clean_space(full_text)) < 500:
        notes.append("Very little text was extracted. The PDF may be scanned or image-only.")

    abstract = extract_abstract(full_text, sections, structured_sections, pages)
    methods = find_structured_section_text(structured_sections, {"methods"}, max_chars=7000) or find_section_text(sections, METHOD_KEYWORDS)
    results = find_structured_section_text(structured_sections, {"results"}, max_chars=7000) or find_section_text(sections, RESULT_KEYWORDS)
    conclusion = find_structured_section_text(structured_sections, {"conclusion"}, max_chars=7000) or find_section_text(sections, CONCLUSION_KEYWORDS)

    quality = build_text_extraction_quality(pages, full_text, structured_sections, title_confidence, title_candidates)

    return {
        "title": title,
        "title_candidates": title_candidates,
        "title_confidence": title_confidence,
        "authors": authors,
        "affiliations": affiliations,
        "abstract": abstract,
        "section_headings": list(sections.keys()),
        "sections": structured_sections,
        "methods": methods,
        "results": results,
        "conclusion": conclusion,
        "figures": image_records or figures_from_captions,
        "tables": tables_from_captions,
        "captions": captions,
        "references_or_citation_metadata": extract_reference_metadata(full_text, metadata),
        "text_extraction_quality": quality,
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
                "title_candidates": [],
                "title_confidence": 0.0,
                "authors": [],
                "affiliations": [],
                "abstract": "",
                "section_headings": [],
                "sections": [],
                "methods": "",
                "results": "",
                "conclusion": "",
                "figures": [],
                "tables": [],
                "captions": [],
                "references_or_citation_metadata": {},
                "text_extraction_quality": {
                    "char_count": 0,
                    "page_count": len(reader.pages),
                    "pages_with_text": 0,
                    "detected_columns": "unknown",
                    "section_count": 0,
                    "section_headings": [],
                    "missing_required_sections": ["abstract", "methods", "results", "conclusion"],
                    "title_confidence": 0.0,
                    "title_candidate_count": 0,
                    "likely_cover_page": False,
                    "body_font_size": 0.0,
                },
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
    metadata_title, title_candidates = infer_title_from_metadata(metadata)
    title = metadata_title or infer_title_from_first_page_text(first_page_text)
    title_confidence = 0.9 if metadata_title else (0.35 if title else 0.0)
    if title and not title_candidates:
        title_candidates = [{"text": title, "source": "plain_text", "page": 1, "score": 8.0}]
    authors, affiliations = extract_authors_and_affiliations(first_page_text, title)

    if len(clean_space(full_text)) < 500:
        notes.append("Very little text was extracted. The PDF may be scanned or image-only.")

    pseudo_sections = [
        {
            "heading": heading,
            "normalized_heading": normalize_section_key(heading),
            "page_start": None,
            "page_end": None,
            "text": body,
            "line_count": len(clean_lines(body)),
            "confidence": 0.45,
        }
        for heading, body in sections.items()
    ]
    quality = build_text_extraction_quality(pages, full_text, pseudo_sections, title_confidence, title_candidates)

    return {
        "title": title,
        "title_candidates": title_candidates,
        "title_confidence": title_confidence,
        "authors": authors,
        "affiliations": affiliations,
        "abstract": extract_abstract(full_text, sections, pseudo_sections, pages),
        "section_headings": list(sections.keys()),
        "sections": pseudo_sections,
        "methods": find_section_text(sections, METHOD_KEYWORDS),
        "results": find_section_text(sections, RESULT_KEYWORDS),
        "conclusion": find_section_text(sections, CONCLUSION_KEYWORDS),
        "figures": figures_from_captions,
        "tables": tables_from_captions,
        "captions": captions,
        "references_or_citation_metadata": extract_reference_metadata(full_text, metadata),
        "text_extraction_quality": quality,
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
