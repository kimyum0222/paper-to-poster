#!/usr/bin/env python3

from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import math
import re
import sys
from collections import Counter
from itertools import permutations
from pathlib import Path
from typing import Any


CANVAS_WIDTH = 1189
CANVAS_HEIGHT = 841
MIN_SECTION_HEIGHT = 118.0


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read JSON from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def rgb_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02x}" for channel in rgb)


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Invalid color: {value}")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    values = []
    for channel in rgb:
        value = channel / 255
        values.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def contrast_ratio(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    bright, dark = sorted([relative_luminance(first), relative_luminance(second)], reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def mix(first: tuple[int, int, int], second: tuple[int, int, int], first_weight: float) -> tuple[int, int, int]:
    weight = max(0.0, min(1.0, first_weight))
    return tuple(round(a * weight + b * (1 - weight)) for a, b in zip(first, second))  # type: ignore[return-value]


def ensure_contrast(color: tuple[int, int, int], background: tuple[int, int, int], minimum: float = 4.5) -> tuple[int, int, int]:
    adjusted = color
    for _ in range(12):
        if contrast_ratio(adjusted, background) >= minimum:
            return adjusted
        adjusted = mix(adjusted, (0, 0, 0), 0.82)
    return adjusted


def color_features(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    red, green, blue = (channel / 255 for channel in rgb)
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    return hue, lightness, saturation


def sample_quantized_colors(image_path: Path, max_samples: int = 24000) -> tuple[Counter[tuple[int, int, int]], int]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to analyze the generated style reference") from exc
    try:
        pixmap = fitz.Pixmap(str(image_path))
        if pixmap.colorspace is None or pixmap.colorspace.n != 3 or pixmap.alpha:
            pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
    except Exception as exc:
        raise RuntimeError(f"Could not decode generated style reference: {exc}") from exc

    pixel_count = pixmap.width * pixmap.height
    stride = max(1, math.ceil(pixel_count / max_samples))
    samples = pixmap.samples
    channels = pixmap.n
    colors: Counter[tuple[int, int, int]] = Counter()
    sampled = 0
    for pixel_index in range(0, pixel_count, stride):
        offset = pixel_index * channels
        if offset + 2 >= len(samples):
            break
        rgb = tuple((samples[offset + channel] // 24) * 24 + 12 for channel in range(3))
        rgb = tuple(min(255, value) for value in rgb)  # type: ignore[assignment]
        colors[rgb] += 1  # type: ignore[arg-type]
        sampled += 1
    if not colors:
        raise RuntimeError("Generated style reference contained no readable pixels")
    return colors, sampled


def load_rgb_grid(image_path: Path, max_dimension: int = 256) -> tuple[list[tuple[int, int, int]], int, int, int, int]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to analyze the generated style reference") from exc
    try:
        pixmap = fitz.Pixmap(str(image_path))
        if pixmap.colorspace is None or pixmap.colorspace.n != 3 or pixmap.alpha:
            pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
    except Exception as exc:
        raise RuntimeError(f"Could not decode generated style reference: {exc}") from exc

    source_width = pixmap.width
    source_height = pixmap.height
    scale = max(1.0, max(source_width, source_height) / max_dimension)
    width = max(1, round(source_width / scale))
    height = max(1, round(source_height / scale))
    samples = pixmap.samples
    channels = pixmap.n
    pixels: list[tuple[int, int, int]] = []
    for y in range(height):
        source_y = min(source_height - 1, round(y * (source_height - 1) / max(1, height - 1)))
        for x in range(width):
            source_x = min(source_width - 1, round(x * (source_width - 1) / max(1, width - 1)))
            offset = (source_y * source_width + source_x) * channels
            pixels.append(tuple(samples[offset + channel] for channel in range(3)))  # type: ignore[arg-type]
    return pixels, width, height, source_width, source_height


def color_distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))


def quantize(rgb: tuple[int, int, int], step: int = 16) -> tuple[int, int, int]:
    return tuple(min(255, (channel // step) * step + step // 2) for channel in rgb)  # type: ignore[return-value]


def bounded(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def runs_where(values: list[float], predicate: Any) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values + [float("inf")]):
        if index < len(values) and predicate(value):
            if start is None:
                start = index
        elif start is not None:
            runs.append((start, index))
            start = None
    return runs


def fill_short_false_runs(mask: list[bool], width: int, height: int, horizontal_gap: int, vertical_gap: int) -> list[bool]:
    """Close short holes caused by placeholder text without joining separate cards."""
    closed = list(mask)
    for y in range(height):
        row_start = y * width
        row = closed[row_start:row_start + width]
        for start, end in runs_where([1.0 if value else 0.0 for value in row], lambda value: value == 0.0):
            if 0 < start and end < width and end - start <= horizontal_gap:
                for x in range(start, end):
                    closed[row_start + x] = True
    for x in range(width):
        column = [closed[y * width + x] for y in range(height)]
        for start, end in runs_where([1.0 if value else 0.0 for value in column], lambda value: value == 0.0):
            if 0 < start and end < height and end - start <= vertical_gap:
                for y in range(start, end):
                    closed[y * width + x] = True
    return closed


def connected_rectangles(mask: list[bool], width: int, height: int) -> list[dict[str, Any]]:
    visited = bytearray(width * height)
    rectangles: list[dict[str, Any]] = []
    for start_index, enabled in enumerate(mask):
        if not enabled or visited[start_index]:
            continue
        stack = [start_index]
        visited[start_index] = 1
        min_x = max_x = start_index % width
        min_y = max_y = start_index // width
        area = 0
        while stack:
            index = stack.pop()
            x = index % width
            y = index // width
            area += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for neighbor in (index - 1, index + 1, index - width, index + width):
                if neighbor < 0 or neighbor >= width * height or visited[neighbor] or not mask[neighbor]:
                    continue
                neighbor_x = neighbor % width
                neighbor_y = neighbor // width
                if abs(neighbor_x - x) + abs(neighbor_y - y) != 1:
                    continue
                visited[neighbor] = 1
                stack.append(neighbor)
        rect_width = max_x - min_x + 1
        rect_height = max_y - min_y + 1
        rectangle_area = rect_width * rect_height
        rectangles.append({
            "x0": min_x,
            "y0": min_y,
            "x1": max_x + 1,
            "y1": max_y + 1,
            "width": rect_width,
            "height": rect_height,
            "area": area,
            "fill_ratio": area / max(1, rectangle_area),
        })
    return rectangles


def detect_panel_rectangles(
    pixels: list[tuple[int, int, int]],
    width: int,
    height: int,
    body_start: int,
    body_end: int,
    background: tuple[int, int, int],
    expected_sections: int,
) -> dict[str, Any]:
    """Detect light rounded-card interiors and separate short decorative strips."""
    background_luminance = relative_luminance(background)
    raw_mask: list[bool] = []
    for y in range(height):
        for x in range(width):
            pixel = pixels[y * width + x]
            luminance = relative_luminance(pixel)
            red, green, blue = pixel
            neutral = max(pixel) - min(pixel) <= 18
            light_card = luminance >= max(0.935, background_luminance + 0.025)
            separated_from_background = color_distance(pixel, background) >= 16
            warm_highlight = red >= 248 and green >= 240 and blue >= 236 and red - blue >= 6
            raw_mask.append(
                body_start <= y < body_end
                and neutral
                and light_card
                and separated_from_background
                and (min(red, green, blue) >= 248 or warm_highlight)
            )

    closed = fill_short_false_runs(
        raw_mask,
        width,
        height,
        horizontal_gap=1,
        vertical_gap=1,
    )
    components = connected_rectangles(closed, width, height)
    candidates: list[dict[str, Any]] = []
    decorative: list[dict[str, Any]] = []
    body_height = max(1, body_end - body_start)
    for component in components:
        width_fraction = component["width"] / width
        height_fraction = component["height"] / height
        body_height_fraction = component["height"] / body_height
        area_fraction = component["width"] * component["height"] / max(1, width * height)
        if width_fraction < 0.12 or height_fraction < 0.045 or component["fill_ratio"] < 0.42:
            continue
        normalized = {
            "x": round(component["x0"] / width, 4),
            "y": round(component["y0"] / height, 4),
            "width": round(width_fraction, 4),
            "height": round(height_fraction, 4),
            "area_fraction": round(area_fraction, 5),
            "fill_ratio": round(component["fill_ratio"], 4),
            "confidence": round(bounded(0.45 + component["fill_ratio"] * 0.35 + min(0.2, area_fraction), 0.0, 0.98), 3),
        }
        if body_height_fraction < 0.14 and width_fraction >= 0.28:
            normalized["role"] = "decorative_strip"
            decorative.append(normalized)
        elif body_height_fraction >= 0.14 and area_fraction >= 0.025:
            normalized["role"] = "content_panel"
            candidates.append(normalized)

    candidates.sort(key=lambda panel: (panel["y"], panel["x"]))
    decorative.sort(key=lambda panel: (panel["y"], panel["x"]))
    if len(candidates) == expected_sections:
        status = "passed"
        reason = "Detected one content panel for every validated narrative section."
    else:
        status = "degraded"
        reason = f"Detected {len(candidates)} content panels for {expected_sections} validated sections."
    return {
        "status": status,
        "reason": reason,
        "expected_section_count": expected_sections,
        "detected_content_panel_count": len(candidates),
        "detected_decorative_strip_count": len(decorative),
        "panels": candidates,
        "decorative_strips": decorative,
    }


def analyze_spatial_composition(
    image_path: Path,
    preferred_columns: int,
    expected_sections: int = 0,
) -> dict[str, Any]:
    pixels, width, height, source_width, source_height = load_rgb_grid(image_path)
    border_depth = max(1, round(min(width, height) * 0.025))
    border_pixels = [
        pixels[y * width + x]
        for y in range(height)
        for x in range(width)
        if x < border_depth or x >= width - border_depth or y < border_depth or y >= height - border_depth
    ]
    background = Counter(quantize(pixel) for pixel in border_pixels).most_common(1)[0][0]
    luminances = [relative_luminance(pixel) for pixel in pixels]
    dark_threshold = 0.30

    row_dark_ratio = [
        sum(luminances[y * width + x] <= dark_threshold for x in range(width)) / width
        for y in range(height)
    ]
    header_candidates = [index for index, ratio in enumerate(row_dark_ratio[: max(2, round(height * 0.34))]) if ratio >= 0.42]
    if header_candidates:
        header_end = max(header_candidates) + 1
        header_fraction = bounded(header_end / height, 0.10, 0.20)
        header_detected = True
    else:
        header_fraction = 0.14
        header_detected = False

    body_start = min(height - 1, max(0, round(height * (header_fraction + 0.025))))
    body_end = max(body_start + 1, round(height * 0.955))
    active = [
        color_distance(pixel, background) >= 19 or relative_luminance(pixel) <= relative_luminance(background) - 0.055
        for pixel in pixels
    ]
    body_height = max(1, body_end - body_start)
    column_activity = [
        sum(active[y * width + x] for y in range(body_start, body_end)) / body_height
        for x in range(width)
    ]
    active_columns = [index for index, ratio in enumerate(column_activity) if ratio >= 0.12]
    if active_columns:
        left_fraction = bounded(min(active_columns) / width, 0.02, 0.07)
        right_fraction = bounded((width - 1 - max(active_columns)) / width, 0.02, 0.07)
        margin_fraction = (left_fraction + right_fraction) / 2
    else:
        margin_fraction = 0.03

    interior_low_runs = [
        (start, end) for start, end in runs_where(column_activity, lambda value: value < 0.075)
        if start > width * 0.08 and end < width * 0.92
    ]
    candidate_gutter_runs = sorted(
        (
            (start, end) for start, end in interior_low_runs
            if width * 0.008 <= end - start <= width * 0.065
        ),
        key=lambda run: run[1] - run[0],
        reverse=True,
    )
    expected_gutters = max(1, preferred_columns - 1)
    selected_gutter_runs = sorted(candidate_gutter_runs[:expected_gutters])
    selected_gutters = [end - start for start, end in selected_gutter_runs]
    gutter_fraction = (
        sum(selected_gutters) / len(selected_gutters) / width if selected_gutters else 0.0185
    )
    gutter_fraction = bounded(gutter_fraction, 0.012, 0.035)

    body_row_activity = [
        sum(active[y * width + x] for x in range(width)) / width
        for y in range(body_start, body_end)
    ]
    horizontal_gaps = [
        end - start for start, end in runs_where(body_row_activity, lambda value: value < 0.075)
        if 1 <= end - start <= height * 0.05
    ]
    panel_gap_fraction = (
        sorted(horizontal_gaps)[len(horizontal_gaps) // 2] / height if horizontal_gaps else 0.021
    )
    panel_gap_fraction = bounded(panel_gap_fraction, 0.014, 0.032)

    column_bounds: list[tuple[int, int]] = []
    if len(selected_gutter_runs) == preferred_columns - 1:
        left_edge = min(active_columns) if active_columns else round(width * margin_fraction)
        right_edge = max(active_columns) + 1 if active_columns else round(width * (1 - margin_fraction))
        cursor = left_edge
        for start, end in selected_gutter_runs:
            column_bounds.append((cursor, start))
            cursor = end
        column_bounds.append((cursor, right_edge))
        if any(end - start < width * 0.14 for start, end in column_bounds):
            column_bounds = []

    vertical_gaps_by_column: list[list[float]] = []
    for start_x, end_x in column_bounds:
        column_pixel_width = max(1, end_x - start_x)
        row_activity = [
            sum(active[y * width + x] for x in range(start_x, end_x)) / column_pixel_width
            for y in range(body_start, body_end)
        ]
        gap_runs = [
            (start, end) for start, end in runs_where(row_activity, lambda value: value < 0.10)
            if height * 0.008 <= end - start <= height * 0.06
            and start > len(row_activity) * 0.05
            and end < len(row_activity) * 0.95
        ]
        vertical_gaps_by_column.append([
            round(((start + end) / 2) / max(1, len(row_activity)), 4)
            for start, end in gap_runs
        ])

    mean_luminance = sum(luminances) / len(luminances)
    luminance_variance = sum((value - mean_luminance) ** 2 for value in luminances) / len(luminances)
    panel_detection = detect_panel_rectangles(
        pixels,
        width,
        height,
        body_start,
        body_end,
        background,
        expected_sections,
    ) if expected_sections else {
        "status": "not_requested",
        "reason": "No validated narrative section count was supplied.",
        "expected_section_count": 0,
        "detected_content_panel_count": 0,
        "detected_decorative_strip_count": 0,
        "panels": [],
        "decorative_strips": [],
    }
    return {
        "reference_width_px": source_width,
        "reference_height_px": source_height,
        "sample_grid_width": width,
        "sample_grid_height": height,
        "reference_aspect_ratio": round(source_width / max(1, source_height), 4),
        "estimated_background": rgb_hex(background),
        "header_detected": header_detected,
        "header_fraction": round(header_fraction, 4),
        "margin_fraction": round(margin_fraction, 4),
        "gutter_fraction": round(gutter_fraction, 4),
        "panel_gap_fraction": round(panel_gap_fraction, 4),
        "luminance_variance": round(luminance_variance, 5),
        "preferred_column_count": preferred_columns,
        "detected_column_bounds": [
            [round(start / width, 4), round(end / width, 4)] for start, end in column_bounds
        ],
        "detected_vertical_gap_fractions": vertical_gaps_by_column,
        "panel_detection": panel_detection,
    }


def hue_distance(first: float, second: float) -> float:
    distance = abs(first - second)
    return min(distance, 1 - distance)


def choose_distinct(candidates: list[tuple[int, int, int]], chosen: list[tuple[int, int, int]], minimum_hue_distance: float = 0.10) -> tuple[int, int, int] | None:
    for candidate in candidates:
        hue, _lightness, _saturation = color_features(candidate)
        if all(hue_distance(hue, color_features(existing)[0]) >= minimum_hue_distance for existing in chosen):
            return candidate
    return candidates[0] if candidates else None


def derive_palette(colors: Counter[tuple[int, int, int]], fallback: dict[str, Any]) -> dict[str, str]:
    ranked = [color for color, _count in colors.most_common(48)]
    white = (255, 255, 255)
    text = hex_rgb(str(fallback.get("text", "#172033")))

    light = [color for color in ranked if relative_luminance(color) >= 0.78 and color_features(color)[2] <= 0.45]
    background = next((color for color in light if contrast_ratio(text, color) >= 7), hex_rgb(str(fallback.get("background", "#eef3f8"))))
    dark = [color for color in ranked if relative_luminance(color) <= 0.22]
    header = next((color for color in dark if contrast_ratio(white, color) >= 7), hex_rgb(str(fallback.get("header_background", "#172a46"))))

    saturated = [
        color for color in ranked
        if color_features(color)[2] >= 0.38 and 0.16 <= relative_luminance(color) <= 0.62
    ]
    primary = choose_distinct(saturated, []) or hex_rgb(str(fallback.get("accent_primary", "#3157c8")))
    secondary = choose_distinct(saturated, [primary]) or hex_rgb(str(fallback.get("accent_secondary", "#0f766e")))
    warm = [color for color in saturated if color_features(color)[0] <= 0.13 or color_features(color)[0] >= 0.94]
    result = choose_distinct(warm, [primary, secondary], 0.05) or hex_rgb(str(fallback.get("accent_result", "#d15b32")))
    purple = [color for color in saturated if 0.68 <= color_features(color)[0] <= 0.86]
    idea = choose_distinct(purple, [primary, secondary], 0.05) or hex_rgb(str(fallback.get("accent_idea", "#7656b5")))
    cyan = [color for color in saturated if 0.46 <= color_features(color)[0] <= 0.58]
    contribution = choose_distinct(cyan, [secondary], 0.04) or hex_rgb(str(fallback.get("accent_contribution", "#1686a0")))

    primary = ensure_contrast(primary, white)
    secondary = ensure_contrast(secondary, white)
    result = ensure_contrast(result, (255, 248, 242))
    idea = ensure_contrast(idea, white)
    contribution = ensure_contrast(contribution, white)
    return {
        "background": rgb_hex(background),
        "panel": "#ffffff",
        "panel_stroke": rgb_hex(mix(header, white, 0.18)),
        "text": rgb_hex(text),
        "muted": str(fallback.get("muted", "#5c687a")),
        "accent_primary": rgb_hex(primary),
        "accent_secondary": rgb_hex(secondary),
        "accent_result": rgb_hex(result),
        "accent_neutral": str(fallback.get("accent_neutral", "#526176")),
        "accent_idea": rgb_hex(idea),
        "accent_contribution": rgb_hex(contribution),
        "header_rule": rgb_hex(mix(header, white, 0.32)),
        "header_background": rgb_hex(header),
        "header_text": "#ffffff",
        "header_muted": rgb_hex(mix(header, white, 0.15)),
        "highlight_background": rgb_hex(mix(result, white, 0.10)),
        "figure_background": rgb_hex(mix(background, white, 0.70)),
    }


def content_sha256(content: dict[str, Any]) -> str:
    payload = json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_analysis_context(
    brief: dict[str, Any],
    content: dict[str, Any] | None,
    narrative_plan: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if narrative_plan is None:
        return {}
    if content is None:
        raise ValueError("Poster content is required when a narrative plan is supplied for spatial analysis")
    expected_hash = content_sha256(content)
    if str(narrative_plan.get("source_content_sha256", "")).strip().lower() != expected_hash:
        raise ValueError("Narrative plan does not match the supplied poster content")
    linkage = brief.get("narrative_plan_linkage") if isinstance(brief.get("narrative_plan_linkage"), dict) else {}
    layout = brief.get("layout_requirements") if isinstance(brief.get("layout_requirements"), dict) else {}
    if linkage.get("validation_status") != "passed" or not layout.get("validated"):
        raise ValueError("Visual brief does not contain a validated narrative layout")
    if str(linkage.get("source_content_sha256", "")).strip().lower() != expected_hash:
        raise ValueError("Visual brief narrative linkage does not match the supplied poster content")

    claims = {
        str(item.get("id", "")).strip(): item
        for item in content.get("poster_claims", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    figures = {
        str(item.get("id", "")).strip(): item
        for item in content.get("figures_to_use", [])
        if isinstance(item, dict) and str(item.get("id", "")).strip()
    }
    sections: dict[str, dict[str, Any]] = {}
    for item in narrative_plan.get("sections", []):
        if not isinstance(item, dict):
            continue
        section_id = str(item.get("id", "")).strip()
        claim_ids = [str(value).strip() for value in item.get("claim_ids", []) if str(value).strip()]
        figure_ids = [str(value).strip() for value in item.get("figure_ids", []) if str(value).strip()]
        if any(claim_id not in claims for claim_id in claim_ids):
            raise ValueError(f"Narrative section {section_id} contains an unknown poster claim ID")
        if any(figure_id not in figures for figure_id in figure_ids):
            raise ValueError(f"Narrative section {section_id} contains an unknown source figure ID")
        sections[section_id] = {
            "heading": str(item.get("heading", "") or item.get("heading_suggestion", "")).strip(),
            "claim_ids": claim_ids,
            "figure_ids": figure_ids,
        }
    return sections


def build_figure_slots(
    section: dict[str, Any],
    narrative: dict[str, Any],
    palette: dict[str, str],
) -> list[dict[str, Any]]:
    source_slots = section.get("figure_slots", [])
    if not isinstance(source_slots, list) or not source_slots:
        return []
    x = float(section["x"])
    y = float(section["y"])
    width = float(section["width"])
    height = float(section["height"])
    padding = min(20.0, max(14.0, width * 0.055))
    available_width = width - padding * 2
    if (
        str(section.get("visual_role", "")) == "hero"
        and len(source_slots) == 1
        and width / max(1.0, height) >= 2.4
    ):
        raw_slot = source_slots[0] if isinstance(source_slots[0], dict) else {}
        ratio = bounded(float(raw_slot.get("aspect_ratio", 1.0) or 1.0), 0.25, 4.0)
        frame_width = width * 0.52 - padding
        frame_height = min(height - 82.0, frame_width / ratio + 32.0)
        frame_height = max(90.0, frame_height)
        figure_id = str(raw_slot.get("figure_id", "")).strip()
        narrative_figure_ids = narrative.get("figure_ids", []) if isinstance(narrative, dict) else []
        if not figure_id and narrative_figure_ids:
            figure_id = str(narrative_figure_ids[0]).strip()
        return [{
            "figure_id": figure_id,
            "asset_class": "source_evidence",
            "x": round(x + width - padding - frame_width, 2),
            "y": round(y + 68.0, 2),
            "width": round(frame_width, 2),
            "height": round(frame_height, 2),
            "aspect_ratio": round(ratio, 4),
            "preserve_aspect_ratio": "xMidYMid meet",
            "background": palette.get("figure_background", "#f8fafc"),
        }]
    maximum_figure_height = max(48.0, height - 86.0)
    minimum_figure_height = min(72.0, maximum_figure_height)
    figure_area_height = bounded(
        height * (0.48 if len(source_slots) == 1 else 0.52),
        minimum_figure_height,
        maximum_figure_height,
    )
    gap = 10.0
    slot_height = (figure_area_height - gap * (len(source_slots) - 1)) / len(source_slots)
    if slot_height < 40.0:
        return []
    start_y = y + height - padding - figure_area_height
    narrative_figure_ids = narrative.get("figure_ids", []) if isinstance(narrative, dict) else []
    slots: list[dict[str, Any]] = []
    for index, raw_slot in enumerate(source_slots):
        if not isinstance(raw_slot, dict):
            continue
        ratio = bounded(float(raw_slot.get("aspect_ratio", 1.0) or 1.0), 0.25, 4.0)
        frame_height = slot_height
        frame_width = min(available_width, frame_height * ratio)
        if frame_width < available_width * 0.66:
            frame_width = available_width * 0.66
        slot_x = x + padding + (available_width - frame_width) / 2
        figure_id = str(raw_slot.get("figure_id", "")).strip()
        if not figure_id and index < len(narrative_figure_ids):
            figure_id = str(narrative_figure_ids[index]).strip()
        slots.append({
            "figure_id": figure_id,
            "asset_class": "source_evidence",
            "x": round(slot_x, 2),
            "y": round(start_y + index * (slot_height + gap), 2),
            "width": round(frame_width, 2),
            "height": round(frame_height, 2),
            "aspect_ratio": round(ratio, 4),
            "preserve_aspect_ratio": "xMidYMid meet",
            "background": palette.get("figure_background", "#f8fafc"),
        })
    return slots


def assign_sections_to_panels(
    raw_sections: list[dict[str, Any]],
    detected_panels: list[dict[str, Any]],
    hero_section_id: str,
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], dict[str, Any]]:
    """Match narrative demand to anonymous reference panels without reading pixels as content."""
    ordered_sections = sorted(raw_sections, key=lambda section: int(section.get("order", 999) or 999))
    ordered_panels = sorted(
        detected_panels,
        key=lambda panel: (float(panel.get("y", 0)), float(panel.get("x", 0))),
    )
    if len(ordered_sections) != len(ordered_panels):
        raise ValueError("Section and detected-panel counts must match before assignment")

    panel_areas = [
        max(0.000001, float(panel.get("width", 0)) * float(panel.get("height", 0)))
        for panel in ordered_panels
    ]
    panel_area_total = sum(panel_areas)
    panel_weights = [area / panel_area_total for area in panel_areas]

    section_demands: list[float] = []
    for section in ordered_sections:
        supplied_weight = float(section.get("relative_area_weight", 0) or 0)
        if supplied_weight > 0:
            section_demands.append(supplied_weight)
            continue
        density = str(section.get("text_density", "medium"))
        bullet_budget = max(1, int(section.get("bullet_budget", 3) or 3))
        figure_count = len(section.get("figure_slots", [])) if isinstance(section.get("figure_slots"), list) else 0
        demand = 1.0 + bullet_budget * 0.18 + figure_count * 1.1
        demand *= {"short": 0.85, "medium": 1.0, "long": 1.2}.get(density, 1.0)
        if str(section.get("visual_role", "")) == "hero":
            demand *= 1.5
        section_demands.append(demand)
    section_demand_total = sum(section_demands)
    section_weights = [demand / section_demand_total for demand in section_demands]

    hero_index = next(
        (
            index
            for index, section in enumerate(ordered_sections)
            if str(section.get("id", "")).strip() == hero_section_id
            or str(section.get("visual_role", "")) == "hero"
        ),
        None,
    )
    largest_panel_index = max(range(len(ordered_panels)), key=lambda index: panel_areas[index])
    best_assignment: tuple[int, ...] | None = None
    best_cost = float("inf")
    maximum_rank_delta = max(1, len(ordered_sections) - 1)
    for assignment in permutations(range(len(ordered_panels))):
        if hero_index is not None and assignment[hero_index] != largest_panel_index:
            continue
        cost = 0.0
        for section_index, panel_index in enumerate(assignment):
            area_delta = section_weights[section_index] - panel_weights[panel_index]
            cost += area_delta * area_delta * 12.0
            cost += abs(section_index - panel_index) / maximum_rank_delta * 0.025
            section = ordered_sections[section_index]
            has_figure = bool(section.get("figure_slots"))
            if has_figure:
                fill_ratio = bounded(float(ordered_panels[panel_index].get("fill_ratio", 0.75) or 0.75), 0.0, 1.0)
                cost += fill_ratio * 0.015
        if cost < best_cost:
            best_cost = cost
            best_assignment = assignment
    if best_assignment is None:
        raise ValueError("Could not assign narrative sections to detected reference panels")

    assignments = [
        (section, ordered_panels[best_assignment[index]])
        for index, section in enumerate(ordered_sections)
    ]
    audit = {
        "method": "global_relative_area_weight_matching_with_hero_largest_guard",
        "hero_section": hero_section_id or None,
        "hero_assigned_to_largest_panel": hero_index is None or best_assignment[hero_index] == largest_panel_index,
        "total_cost": round(best_cost, 6),
        "section_area_weights": {
            str(section.get("id", "")).strip(): round(section_weights[index], 6)
            for index, section in enumerate(ordered_sections)
        },
        "assignments": [
            {
                "section_id": str(section.get("id", "")).strip(),
                "panel_reading_index": best_assignment[index],
                "panel_area_weight": round(panel_weights[best_assignment[index]], 6),
            }
            for index, section in enumerate(ordered_sections)
        ],
    }
    return assignments, audit


def derive_spatial_design_tokens(
    brief: dict[str, Any],
    measurements: dict[str, Any],
    palette: dict[str, str],
    narrative_sections: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    layout = brief.get("layout_requirements") if isinstance(brief.get("layout_requirements"), dict) else {}
    if not layout.get("validated") or not isinstance(layout.get("sections"), list):
        return {
            "status": "not_applied",
            "reason": "A validated content-aware narrative layout was not supplied.",
            "measurements": measurements,
        }

    raw_sections = [section for section in layout.get("sections", []) if isinstance(section, dict)]
    if not 3 <= len(raw_sections) <= 7:
        raise ValueError("Validated layout must contain three to seven sections")
    columns = max(2, min(4, int(layout.get("preferred_column_count", 3) or 3), len(raw_sections)))
    margin = round(bounded(float(measurements["margin_fraction"]) * CANVAS_WIDTH, 26.0, 50.0), 2)
    gutter = round(bounded(float(measurements["gutter_fraction"]) * CANVAS_WIDTH, 16.0, 34.0), 2)
    panel_gap = round(bounded(float(measurements["panel_gap_fraction"]) * CANVAS_HEIGHT, 12.0, 26.0), 2)
    header_height = round(bounded(float(measurements["header_fraction"]) * CANVAS_HEIGHT, 92.0, 145.0), 2)
    footer_height = 32.0
    body_y = header_height + panel_gap
    body_height = CANVAS_HEIGHT - body_y - footer_height - 10.0
    panel_detection = measurements.get("panel_detection") if isinstance(measurements.get("panel_detection"), dict) else {}
    detected_panels = panel_detection.get("panels") if isinstance(panel_detection.get("panels"), list) else []
    if panel_detection.get("status") != "passed" or len(detected_panels) != len(raw_sections):
        return {
            "status": "degraded",
            "reason": panel_detection.get("reason") or "Reference panel geometry could not be recovered safely.",
            "source": "reference_pixels_plus_verified_narrative_constraints",
            "measurements": measurements,
        }

    column_width = (CANVAS_WIDTH - margin * 2 - gutter * (columns - 1)) / columns
    detected_bounds = measurements.get("detected_column_bounds", [])
    column_geometry: list[tuple[float, float]] = []
    if isinstance(detected_bounds, list) and len(detected_bounds) == columns:
        for bound in detected_bounds:
            if not isinstance(bound, list) or len(bound) != 2:
                column_geometry = []
                break
            start = bounded(float(bound[0]), 0.0, 1.0) * CANVAS_WIDTH
            end = bounded(float(bound[1]), 0.0, 1.0) * CANVAS_WIDTH
            if end - start < 150:
                column_geometry = []
                break
            column_geometry.append((start, end - start))
    if len(column_geometry) != columns:
        column_geometry = [
            (margin + column_index * (column_width + gutter), column_width)
            for column_index in range(columns)
        ]
    vertical_gaps = measurements.get("detected_vertical_gap_fractions", [])

    design_sections: list[dict[str, Any]] = []
    reference_body_top = bounded(float(measurements.get("header_fraction", 0.14)) + 0.025, 0.10, 0.30)
    reference_body_bottom = 0.955
    reference_body_span = max(0.2, reference_body_bottom - reference_body_top)
    hero_id = str(layout.get("hero_section", "")).strip()
    assigned_sections, panel_assignment = assign_sections_to_panels(
        raw_sections,
        [panel for panel in detected_panels if isinstance(panel, dict)],
        hero_id,
    )
    for raw_section, panel in assigned_sections:
        section_id = str(raw_section.get("id", "")).strip()
        narrative = narrative_sections.get(section_id, {})
        density = str(raw_section.get("text_density", "medium"))
        role = str(raw_section.get("visual_role", "supporting"))
        section_x = bounded(float(panel.get("x", 0.03)), 0.0, 1.0) * CANVAS_WIDTH
        section_width = bounded(float(panel.get("width", 0.25)), 0.12, 1.0) * CANVAS_WIDTH
        relative_y = (float(panel.get("y", reference_body_top)) - reference_body_top) / reference_body_span
        relative_height = float(panel.get("height", 0.2)) / reference_body_span
        section_y = body_y + bounded(relative_y, 0.0, 1.0) * body_height
        section_height = bounded(relative_height, 0.08, 1.0) * body_height
        section_width = min(section_width, CANVAS_WIDTH - section_x - margin * 0.5)
        section_height = min(section_height, body_y + body_height - section_y)
        nominal_column_width = max(1.0, (CANVAS_WIDTH - 2 * margin) / columns)
        column = max(1, min(columns, int(section_x / nominal_column_width) + 1))
        column_span = max(1, min(columns, round(section_width / nominal_column_width)))
        section = {
            "section_id": section_id,
            "heading": narrative.get("heading") or raw_section.get("semantic_role") or section_id.replace("_", " ").title(),
            "reading_order": int(raw_section.get("order", len(design_sections) + 1) or len(design_sections) + 1),
            "column": column,
            "column_span": column_span,
            "reference_panel_confidence": float(panel.get("confidence", 0.0) or 0.0),
            "x": round(section_x, 2),
            "y": round(section_y, 2),
            "width": round(section_width, 2),
            "height": round(section_height, 2),
            "background": palette.get("highlight_background") if role == "hero" else palette.get("panel", "#ffffff"),
            "accent": palette.get("accent_result") if role == "hero" else palette.get("accent_primary"),
            "visual_role": role,
            "priority": int(raw_section.get("priority", 3) or 3),
            "text_density": density,
            "bullet_budget": int(raw_section.get("bullet_budget", 3) or 3),
            "claim_ids": list(narrative.get("claim_ids", [])),
            "figure_ids": list(narrative.get("figure_ids", [])),
            "title_style": {
                "font_size": 18.0 if role == "hero" else 16.5,
                "font_weight": 700,
                "color": palette.get("text", "#162033"),
            },
            "body_style": {
                "font_size": {"short": 11.2, "medium": 10.6, "long": 9.8}.get(density, 10.6),
                "minimum_font_size": 8.8,
                "line_height_ratio": 1.32,
                "color": palette.get("text", "#162033"),
            },
            "figure_slots": [],
        }
        section["figure_slots"] = build_figure_slots(
            {**section, "figure_slots": raw_section.get("figure_slots", [])},
            narrative,
            palette,
        )
        design_sections.append(section)

    if hero_id and not any(section["section_id"] == hero_id and section["visual_role"] == "hero" for section in design_sections):
        raise ValueError("Derived spatial design lost the narrative hero section")
    decorative_strips = panel_detection.get("decorative_strips") if isinstance(panel_detection.get("decorative_strips"), list) else []
    body_flow = None
    if decorative_strips:
        strip = max(
            (item for item in decorative_strips if isinstance(item, dict)),
            key=lambda item: float(item.get("width", 0)) * float(item.get("height", 0)),
            default=None,
        )
        if strip:
            strip_relative_y = (float(strip.get("y", reference_body_top)) - reference_body_top) / reference_body_span
            strip_relative_h = float(strip.get("height", 0.08)) / reference_body_span
            body_flow = {
                "enabled": True,
                "asset_class": "generated_decorative",
                "render_mode": "vector_substitute",
                "x": round(float(strip.get("x", 0.03)) * CANVAS_WIDTH, 2),
                "y": round(body_y + bounded(strip_relative_y, 0.0, 1.0) * body_height, 2),
                "width": round(float(strip.get("width", 0.45)) * CANVAS_WIDTH, 2),
                "height": round(bounded(strip_relative_h, 0.04, 0.18) * body_height, 2),
                "concepts": ["reasoning", "observation", "tool", "action", "verification"],
                "scientific_meaning": "none",
            }

    return {
        "status": "passed",
        "source": "reference_pixels_plus_verified_narrative_constraints",
        "panel_assignment": panel_assignment,
        "canvas": {"width": CANVAS_WIDTH, "height": CANVAS_HEIGHT, "unit": "mm-like viewBox units"},
        "grid": {
            "columns": columns,
            "margin": margin,
            "gutter": gutter,
            "header_height": header_height,
            "footer_height": footer_height,
            "panel_gap": panel_gap,
            "body_y": round(body_y, 2),
            "body_height": round(body_height, 2),
            "column_bounds": [
                {"x": round(x, 2), "width": round(width, 2)} for x, width in column_geometry
            ],
        },
        "sections": sorted(design_sections, key=lambda section: section["reading_order"]),
        "spacing": {
            "panel_gap": panel_gap,
            "panel_padding_x": 18.0,
            "panel_padding_y": 16.0,
        },
        "card_style": {
            "radius": 8.0,
            "stroke_width": 1.0,
            "shadow_opacity": round(bounded(0.12 + float(measurements["luminance_variance"]) * 0.8, 0.12, 0.24), 3),
        },
        "decorations": {
            "header_band": bool(measurements.get("header_detected")),
            "header_rounded": bool(measurements.get("header_detected")),
            "accent_rule": False,
            "background_motif": "none",
            "scientific_meaning": "none",
            "header_process": {
                "enabled": bool(measurements.get("header_detected")),
                "asset_class": "generated_decorative",
                "render_mode": "vector_substitute",
                "concepts": ["reasoning", "observation", "tool", "action", "verification"],
                "scientific_meaning": "none",
            },
            "body_flow": body_flow,
        },
        "measurements": measurements,
    }


def analyze_reference(
    image_path: Path,
    brief: dict[str, Any],
    content: dict[str, Any] | None = None,
    narrative_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not image_path.exists():
        raise ValueError(f"Style reference image does not exist: {image_path}")
    generation = brief.get("generation") if isinstance(brief.get("generation"), dict) else {}
    if brief.get("status") != "generated" or generation.get("status") != "generated":
        raise ValueError("Style reference was not generated in this run")
    image_bytes = image_path.read_bytes()
    image_sha256 = hashlib.sha256(image_bytes).hexdigest()
    generation_sha256 = str(generation.get("sha256", "")).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", generation_sha256):
        raise ValueError("Style-reference generation metadata does not contain a valid SHA-256")
    if image_sha256 != generation_sha256:
        raise ValueError("Style reference does not match the image generated in this run")
    tokens = brief.get("design_tokens") if isinstance(brief.get("design_tokens"), dict) else {}
    fallback = tokens.get("color_palette") if isinstance(tokens.get("color_palette"), dict) else {}
    colors, sampled = sample_quantized_colors(image_path)
    palette = derive_palette(colors, fallback)
    narrative_sections = validate_analysis_context(brief, content, narrative_plan)
    layout = brief.get("layout_requirements") if isinstance(brief.get("layout_requirements"), dict) else {}
    preferred_columns = max(2, min(4, int(layout.get("preferred_column_count", 3) or 3)))
    expected_sections = len(layout.get("sections", [])) if layout.get("validated") and isinstance(layout.get("sections"), list) else 0
    measurements = analyze_spatial_composition(image_path, preferred_columns, expected_sections)
    spatial_design = derive_spatial_design_tokens(
        brief,
        measurements,
        palette,
        narrative_sections,
    )
    derived_tokens: dict[str, Any] = {"color_palette": palette}
    if spatial_design.get("status") == "passed":
        for key in ["canvas", "grid", "sections", "spacing", "card_style", "decorations"]:
            derived_tokens[key] = spatial_design[key]
    analysis_status = "passed" if not expected_sections or spatial_design.get("status") == "passed" else "degraded"
    return {
        "status": analysis_status,
        "method": "guarded_pixel_palette_and_spatial_composition_analysis",
        "source_path": str(image_path),
        "source_sha256": image_sha256,
        "sampled_pixel_count": sampled,
        "dominant_colors": [rgb_hex(color) for color, _count in colors.most_common(12)],
        "spatial_design": spatial_design,
        "derived_design_tokens": derived_tokens,
        "scientific_content_influence": "none_from_reference_pixels; verified claim and source-figure IDs only constrain section mapping",
    }


def update_brief(brief: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    updated = dict(brief)
    updated["visual_analysis"] = analysis
    if analysis.get("status") == "passed":
        tokens = dict(updated.get("design_tokens")) if isinstance(updated.get("design_tokens"), dict) else {}
        derived = analysis.get("derived_design_tokens")
        if isinstance(derived, dict):
            for key in ["color_palette", "canvas", "grid", "sections", "spacing", "card_style", "decorations"]:
                if key in derived:
                    tokens[key] = derived[key]
        updated["design_tokens"] = tokens
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive safe deterministic design tokens from a generated style reference.")
    parser.add_argument("--brief-json", default="outputs/poster_visual_brief.json")
    parser.add_argument("--image", default="outputs/poster_style_reference.png")
    parser.add_argument("--output-json", default="outputs/poster_style_analysis.json")
    parser.add_argument("--content-json", default=None)
    parser.add_argument("--narrative-plan-json", default=None)
    parser.add_argument("--mode", choices=["auto", "required"], default="auto")
    args = parser.parse_args()

    brief_path = Path(args.brief_json)
    try:
        brief = read_json(brief_path)
        content = read_json(Path(args.content_json)) if args.content_json else None
        narrative_plan = read_json(Path(args.narrative_plan_json)) if args.narrative_plan_json else None
        analysis = analyze_reference(Path(args.image), brief, content, narrative_plan)
    except Exception as exc:
        generation_status = ""
        try:
            generation_status = str((brief.get("generation") or {}).get("status", ""))
        except (NameError, AttributeError):
            pass
        status = "skipped" if args.mode == "auto" and generation_status != "generated" else "failed"
        analysis = {"status": status, "method": "not_run", "failure": str(exc)}
        if 'brief' in locals():
            write_json(brief_path, update_brief(brief, analysis))
        write_json(Path(args.output_json), analysis)
        print(f"Style-reference analysis {status}: {exc}", file=sys.stderr)
        return 0 if args.mode == "auto" else 2

    write_json(brief_path, update_brief(brief, analysis))
    write_json(Path(args.output_json), analysis)
    print(f"Wrote {args.output_json}")
    print(f"Style-reference analysis: {analysis['status']}")
    return 0 if analysis.get("status") == "passed" or args.mode == "auto" else 2


if __name__ == "__main__":
    sys.exit(main())
