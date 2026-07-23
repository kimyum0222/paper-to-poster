#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import mimetypes
import re
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

from poster_typesetting import (
    canonical_json_sha256,
    clean_space,
    configure_measurement_font,
    estimate_text_width,
    lines_preserve_text,
    resolve_font,
    wrap_text,
)


CANVAS_W = 1189
CANVAS_H = 841
MARGIN = 34
GUTTER = 22
HEADER_H = 105
FOOTER_H = 34
COLUMN_W = (CANVAS_W - 2 * MARGIN - 2 * GUTTER) / 3

DEFAULT_COLORS = {
    "background": "#f4f7fb",
    "panel": "#ffffff",
    "panel_stroke": "#d7dee8",
    "text": "#162033",
    "muted": "#5b677a",
    "accent_primary": "#2563eb",
    "accent_secondary": "#16a34a",
    "accent_result": "#ea580c",
    "accent_neutral": "#475569",
    "accent_idea": "#7c3aed",
    "accent_contribution": "#0891b2",
    "header_rule": "#b8c7db",
    "header_background": "#12233f",
    "header_text": "#ffffff",
    "header_muted": "#d7e3f3",
    "highlight_background": "#fff7ed",
    "figure_background": "#f8fafc",
}

DEFAULT_TYPOGRAPHY = {
    "font_family": "Arial, Helvetica, sans-serif",
    "title": 32,
    "authors": 13,
    "section_title": 18,
    "body": 11.5,
    "caption": 8.8,
    "footer": 8.5,
    "line_height_ratio": 1.3,
}

DEFAULT_CARD_STYLE = {
    "radius": 8,
    "padding_x": 20,
    "padding_y": 18,
    "accent_bar_width": 6,
    "stroke_width": 1.1,
    "shadow_opacity": 0.22,
}

