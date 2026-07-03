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


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


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
) -> str:
    w = width
    h = height
    parts = [
        f'<g id="{escape(section_id)}">',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="10" fill="#ffffff" stroke="#d7dee8" stroke-width="1.2"/>',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="7" height="{h:.1f}" rx="3" fill="{accent}"/>',
        f'<text class="section-title" x="{x + 18:.1f}" y="{y + 27:.1f}" font-size="18">{escape(heading)}</text>',
    ]

    current_y = y + 50
    for bullet in bullets[:max_bullets]:
        text_svg, current_y = svg_text_lines(
            bullet,
            x + 22,
            current_y,
            w - 38,
            font_size=11.5,
            line_height=15,
            css_class="body",
            max_lines=3,
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
) -> str:
    w = width
    h = height
    figures = content.get("figures_to_use", [])
    figure = figures[0] if isinstance(figures, list) and figures else None
    parts = [
        '<g id="key-figure">',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="10" fill="#ffffff" stroke="#d7dee8" stroke-width="1.2"/>',
        f'<text class="section-title" x="{x + 18:.1f}" y="{y + 27:.1f}" font-size="18">Key Figure</text>',
    ]

    if isinstance(figure, dict):
        asset = clean_space(figure.get("asset_path", ""))
        caption = clean_space(figure.get("caption", "") or figure.get("text", ""))
        image_data = None
        if asset:
            image_data = image_to_data_uri(outputs_dir / asset)

        if image_data:
            img_x = x + 18
            img_y = y + 42
            img_w = w - 36
            img_h = h - 92
            parts.append(
                f'<image x="{img_x:.1f}" y="{img_y:.1f}" width="{img_w:.1f}" height="{img_h:.1f}" href="{image_data}" preserveAspectRatio="xMidYMid meet"/>'
            )
            cap_svg, _ = svg_text_lines(
                caption,
                x + 18,
                y + h - 35,
                w - 36,
                font_size=8.8,
                line_height=11,
                css_class="caption",
                max_lines=3,
            )
            parts.append(cap_svg)
        elif caption:
            cap_svg, _ = svg_text_lines(
                caption,
                x + 22,
                y + 58,
                w - 44,
                font_size=11,
                line_height=15,
                css_class="body",
                max_lines=9,
            )
            parts.append(cap_svg)
        else:
            parts.append(
                f'<text class="muted" x="{x + 22:.1f}" y="{y + 65:.1f}" font-size="12">No usable figure asset was selected.</text>'
            )
    else:
        parts.append(
            f'<text class="muted" x="{x + 22:.1f}" y="{y + 65:.1f}" font-size="12">No extracted figure available.</text>'
        )

    parts.append("</g>")
    return "\n".join(parts)


def build_layout() -> dict[str, Any]:
    col1_x = MARGIN
    col2_x = MARGIN + COLUMN_W + GUTTER
    col3_x = MARGIN + 2 * (COLUMN_W + GUTTER)
    body_y = HEADER_H + 22
    body_h = CANVAS_H - body_y - FOOTER_H - 18

    layout = {
        "canvas_width": CANVAS_W,
        "canvas_height": CANVAS_H,
        "viewBox": f"0 0 {CANVAS_W} {CANVAS_H}",
        "column_count": 3,
        "margin": MARGIN,
        "gutter": GUTTER,
        "section_order": [
            "problem", "core_idea", "method", "key-figure",
            "results", "contribution", "conclusion", "footer",
        ],
        "section_bounding_boxes": {
            "header": {"x": MARGIN, "y": 24, "width": CANVAS_W - 2 * MARGIN, "height": HEADER_H - 28},
            "problem": {"x": col1_x, "y": body_y, "width": COLUMN_W, "height": 174},
            "core_idea": {"x": col1_x, "y": body_y + 192, "width": COLUMN_W, "height": 210},
            "method": {"x": col2_x, "y": body_y, "width": COLUMN_W, "height": 226},
            "key-figure": {"x": col2_x, "y": body_y + 244, "width": COLUMN_W, "height": body_h - 244},
            "results": {"x": col3_x, "y": body_y, "width": COLUMN_W, "height": 252},
            "contribution": {"x": col3_x, "y": body_y + 270, "width": COLUMN_W, "height": 168},
            "conclusion": {"x": col3_x, "y": body_y + 456, "width": COLUMN_W, "height": body_h - 456},
            "footer": {"x": MARGIN, "y": CANVAS_H - FOOTER_H, "width": CANVAS_W - 2 * MARGIN, "height": FOOTER_H - 8},
        },
        "typography_scale": {
            "title": 32,
            "authors": 13,
            "section_title": 18,
            "body": 11.5,
            "caption": 8.8,
            "footer": 8.5,
        },
        "figure_placements": {
            "primary": "key-figure"
        },
        "color_tokens": {
            "background": "#f4f7fb",
            "panel": "#ffffff",
            "text": "#162033",
            "muted": "#5b677a",
            "accent_blue": "#2563eb",
            "accent_green": "#16a34a",
            "accent_orange": "#ea580c",
        },
        "overflow_handling_decisions": [
            "Bullets are wrapped to fixed line limits.",
            "Extra bullets are dropped after section height is filled.",
            "Only one key figure is rendered in the MVP layout.",
        ],
        "asset_embedding_mode": "data_uri_when_available",
    }
    return layout


