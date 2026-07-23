#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


FONT_CANDIDATES = (
    ("Arial", "/System/Library/Fonts/Supplemental/Arial.ttf"),
    ("Helvetica", "/System/Library/Fonts/Helvetica.ttc"),
    ("PingFang SC", "/System/Library/Fonts/PingFang.ttc"),
    ("Hiragino Sans GB", "/System/Library/Fonts/Hiragino Sans GB.ttc"),
    ("Noto Sans CJK SC", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ("DejaVu Sans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)

_active_font_path: str | None = None


def clean_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def canonical_json_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preferred_family_names(value: Any) -> list[str]:
    return [
        item.strip().strip("'\"")
        for item in clean_space(value).split(",")
        if item.strip() and item.strip().casefold() not in {"sans-serif", "serif", "monospace"}
    ]


def resolve_font(preferred_family: Any) -> dict[str, Any]:
    preferred = preferred_family_names(preferred_family)
    by_name = {name.casefold(): (name, path) for name, path in FONT_CANDIDATES}
    ordered = [by_name[name.casefold()] for name in preferred if name.casefold() in by_name]
    ordered.extend(candidate for candidate in FONT_CANDIDATES if candidate not in ordered)
    for family, raw_path in ordered:
        path = Path(raw_path)
        if path.is_file():
            return {
                "status": "resolved",
                "requested_font_family": clean_space(preferred_family) or "sans-serif",
                "resolved_font_family": family,
                "resolved_font_path": str(path),
                "resolved_font_sha256": file_sha256(path),
                "fallback_used": family.casefold() not in {name.casefold() for name in preferred},
            }
    return {
        "status": "fallback_estimator",
        "requested_font_family": clean_space(preferred_family) or "sans-serif",
        "resolved_font_family": preferred[0] if preferred else "sans-serif",
        "resolved_font_path": None,
        "resolved_font_sha256": None,
        "fallback_used": True,
    }


def configure_measurement_font(path: Any) -> bool:
    global _active_font_path
    normalized = clean_space(path)
    if normalized and Path(normalized).is_file():
        _active_font_path = normalized
        measurement_font.cache_clear()
        return True
    _active_font_path = None
    measurement_font.cache_clear()
    return False


@lru_cache(maxsize=96)
def measurement_font(font_size_quarters: int) -> Any:
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    candidates = [_active_font_path] if _active_font_path else []
    candidates.extend(path for _family, path in FONT_CANDIDATES if path != _active_font_path)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, max(4, font_size_quarters))
        except OSError:
            continue
    return None


def estimate_text_width(text: str, font_size: float) -> float:
    normalized = clean_space(text)
    scale = 4
    font = measurement_font(max(4, round(font_size * scale)))
    if font is not None:
        try:
            return float(font.getlength(normalized)) / scale
        except (AttributeError, TypeError):
            try:
                box = font.getbbox(normalized)
                return float(box[2] - box[0]) / scale
            except (AttributeError, TypeError):
                pass
    cjk_count = sum("\u2e80" <= char <= "\u9fff" for char in normalized)
    return (len(normalized) - cjk_count) * font_size * 0.52 + cjk_count * font_size


def wrap_units(text: str) -> list[str]:
    if not any("\u2e80" <= char <= "\u9fff" for char in text):
        return text.split()
    units: list[str] = []
    buffer = ""
    for char in text:
        if "\u2e80" <= char <= "\u9fff":
            if buffer:
                units.extend(buffer.split())
                buffer = ""
            units.append(char)
        elif char.isspace():
            if buffer:
                units.append(buffer)
                buffer = ""
        else:
            buffer += char
    if buffer:
        units.append(buffer)
    return units


def join_wrap_units(units: list[str]) -> str:
    result = ""
    for unit in units:
        if result and not ("\u2e80" <= unit[0] <= "\u9fff") and not ("\u2e80" <= result[-1] <= "\u9fff"):
            result += " "
        result += unit
    return result


def wrap_text(text: str, max_width: float, font_size: float, max_lines: int | None = None) -> list[str]:
    normalized = clean_space(text)
    if not normalized:
        return []
    words = wrap_units(normalized)
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = join_wrap_units(current + [word])
        if current and estimate_text_width(candidate, font_size) > max_width:
            lines.append(join_wrap_units(current))
            current = [word]
            if max_lines is not None and len(lines) >= max_lines:
                break
        else:
            current.append(word)
    if current and (max_lines is None or len(lines) < max_lines):
        lines.append(join_wrap_units(current))
    if max_lines is not None:
        lines = lines[:max_lines]
        if len(lines) == max_lines:
            original = "".join(words)
            displayed = "".join(wrap_units(" ".join(lines)))
            if len(displayed) < len(original):
                lines[-1] = lines[-1].rstrip(".,;:") + "…"
    return lines


def lines_preserve_text(text: str, lines: Any) -> bool:
    if not isinstance(lines, list) or not lines or not all(isinstance(line, str) and line.strip() for line in lines):
        return False
    original = re.sub(r"\s+", "", clean_space(text)).rstrip("…")
    rendered = re.sub(r"\s+", "", "".join(lines)).rstrip("…")
    return rendered == original or (lines[-1].endswith("…") and original.startswith(rendered))
