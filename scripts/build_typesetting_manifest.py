#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from poster_typesetting import (
    canonical_json_sha256,
    clean_space,
    configure_measurement_font,
    estimate_text_width,
    resolve_font,
    wrap_text,
)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def verified_claims(content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in content.get("poster_claims", []):
        if not isinstance(item, dict) or item.get("evidence_status") != "verified":
            continue
        claim_id = clean_space(item.get("id", ""))
        refs = item.get("source_refs", [])
        if claim_id and isinstance(refs, list) and any(
            isinstance(ref, dict) and ref.get("verification_status") == "verified" and ref.get("page")
            for ref in refs
        ):
            result[claim_id] = item
    return result


def build_manifest(content: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    catalog = verified_claims(content)
    typography = design.get("typography") if isinstance(design.get("typography"), dict) else {}
    font = resolve_font(typography.get("font_family", "Arial, Helvetica, sans-serif"))
    configure_measurement_font(font.get("resolved_font_path"))
    card = design.get("card_style") if isinstance(design.get("card_style"), dict) else {}
    padding = float(card.get("padding_x", 20) or 20)
    sections: list[dict[str, Any]] = []
    for section in design.get("sections", []):
        if not isinstance(section, dict):
            continue
        section_id = clean_space(section.get("section_id", ""))
        body_style = section.get("body_style") if isinstance(section.get("body_style"), dict) else {}
        font_size = float(body_style.get("font_size", typography.get("body", 10.8)) or 10.8)
        minimum_font_size = float(body_style.get("minimum_font_size", 8.8) or 8.8)
        line_height_ratio = float(body_style.get("line_height_ratio", typography.get("line_height_ratio", 1.34)) or 1.34)
        width = float(section.get("width", 0) or 0)
        available_width = max(80.0, width - padding * 2)
        slots = section.get("figure_slots", []) if isinstance(section.get("figure_slots"), list) else []
        side_slots = [
            slot for slot in slots if isinstance(slot, dict)
            and float(slot.get("x", 0)) >= float(section.get("x", 0)) + width * 0.42
            and float(slot.get("y", 0)) <= float(section.get("y", 0)) + 90
        ]
        if side_slots:
            available_width = max(
                120.0,
                min(float(slot.get("x", 0)) for slot in side_slots) - float(section.get("x", 0)) - padding * 2,
            )
        entries: list[dict[str, Any]] = []
        budget = max(1, min(5, int(section.get("bullet_budget", 3) or 3)))
        max_lines = 2 if clean_space(section.get("visual_role", "supporting")) == "hero" else 3
        for claim_id in [clean_space(value) for value in section.get("claim_ids", [])][:budget]:
            claim = catalog.get(claim_id)
            text = clean_space(claim.get("claim", "")) if claim else ""
            if not text:
                continue
            lines = wrap_text(text, available_width, font_size, max_lines=max_lines)
            entries.append({
                "claim_id": claim_id,
                "text": text,
                "character_count": len(text),
                "preferred_font_size": font_size,
                "minimum_font_size": minimum_font_size,
                "line_height_ratio": line_height_ratio,
                "available_width": round(available_width, 2),
                "estimated_unwrapped_width": round(estimate_text_width(text, font_size), 2),
                "wrapped_lines": lines,
                "maximum_line_count": max_lines,
                "estimated_line_count": len(lines),
                "source_policy": "verified_claim_text_only",
            })
        sections.append({
            "section_id": section_id,
            "box": {key: section.get(key) for key in ["x", "y", "width", "height"]},
            "text_density": section.get("text_density"),
            "bullet_budget": budget,
            "available_text_width": round(available_width, 2),
            "entries": entries,
        })
    return {
        "version": 2,
        "measurement_backend": "Pillow local font metrics with deterministic fallback",
        "content_sha256": canonical_json_sha256(content),
        "design_sha256": canonical_json_sha256(design),
        "font": font,
        "content_policy": "Only locally verified claim text is measured; reference-image text pixels are ignored.",
        "sections": sections,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an auditable text fitting manifest for the deterministic SVG renderer.")
    parser.add_argument("--content-json", default="outputs/poster_content.json")
    parser.add_argument("--design-json", default="outputs/poster_design_spec.json")
    parser.add_argument("--output-json", default="outputs/poster_typesetting_manifest.json")
    args = parser.parse_args()
    try:
        content = read_json(Path(args.content_json))
        design = read_json(Path(args.design_json))
        manifest = build_manifest(content, design)
        output = Path(args.output_json)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {args.output_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