SAFE_TRACED_ELEMENTS = {"g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
SAFE_TRACED_ATTRIBUTES = {
    "d", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "opacity", "transform",
    "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
    "width", "height", "points",
}


def deep_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def merged_dict(defaults: dict[str, Any], overrides: Any) -> dict[str, Any]:
    result = dict(defaults)
    if isinstance(overrides, dict):
        result.update(overrides)
    return result


def load_json_or_empty(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def svg_text_lines(
    text: str,
    x: float,
    y: float,
    max_width: float,
    font_size: float,
    line_height: float,
    css_class: str = "",
    max_lines: int | None = None,
    bullet: bool = False,
    fill: str | None = None,
    wrapped_lines: list[str] | None = None,
) -> tuple[str, float]:
    lines = wrapped_lines if wrapped_lines is not None and lines_preserve_text(text, wrapped_lines) else wrap_text(text, max_width, font_size, max_lines=max_lines)
    if not lines:
        return "", y

    class_attr = f' class="{css_class}"' if css_class else ""
    fill_attr = f' fill="{escape(fill)}"' if fill else ""
    bullet_prefix = "• " if bullet else ""
    tspans = []
    for index, line in enumerate(lines):
        prefix = bullet_prefix if index == 0 else "  "
        dy = 0 if index == 0 else line_height
        tspans.append(
            f'<tspan x="{x:.1f}" dy="{dy:.1f}">{escape(prefix + line)}</tspan>'
        )

    svg = f'<text{class_attr}{fill_attr} font-size="{font_size}" x="{x:.1f}" y="{y:.1f}">' + "".join(tspans) + "</text>"
    return svg, y + line_height * len(lines)


def image_to_data_uri(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def svg_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def safe_generated_vector_path(value: Any) -> str | None:
    text = clean_space(value).replace("\\", "/")
    parts = [part for part in text.split("/") if part]
    if len(parts) == 3 and parts[:2] == ["assets", "generated"] and parts[-1].endswith(".svg"):
        return "/".join(parts)
    return None


@lru_cache(maxsize=16)
def load_safe_traced_svg(path_text: str, expected_sha256: str) -> tuple[str, tuple[float, float, float, float], int] | None:
    path = Path(path_text)
    if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
        return None
    expected = expected_sha256.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or file_sha256(path) != expected:
        return None
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return None
    if svg_local_name(root.tag) != "svg":
        return None
    try:
        view_box_values = tuple(float(value) for value in str(root.attrib.get("viewBox", "")).replace(",", " ").split())
    except ValueError:
        return None
    if len(view_box_values) != 4 or view_box_values[2] <= 0 or view_box_values[3] <= 0:
        return None
    if not all(math.isfinite(value) for value in view_box_values):
        return None

    element_count = 0

    def clean(source: ET.Element) -> ET.Element | None:
        nonlocal element_count
        tag = svg_local_name(source.tag)
        if tag not in SAFE_TRACED_ELEMENTS:
            return None
        if tag == "path" and not str(source.attrib.get("d", "")).strip():
            return None
        element_count += 1
        if element_count > 5000:
            raise ValueError("too many traced vector elements")
        target = ET.Element(tag)
        for raw_name, raw_value in source.attrib.items():
            name = svg_local_name(raw_name)
            lower = raw_value.lower()
            if name in SAFE_TRACED_ATTRIBUTES and "url(" not in lower and "javascript:" not in lower:
                target.set(name, raw_value)
        for child in source:
            cleaned = clean(child)
            if cleaned is not None:
                target.append(cleaned)
        return target

    try:
        children = [clean(child) for child in root]
    except ValueError:
        return None
    allowed = [child for child in children if child is not None]
    if not allowed or element_count == 0:
        return None
    markup = "".join(ET.tostring(child, encoding="unicode") for child in allowed)
    return markup, view_box_values, element_count


def draw_traced_decorative(
    config: dict[str, Any],
    outputs_dir: Path | None,
    x: float,
    y: float,
    width: float,
    height: float,
) -> str | None:
    if outputs_dir is None or config.get("render_mode") != "vtracer_inline":
        return None
    relative_path = safe_generated_vector_path(config.get("vector_path"))
    expected_sha256 = str(config.get("vector_sha256", "") or "")
    if not relative_path:
        return None
    loaded = load_safe_traced_svg(str(outputs_dir / relative_path), expected_sha256)
    if not loaded:
        return None
    markup, (view_x, view_y, view_width, view_height), element_count = loaded
    scale = min(width / view_width, height / view_height)
    draw_width = view_width * scale
    draw_height = view_height * scale
    translate_x = x + (width - draw_width) / 2 - view_x * scale
    translate_y = y + (height - draw_height) / 2 - view_y * scale
    return (
        f'<g data-vectorizer="vtracer" data-vector-elements="{element_count}" '
        f'transform="translate({translate_x:.4f} {translate_y:.4f}) scale({scale:.6f})">'
        f'{markup}</g>'
    )


def get_section(content: dict[str, Any], key: str) -> dict[str, Any]:
    section = content.get(key)
    if isinstance(section, dict):
        return section
    return {"heading": key.replace("_", " ").title(), "bullets": []}


def section_bullets(content: dict[str, Any], key: str) -> list[str]:
    section = get_section(content, key)
    bullets = section.get("bullets", [])
    if not isinstance(bullets, list):
        return []
    return [clean_space(str(bullet)) for bullet in bullets if clean_space(str(bullet))]


def draw_decorative_icon(concept: str, cx: float, cy: float, radius: float, stroke: str, accent: str) -> str:
    r = max(6.0, radius)
    sw = max(1.2, r * 0.09)
    parts = [
        f'<g data-concept="{escape(concept)}" fill="none" stroke="{stroke}" stroke-width="{sw:.2f}" stroke-linecap="round" stroke-linejoin="round">',
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" stroke-opacity="0.72"/>',
    ]
    if concept == "reasoning":
        nodes = [(cx, cy - r * 0.46), (cx - r * 0.48, cy - r * 0.05), (cx + r * 0.48, cy - r * 0.05), (cx - r * 0.30, cy + r * 0.48), (cx + r * 0.30, cy + r * 0.48)]
        for x1, y1 in nodes:
            parts.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x1:.1f}" y2="{y1:.1f}"/>')
            parts.append(f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="{max(1.8, r * 0.11):.1f}" fill="{stroke}" stroke="none"/>')
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{max(2.0, r * 0.13):.1f}" fill="{stroke}" stroke="none"/>')
    elif concept == "observation":
        parts.append(f'<path d="M {cx-r*0.48:.1f} {cy+r*0.10:.1f} C {cx-r*0.68:.1f} {cy-r*0.18:.1f}, {cx-r*0.38:.1f} {cy-r*0.48:.1f}, {cx-r*0.12:.1f} {cy-r*0.36:.1f} C {cx+r*0.10:.1f} {cy-r*0.62:.1f}, {cx+r*0.54:.1f} {cy-r*0.40:.1f}, {cx+r*0.48:.1f} {cy-r*0.08:.1f} C {cx+r*0.70:.1f} {cy+r*0.18:.1f}, {cx+r*0.40:.1f} {cy+r*0.42:.1f}, {cx+r*0.08:.1f} {cy+r*0.34:.1f} L {cx-r*0.22:.1f} {cy+r*0.34:.1f} C {cx-r*0.48:.1f} {cy+r*0.36:.1f}, {cx-r*0.62:.1f} {cy+r*0.24:.1f}, {cx-r*0.48:.1f} {cy+r*0.10:.1f} Z"/>')
        for dx, dy in [(-0.28, 0.60), (0.0, 0.70), (0.28, 0.60)]:
            parts.append(f'<circle cx="{cx+r*dx:.1f}" cy="{cy+r*dy:.1f}" r="{max(1.4, r*0.08):.1f}" fill="{stroke}" stroke="none"/>')
    elif concept == "tool":
        parts.append(f'<path d="M {cx-r*0.48:.1f} {cy+r*0.45:.1f} L {cx+r*0.32:.1f} {cy-r*0.35:.1f} M {cx-r*0.48:.1f} {cy-r*0.34:.1f} L {cx+r*0.42:.1f} {cy+r*0.48:.1f}"/>')
        parts.append(f'<circle cx="{cx-r*0.48:.1f}" cy="{cy+r*0.45:.1f}" r="{r*0.10:.1f}"/>')
        parts.append(f'<path d="M {cx+r*0.20:.1f} {cy-r*0.48:.1f} Q {cx+r*0.54:.1f} {cy-r*0.58:.1f} {cx+r*0.50:.1f} {cy-r*0.22:.1f} L {cx+r*0.30:.1f} {cy-r*0.04:.1f}"/>')
    elif concept == "action":
        parts.append(f'<path d="M {cx:.1f} {cy-r*0.50:.1f} V {cy-r*0.10:.1f} M {cx-r*0.48:.1f} {cy+r*0.42:.1f} V {cy+r*0.12:.1f} H {cx+r*0.48:.1f} V {cy+r*0.42:.1f} M {cx:.1f} {cy-r*0.10:.1f} V {cy+r*0.42:.1f}"/>')
        for x1, y1 in [(cx, cy-r*0.58), (cx-r*0.48, cy+r*0.54), (cx, cy+r*0.54), (cx+r*0.48, cy+r*0.54)]:
            parts.append(f'<rect x="{x1-r*0.10:.1f}" y="{y1-r*0.08:.1f}" width="{r*0.20:.1f}" height="{r*0.16:.1f}" rx="{r*0.04:.1f}"/>')
    else:
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r*0.78:.1f}" fill="{accent}" stroke="none"/>')
        parts.append(f'<path d="M {cx-r*0.38:.1f} {cy:.1f} L {cx-r*0.10:.1f} {cy+r*0.28:.1f} L {cx+r*0.42:.1f} {cy-r*0.30:.1f}" stroke="#ffffff" stroke-width="{sw*1.35:.2f}"/>')
    parts.append("</g>")
    return "".join(parts)


def draw_process_sequence(
    config: dict[str, Any],
    colors: dict[str, Any],
    include_card: bool = False,
    outputs_dir: Path | None = None,
) -> str:
    if not isinstance(config, dict) or not config.get("enabled"):
        return ""
    x = float(config.get("x", 0))
    y = float(config.get("y", 0))
    width = float(config.get("width", 0))
    height = float(config.get("height", 0))
    concepts = [clean_space(value) for value in config.get("concepts", []) if clean_space(value)][:5]
    if width <= 0 or height <= 0 or not concepts:
        return ""
    parts = ['<g class="generated-decorative" data-asset-class="generated_decorative" aria-hidden="true">']
    if include_card:
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" rx="{min(12.0, height*0.18):.1f}" fill="{colors["panel"]}" stroke="{colors["panel_stroke"]}"/>')
    traced = draw_traced_decorative(config, outputs_dir, x, y, width, height)
    if traced:
        parts.append(traced)
        parts.append("</g>")
        return "\n".join(parts)
    padding = max(10.0, height * 0.18)
    inner_width = max(1.0, width - 2 * padding)
    step = inner_width / max(1, len(concepts))
    radius = min(height * 0.28, step * 0.24)
    cy = y + height / 2
    centers = [x + padding + step * (index + 0.5) for index in range(len(concepts))]
    for index, (concept, cx) in enumerate(zip(concepts, centers)):
        if index:
            previous = centers[index - 1]
            start = previous + radius + step * 0.08
            end = cx - radius - step * 0.08
            parts.append(f'<line x1="{start:.1f}" y1="{cy:.1f}" x2="{end:.1f}" y2="{cy:.1f}" stroke="{colors["header_muted"]}" stroke-width="1.5" stroke-opacity="0.72"/>')
            parts.append(f'<path d="M {end-4:.1f} {cy-3.5:.1f} L {end:.1f} {cy:.1f} L {end-4:.1f} {cy+3.5:.1f}" fill="none" stroke="{colors["header_muted"]}" stroke-width="1.5"/>')
        icon_stroke = colors["accent_result"] if concept == "verification" else colors["header_muted"]
        parts.append(draw_decorative_icon(concept, cx, cy, radius, str(icon_stroke), str(colors["accent_secondary"])))
    parts.append("</g>")
    return "\n".join(parts)


def draw_header(
    content: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    canvas_w: int,
    typography: dict[str, Any],
    colors: dict[str, Any],
    design: dict[str, Any],
    outputs_dir: Path | None = None,
) -> str:
    title = clean_space(content.get("title", "Untitled Paper"))
    authors = content.get("authors", [])
    affiliations = content.get("affiliations", [])
    authors_text = "; ".join(clean_space(author) for author in authors[:4]) if isinstance(authors, list) else ""
    affiliations_text = "; ".join(clean_space(aff) for aff in affiliations[:2]) if isinstance(affiliations, list) else ""
    hero_message = clean_space(design.get("hero_message", "") or content.get("take_home_message", ""))
    decorations = design.get("decorations") if isinstance(design.get("decorations"), dict) else {}
    header_process = decorations.get("header_process") if isinstance(decorations.get("header_process"), dict) else {}
    process_enabled = bool(header_process.get("enabled"))

    title_size = float(typography.get("title", 32))
    title_line_h = title_size * 1.08
    header_bottom = max(70.0, y + height - 8.0)
    rounded = bool(decorations.get("header_rounded"))
    header_inset = max(10.0, x * 0.45) if rounded else 0.0
    header_y = 6.0 if rounded else 0.0
    parts = ['<g id="header">']
    parts.append(f'<rect x="{header_inset:.1f}" y="{header_y:.1f}" width="{canvas_w-2*header_inset:.1f}" height="{header_bottom-header_y:.1f}" rx="{14 if rounded else 0}" fill="{colors["header_background"]}"/>')
    if decorations.get("accent_rule"):
        parts.append(f'<rect x="{x:.1f}" y="{header_bottom + 4:.1f}" width="{width:.1f}" height="3.2" fill="{colors["accent_result"]}"/>')

    title_width = width * (0.56 if process_enabled else 0.72)
    title_lines = wrap_text(title, title_width, title_size, max_lines=2)
    title_y = y + 28
    for i, line in enumerate(title_lines):
        parts.append(
            f'<text class="title-light" x="{x:.1f}" y="{title_y + i * title_line_h:.1f}" font-weight="700" font-size="{title_size:.1f}" fill="{colors["header_text"]}">{escape(line)}</text>'
        )

    meta_y = min(title_y + title_line_h * len(title_lines) + 12, header_bottom - 10)
    if authors_text:
        author_size = 9.5 if process_enabled else float(typography.get("authors", 13))
        author_svg, meta_y = svg_text_lines(
            authors_text,
            x,
            meta_y,
            title_width,
            author_size,
            author_size * 1.25,
            "authors-light",
            max_lines=1 if process_enabled else 2,
            fill=str(colors["header_muted"]),
        )
        parts.append(author_svg)
    if affiliations_text:
        aff_svg, _ = svg_text_lines(
            affiliations_text,
            x,
            meta_y + 2,
            width * 0.7,
            9.5,
            12.5,
            "muted-light",
            max_lines=1,
            fill=str(colors["header_muted"]),
        )
        parts.append(aff_svg)

    if process_enabled:
        process_config = {
            **header_process,
            "x": x + width * 0.60,
            "y": y + 19,
            "width": width * 0.38,
            "height": max(52.0, header_bottom - 34),
        }
        parts.append(draw_process_sequence(process_config, colors, include_card=False, outputs_dir=outputs_dir))
    elif hero_message:
        callout_w = width * 0.28
        callout_x = x + width - callout_w
        callout_y = y + 18
        callout_h = max(68, height - 36)
        parts.append(
            f'<rect x="{callout_x:.1f}" y="{callout_y:.1f}" width="{callout_w:.1f}" height="{callout_h:.1f}" rx="8" fill="#ffffff" opacity="0.10" stroke="#ffffff" stroke-opacity="0.20"/>'
        )
        parts.append(
            f'<text class="eyebrow-light" x="{callout_x + 16:.1f}" y="{callout_y + 22:.1f}" font-weight="700" font-size="8.8" fill="{colors["header_muted"]}">TAKE-HOME</text>'
        )
        msg_svg, _ = svg_text_lines(
            hero_message,
            callout_x + 16,
            callout_y + 43,
            callout_w - 32,
            12.5,
            16,
            "hero-message",
            max_lines=3,
            fill=str(colors["header_text"]),
        )
        parts.append(msg_svg)

    parts.append("</g>")
    return "\n".join(parts)


def draw_section_label(label: str, x: float, y: float, accent: str, colors: dict[str, Any]) -> str:
    text_w = max(58, estimate_text_width(label.upper(), 8.6) + 18)
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{text_w:.1f}" height="18" rx="9" fill="{accent}" opacity="0.12"/>'
        f'<text class="eyebrow" x="{x + 9:.1f}" y="{y + 12.2:.1f}" font-weight="700" font-size="8.6" fill="{accent}">{escape(label.upper())}</text>'
    )


def draw_result_callouts(
    callouts: list[dict[str, Any]],
    x: float,
    y: float,
    width: float,
    colors: dict[str, Any],
    typography: dict[str, Any],
    callout_style: dict[str, Any] | None = None,
) -> tuple[str, float]:
    valid = [item for item in callouts if isinstance(item, dict)][:3]
    if not valid:
        return "", y

    callout_style = callout_style if isinstance(callout_style, dict) else {}
    callout_h = float(callout_style.get("height", 74) or 74)
    value_min_size = float(callout_style.get("value_min_font_size", 7.4) or 7.4)
    value_max_size = float(callout_style.get("value_max_font_size", 18.0) or 18.0)
    label_min_size = float(callout_style.get("label_min_font_size", 6.2) or 6.2)
    label_max_size = float(callout_style.get("label_max_font_size", 8.5) or 8.5)
    detail_scale = float(callout_style.get("detail_font_scale", 1.0) or 1.0)
    detail_lines = int(callout_style.get("detail_lines", 2) or 2)

    gap = 8
    box_w = (width - gap * (len(valid) - 1)) / len(valid)
    parts: list[str] = []
    for index, item in enumerate(valid):
        box_x = x + index * (box_w + gap)
        label = clean_space(item.get("label", "Evidence"))
        value = clean_space(item.get("value", ""))
        detail = clean_space(item.get("detail", ""))
        value_size = min(value_max_size, max(value_min_size, (box_w - 24) / max(1, len(value)) / 0.52))
        label_size = min(label_max_size, max(label_min_size, (box_w - 24) / max(1, len(label.upper())) / 0.52))
        detail_size = float(typography.get("caption", 8.2)) * detail_scale
        parts.append(
            f'<g id="result-callout-{index + 1}">'
            f'<rect x="{box_x:.1f}" y="{y:.1f}" width="{box_w:.1f}" height="{callout_h:.1f}" rx="7" fill="{colors["highlight_background"]}" stroke="{colors["accent_result"]}" stroke-opacity="0.28"/>'
        )
        parts.append(f'<text class="callout-label" x="{box_x + 10:.1f}" y="{y + 17:.1f}" font-weight="700" fill="{colors["accent_result"]}" font-size="{label_size:.1f}">{escape(label.upper())}</text>')
        parts.append(f'<text class="callout-value" x="{box_x + 10:.1f}" y="{y + 40:.1f}" font-weight="700" fill="{colors["accent_result"]}" font-size="{value_size:.1f}">{escape(value)}</text>')
        detail_svg, _ = svg_text_lines(
            detail,
            box_x + 10,
            y + 57,
            box_w - 20,
            detail_size,
            detail_size * 1.28,
            "caption",
            max_lines=detail_lines,
            fill=str(colors["muted"]),
        )
        parts.append(detail_svg)
        parts.append("</g>")

    return "\n".join(parts), y + callout_h + 12


def draw_panel(
    section_id: str,
    heading: str,
    bullets: list[str],
    x: float,
    y: float,
    width: float,
    height: float,
    accent: str = "#2563eb",
    max_bullets: int = 5,
    typography: dict[str, Any] | None = None,
    colors: dict[str, Any] | None = None,
    card_style: dict[str, Any] | None = None,
    variant: str = "standard",
    callouts: list[dict[str, Any]] | None = None,
    callout_style: dict[str, Any] | None = None,
    content_bottom: float | None = None,
    panel_fill: str | None = None,
    title_size_override: float | None = None,
    body_size_override: float | None = None,
    line_height_ratio_override: float | None = None,
    content_width_override: float | None = None,
    wrapped_bullets: list[list[str] | None] | None = None,
) -> str:
    typography = merged_dict(DEFAULT_TYPOGRAPHY, typography)
    colors = merged_dict(DEFAULT_COLORS, colors)
    card_style = merged_dict(DEFAULT_CARD_STYLE, card_style)
    w = width
    h = height
    radius = float(card_style.get("radius", 8))
    padding_x = float(card_style.get("padding_x", 20))
    accent_w = float(card_style.get("accent_bar_width", 6))
    stroke_w = float(card_style.get("stroke_width", 1.1))
    shadow_opacity = float(card_style.get("shadow_opacity", 0.22))
    title_size = float(title_size_override or typography.get("section_title", 18))
    body_size = float(body_size_override or typography.get("body", 11.5))
    body_line = body_size * float(line_height_ratio_override or typography.get("line_height_ratio", 1.3))
    content_width = min(
        w - padding_x * 2,
        max(80.0, float(content_width_override)) if content_width_override is not None else w - padding_x * 2,
    )
    text_limit = min(y + h - 14, content_bottom) if content_bottom is not None else y + h - 14
    title_y = y + 35 if variant == "hero" else y + 31
    parts = [
        f'<g id="{escape(section_id)}">',
        f'<rect x="{x + 2.2:.1f}" y="{y + 3.0:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{radius:.1f}" fill="#91a4bd" opacity="{shadow_opacity:.2f}"/>',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{radius:.1f}" fill="{panel_fill or colors["panel"]}" stroke="{colors["panel_stroke"]}" stroke-width="{stroke_w:.1f}"/>',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{accent_w:.1f}" rx="{min(radius, 3):.1f}" fill="{accent}"/>',
        draw_section_label(heading, x + padding_x, y + 15, accent, colors),
    ]
    if variant == "hero":
        parts.append(
            f'<text class="section-title" x="{x + padding_x:.1f}" y="{title_y + 18:.1f}" font-weight="700" font-size="{title_size + 2:.1f}" fill="{colors["text"]}">{escape(heading)}</text>'
        )
        current_y = title_y + 34
        if callouts:
            callout_svg, current_y = draw_result_callouts(callouts, x + padding_x, current_y, content_width, colors, typography, callout_style)
            parts.append(callout_svg)
    else:
        parts.append(
            f'<text class="section-title" x="{x + padding_x:.1f}" y="{title_y + 18:.1f}" font-weight="700" font-size="{title_size:.1f}" fill="{colors["text"]}">{escape(heading)}</text>'
        )
        current_y = title_y + 38

    for bullet_index, bullet in enumerate(bullets[:max_bullets]):
        max_lines = 2 if variant in {"compact", "hero"} else 3
        supplied_lines = None
        if wrapped_bullets is not None and bullet_index < len(wrapped_bullets):
            candidate = wrapped_bullets[bullet_index]
            if candidate is not None and len(candidate) <= max_lines and lines_preserve_text(bullet, candidate):
                supplied_lines = candidate
        projected_lines = supplied_lines or wrap_text(bullet, content_width, body_size, max_lines=max_lines)
        if current_y + body_line * len(projected_lines) > text_limit:
            break
        text_svg, current_y = svg_text_lines(
            bullet,
            x + padding_x + 2,
            current_y,
            content_width,
            font_size=body_size,
            line_height=body_line,
            css_class="body",
            max_lines=max_lines,
            bullet=True,
            wrapped_lines=supplied_lines,
        )
        parts.append(text_svg)
        current_y += 5
        if current_y > text_limit:
            break

    parts.append("</g>")
    return "\n".join(parts)


def draw_figure_panel(
    content: dict[str, Any],
    outputs_dir: Path,
    x: float,
    y: float,
    width: float,
    height: float,
    typography: dict[str, Any] | None = None,
    colors: dict[str, Any] | None = None,
    card_style: dict[str, Any] | None = None,
    image_config: dict[str, Any] | None = None,
) -> str:
    typography = merged_dict(DEFAULT_TYPOGRAPHY, typography)
    colors = merged_dict(DEFAULT_COLORS, colors)
    card_style = merged_dict(DEFAULT_CARD_STYLE, card_style)
    image_config = image_config if isinstance(image_config, dict) else {}
    w = width
    h = height
    figures = content.get("figures_to_use", [])
    max_figures = int(image_config.get("max_figures", 2) or 2)
    selected = figures[:max_figures] if isinstance(figures, list) else []
    radius = float(card_style.get("radius", 8))
    stroke_w = float(card_style.get("stroke_width", 1.1))
    shadow_opacity = float(card_style.get("shadow_opacity", 0.22))
    title_size = float(typography.get("section_title", 18))
    parts = [
        '<g id="key-figure">',
        f'<rect x="{x + 2.2:.1f}" y="{y + 3.0:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{radius:.1f}" fill="#91a4bd" opacity="{shadow_opacity:.2f}"/>',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{radius:.1f}" fill="{colors["panel"]}" stroke="{colors["panel_stroke"]}" stroke-width="{stroke_w:.1f}"/>',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="6" rx="{min(radius, 3):.1f}" fill="{colors["accent_secondary"]}"/>',
        draw_section_label("Key Figures", x + 18, y + 15, str(colors["accent_secondary"]), colors),
        f'<text class="section-title" x="{x + 18:.1f}" y="{y + 54:.1f}" font-weight="700" font-size="{title_size:.1f}" fill="{colors["text"]}">Key Figures</text>',
    ]

    if selected:
        gap = 14
        slot_count = len(selected)
        slot_h = (h - 82 - gap * (slot_count - 1)) / slot_count
        for index, figure in enumerate(selected):
            if not isinstance(figure, dict):
                continue
            slot_y = y + 70 + index * (slot_h + gap)
            slot_id = "primary-figure" if index == 0 else "secondary-figure"
            role = clean_space(figure.get("role", "")).replace("_", " ").title()
            title = role or ("Primary Figure" if index == 0 else "Supporting Figure")
            parts.append(f'<g id="{slot_id}">')
            parts.append(f'<text class="muted" x="{x + 18:.1f}" y="{slot_y + 10:.1f}" fill="{colors["muted"]}" font-size="9">{escape(title)}</text>')
            parts.append(draw_figure_item(figure, outputs_dir, x + 18, slot_y + 16, w - 36, slot_h - 18, typography, colors, image_config))
            parts.append("</g>")
    else:
        parts.append(
            f'<text class="muted" x="{x + 22:.1f}" y="{y + 65:.1f}" fill="{colors["muted"]}" font-size="12">No extracted figure available.</text>'
        )

    parts.append("</g>")
    return "\n".join(parts)


def draw_figure_item(
    figure: dict[str, Any],
    outputs_dir: Path,
    x: float,
    y: float,
    width: float,
    height: float,
    typography: dict[str, Any] | None = None,
    colors: dict[str, Any] | None = None,
    image_config: dict[str, Any] | None = None,
) -> str:
    typography = merged_dict(DEFAULT_TYPOGRAPHY, typography)
    colors = merged_dict(DEFAULT_COLORS, colors)
    image_config = image_config if isinstance(image_config, dict) else {}
    parts: list[str] = []
    if isinstance(figure, dict):
        asset = clean_space(figure.get("asset_path", ""))
        caption = clean_space(figure.get("caption", "") or figure.get("text", ""))
        image_data = None
        if asset:
            image_data = image_to_data_uri(outputs_dir / asset)

        if image_data:
            img_x = x
            img_y = y
            img_w = width
            caption_lines = int(image_config.get("caption_lines", 2) or 2)
            caption_size = float(typography.get("caption", 8.8))
            caption_line = caption_size * float(typography.get("line_height_ratio", 1.3))
            img_h = max(45.0, height - caption_line * caption_lines - 9)
            parts.append(
                f'<rect x="{img_x:.1f}" y="{img_y:.1f}" width="{img_w:.1f}" height="{img_h:.1f}" rx="6" fill="{colors["figure_background"]}" stroke="{colors["panel_stroke"]}"/>'
            )
            parts.append(
                f'<image x="{img_x:.1f}" y="{img_y:.1f}" width="{img_w:.1f}" height="{img_h:.1f}" href="{image_data}" preserveAspectRatio="{escape(str(image_config.get("preserve_aspect_ratio", "xMidYMid meet")))}"/>'
            )
            cap_svg, _ = svg_text_lines(
                caption,
                x,
                y + img_h + 11,
                width,
                font_size=caption_size,
                line_height=caption_line,
                css_class="caption",
                max_lines=caption_lines,
                fill=str(colors["muted"]),
            )
            parts.append(cap_svg)
        elif caption:
            cap_svg, _ = svg_text_lines(
                caption,
                x,
                y + 13,
                width,
                font_size=11,
                line_height=15,
                css_class="body",
                max_lines=5,
            )
            parts.append(cap_svg)
        else:
            parts.append(
                f'<text class="muted" x="{x:.1f}" y="{y + 18:.1f}" fill="{colors["muted"]}" font-size="12">No usable figure asset was selected.</text>'
            )
    else:
        parts.append(
            f'<text class="muted" x="{x:.1f}" y="{y + 18:.1f}" fill="{colors["muted"]}" font-size="12">No extracted figure available.</text>'
        )

    return "\n".join(parts)


def verified_claim_texts(content: dict[str, Any], claim_ids: list[str], budget: int) -> list[str]:
    return [text for _claim_id, text in verified_claim_entries(content, claim_ids, budget)]


def verified_claim_entries(content: dict[str, Any], claim_ids: list[str], budget: int) -> list[tuple[str, str]]:
    catalog: dict[str, dict[str, Any]] = {}
    for item in content.get("poster_claims", []):
        if not isinstance(item, dict) or item.get("evidence_status") != "verified":
            continue
        refs = item.get("source_refs", [])
        if not isinstance(refs, list) or not any(
            isinstance(ref, dict) and ref.get("verification_status") == "verified" and ref.get("page")
            for ref in refs
        ):
            continue
        claim_id = clean_space(item.get("id", ""))
        if claim_id:
            catalog[claim_id] = item
    entries: list[tuple[str, str]] = []
    for claim_id in claim_ids:
        normalized_id = clean_space(claim_id)
        item = catalog.get(normalized_id)
        text = clean_space(item.get("claim", "")) if item else ""
        if text and all(existing_text != text for _existing_id, existing_text in entries):
            entries.append((normalized_id, text))
        if len(entries) >= budget:
            break
    return entries


def validated_typesetting_sections(
    content: dict[str, Any],
    design: dict[str, Any],
    manifest: dict[str, Any] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    if not manifest:
        return {}
    if manifest.get("content_sha256") != canonical_json_sha256(content):
        raise ValueError("Typesetting manifest does not match poster content")
    if manifest.get("design_sha256") != canonical_json_sha256(design):
        raise ValueError("Typesetting manifest does not match poster design")
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for section in manifest.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_id = clean_space(section.get("section_id", ""))
        if not section_id:
            continue
        result[section_id] = {
            clean_space(entry.get("claim_id", "")): entry
            for entry in section.get("entries", [])
            if isinstance(entry, dict) and clean_space(entry.get("claim_id", ""))
        }
    return result


def source_figure_catalog(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for item in content.get("figures_to_use", []):
        if not isinstance(item, dict):
            continue
        figure_id = clean_space(item.get("id", ""))
        asset_path = clean_space(item.get("asset_path", "")).replace("\\", "/")
        asset_class = clean_space(item.get("asset_class", "source_evidence")) or "source_evidence"
        if figure_id and asset_class == "source_evidence" and not asset_path.startswith("assets/generated/"):
            catalog[figure_id] = item
    return catalog


def build_source_asset_manifest(
    content: dict[str, Any],
    outputs_dir: Path,
    design: dict[str, Any],
) -> list[dict[str, Any]]:
    catalog = source_figure_catalog(content)
    explicit_sections = design.get("sections") if isinstance(design.get("sections"), list) else []
    if explicit_sections:
        included_ids = [
            clean_space(slot.get("figure_id", ""))
            for section in explicit_sections if isinstance(section, dict)
            for slot in section.get("figure_slots", []) if isinstance(slot, dict)
            and clean_space(slot.get("figure_id", ""))
        ]
    else:
        included_ids = list(catalog)[:2]
    manifest: list[dict[str, Any]] = []
    for figure_id in dict.fromkeys(included_ids):
        figure = catalog.get(figure_id)
        if not figure:
            continue
        relative_path = clean_space(figure.get("asset_path", "")).replace("\\", "/")
        asset_path = outputs_dir / relative_path
        manifest.append({
            "id": figure_id,
            "asset_class": "source_evidence",
            "included": True,
            "source_page": figure.get("page"),
            "caption": clean_space(figure.get("caption", "") or figure.get("text", "")),
            "asset_path": relative_path,
            "sha256": file_sha256(asset_path) if asset_path.is_file() else None,
            "embedding": "data_uri" if asset_path.is_file() else "missing",
            "preserve_aspect_ratio": "xMidYMid meet",
            "scientific_meaning": "unchanged source figure",
        })
    return manifest


def section_accent(section_id: str, visual_role: str, colors: dict[str, Any]) -> str:
    if visual_role == "hero" or section_id == "results":
        return str(colors["accent_result"])
    if section_id in {"method", "theoretical_foundation"}:
        return str(colors["accent_secondary"])
    if section_id in {"core_idea", "innovation"}:
        return str(colors["accent_idea"])
    if section_id in {"contribution", "significance"}:
        return str(colors["accent_contribution"])
    if section_id in {"conclusion", "limitations"}:
        return str(colors["accent_neutral"])
    return str(colors["accent_primary"])


def draw_art_directed_section(
    content: dict[str, Any],
    outputs_dir: Path,
    section: dict[str, Any],
    typography: dict[str, Any],
    colors: dict[str, Any],
    card_style: dict[str, Any],
    image_config: dict[str, Any],
    result_callouts: list[dict[str, Any]],
    callout_style: dict[str, Any],
    typesetting_entries: dict[str, dict[str, Any]] | None = None,
) -> str:
    section_id = clean_space(section.get("section_id", "section"))
    heading = clean_space(section.get("heading", section_id.replace("_", " ").title()))
    claim_ids = section.get("claim_ids", []) if isinstance(section.get("claim_ids"), list) else []
    budget = max(1, min(5, int(section.get("bullet_budget", 3) or 3)))
    claim_entries = verified_claim_entries(content, [clean_space(value) for value in claim_ids], budget)
    bullets = [text for _claim_id, text in claim_entries]
    supplied_wrapping: list[list[str] | None] = []
    typesetting_entries = typesetting_entries or {}
    for claim_id, text in claim_entries:
        entry = typesetting_entries.get(claim_id, {})
        lines = entry.get("wrapped_lines") if clean_space(entry.get("text", "")) == text else None
        supplied_wrapping.append(lines if lines_preserve_text(text, lines) else None)
    slots = section.get("figure_slots", []) if isinstance(section.get("figure_slots"), list) else []
    first_slot_y = min((float(slot.get("y", 0)) for slot in slots if isinstance(slot, dict)), default=None)
    side_slots = [
        slot for slot in slots if isinstance(slot, dict)
        and float(slot.get("x", 0)) >= float(section.get("x", 0)) + float(section.get("width", 0)) * 0.42
        and float(slot.get("y", 0)) <= float(section.get("y", 0)) + 90
    ]
    side_content_width = None
    if side_slots:
        padding_x = float(card_style.get("padding_x", 20) or 20)
        side_content_width = max(
            120.0,
            min(float(slot.get("x", 0)) for slot in side_slots) - float(section.get("x", 0)) - padding_x * 2,
        )
    title_style = section.get("title_style") if isinstance(section.get("title_style"), dict) else {}
    body_style = section.get("body_style") if isinstance(section.get("body_style"), dict) else {}
    visual_role = clean_space(section.get("visual_role", "supporting"))
    panel = draw_panel(
        section_id.replace("_", "-"),
        heading,
        bullets,
        float(section["x"]),
        float(section["y"]),
        float(section["width"]),
        float(section["height"]),
        accent=section_accent(section_id, visual_role, colors),
        max_bullets=budget,
        typography=typography,
        colors=colors,
        card_style=card_style,
        variant="hero" if visual_role == "hero" else "standard",
        callouts=result_callouts if section_id == "results" and visual_role == "hero" else None,
        callout_style=callout_style,
        content_bottom=(first_slot_y - 10 if first_slot_y is not None and not side_slots else None),
        panel_fill=str(section.get("background") or colors["panel"]),
        title_size_override=float(title_style.get("font_size", typography.get("section_title", 16.5))),
        body_size_override=float(body_style.get("font_size", typography.get("body", 10.8))),
        line_height_ratio_override=float(body_style.get("line_height_ratio", typography.get("line_height_ratio", 1.3))),
        content_width_override=side_content_width,
        wrapped_bullets=supplied_wrapping,
    )
    figures = source_figure_catalog(content)
    parts = [panel]
    for index, slot in enumerate(slots, start=1):
        if not isinstance(slot, dict):
            continue
        figure_id = clean_space(slot.get("figure_id", ""))
        figure = figures.get(figure_id)
        if not figure:
            continue
        parts.append(f'<g id="figure-slot-{escape(section_id)}-{index}">')
        parts.append(draw_figure_item(
            figure,
            outputs_dir,
            float(slot["x"]),
            float(slot["y"]),
            float(slot["width"]),
            float(slot["height"]),
            typography,
            colors,
            {**image_config, "preserve_aspect_ratio": "xMidYMid meet"},
        ))
        parts.append("</g>")
    return "\n".join(parts)


def require_explicit_source_assets(
    content: dict[str, Any],
    outputs_dir: Path,
    sections: list[dict[str, Any]],
) -> None:
    figures = source_figure_catalog(content)
    for section in sections:
        for slot in section.get("figure_slots", []):
            if not isinstance(slot, dict):
                continue
            figure_id = clean_space(slot.get("figure_id", ""))
            figure = figures.get(figure_id)
            if not figure:
                raise ValueError(f"Explicit design references an unknown or non-evidence figure: {figure_id or '[empty]'}")
            asset_path = clean_space(figure.get("asset_path", ""))
            if not asset_path or not (outputs_dir / asset_path).is_file():
                raise ValueError(f"Explicit design source figure asset is missing: {figure_id} ({asset_path or 'no path'})")


def template_boxes(
    template: str,
    margin: float,
    column_w: float,
    gutter: float,
    body_y: float,
    body_h: float,
    canvas_w: int,
    canvas_h: int,
    footer_h: float,
    header_h: float,
) -> dict[str, dict[str, float]]:
    col1_x = margin
    col2_x = margin + column_w + gutter
    col3_x = margin + 2 * (column_w + gutter)
    footer_box = {"x": margin, "y": canvas_h - footer_h, "width": canvas_w - 2 * margin, "height": footer_h - 8}
    header_box = {"x": margin, "y": 0, "width": canvas_w - 2 * margin, "height": header_h + 8}

    if template == "result_centered":
        return {
            "header": header_box,
            "problem": {"x": col1_x, "y": body_y, "width": column_w, "height": 168},
            "core_idea": {"x": col1_x, "y": body_y + 186, "width": column_w, "height": body_h - 186},
            "method": {"x": col2_x, "y": body_y, "width": column_w, "height": 190},
            "key-figure": {"x": col2_x, "y": body_y + 208, "width": column_w, "height": body_h - 208},
            "results": {"x": col3_x, "y": body_y, "width": column_w, "height": 336},
            "contribution": {"x": col3_x, "y": body_y + 354, "width": column_w, "height": 152},
            "conclusion": {"x": col3_x, "y": body_y + 524, "width": column_w, "height": body_h - 524},
            "footer": footer_box,
        }

    if template == "method_centered":
        return {
            "header": header_box,
            "problem": {"x": col1_x, "y": body_y, "width": column_w, "height": 178},
            "core_idea": {"x": col1_x, "y": body_y + 196, "width": column_w, "height": body_h - 196},
            "method": {"x": col2_x, "y": body_y, "width": column_w, "height": 270},
            "key-figure": {"x": col2_x, "y": body_y + 288, "width": column_w, "height": body_h - 288},
            "results": {"x": col3_x, "y": body_y, "width": column_w, "height": 238},
            "contribution": {"x": col3_x, "y": body_y + 256, "width": column_w, "height": 182},
            "conclusion": {"x": col3_x, "y": body_y + 456, "width": column_w, "height": body_h - 456},
            "footer": footer_box,
        }

    if template == "case_study":
        return {
            "header": header_box,
            "problem": {"x": col1_x, "y": body_y, "width": column_w, "height": 158},
            "core_idea": {"x": col1_x, "y": body_y + 176, "width": column_w, "height": 184},
            "method": {"x": col1_x, "y": body_y + 378, "width": column_w, "height": body_h - 378},
            "key-figure": {"x": col2_x, "y": body_y, "width": column_w, "height": body_h},
            "results": {"x": col3_x, "y": body_y, "width": column_w, "height": 272},
            "contribution": {"x": col3_x, "y": body_y + 290, "width": column_w, "height": 168},
            "conclusion": {"x": col3_x, "y": body_y + 476, "width": column_w, "height": body_h - 476},
            "footer": footer_box,
        }

    if template == "text_fallback":
        return {
            "header": header_box,
            "problem": {"x": col1_x, "y": body_y, "width": column_w, "height": 190},
            "core_idea": {"x": col1_x, "y": body_y + 208, "width": column_w, "height": body_h - 208},
            "method": {"x": col2_x, "y": body_y, "width": column_w, "height": 300},
            "key-figure": {"x": col2_x, "y": body_y + 318, "width": column_w, "height": body_h - 318},
            "results": {"x": col3_x, "y": body_y, "width": column_w, "height": 300},
            "contribution": {"x": col3_x, "y": body_y + 318, "width": column_w, "height": 164},
            "conclusion": {"x": col3_x, "y": body_y + 500, "width": column_w, "height": body_h - 500},
            "footer": footer_box,
        }

    return template_boxes(
        "method_centered",
        margin,
        column_w,
        gutter,
        body_y,
        body_h,
        canvas_w,
        canvas_h,
        footer_h,
        header_h,
    )


def build_component_boxes(
    boxes: dict[str, dict[str, float]],
    design: dict[str, Any],
    card_style: dict[str, Any],
) -> dict[str, dict[str, float]]:
    component_boxes: dict[str, dict[str, float]] = {}
    explicit_sections = design.get("sections")
    if isinstance(explicit_sections, list):
        for section in explicit_sections:
            if not isinstance(section, dict):
                continue
            section_id = clean_space(section.get("section_id", "section"))
            for index, slot in enumerate(section.get("figure_slots", []), start=1):
                if not isinstance(slot, dict):
                    continue
                component_boxes[f"figure-slot-{section_id}-{index}"] = {
                    "x": float(slot.get("x", 0)),
                    "y": float(slot.get("y", 0)),
                    "width": float(slot.get("width", 0)),
                    "height": float(slot.get("height", 0)),
                }
    results_box = boxes.get("results")
    callouts = design.get("callouts")
    if not results_box or not isinstance(callouts, list):
        return component_boxes

    valid_count = min(3, len([item for item in callouts if isinstance(item, dict)]))
    if not valid_count:
        return component_boxes

    callout_style = design.get("callout_style") if isinstance(design.get("callout_style"), dict) else {}
    callout_h = float(callout_style.get("height", 74) or 74)
    padding_x = float(card_style.get("padding_x", 20))
    x = float(results_box["x"]) + padding_x
    y = float(results_box["y"]) + 69
    width = float(results_box["width"]) - padding_x * 2
    if isinstance(explicit_sections, list):
        result_section = next(
            (section for section in explicit_sections if isinstance(section, dict) and clean_space(section.get("section_id", "")) == "results"),
            None,
        )
        if isinstance(result_section, dict):
            side_slots = [
                slot for slot in result_section.get("figure_slots", []) if isinstance(slot, dict)
                and float(slot.get("x", 0)) >= float(result_section.get("x", 0)) + float(result_section.get("width", 0)) * 0.42
                and float(slot.get("y", 0)) <= float(result_section.get("y", 0)) + 90
            ]
            if side_slots:
                width = max(
                    120.0,
                    min(float(slot.get("x", 0)) for slot in side_slots) - float(result_section.get("x", 0)) - 38.0,
                )
    gap = 8
    box_w = (width - gap * (valid_count - 1)) / valid_count
    for index in range(valid_count):
        component_boxes[f"result-callout-{index + 1}"] = {
            "x": x + index * (box_w + gap),
            "y": y,
            "width": box_w,
            "height": callout_h,
        }
    return component_boxes


def build_layout(design: dict[str, Any] | None = None) -> dict[str, Any]:
    design = design or {}
    canvas_w = int(deep_get(design, "canvas", "width", default=CANVAS_W) or CANVAS_W)
    canvas_h = int(deep_get(design, "canvas", "height", default=CANVAS_H) or CANVAS_H)
    margin = float(deep_get(design, "grid", "margin", default=MARGIN) or MARGIN)
    gutter = float(deep_get(design, "grid", "gutter", default=GUTTER) or GUTTER)
    header_h = float(deep_get(design, "grid", "header_height", default=HEADER_H) or HEADER_H)
    footer_h = float(deep_get(design, "grid", "footer_height", default=FOOTER_H) or FOOTER_H)
    column_count = max(1, int(deep_get(design, "grid", "columns", default=3) or 3))
    column_w = (canvas_w - 2 * margin - (column_count - 1) * gutter) / column_count
    body_y = header_h + 22
    body_h = canvas_h - body_y - footer_h - 18
    template = str(design.get("template", "method_centered") or "method_centered")
    explicit_sections = design.get("sections") if isinstance(design.get("sections"), list) else []
    if explicit_sections:
        boxes = {
            "header": {"x": margin, "y": 0, "width": canvas_w - 2 * margin, "height": header_h + 8},
            "footer": {"x": margin, "y": canvas_h - footer_h, "width": canvas_w - 2 * margin, "height": footer_h - 8},
        }
        for section in explicit_sections:
            if not isinstance(section, dict):
                continue
            section_id = clean_space(section.get("section_id", ""))
            if section_id:
                boxes[section_id] = {
                    "x": float(section.get("x", 0)),
                    "y": float(section.get("y", 0)),
                    "width": float(section.get("width", 0)),
                    "height": float(section.get("height", 0)),
                }
    else:
        boxes = template_boxes(template, margin, column_w, gutter, body_y, body_h, canvas_w, canvas_h, footer_h, header_h)
    typography = merged_dict(DEFAULT_TYPOGRAPHY, design.get("typography"))
    card_style = merged_dict(DEFAULT_CARD_STYLE, design.get("card_style"))
    component_boxes = build_component_boxes(boxes, design, card_style)

    layout = {
        "canvas_width": canvas_w,
        "canvas_height": canvas_h,
        "viewBox": f"0 0 {canvas_w} {canvas_h}",
        "column_count": column_count,
        "margin": margin,
        "gutter": gutter,
        "template": "art_directed_grid" if explicit_sections else template,
        "layout_source": design.get("layout_source", "deterministic_template"),
        "template_rationale": design.get("template_rationale", ""),
        "section_order": (
            [clean_space(section.get("section_id", "")) for section in explicit_sections if isinstance(section, dict)] + ["footer"]
            if explicit_sections else deep_get(design, "visual_hierarchy", "section_order", default=[
                "problem", "core_idea", "method", "key-figure",
                "results", "contribution", "conclusion", "footer",
            ])
        ),
        "section_bounding_boxes": boxes,
        "component_bounding_boxes": component_boxes,
        "typography_scale": typography,
        "figure_placements": (
            {
                clean_space(slot.get("figure_id", f"figure-{index}")): f"{clean_space(section.get('section_id', 'section'))}/figure-slot-{index}"
                for section in explicit_sections if isinstance(section, dict)
                for index, slot in enumerate(section.get("figure_slots", []), start=1) if isinstance(slot, dict)
            }
            if explicit_sections else {
                "primary": "key-figure/primary-figure",
                "secondary": "key-figure/secondary-figure",
            }
        ),
        "color_tokens": merged_dict(DEFAULT_COLORS, design.get("color_palette")),
        "card_style": card_style,
        "overflow_handling_decisions": design.get("overflow_rules") or [
            "Bullets are wrapped to fixed line limits.",
            "Extra bullets are dropped after section height is filled.",
            "Up to two selected figures are stacked in the key figure panel.",
        ],
        "asset_embedding_mode": "data_uri_when_available",
        "decorative_assets": design.get("decorative_assets", []),
        "visual_semantics": design.get("visual_semantics", {}),
        "visual_review_repair": design.get("visual_review_repair", {}),
    }
    return layout


def resolved_decorative_assets(design: dict[str, Any], outputs_dir: Path) -> list[dict[str, Any]]:
    decorations = design.get("decorations") if isinstance(design.get("decorations"), dict) else {}
    target_by_id = {
        "header-process-icons": "header_process",
        "body-process-strip": "body_flow",
    }
    resolved: list[dict[str, Any]] = []
    for raw in design.get("decorative_assets", []):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        target = target_by_id.get(str(item.get("id", "")))
        config = decorations.get(target) if target and isinstance(decorations.get(target), dict) else {}
        requested_mode = str(config.get("render_mode", item.get("render_mode", "vector_substitute")))
        item["requested_render_mode"] = requested_mode
        if requested_mode == "vtracer_inline":
            relative_path = safe_generated_vector_path(config.get("vector_path"))
            expected_sha256 = str(config.get("vector_sha256", "") or "")
            loaded = (
                load_safe_traced_svg(str(outputs_dir / relative_path), expected_sha256)
                if relative_path else None
            )
            if loaded:
                item.update({
                    "render_mode": "vtracer_inline",
                    "vector_path": relative_path,
                    "vector_sha256": expected_sha256,
                    "vector_integrity": "verified",
                    "vector_element_count": loaded[2],
                })
            else:
                item.update({
                    "render_mode": "vector_substitute",
                    "vector_integrity": "failed",
                    "fallback": "deterministic_vector_substitute",
                })
        else:
            item["render_mode"] = "vector_substitute"
            item["vector_integrity"] = "not_applicable"
        resolved.append(item)
    return resolved


def build_svg(
    content: dict[str, Any],
    outputs_dir: Path,
    design: dict[str, Any] | None = None,
    typesetting_manifest: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    design = design or {}
    typesetting_sections = validated_typesetting_sections(content, design, typesetting_manifest)
    layout = build_layout(design)
    layout["decorative_assets"] = resolved_decorative_assets(design, outputs_dir)
    source_assets = build_source_asset_manifest(content, outputs_dir, design)
    layout["source_assets"] = source_assets
    layout["asset_manifest"] = source_assets + [
        item for item in layout.get("decorative_assets", []) if isinstance(item, dict)
    ]
    boxes = layout["section_bounding_boxes"]
    canvas_w = int(layout["canvas_width"])
    canvas_h = int(layout["canvas_height"])
    margin = float(layout["margin"])
    typography = merged_dict(DEFAULT_TYPOGRAPHY, layout.get("typography_scale"))
    font_metadata = (
        typesetting_manifest.get("font")
        if isinstance(typesetting_manifest, dict) and isinstance(typesetting_manifest.get("font"), dict)
        else resolve_font(typography.get("font_family", DEFAULT_TYPOGRAPHY["font_family"]))
    )
    configure_measurement_font(font_metadata.get("resolved_font_path"))
    layout["font_metrics"] = font_metadata
    layout["typesetting_manifest"] = {
        "applied": bool(typesetting_manifest),
        "version": typesetting_manifest.get("version") if isinstance(typesetting_manifest, dict) else None,
        "content_sha256": typesetting_manifest.get("content_sha256") if isinstance(typesetting_manifest, dict) else None,
        "design_sha256": typesetting_manifest.get("design_sha256") if isinstance(typesetting_manifest, dict) else None,
    }
    colors = merged_dict(DEFAULT_COLORS, layout.get("color_tokens"))
    card_style = merged_dict(DEFAULT_CARD_STYLE, layout.get("card_style"))
    image_config = design.get("image_placement") if isinstance(design.get("image_placement"), dict) else {}
    card_variants = design.get("card_variants") if isinstance(design.get("card_variants"), dict) else {}
    result_callouts = design.get("callouts") if isinstance(design.get("callouts"), list) else content.get("result_callouts", [])
    if not isinstance(result_callouts, list):
        result_callouts = []
    callout_style = design.get("callout_style") if isinstance(design.get("callout_style"), dict) else {}

    title = clean_space(content.get("title", "Untitled Paper"))
    authors = content.get("authors", [])
    affiliations = content.get("affiliations", [])
    authors_text = "; ".join(clean_space(author) for author in authors[:4]) if isinstance(authors, list) else ""
    affiliations_text = "; ".join(clean_space(aff) for aff in affiliations[:2]) if isinstance(affiliations, list) else ""

    renderer_font_family = str(font_metadata.get("resolved_font_family") or typography.get("font_family") or "sans-serif")
    font_family = escape(renderer_font_family)
    style = """
    <style>
      .title { font-family: FONT_FAMILY; font-weight: 700; fill: TEXT_COLOR; }
      .title-light { font-family: FONT_FAMILY; font-weight: 700; fill: HEADER_TEXT; }
      .authors { font-family: FONT_FAMILY; fill: MUTED_COLOR; }
      .authors-light { font-family: FONT_FAMILY; fill: HEADER_MUTED; }
      .section-title { font-family: FONT_FAMILY; font-weight: 700; fill: TEXT_COLOR; }
      .body { font-family: FONT_FAMILY; fill: BODY_COLOR; }
      .caption { font-family: FONT_FAMILY; fill: MUTED_COLOR; }
      .muted { font-family: FONT_FAMILY; fill: MUTED_COLOR; }
      .muted-light { font-family: FONT_FAMILY; fill: HEADER_MUTED; }
      .eyebrow { font-family: FONT_FAMILY; font-weight: 700; letter-spacing: 0.6px; }
      .eyebrow-light { font-family: FONT_FAMILY; font-weight: 700; fill: HEADER_MUTED; letter-spacing: 0.7px; }
      .hero-message { font-family: FONT_FAMILY; font-weight: 700; fill: HEADER_TEXT; }
      .callout-label { font-family: FONT_FAMILY; font-weight: 700; fill: ACCENT_RESULT; letter-spacing: 0.5px; }
      .callout-value { font-family: FONT_FAMILY; font-weight: 800; fill: ACCENT_RESULT; }
      .footer { font-family: FONT_FAMILY; fill: MUTED_COLOR; }
    </style>
    """
    style = (
        style.replace("FONT_FAMILY", font_family)
        .replace("TEXT_COLOR", str(colors["text"]))
        .replace("BODY_COLOR", str(colors["text"]))
        .replace("MUTED_COLOR", str(colors["muted"]))
        .replace("HEADER_TEXT", str(colors["header_text"]))
        .replace("HEADER_MUTED", str(colors["header_muted"]))
        .replace("ACCENT_RESULT", str(colors["accent_result"]))
    )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1189mm" height="841mm" viewBox="0 0 {canvas_w} {canvas_h}" role="img" font-family="{font_family}" fill="{colors["text"]}">',
        f'<title>{escape(title)}</title>',
        f'<desc>Academic SVG poster generated from extracted paper content using template {escape(str(layout.get("template", "default")))}.</desc>',
        style,
        f'<rect x="0" y="0" width="{canvas_w}" height="{canvas_h}" fill="{colors["background"]}"/>',
        draw_header(content, **boxes["header"], canvas_w=canvas_w, typography=typography, colors=colors, design=design, outputs_dir=outputs_dir),
    ]

    decorations = design.get("decorations") if isinstance(design.get("decorations"), dict) else {}
    body_flow = decorations.get("body_flow") if isinstance(decorations.get("body_flow"), dict) else {}
    if body_flow.get("enabled"):
        parts.append('<g id="decorative-body-flow">')
        parts.append(draw_process_sequence(body_flow, colors, include_card=True, outputs_dir=outputs_dir))
        parts.append("</g>")

    explicit_sections = design.get("sections") if isinstance(design.get("sections"), list) else []
    if explicit_sections:
        require_explicit_source_assets(
            content,
            outputs_dir,
            [section for section in explicit_sections if isinstance(section, dict)],
        )
        parts.append('<g id="art-directed-sections">')
        for section in explicit_sections:
            if not isinstance(section, dict):
                continue
            parts.append(draw_art_directed_section(
                content,
                outputs_dir,
                section,
                typography,
                colors,
                card_style,
                image_config,
                result_callouts,
                callout_style,
                typesetting_sections.get(clean_space(section.get("section_id", "")), {}),
            ))
        parts.append("</g>")
    else:
        problem_box = boxes["problem"]
        core_box = boxes["core_idea"]
        method_box = boxes["method"]
        figure_box = boxes["key-figure"]
        results_box = boxes["results"]
        contribution_box = boxes["contribution"]
        conclusion_box = boxes["conclusion"]

        parts.append('<g id="column-1">')
        parts.append(draw_panel("problem", "Problem / Motivation", section_bullets(content, "problem") + section_bullets(content, "motivation")[:1], **problem_box, accent=str(colors["accent_primary"]), max_bullets=4, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("problem", "standard"))))
        parts.append(draw_panel("core-idea", "Core Idea", section_bullets(content, "core_idea"), **core_box, accent=str(colors["accent_idea"]), max_bullets=4, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("core_idea", "standard"))))
        parts.append("</g>")

        parts.append('<g id="column-2">')
        parts.append(draw_panel("method", "Method", section_bullets(content, "method"), **method_box, accent=str(colors["accent_secondary"]), max_bullets=5, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("method", "standard"))))
        parts.append(draw_figure_panel(content, outputs_dir, **figure_box, typography=typography, colors=colors, card_style=card_style, image_config=image_config))
        parts.append("</g>")

        parts.append('<g id="column-3">')
        parts.append(draw_panel("results", "Results", section_bullets(content, "results"), **results_box, accent=str(colors["accent_result"]), max_bullets=6, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("results", "hero")), callouts=result_callouts, callout_style=callout_style))
        parts.append(draw_panel("contribution", "Contributions", section_bullets(content, "contribution"), **contribution_box, accent=str(colors["accent_contribution"]), max_bullets=4, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("contribution", "compact"))))
        conclusion_bullets = section_bullets(content, "conclusion") + section_bullets(content, "limitations")[:1]
        parts.append(draw_panel("conclusion", "Conclusion", conclusion_bullets, **conclusion_box, accent=str(colors["accent_neutral"]), max_bullets=4, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("conclusion", "compact"))))
        parts.append("</g>")

    footer = content.get("footer_metadata", {}) if isinstance(content.get("footer_metadata", {}), dict) else {}
    omitted = content.get("omitted_sections", [])
    footer_text = f"Source: {footer.get('source_pdf', '') or 'paper PDF'}"
    if omitted:
        footer_text += " | Omitted or weak sections: " + ", ".join(str(item) for item in omitted[:6])

    parts.append('<g id="footer">')
    footer_size = float(typography.get("footer", 8.5))
    footer_svg, _ = svg_text_lines(footer_text, margin, canvas_h - 18, canvas_w - 2 * margin, footer_size, footer_size * 1.3, "footer", max_lines=2, fill=str(colors["muted"]))
    parts.append(footer_svg)
    parts.append("</g>")

    parts.append("</svg>")

    return "\n".join(parts), layout


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate outputs/poster.svg from poster_content.json.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--design-json", default="outputs/poster_design_spec.json")
    parser.add_argument("--typesetting-manifest-json", default=None)
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--svg-path", default="outputs/poster.svg")
    parser.add_argument("--layout-json", default="outputs/poster_layout.json")
    args = parser.parse_args()

    content_json = Path(args.content_json)
    design_json = Path(args.design_json)
    typesetting_manifest_json = Path(args.typesetting_manifest_json) if args.typesetting_manifest_json else None
    outputs_dir = Path(args.outputs_dir)
    svg_path = Path(args.svg_path)
    layout_json = Path(args.layout_json)

    if not content_json.exists():
        print(f"Error: content JSON does not exist: {content_json}", file=sys.stderr)
        return 1

    content = json.loads(content_json.read_text(encoding="utf-8"))
    design = load_json_or_empty(design_json)
    typesetting_manifest = load_json_or_empty(typesetting_manifest_json)
    try:
        svg, layout = build_svg(content, outputs_dir, design, typesetting_manifest)
    except (OSError, TypeError, ValueError) as exc:
        print(f"Error: could not build SVG: {exc}", file=sys.stderr)
        return 1

    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg, encoding="utf-8")
    layout_json.parent.mkdir(parents=True, exist_ok=True)
    layout_json.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {svg_path}")
    print(f"Wrote {layout_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
