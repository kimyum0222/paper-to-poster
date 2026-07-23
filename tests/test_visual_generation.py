from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_poster_style_reference import analyze_reference, update_brief
from build_poster_design import apply_decorative_vectors, build_design_spec
from build_poster_svg import build_svg
from build_typesetting_manifest import build_manifest
from build_poster_visual_brief import build_visual_brief
from check_poster_style_conformance import build_report as build_conformance_report
from generate_poster_style_with_rightcode import (
    ImageTaskTimeout,
    RightCodeStageError,
    generate_style_reference,
    poll_for_result,
    resume_style_reference,
)
from run_pipeline import write_generation_report
from plan_poster_narrative_with_openai import local_plan
from repair_poster_layout import repair_design
from validate_svg import validate_svg
from vectorize_reference_decorations import sanitize_vector_svg, vectorize_reference


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2n3sAAAAASUVORK5CYII="
)


def rgb_png(width: int, height: int, pixels: list[tuple[int, int, int]]) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = binascii.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    rows = []
    for row in range(height):
        row_pixels = pixels[row * width:(row + 1) * width]
        rows.append(b"\x00" + b"".join(bytes(pixel) for pixel in row_pixels))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def sample_content() -> dict:
    def claim(claim_id: str, section: str, text: str) -> dict:
        return {
            "id": claim_id,
            "section": section,
            "claim": text,
            "source": section,
            "source_text": text,
            "evidence_status": "verified",
            "source_refs": [{
                "page": 1,
                "quote": text,
                "verification_status": "verified",
                "bbox": [10, 20, 300, 40],
            }],
        }

    return {
        "title": "Agent Planning with Verified Tools",
        "take_home_message": "The method improves accuracy by 12%.",
        "result_callouts": [{"label": "Accuracy", "value": "12%", "detail": "Verified result"}],
        "results": {"bullets": ["A verified result"]},
        "method": {"bullets": ["A verified method"]},
        "poster_claims": [
            claim("problem_1", "problem", "Tool use requires reliable planning."),
            claim("take_home_message", "take_home_message", "The verified method coordinates reasoning and acting."),
            claim("method_1", "method", "The method interleaves reasoning traces with actions."),
            claim("result_callout_1", "result_callouts", "The method improves accuracy by 12%."),
        ],
        "figures_to_use": [{
            "id": "figure_1",
            "role": "result_evidence",
            "page": 4,
            "asset_path": "assets/figure_1.png",
            "width_px": 800,
            "height_px": 400,
        }],
    }


def attach_passed_analysis(brief: dict, palette: dict | None = None) -> dict:
    image_sha256 = "a" * 64
    brief["status"] = "generated"
    brief["generation"] = {
        "status": "generated",
        "output_path": "outputs/poster_style_reference.png",
        "sha256": image_sha256,
    }
    brief["visual_analysis"] = {
        "status": "passed",
        "method": "test_pixel_analysis",
        "source_sha256": image_sha256,
        "derived_design_tokens": {
            "color_palette": dict(palette or brief["design_tokens"]["color_palette"]),
        },
    }
    return brief


