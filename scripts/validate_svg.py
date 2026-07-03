#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


XLINK_NS = "{http://www.w3.org/1999/xlink}"
REMOTE_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
CSS_REMOTE_URL_RE = re.compile(r"url\(\s*['\"]?https?://", re.IGNORECASE)
CSS_IMPORT_RE = re.compile(r"@import\s+['\"]?https?://", re.IGNORECASE)


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def is_remote_reference(value: str) -> bool:
    return bool(REMOTE_SCHEME_RE.match(value.strip()))


def contains_remote_css_reference(value: str) -> bool:
    return bool(CSS_REMOTE_URL_RE.search(value) or CSS_IMPORT_RE.search(value))


def collect_svg_elements(root: ET.Element, name: str) -> list[ET.Element]:
    return [el for el in root.iter() if local_name(el.tag) == name]


def get_href(el: ET.Element) -> str | None:
    return (
        el.attrib.get("href")
        or el.attrib.get(f"{XLINK_NS}href")
        or el.attrib.get("{http://www.w3.org/1999/xlink}href")
    )


def parse_number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.match(r"\s*(-?\d+(?:\.\d+)?)", value)
    if not match:
        return None
    return float(match.group(1))


def parse_viewbox(value: str | None) -> tuple[float, float, float, float] | None:
    if not value:
        return None
    parts = value.replace(",", " ").split()
    if len(parts) != 4:
        return None
    try:
        return tuple(float(part) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def normalize_box(raw_box: object) -> tuple[float, float, float, float] | None:
    if isinstance(raw_box, dict):
        keys = set(raw_box)
        if {"x", "y", "width", "height"}.issubset(keys):
            return (
                float(raw_box["x"]),
                float(raw_box["y"]),
                float(raw_box["width"]),
                float(raw_box["height"]),
            )
        if {"x", "y", "w", "h"}.issubset(keys):
            return (
                float(raw_box["x"]),
                float(raw_box["y"]),
                float(raw_box["w"]),
                float(raw_box["h"]),
            )
        if {"x1", "y1", "x2", "y2"}.issubset(keys):
            x1 = float(raw_box["x1"])
            y1 = float(raw_box["y1"])
            x2 = float(raw_box["x2"])
            y2 = float(raw_box["y2"])
            return (x1, y1, x2 - x1, y2 - y1)

    if isinstance(raw_box, (list, tuple)) and len(raw_box) == 4:
        x, y, width, height = raw_box
        return (float(x), float(y), float(width), float(height))

    return None


def boxes_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def validate_layout_json(
    layout_path: Path,
    canvas_box: tuple[float, float, float, float] | None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not layout_path.exists():
        warnings.append(f"Layout JSON does not exist: {layout_path}")
        return errors, warnings

    try:
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        errors.append(f"Layout JSON is not valid UTF-8: {layout_path}")
        return errors, warnings
    except json.JSONDecodeError as exc:
        errors.append(f"Layout JSON parse error: {exc}")
        return errors, warnings

    boxes_raw = layout.get("section_bounding_boxes")
    if not boxes_raw:
        warnings.append("Layout JSON is missing section_bounding_boxes.")
        return errors, warnings

    if isinstance(boxes_raw, dict):
        items = list(boxes_raw.items())
    elif isinstance(boxes_raw, list):
        items = [
            (str(item.get("id", index)), item.get("box", item))
            if isinstance(item, dict)
            else (str(index), item)
            for index, item in enumerate(boxes_raw)
        ]
    else:
        warnings.append("section_bounding_boxes should be a dict or list.")
        return errors, warnings

    boxes: list[tuple[str, tuple[float, float, float, float]]] = []
    for name, raw_box in items:
        try:
            box = normalize_box(raw_box)
        except (TypeError, ValueError):
            box = None
        if box is None:
            warnings.append(f"Could not parse layout box for section: {name}")
            continue
        boxes.append((name, box))

        x, y, width, height = box
        if width <= 0 or height <= 0:
            warnings.append(f"Layout box has non-positive size: {name}")

        if canvas_box:
            cx, cy, cw, ch = canvas_box
            if x < cx or y < cy or x + width > cx + cw or y + height > cy + ch:
                warnings.append(f"Layout box falls outside the SVG canvas: {name}")

    for index, (name, box) in enumerate(boxes):
        for other_name, other_box in boxes[index + 1 :]:
            if boxes_overlap(box, other_box):
                warnings.append(f"Layout boxes may overlap: {name} and {other_name}")

    return errors, warnings


def validate_svg(
    svg_path: Path,
    outputs_dir: Path,
    layout_path: Path | None = None,
) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not svg_path.exists():
        return False, [f"SVG file does not exist: {svg_path}"], warnings

    try:
        text = svg_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False, [f"SVG is not valid UTF-8: {svg_path}"], warnings

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return False, [f"SVG XML parse error: {exc}"], warnings

    if local_name(root.tag) != "svg":
        errors.append("Root element is not <svg>.")

    for attr in ["width", "height", "viewBox"]:
        if not root.attrib.get(attr):
            errors.append(f"Root <svg> is missing required attribute: {attr}")

    if not collect_svg_elements(root, "title"):
        errors.append("SVG is missing <title>.")

    if not collect_svg_elements(root, "desc"):
        errors.append("SVG is missing <desc>.")

    if collect_svg_elements(root, "script"):
        errors.append("SVG contains <script>, which is not allowed.")

    if collect_svg_elements(root, "foreignObject"):
        errors.append("SVG contains <foreignObject>, which is not allowed by default.")

    for el in root.iter():
        for attr_name, attr_value in el.attrib.items():
            if attr_name.startswith("xmlns"):
                continue
            if is_remote_reference(attr_value):
                errors.append(f"SVG contains remote reference in {attr_name}: {attr_value}")
            if contains_remote_css_reference(attr_value):
                errors.append(f"SVG contains remote CSS reference in {attr_name}.")

    for style in collect_svg_elements(root, "style"):
        style_text = "".join(style.itertext())
        if contains_remote_css_reference(style_text):
            errors.append("SVG contains remote CSS reference in <style>.")

    images = collect_svg_elements(root, "image")
    text_elements = collect_svg_elements(root, "text")
    if not text_elements:
        warnings.append("SVG contains no editable <text> elements.")

    group_ids = {el.attrib.get("id") for el in collect_svg_elements(root, "g")}
    for expected_id in ["header", "results", "footer"]:
        if expected_id not in group_ids:
            warnings.append(f"SVG is missing expected semantic group id: {expected_id}")

    if len(images) == 1:
        image = images[0]
        width = image.attrib.get("width")
        height = image.attrib.get("height")
        if width == root.attrib.get("width") and height == root.attrib.get("height"):
            warnings.append(
                "SVG may be a full-canvas raster image instead of an editable vector poster."
            )

    for image in images:
        href = get_href(image)
        if not href:
            warnings.append("<image> element is missing href.")
            continue

        if href.startswith("data:"):
            if not href.startswith("data:image/"):
                warnings.append("<image> data URI is not an image MIME type.")
            continue

        if is_remote_reference(href):
            errors.append(f"Remote image reference is not allowed: {href}")
            continue

        asset_path = (svg_path.parent / href).resolve()
        try:
            asset_path.relative_to(outputs_dir.resolve())
        except ValueError:
            errors.append(f"Image reference points outside outputs directory: {href}")
            continue

        if not asset_path.exists():
            errors.append(f"Referenced local image asset does not exist: {href}")

    viewbox = parse_viewbox(root.attrib.get("viewBox"))
    if viewbox is None:
        width = parse_number(root.attrib.get("width"))
        height = parse_number(root.attrib.get("height"))
        viewbox = (0.0, 0.0, width, height) if width and height else None

    if layout_path is None:
        layout_path = outputs_dir / "poster_layout.json"
    layout_errors, layout_warnings = validate_layout_json(layout_path, viewbox)
    errors.extend(layout_errors)
    warnings.extend(layout_warnings)

    return len(errors) == 0, errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated SVG poster.")
    parser.add_argument("svg_path", nargs="?", default="outputs/poster.svg")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--layout-json", default=None)
    args = parser.parse_args()

    svg_path = Path(args.svg_path)
    outputs_dir = Path(args.outputs_dir)
    layout_path = Path(args.layout_json) if args.layout_json else None

    ok, errors, warnings = validate_svg(svg_path, outputs_dir, layout_path)

    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")

    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("SVG validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
