#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import sys
from html import escape
from pathlib import Path
from typing import Any


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


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


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


def estimate_text_width(text: str, font_size: float) -> float:
    # Approximation for SVG wrapping. This is intentionally conservative.
    return len(text) * font_size * 0.52


def wrap_text(text: str, max_width: float, font_size: float, max_lines: int | None = None) -> list[str]:
    text = clean_space(text)
    if not text:
        return []

    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join(current + [word])
        if current and estimate_text_width(candidate, font_size) > max_width:
            lines.append(" ".join(current))
            current = [word]
            if max_lines is not None and len(lines) >= max_lines:
                break
        else:
            current.append(word)

    if current and (max_lines is None or len(lines) < max_lines):
        lines.append(" ".join(current))

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]

    if max_lines is not None and len(lines) == max_lines:
        original = " ".join(words)
        displayed = " ".join(lines)
        if len(displayed) < len(original):
            lines[-1] = lines[-1].rstrip(".,;:") + "…"

    return lines


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
) -> tuple[str, float]:
    lines = wrap_text(text, max_width, font_size, max_lines=max_lines)
    if not lines:
        return "", y

    class_attr = f' class="{css_class}"' if css_class else ""
    bullet_prefix = "• " if bullet else ""
    tspans = []
    for index, line in enumerate(lines):
        prefix = bullet_prefix if index == 0 else "  "
        dy = 0 if index == 0 else line_height
        tspans.append(
            f'<tspan x="{x:.1f}" dy="{dy:.1f}">{escape(prefix + line)}</tspan>'
        )

    svg = f'<text{class_attr} font-size="{font_size}" x="{x:.1f}" y="{y:.1f}">' + "".join(tspans) + "</text>"
    return svg, y + line_height * len(lines)


def image_to_data_uri(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


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
) -> str:
    title = clean_space(content.get("title", "Untitled Paper"))
    authors = content.get("authors", [])
    affiliations = content.get("affiliations", [])
    authors_text = "; ".join(clean_space(author) for author in authors[:4]) if isinstance(authors, list) else ""
    affiliations_text = "; ".join(clean_space(aff) for aff in affiliations[:2]) if isinstance(affiliations, list) else ""
    hero_message = clean_space(design.get("hero_message", "") or content.get("take_home_message", ""))

    title_size = float(typography.get("title", 32))
    title_line_h = title_size * 1.08
    parts = [
        '<g id="header">',
        f'<rect x="0" y="0" width="{canvas_w}" height="{y + height + 8:.1f}" fill="{colors["header_background"]}"/>',
        f'<rect x="{x:.1f}" y="{y + height + 4:.1f}" width="{width:.1f}" height="3.2" fill="{colors["accent_result"]}"/>',
    ]

    title_lines = wrap_text(title, width * 0.72, title_size, max_lines=2)
    title_y = y + 28
    for i, line in enumerate(title_lines):
        parts.append(
            f'<text class="title-light" x="{x:.1f}" y="{title_y + i * title_line_h:.1f}" font-size="{title_size:.1f}">{escape(line)}</text>'
        )

    meta_y = title_y + title_line_h * len(title_lines) + 12
    if authors_text:
        author_size = float(typography.get("authors", 13))
        author_svg, meta_y = svg_text_lines(
            authors_text,
            x,
            meta_y,
            width * 0.7,
            author_size,
            author_size * 1.25,
            "authors-light",
            max_lines=2,
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
        )
        parts.append(aff_svg)

    if hero_message:
        callout_w = width * 0.28
        callout_x = x + width - callout_w
        callout_y = y + 18
        callout_h = max(68, height - 36)
        parts.append(
            f'<rect x="{callout_x:.1f}" y="{callout_y:.1f}" width="{callout_w:.1f}" height="{callout_h:.1f}" rx="8" fill="#ffffff" opacity="0.10" stroke="#ffffff" stroke-opacity="0.20"/>'
        )
        parts.append(
            f'<text class="eyebrow-light" x="{callout_x + 16:.1f}" y="{callout_y + 22:.1f}" font-size="8.8">TAKE-HOME</text>'
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
        )
        parts.append(msg_svg)

    parts.append("</g>")
    return "\n".join(parts)


