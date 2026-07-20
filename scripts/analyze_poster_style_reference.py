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
from pathlib import Path
from typing import Any


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


def analyze_reference(image_path: Path, brief: dict[str, Any]) -> dict[str, Any]:
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
    return {
        "status": "passed",
        "method": "quantized_pixel_palette_with_contrast_guards",
        "source_path": str(image_path),
        "source_sha256": image_sha256,
        "sampled_pixel_count": sampled,
        "dominant_colors": [rgb_hex(color) for color, _count in colors.most_common(12)],
        "derived_design_tokens": {"color_palette": palette},
        "scientific_content_influence": "none",
    }


def update_brief(brief: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    updated = dict(brief)
    updated["visual_analysis"] = analysis
    if analysis.get("status") == "passed":
        tokens = dict(updated.get("design_tokens")) if isinstance(updated.get("design_tokens"), dict) else {}
        derived = analysis.get("derived_design_tokens")
        if isinstance(derived, dict) and isinstance(derived.get("color_palette"), dict):
            tokens["color_palette"] = derived["color_palette"]
        updated["design_tokens"] = tokens
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive safe deterministic design tokens from a generated style reference.")
    parser.add_argument("--brief-json", default="outputs/poster_visual_brief.json")
    parser.add_argument("--image", default="outputs/poster_style_reference.png")
    parser.add_argument("--output-json", default="outputs/poster_style_analysis.json")
    parser.add_argument("--mode", choices=["auto", "required"], default="auto")
    args = parser.parse_args()

    brief_path = Path(args.brief_json)
    try:
        brief = read_json(brief_path)
        analysis = analyze_reference(Path(args.image), brief)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