class VisualBriefTests(unittest.TestCase):
    def test_vtracer_svg_is_sanitized_and_inlined_only_as_decoration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            generated = outputs / "assets" / "generated"
            generated.mkdir(parents=True)
            raw_svg = generated / "raw.svg"
            safe_svg = generated / "header-process-icons.svg"
            raw_svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 40">'
                '<script>alert(1)</script><text x="1" y="10">fake text</text>'
                '<image href="https://example.com/fake.png"/>'
                '<path d="M5 20 L30 5 L55 20" fill="none" stroke="#ffffff"/>'
                '</svg>',
                encoding="utf-8",
            )
            metadata = sanitize_vector_svg(raw_svg, safe_svg)
            sanitized = safe_svg.read_text(encoding="utf-8")
            self.assertEqual(metadata["path_count"], 1)
            self.assertNotIn("script", sanitized)
            self.assertNotIn("fake text", sanitized)
            self.assertNotIn("example.com", sanitized)

            design = build_design_spec(sample_content())
            design["art_direction"] = {"reference_sha256": "a" * 64}
            design["decorations"] = {
                "header_rounded": True,
                "header_process": {
                    "enabled": True,
                    "asset_class": "generated_decorative",
                    "render_mode": "vector_substitute",
                    "concepts": ["reasoning", "verification"],
                    "scientific_meaning": "none",
                },
            }
            design["decorative_assets"] = [{
                "id": "header-process-icons",
                "asset_class": "generated_decorative",
                "render_mode": "vector_substitute",
                "included": True,
                "scientific_meaning": "none",
            }]
            report = {
                "status": "generated",
                "vectorizer": "vtracer",
                "reference_sha256": "a" * 64,
                "assets": [{
                    "id": "header-process-icons",
                    "status": "generated",
                    "vector_path": "assets/generated/header-process-icons.svg",
                    "vector_sha256": hashlib.sha256(safe_svg.read_bytes()).hexdigest(),
                    "element_count": 1,
                }],
            }
            design = apply_decorative_vectors(design, report)
            assets = outputs / "assets"
            (assets / "figure_1.png").write_bytes(ONE_PIXEL_PNG)
            svg, layout = build_svg(sample_content(), outputs, design)
        self.assertIn('data-vectorizer="vtracer"', svg)
        self.assertIn('data-asset-class="generated_decorative"', svg)
        self.assertNotIn("fake text", svg)
        self.assertNotIn("example.com", svg)
        self.assertEqual(layout["decorative_assets"][0]["vector_integrity"], "verified")
        self.assertEqual(layout["decorative_assets"][0]["render_mode"], "vtracer_inline")

    def test_missing_vtracer_auto_mode_records_safe_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "reference.png"
            reference.write_bytes(ONE_PIXEL_PNG)
            digest = hashlib.sha256(reference.read_bytes()).hexdigest()
            report = vectorize_reference(
                reference,
                {"status": "passed", "source_sha256": digest, "spatial_design": {"status": "passed"}},
                root / "assets" / "generated",
                "definitely-not-installed-vtracer",
                "auto",
            )
        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["fallback"], "deterministic_vector_substitute")

    def test_default_reference_aspect_is_close_to_a0_landscape(self) -> None:
        brief = build_visual_brief(sample_content(), "gpt-image-2")
        self.assertEqual(brief["layout_requirements"]["canvas_aspect_ratio"], "4:3")
        self.assertIn("Create a 4:3", brief["prompt"])

    def test_overflow_repair_targets_explicit_section_typography(self) -> None:
        design = {
            "typography": {"body": 10.8},
            "grid": {"header_height": 116},
            "sections": [{
                "section_id": "method",
                "x": 20,
                "y": 140,
                "width": 300,
                "height": 400,
                "body_style": {"font_size": 10.6, "line_height_ratio": 1.32},
            }],
        }
        overflow = {
            "overflow_items": [{
                "section": "method",
                "overflow": {"bottom": True},
            }],
        }
        repaired, actions = repair_design(design, overflow, 1)
        self.assertTrue(actions)
        self.assertLess(repaired["sections"][0]["body_style"]["font_size"], 10.6)
        self.assertEqual(repaired["sections"][0]["height"], 400)

    def test_brief_excludes_claim_metrics_from_image_prompt(self) -> None:
        brief = build_visual_brief(sample_content(), "gpt-image-2", "custom/reference.png")
        self.assertEqual(brief["status"], "planned")
        self.assertEqual(brief["generated_asset_requests"][0]["asset_class"], "style_reference_only")
        self.assertNotIn("12%", brief["prompt"])
        self.assertNotIn(sample_content()["title"], brief["prompt"])
        self.assertIn("Do not render any legible text", brief["prompt"])
        self.assertEqual(brief["source_asset_roles"][0]["asset_class"], "source_evidence")
        self.assertEqual(brief["generated_asset_requests"][0]["output_path"], "custom/reference.png")

    def test_narrative_plan_drives_content_aware_placeholder_layout(self) -> None:
        content = sample_content()
        plan = local_plan(content, "visual brief test")
        brief = build_visual_brief(
            content,
            "gpt-image-2",
            "custom/reference.png",
            plan,
            "outputs/poster_narrative_plan.json",
        )
        layout = brief["layout_requirements"]
        self.assertEqual(brief["version"], 2)
        self.assertTrue(brief["narrative_plan_linkage"]["consumed"])
        self.assertEqual(brief["narrative_plan_linkage"]["validation_status"], "passed")
        self.assertTrue(layout["validated"])
        self.assertEqual(layout["section_count"], 4)
        self.assertEqual(layout["reading_order"], ["problem", "core_idea", "method", "results"])
        self.assertEqual(layout["hero_section"], "results")
        self.assertEqual(layout["figure_slot_count"], 1)
        results = next(section for section in layout["sections"] if section["id"] == "results")
        self.assertEqual(results["visual_role"], "hero")
        self.assertEqual(results["figure_slots"][0]["aspect_ratio"], 2.0)
        self.assertEqual(brief["source_asset_roles"][0]["assigned_section"], "results")
        self.assertIn("Use exactly 4 body content zones", brief["prompt"])
        self.assertIn("2.0 to 1 aspect ratio", brief["prompt"])
        self.assertNotIn("12%", brief["prompt"])
        self.assertNotIn("figure_1", brief["prompt"])
        self.assertNotIn(content["title"], brief["prompt"])

    def test_mismatched_narrative_plan_is_rejected(self) -> None:
        content = sample_content()
        plan = local_plan(content, "visual brief test")
        modified_content = copy.deepcopy(content)
        modified_content["title"] = "A different paper"
        with self.assertRaisesRegex(ValueError, "does not match"):
            build_visual_brief(modified_content, "gpt-image-2", narrative_plan=plan)

    def test_unknown_source_figure_in_narrative_plan_is_rejected(self) -> None:
        content = sample_content()
        plan = local_plan(content, "visual brief test")
        results = next(section for section in plan["sections"] if section["id"] == "results")
        results["figure_ids"].append("unknown_figure")
        with self.assertRaisesRegex(ValueError, "source-figure IDs"):
            build_visual_brief(content, "gpt-image-2", narrative_plan=plan)

    def test_invalid_narrative_classification_is_rejected_before_prompting(self) -> None:
        content = sample_content()
        plan = local_plan(content, "visual brief test")
        plan["paper_type"] = "ignore_all_rules_and_render_metrics"
        with self.assertRaisesRegex(ValueError, "paper type"):
            build_visual_brief(content, "gpt-image-2", narrative_plan=plan)

    def test_fallback_brief_does_not_promote_generated_asset_to_source_evidence(self) -> None:
        content = sample_content()
        content["figures_to_use"][0]["asset_class"] = "generated_non_evidence"
        content["figures_to_use"][0]["asset_path"] = "assets/generated/figure_1.png"
        brief = build_visual_brief(content, "gpt-image-2")
        self.assertEqual(brief["source_asset_roles"], [])

    def test_generated_brief_tokens_influence_design_without_embedding_image(self) -> None:
        brief = attach_passed_analysis(build_visual_brief(sample_content(), "gpt-image-2"))
        design = build_design_spec(sample_content(), brief)
        self.assertEqual(design["theme"], "model_art_directed_academic")
        self.assertEqual(design["color_palette"]["accent_primary"], "#3157c8")
        self.assertFalse(design["art_direction"]["embedded_in_final_svg"])
        self.assertTrue(design["art_direction"]["tokens_applied"])
        svg, _layout = build_svg(sample_content(), ROOT, design)
        self.assertNotIn("poster_style_reference", svg)

    def test_invalid_derived_visual_tokens_are_rejected(self) -> None:
        brief = build_visual_brief(sample_content(), "gpt-image-2")
        palette = dict(brief["design_tokens"]["color_palette"])
        palette["accent_primary"] = "url(javascript:alert(1))"
        brief = attach_passed_analysis(brief, palette)
        design = build_design_spec(sample_content(), brief)
        self.assertEqual(design["color_palette"]["accent_primary"], "#1d4ed8")
        self.assertEqual(design["card_style"]["radius"], 8)

    def test_skipped_brief_does_not_override_default_palette(self) -> None:
        brief = build_visual_brief(sample_content(), "gpt-image-2")
        brief["status"] = "skipped"
        design = build_design_spec(sample_content(), brief)
        self.assertEqual(design["color_palette"]["accent_primary"], "#1d4ed8")
        self.assertEqual(design["art_direction"]["status"], "skipped")

    def test_generated_reference_without_pixel_analysis_does_not_apply_tokens(self) -> None:
        brief = build_visual_brief(sample_content(), "gpt-image-2")
        brief["status"] = "generated"
        brief["generation"] = {"status": "generated", "output_path": "outputs/poster_style_reference.png"}
        design = build_design_spec(sample_content(), brief)
        self.assertEqual(design["color_palette"]["accent_primary"], "#1d4ed8")
        self.assertFalse(design["art_direction"]["tokens_applied"])

    def test_reference_pixels_are_analyzed_into_guarded_design_tokens(self) -> None:
        pixels = [
            (245, 248, 252), (245, 248, 252), (18, 35, 63), (18, 35, 63),
            (49, 87, 200), (49, 87, 200), (15, 118, 110), (209, 91, 50),
            (118, 86, 181), (22, 134, 160), (255, 255, 255), (49, 87, 200),
            (245, 248, 252), (18, 35, 63), (15, 118, 110), (209, 91, 50),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "reference.png"
            image_bytes = rgb_png(4, 4, pixels)
            image_path.write_bytes(image_bytes)
            brief = build_visual_brief(sample_content(), "gpt-image-2")
            brief["status"] = "generated"
            brief["generation"] = {
                "status": "generated",
                "output_path": str(image_path),
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
            }
            analysis = analyze_reference(image_path, brief)

        updated = update_brief(brief, analysis)
        self.assertEqual(analysis["status"], "passed")
        self.assertEqual(len(analysis["source_sha256"]), 64)
        self.assertGreater(analysis["sampled_pixel_count"], 0)
        self.assertRegex(updated["design_tokens"]["color_palette"]["accent_primary"], r"^#[0-9a-f]{6}$")
        design = build_design_spec(sample_content(), updated)
        self.assertTrue(design["art_direction"]["tokens_applied"])
        self.assertEqual(
            design["color_palette"]["accent_primary"],
            updated["design_tokens"]["color_palette"]["accent_primary"],
        )
        svg, _layout = build_svg(sample_content(), ROOT, design)
        self.assertIn(design["color_palette"]["accent_primary"], svg)
        self.assertNotIn("reference.png", svg)

    def test_reference_and_narrative_produce_executable_section_geometry(self) -> None:
        width, height = 160, 90
        background = (238, 243, 248)
        pixels = [background] * (width * height)

        def paint(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
            for y in range(y0, y1):
                for x in range(x0, x1):
                    pixels[y * width + x] = color

        paint(0, 0, width, 14, (18, 35, 63))
        paint(6, 18, 52, 50, (255, 255, 255))
        paint(6, 54, 52, 84, (255, 255, 255))
        paint(57, 18, 106, 84, (255, 255, 255))
        paint(111, 18, 154, 84, (255, 248, 242))
        paint(111, 18, 154, 20, (209, 91, 50))

        content = sample_content()
        plan = local_plan(content, "executable visual geometry test")
        brief = build_visual_brief(content, "gpt-image-2", narrative_plan=plan)
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "reference.png"
            image_bytes = rgb_png(width, height, pixels)
            image_path.write_bytes(image_bytes)
            brief["status"] = "generated"
            brief["generation"] = {
                "status": "generated",
                "output_path": str(image_path),
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
            }
            analysis = analyze_reference(image_path, brief, content, plan)

        updated = update_brief(brief, analysis)
        design = build_design_spec(content, updated)
        self.assertEqual(analysis["spatial_design"]["status"], "passed")
        self.assertEqual(len(analysis["spatial_design"]["measurements"]["detected_column_bounds"]), 3)
        self.assertTrue(design["art_direction"]["spatial_tokens_applied"])
        self.assertEqual(design["layout_source"], "reference_pixels_plus_verified_narrative_constraints")
        self.assertEqual([section["section_id"] for section in design["sections"]], plan["reading_order"])
        self.assertEqual(len(design["sections"]), 4)
        self.assertAlmostEqual(design["sections"][0]["x"], 6 / width * 1189, delta=12)
        hero = next(section for section in design["sections"] if section["section_id"] == plan["hero_section"])
        self.assertEqual(hero["visual_role"], "hero")
        self.assertTrue(any(section["claim_ids"] for section in design["sections"]))
        self.assertTrue(any(section["figure_slots"] for section in design["sections"]))

        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            assets = outputs / "assets"
            assets.mkdir()
            (assets / "figure_1.png").write_bytes(ONE_PIXEL_PNG)
            svg, layout = build_svg(content, outputs, design)
            svg_path = outputs / "poster.svg"
            layout_path = outputs / "poster_layout.json"
            svg_path.write_text(svg, encoding="utf-8")
            layout_path.write_text(json.dumps(layout), encoding="utf-8")
            valid, errors, _warnings, checks = validate_svg(svg_path, outputs, layout_path)

        self.assertTrue(valid, errors)
        self.assertFalse([check for check in checks if check.get("has_overflow")])
        self.assertEqual(layout["template"], "art_directed_grid")
        self.assertEqual(layout["layout_source"], "reference_pixels_plus_verified_narrative_constraints")
        self.assertIn("The method interleaves reasoning traces with", svg)
        self.assertIn("actions.", svg)
        self.assertIn("data:image/png;base64", svg)
        self.assertNotIn("poster_style_reference", svg)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "source figure asset is missing"):
                build_svg(content, Path(tmp), design)

    def test_reference_panels_preserve_spanning_hero_and_vector_decorations(self) -> None:
        width, height = 160, 90
        background = (238, 243, 248)
        pixels = [background] * (width * height)

        def paint(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
            for y in range(y0, y1):
                for x in range(x0, x1):
                    pixels[y * width + x] = color

        paint(0, 0, width, 14, (18, 35, 63))
        paint(4, 17, 38, 47, (255, 255, 255))
        paint(41, 17, 72, 47, (255, 255, 255))
        paint(75, 17, 156, 55, (255, 255, 255))
        paint(4, 49, 72, 55, (255, 255, 255))
        paint(4, 58, 156, 86, (255, 248, 242))

        content = sample_content()
        plan = local_plan(content, "spanning panel test")
        brief = build_visual_brief(content, "gpt-image-2", narrative_plan=plan)
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "reference.png"
            image_bytes = rgb_png(width, height, pixels)
            image_path.write_bytes(image_bytes)
            brief["status"] = "generated"
            brief["generation"] = {
                "status": "generated",
                "output_path": str(image_path),
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
            }
            analysis = analyze_reference(image_path, brief, content, plan)

        design = build_design_spec(content, update_brief(brief, analysis))
        results = next(section for section in design["sections"] if section["section_id"] == "results")
        self.assertEqual(results["column_span"], 3)
        self.assertGreater(results["width"], 1000)
        self.assertTrue(design["decorations"]["body_flow"]["enabled"])
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            assets = outputs / "assets"
            assets.mkdir()
            (assets / "figure_1.png").write_bytes(ONE_PIXEL_PNG)
            svg, layout = build_svg(content, outputs, design)
        self.assertIn('data-asset-class="generated_decorative"', svg)
        self.assertIn('data-concept="verification"', svg)
        self.assertTrue(layout["source_assets"])
        self.assertTrue(all(asset["asset_class"] == "source_evidence" for asset in layout["source_assets"]))
        self.assertTrue(all(asset["sha256"] for asset in layout["source_assets"]))
        self.assertEqual(len(layout["asset_manifest"]), len(layout["source_assets"]) + len(layout["decorative_assets"]))
        manifest = build_manifest(content, design)
        self.assertTrue(any(section["entries"] for section in manifest["sections"]))
        conformance = build_conformance_report(analysis, design, layout)
        self.assertEqual(conformance["status"], "passed")
        self.assertFalse(conformance["pixel_similarity_measured"])

    def test_hero_and_content_demand_control_panel_assignment(self) -> None:
        width, height = 160, 90
        background = (238, 243, 248)
        pixels = [background] * (width * height)

        def paint(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
            for y in range(y0, y1):
                for x in range(x0, x1):
                    pixels[y * width + x] = color

        paint(0, 0, width, 14, (18, 35, 63))
        paint(4, 18, 37, 50, (255, 255, 255))
        paint(4, 54, 37, 84, (255, 255, 255))
        paint(41, 18, 82, 84, (255, 255, 255))
        paint(86, 18, 156, 84, (255, 248, 242))

        content = sample_content()
        content["figures_to_use"].append({
            "id": "figure_method",
            "role": "method_overview",
            "page": 3,
            "asset_path": "assets/figure_method.png",
            "width_px": 720,
            "height_px": 480,
        })
        plan = local_plan(content, "content demand panel assignment test")
        brief = build_visual_brief(content, "gpt-image-2", narrative_plan=plan)
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "reference.png"
            image_bytes = rgb_png(width, height, pixels)
            image_path.write_bytes(image_bytes)
            brief["status"] = "generated"
            brief["generation"] = {
                "status": "generated",
                "output_path": str(image_path),
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
            }
            analysis = analyze_reference(image_path, brief, content, plan)

        self.assertEqual(analysis["spatial_design"]["status"], "passed")
        sections = {
            section["section_id"]: section
            for section in analysis["spatial_design"]["sections"]
        }
        self.assertGreater(sections["results"]["x"], 600)
        self.assertGreater(sections["results"]["width"], sections["method"]["width"])
        self.assertGreater(sections["method"]["x"], sections["problem"]["x"])
        self.assertLess(sections["method"]["x"], sections["results"]["x"])
        self.assertLess(sections["problem"]["y"], sections["core_idea"]["y"])
        assignment = analysis["spatial_design"]["panel_assignment"]
        self.assertEqual(
            assignment["method"],
            "global_relative_area_weight_matching_with_hero_largest_guard",
        )
        self.assertTrue(assignment["hero_assigned_to_largest_panel"])

    def test_missing_reference_panels_is_degraded_not_silently_passed(self) -> None:
        width, height = 120, 70
        background = (238, 243, 248)
        pixels = [background] * (width * height)
        for y in range(0, 11):
            for x in range(width):
                pixels[y * width + x] = (18, 35, 63)
        for y in range(16, 60):
            for x in range(8, 112):
                pixels[y * width + x] = (255, 255, 255)
        content = sample_content()
        plan = local_plan(content, "degraded panel test")
        brief = build_visual_brief(content, "gpt-image-2", narrative_plan=plan)
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "reference.png"
            image_bytes = rgb_png(width, height, pixels)
            image_path.write_bytes(image_bytes)
            brief["status"] = "generated"
            brief["generation"] = {
                "status": "generated",
                "output_path": str(image_path),
                "sha256": hashlib.sha256(image_bytes).hexdigest(),
            }
            analysis = analyze_reference(image_path, brief, content, plan)
        self.assertEqual(analysis["status"], "degraded")
        self.assertEqual(analysis["spatial_design"]["status"], "degraded")
        self.assertNotIn("sections", analysis["derived_design_tokens"])

    def test_hash_mismatch_prevents_visual_tokens_from_reaching_design(self) -> None:
        brief = attach_passed_analysis(build_visual_brief(sample_content(), "gpt-image-2"))
        brief["visual_analysis"]["source_sha256"] = "b" * 64
        design = build_design_spec(sample_content(), brief)
        self.assertFalse(design["art_direction"]["reference_hash_verified"])
        self.assertFalse(design["art_direction"]["tokens_applied"])
        self.assertEqual(design["color_palette"]["accent_primary"], "#1d4ed8")

    def test_failed_run_report_does_not_reuse_stale_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            (outputs / "poster_visual_brief.json").write_text(
                json.dumps({"status": "failed", "provider": "rightcode", "model": "gpt-image-2"}),
                encoding="utf-8",
            )
            (outputs / "poster_visual_generation.json").write_text(
                json.dumps({"status": "failed", "failure": "missing key"}),
                encoding="utf-8",
            )
            (outputs / "poster_style_analysis.json").write_text(
                json.dumps({"status": "passed", "method": "stale_analysis"}),
                encoding="utf-8",
            )
            (outputs / "poster_layout.json").write_text(
                json.dumps({"template": "stale_template", "layout_source": "stale_layout_source"}),
                encoding="utf-8",
            )
            (outputs / "poster_overflow_report.json").write_text(
                json.dumps({"status": "stale_overflow_status", "overflow_line_count": 99}),
                encoding="utf-8",
            )
            steps = [
                {"command": ["python", "scripts/build_poster_visual_brief.py"], "returncode": 0},
                {"command": ["python", "scripts/generate_poster_style_with_rightcode.py"], "returncode": 2},
            ]
            write_generation_report(outputs, "paper.pdf", steps, failed_step=steps[-1]["command"])
            report = (outputs / "generation_report.md").read_text(encoding="utf-8")

        self.assertIn("Reference-pixel analysis: not run", report)
        self.assertIn("Derived design tokens applied: False", report)
        self.assertNotIn("stale_analysis", report)
        self.assertNotIn("stale_template", report)
        self.assertNotIn("stale_layout_source", report)
        self.assertNotIn("stale_overflow_status", report)


class RightCodeAsyncGenerationTests(unittest.TestCase):
    def test_post_disconnect_is_unknown_and_not_safe_to_retry(self) -> None:
        brief = build_visual_brief(sample_content(), "gpt-image-2")

        def requester(*_args) -> dict:
            raise ConnectionError("remote end closed connection")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RightCodeStageError) as caught:
                generate_style_reference(
                    brief,
                    Path(tmp) / "reference.png",
                    "test-key",
                    "https://www.right.codes/draw/v1",
                    "https://www.right.codes/v1",
                    "gpt-image-2",
                    "16:9",
                    "1K",
                    30,
                    5,
                    0.01,
                    requester=requester,
                    sleeper=lambda _seconds: None,
                )

        self.assertEqual(caught.exception.stage, "post_submission")
        self.assertEqual(caught.exception.submission_outcome, "unknown")
        self.assertFalse(caught.exception.safe_to_retry)
        self.assertNotIn("test-key", str(caught.exception))

    def test_get_status_retries_without_new_submission(self) -> None:
        calls = 0

        def requester(method: str, _url: str, _api_key: str, _payload: dict | None, _timeout: float) -> dict:
            nonlocal calls
            self.assertEqual(method, "GET")
            calls += 1
            if calls < 3:
                raise ConnectionError("temporary polling failure")
            return {"data": [{"b64_json": base64.b64encode(ONE_PIXEL_PNG).decode("ascii")}]}

        payload = poll_for_result(
            "task_retry123",
            "https://www.right.codes/v1",
            "test-key",
            30,
            5,
            0.01,
            requester,
            sleeper=lambda _seconds: None,
        )
        self.assertIsNotNone(payload)
        self.assertEqual(calls, 3)

    def test_image_download_retries_without_resubmission(self) -> None:
        responses = [
            {"task_id": "task_download123", "status": "processing"},
            {"data": [{"url": "https://cdn.example.com/result.png?signature=secret"}]},
        ]
        request_calls: list[str] = []
        download_calls = 0

        def requester(method: str, _url: str, _api_key: str, _payload: dict | None, _timeout: float) -> dict:
            request_calls.append(method)
            return responses.pop(0)

        def downloader(_url: str, _timeout: float) -> bytes:
            nonlocal download_calls
            download_calls += 1
            if download_calls < 3:
                raise ConnectionError("temporary CDN failure")
            return ONE_PIXEL_PNG

        brief = build_visual_brief(sample_content(), "gpt-image-2")
        with tempfile.TemporaryDirectory() as tmp:
            metadata = generate_style_reference(
                brief,
                Path(tmp) / "reference.png",
                "test-key",
                "https://www.right.codes/draw/v1",
                "https://www.right.codes/v1",
                "gpt-image-2",
                "16:9",
                "1K",
                30,
                5,
                0.01,
                requester=requester,
                downloader=downloader,
                sleeper=lambda _seconds: None,
            )

        self.assertEqual(request_calls.count("POST"), 1)
        self.assertEqual(download_calls, 3)
        self.assertEqual(metadata["endpoints"]["download"], "https://cdn.example.com/result.png")

    def test_submit_poll_and_save_base64_png(self) -> None:
        responses = [
            {"task_id": "task_123", "status": "processing"},
            {"task_id": "task_123", "status": "in_progress", "progress": 40},
            {"data": [{"b64_json": base64.b64encode(ONE_PIXEL_PNG).decode("ascii")}]},
        ]
        calls: list[tuple[str, str, dict | None]] = []

        def requester(method: str, url: str, api_key: str, payload: dict | None, timeout: float) -> dict:
            self.assertEqual(api_key, "test-key")
            calls.append((method, url, payload))
            return responses.pop(0)

        content = sample_content()
        plan = local_plan(content, "Right Code request metadata test")
        brief = build_visual_brief(content, "gpt-image-2", narrative_plan=plan)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "poster_style_reference.png"
            metadata = generate_style_reference(
                brief,
                output,
                "test-key",
                "https://www.right.codes/draw/v1",
                "https://www.right.codes/v1",
                "gpt-image-2",
                "16:9",
                "1K",
                30,
                5,
                0.01,
                requester=requester,
                downloader=lambda _url, _timeout: b"",
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(output.read_bytes(), ONE_PIXEL_PNG)

        self.assertEqual(metadata["status"], "generated")
        self.assertEqual(metadata["asset_class"], "style_reference_only")
        self.assertFalse(metadata["included_in_final_svg"])
        self.assertTrue(metadata["request"]["content_aware_layout"])
        self.assertEqual(metadata["request"]["section_count"], 4)
        self.assertEqual(metadata["request"]["hero_section"], "results")
        self.assertEqual(metadata["request"]["figure_slot_count"], 1)
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "https://www.right.codes/draw/v1/images/generations")
        self.assertTrue(calls[0][2]["async"])
        self.assertNotIn("imageSize", calls[0][2])
        self.assertIn("/tasks/task_123", calls[1][1])

    def test_resume_existing_task_without_new_submission(self) -> None:
        responses = [
            {"task_id": "task_229cbd3d6c8c4f1c90748b2dbc35df1a", "status": "in_progress", "progress": 72},
            {"data": [{"b64_json": base64.b64encode(ONE_PIXEL_PNG).decode("ascii")}]},
        ]
        calls: list[tuple[str, str, dict | None]] = []

        def requester(method: str, url: str, api_key: str, payload: dict | None, timeout: float) -> dict:
            calls.append((method, url, payload))
            return responses.pop(0)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "resumed.png"
            metadata = resume_style_reference(
                output,
                "test-key",
                "https://www.right.codes/v1",
                "task_229cbd3d6c8c4f1c90748b2dbc35df1a",
                "gpt-image-2",
                30,
                5,
                0.01,
                requester=requester,
                downloader=lambda _url, _timeout: b"",
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(output.read_bytes(), ONE_PIXEL_PNG)

        self.assertTrue(metadata["request"]["resumed"])
        self.assertTrue(calls)
        self.assertTrue(all(method == "GET" and payload is None for method, _url, payload in calls))
        self.assertTrue(all("/tasks/task_229cbd3d6c8c4f1c90748b2dbc35df1a" in url for _method, url, _payload in calls))

    def test_timeout_preserves_resumable_task_id(self) -> None:
        times = iter([0.0, 2.0])
        with self.assertRaises(ImageTaskTimeout) as caught:
            poll_for_result(
                "task_229cbd3d6c8c4f1c90748b2dbc35df1a",
                "https://www.right.codes/v1",
                "test-key",
                1,
                5,
                0.01,
                lambda *_args: {},
                sleeper=lambda _seconds: None,
                clock=lambda: next(times),
            )
        self.assertEqual(caught.exception.task_id, "task_229cbd3d6c8c4f1c90748b2dbc35df1a")

    def test_failed_task_surfaces_provider_message(self) -> None:
        def requester(method: str, url: str, api_key: str, payload: dict | None, timeout: float) -> dict:
            return {"status": "failed", "error": {"message": "upstream failed"}}

        with self.assertRaisesRegex(RuntimeError, "upstream failed"):
            poll_for_result(
                "task_bad",
                "https://www.right.codes/v1",
                "test-key",
                10,
                5,
                0.01,
                requester,
                sleeper=lambda _seconds: None,
            )


if __name__ == "__main__":
    unittest.main()