def draw_section_label(label: str, x: float, y: float, accent: str, colors: dict[str, Any]) -> str:
    text_w = max(58, estimate_text_width(label.upper(), 8.6) + 18)
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{text_w:.1f}" height="18" rx="9" fill="{accent}" opacity="0.12"/>'
        f'<text class="eyebrow" x="{x + 9:.1f}" y="{y + 12.2:.1f}" font-size="8.6" fill="{accent}">{escape(label.upper())}</text>'
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
        parts.append(f'<text class="callout-label" x="{box_x + 10:.1f}" y="{y + 17:.1f}" font-size="{label_size:.1f}">{escape(label.upper())}</text>')
        parts.append(f'<text class="callout-value" x="{box_x + 10:.1f}" y="{y + 40:.1f}" font-size="{value_size:.1f}">{escape(value)}</text>')
        detail_svg, _ = svg_text_lines(
            detail,
            box_x + 10,
            y + 57,
            box_w - 20,
            detail_size,
            detail_size * 1.28,
            "caption",
            max_lines=detail_lines,
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
    title_size = float(typography.get("section_title", 18))
    body_size = float(typography.get("body", 11.5))
    body_line = body_size * float(typography.get("line_height_ratio", 1.3))
    title_y = y + 35 if variant == "hero" else y + 31
    parts = [
        f'<g id="{escape(section_id)}">',
        f'<rect x="{x + 2.2:.1f}" y="{y + 3.0:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{radius:.1f}" fill="#91a4bd" opacity="{shadow_opacity:.2f}"/>',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{radius:.1f}" fill="{colors["panel"]}" stroke="{colors["panel_stroke"]}" stroke-width="{stroke_w:.1f}"/>',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{accent_w:.1f}" rx="{min(radius, 3):.1f}" fill="{accent}"/>',
        draw_section_label(heading, x + padding_x, y + 15, accent, colors),
    ]
    if variant == "hero":
        parts.append(
            f'<text class="section-title" x="{x + padding_x:.1f}" y="{title_y + 18:.1f}" font-size="{title_size + 2:.1f}">{escape(heading)}</text>'
        )
        current_y = title_y + 34
        if callouts:
            callout_svg, current_y = draw_result_callouts(callouts, x + padding_x, current_y, w - padding_x * 2, colors, typography, callout_style)
            parts.append(callout_svg)
    else:
        parts.append(
            f'<text class="section-title" x="{x + padding_x:.1f}" y="{title_y + 18:.1f}" font-size="{title_size:.1f}">{escape(heading)}</text>'
        )
        current_y = title_y + 38

    for bullet in bullets[:max_bullets]:
        max_lines = 2 if variant in {"compact", "hero"} else 3
        projected_lines = wrap_text(bullet, w - padding_x * 2, body_size, max_lines=max_lines)
        if current_y + body_line * len(projected_lines) > y + h - 14:
            break
        text_svg, current_y = svg_text_lines(
            bullet,
            x + padding_x + 2,
            current_y,
            w - padding_x * 2,
            font_size=body_size,
            line_height=body_line,
            css_class="body",
            max_lines=max_lines,
            bullet=True,
        )
        parts.append(text_svg)
        current_y += 5
        if current_y > y + h - 14:
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
        f'<text class="section-title" x="{x + 18:.1f}" y="{y + 54:.1f}" font-size="{title_size:.1f}">Key Figures</text>',
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
            parts.append(f'<text class="muted" x="{x + 18:.1f}" y="{slot_y + 10:.1f}" font-size="9">{escape(title)}</text>')
            parts.append(draw_figure_item(figure, outputs_dir, x + 18, slot_y + 16, w - 36, slot_h - 18, typography, colors, image_config))
            parts.append("</g>")
    else:
        parts.append(
            f'<text class="muted" x="{x + 22:.1f}" y="{y + 65:.1f}" font-size="12">No extracted figure available.</text>'
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
                f'<text class="muted" x="{x:.1f}" y="{y + 18:.1f}" font-size="12">No usable figure asset was selected.</text>'
            )
    else:
        parts.append(
            f'<text class="muted" x="{x:.1f}" y="{y + 18:.1f}" font-size="12">No extracted figure available.</text>'
        )

    return "\n".join(parts)


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
    column_w = (canvas_w - 2 * margin - 2 * gutter) / 3
    col1_x = margin
    col2_x = margin + column_w + gutter
    col3_x = margin + 2 * (column_w + gutter)
    body_y = header_h + 22
    body_h = canvas_h - body_y - footer_h - 18
    template = str(design.get("template", "method_centered") or "method_centered")
    boxes = template_boxes(template, margin, column_w, gutter, body_y, body_h, canvas_w, canvas_h, footer_h, header_h)
    typography = merged_dict(DEFAULT_TYPOGRAPHY, design.get("typography"))
    card_style = merged_dict(DEFAULT_CARD_STYLE, design.get("card_style"))
    component_boxes = build_component_boxes(boxes, design, card_style)

    layout = {
        "canvas_width": canvas_w,
        "canvas_height": canvas_h,
        "viewBox": f"0 0 {canvas_w} {canvas_h}",
        "column_count": 3,
        "margin": margin,
        "gutter": gutter,
        "template": template,
        "template_rationale": design.get("template_rationale", ""),
        "section_order": deep_get(design, "visual_hierarchy", "section_order", default=[
            "problem", "core_idea", "method", "key-figure",
            "results", "contribution", "conclusion", "footer",
        ]),
        "section_bounding_boxes": boxes,
        "component_bounding_boxes": component_boxes,
        "typography_scale": typography,
        "figure_placements": {
            "primary": "key-figure/primary-figure",
            "secondary": "key-figure/secondary-figure",
        },
        "color_tokens": merged_dict(DEFAULT_COLORS, design.get("color_palette")),
        "card_style": card_style,
        "overflow_handling_decisions": design.get("overflow_rules") or [
            "Bullets are wrapped to fixed line limits.",
            "Extra bullets are dropped after section height is filled.",
            "Up to two selected figures are stacked in the key figure panel.",
        ],
        "asset_embedding_mode": "data_uri_when_available",
    }
    return layout


def build_svg(content: dict[str, Any], outputs_dir: Path, design: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    design = design or {}
    layout = build_layout(design)
    boxes = layout["section_bounding_boxes"]
    canvas_w = int(layout["canvas_width"])
    canvas_h = int(layout["canvas_height"])
    margin = float(layout["margin"])
    typography = merged_dict(DEFAULT_TYPOGRAPHY, layout.get("typography_scale"))
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

    font_family = escape(str(typography.get("font_family", DEFAULT_TYPOGRAPHY["font_family"])))
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
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1189mm" height="841mm" viewBox="0 0 {canvas_w} {canvas_h}" role="img">',
        f'<title>{escape(title)}</title>',
        f'<desc>Academic SVG poster generated from extracted paper content using template {escape(str(layout.get("template", "default")))}.</desc>',
        style,
        f'<rect x="0" y="0" width="{canvas_w}" height="{canvas_h}" fill="{colors["background"]}"/>',
        draw_header(content, **boxes["header"], canvas_w=canvas_w, typography=typography, colors=colors, design=design),
    ]

    problem_box = boxes["problem"]
    core_box = boxes["core_idea"]
    method_box = boxes["method"]
    figure_box = boxes["key-figure"]
    results_box = boxes["results"]
    contribution_box = boxes["contribution"]
    conclusion_box = boxes["conclusion"]

    parts.append('<g id="column-1">')
    parts.append(draw_panel("problem", "Problem / Motivation", section_bullets(content, "problem") + section_bullets(content, "motivation")[:1], **problem_box, accent=str(colors["accent_primary"]), max_bullets=4, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("problem", "standard"))))
    parts.append(draw_panel("core-idea", "Core Idea", section_bullets(content, "core_idea"), **core_box, accent="#7c3aed", max_bullets=4, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("core_idea", "standard"))))
    parts.append("</g>")

    parts.append('<g id="column-2">')
    parts.append(draw_panel("method", "Method", section_bullets(content, "method"), **method_box, accent=str(colors["accent_secondary"]), max_bullets=5, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("method", "standard"))))
    parts.append(draw_figure_panel(content, outputs_dir, **figure_box, typography=typography, colors=colors, card_style=card_style, image_config=image_config))
    parts.append("</g>")

    parts.append('<g id="column-3">')
    parts.append(draw_panel("results", "Results", section_bullets(content, "results"), **results_box, accent=str(colors["accent_result"]), max_bullets=6, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("results", "hero")), callouts=result_callouts, callout_style=callout_style))
    parts.append(draw_panel("contribution", "Contributions", section_bullets(content, "contribution"), **contribution_box, accent="#0891b2", max_bullets=4, typography=typography, colors=colors, card_style=card_style, variant=str(card_variants.get("contribution", "compact"))))
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
    footer_svg, _ = svg_text_lines(footer_text, margin, canvas_h - 18, canvas_w - 2 * margin, footer_size, footer_size * 1.3, "footer", max_lines=2)
    parts.append(footer_svg)
    parts.append("</g>")

    parts.append("</svg>")

    return "\n".join(parts), layout


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate outputs/poster.svg from poster_content.json.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--design-json", default="outputs/poster_design_spec.json")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--svg-path", default="outputs/poster.svg")
    parser.add_argument("--layout-json", default="outputs/poster_layout.json")
    args = parser.parse_args()

    content_json = Path(args.content_json)
    design_json = Path(args.design_json)
    outputs_dir = Path(args.outputs_dir)
    svg_path = Path(args.svg_path)
    layout_json = Path(args.layout_json)

    if not content_json.exists():
        print(f"Error: content JSON does not exist: {content_json}", file=sys.stderr)
        return 1

    content = json.loads(content_json.read_text(encoding="utf-8"))
    design = load_json_or_empty(design_json)
    svg, layout = build_svg(content, outputs_dir, design)

    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg, encoding="utf-8")
    layout_json.parent.mkdir(parents=True, exist_ok=True)
    layout_json.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {svg_path}")
    print(f"Wrote {layout_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