def build_svg(content: dict[str, Any], outputs_dir: Path) -> tuple[str, dict[str, Any]]:
    layout = build_layout()
    boxes = layout["section_bounding_boxes"]

    title = clean_space(content.get("title", "Untitled Paper"))
    authors = content.get("authors", [])
    affiliations = content.get("affiliations", [])
    authors_text = "; ".join(clean_space(author) for author in authors[:4]) if isinstance(authors, list) else ""
    affiliations_text = "; ".join(clean_space(aff) for aff in affiliations[:2]) if isinstance(affiliations, list) else ""

    style = """
    <style>
      .title { font-family: Arial, Helvetica, sans-serif; font-weight: 700; fill: #162033; }
      .authors { font-family: Arial, Helvetica, sans-serif; fill: #3b4658; }
      .section-title { font-family: Arial, Helvetica, sans-serif; font-weight: 700; fill: #162033; }
      .body { font-family: Arial, Helvetica, sans-serif; fill: #233044; }
      .caption { font-family: Arial, Helvetica, sans-serif; fill: #5b677a; }
      .muted { font-family: Arial, Helvetica, sans-serif; fill: #6b7280; }
      .footer { font-family: Arial, Helvetica, sans-serif; fill: #5b677a; }
    </style>
    """

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1189mm" height="841mm" viewBox="0 0 {CANVAS_W} {CANVAS_H}" role="img">',
        f'<title>{escape(title)}</title>',
        f'<desc>Academic SVG poster generated from extracted paper content.</desc>',
        style,
        f'<rect x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}" fill="#f4f7fb"/>',
        '<g id="header">',
    ]

    title_lines = wrap_text(title, CANVAS_W - 2 * MARGIN, 32, max_lines=2)
    title_y = 44
    for i, line in enumerate(title_lines):
        parts.append(f'<text class="title" x="{MARGIN}" y="{title_y + i * 36}" font-size="32">{escape(line)}</text>')

    meta_y = title_y + 36 * len(title_lines) + 14
    if authors_text:
        author_svg, meta_y = svg_text_lines(authors_text, MARGIN, meta_y, CANVAS_W - 2 * MARGIN, 13, 16, "authors", max_lines=2)
        parts.append(author_svg)
    if affiliations_text:
        aff_svg, meta_y = svg_text_lines(affiliations_text, MARGIN, meta_y + 2, CANVAS_W - 2 * MARGIN, 10, 13, "muted", max_lines=1)
        parts.append(aff_svg)

    parts.append("</g>")

    problem_box = boxes["problem"]
    core_box = boxes["core_idea"]
    method_box = boxes["method"]
    figure_box = boxes["key-figure"]
    results_box = boxes["results"]
    contribution_box = boxes["contribution"]
    conclusion_box = boxes["conclusion"]

    parts.append('<g id="column-1">')
    parts.append(draw_panel("problem", "Problem / Motivation", section_bullets(content, "problem") + section_bullets(content, "motivation")[:1], **problem_box, accent="#2563eb", max_bullets=4))
    parts.append(draw_panel("core-idea", "Core Idea", section_bullets(content, "core_idea"), **core_box, accent="#7c3aed", max_bullets=4))
    parts.append("</g>")

    parts.append('<g id="column-2">')
    parts.append(draw_panel("method", "Method", section_bullets(content, "method"), **method_box, accent="#16a34a", max_bullets=5))
    parts.append(draw_figure_panel(content, outputs_dir, **figure_box))
    parts.append("</g>")

    parts.append('<g id="column-3">')
    parts.append(draw_panel("results", "Results", section_bullets(content, "results"), **results_box, accent="#ea580c", max_bullets=6))
    parts.append(draw_panel("contribution", "Contributions", section_bullets(content, "contribution"), **contribution_box, accent="#0891b2", max_bullets=4))
    conclusion_bullets = section_bullets(content, "conclusion") + section_bullets(content, "limitations")[:1]
    parts.append(draw_panel("conclusion", "Conclusion", conclusion_bullets, **conclusion_box, accent="#475569", max_bullets=4))
    parts.append("</g>")

    footer = content.get("footer_metadata", {}) if isinstance(content.get("footer_metadata", {}), dict) else {}
    omitted = content.get("omitted_sections", [])
    footer_text = f"Source: {footer.get('source_pdf', '') or 'paper PDF'}"
    if omitted:
        footer_text += " | Omitted or weak sections: " + ", ".join(str(item) for item in omitted[:6])

    parts.append('<g id="footer">')
    footer_svg, _ = svg_text_lines(footer_text, MARGIN, CANVAS_H - 18, CANVAS_W - 2 * MARGIN, 8.5, 11, "footer", max_lines=2)
    parts.append(footer_svg)
    parts.append("</g>")

    parts.append("</svg>")

    return "\n".join(parts), layout


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate outputs/poster.svg from poster_content.json.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--svg-path", default="outputs/poster.svg")
    parser.add_argument("--layout-json", default="outputs/poster_layout.json")
    args = parser.parse_args()

    content_json = Path(args.content_json)
    outputs_dir = Path(args.outputs_dir)
    svg_path = Path(args.svg_path)
    layout_json = Path(args.layout_json)

    if not content_json.exists():
        print(f"Error: content JSON does not exist: {content_json}", file=sys.stderr)
        return 1

    content = json.loads(content_json.read_text(encoding="utf-8"))
    svg, layout = build_svg(content, outputs_dir)

    svg_path.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(svg, encoding="utf-8")
    layout_json.parent.mkdir(parents=True, exist_ok=True)
    layout_json.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {svg_path}")
    print(f"Wrote {layout_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
