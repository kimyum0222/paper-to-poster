from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_reference_with_vision import normalize_report as normalize_reference_report
from apply_visual_review_repairs import apply_review_repairs
from build_poster_design import apply_reference_vision_adjustments
from poster_vision_utils import sha256_file
from review_rendered_poster_with_vision import normalize_report as normalize_preview_report


def base_design(reference_sha256: str) -> dict:
    return {
        "art_direction": {"reference_sha256": reference_sha256},
        "card_style": {"radius": 8.0, "stroke_width": 1.0, "shadow_opacity": 0.18},
        "typography": {
            "title": 34.0,
            "section_title": 16.5,
            "body": 10.8,
            "caption": 8.2,
            "line_height_ratio": 1.34,
        },
        "decorations": {"header_rounded": False, "accent_rule": False},
        "sections": [{
            "section_id": "results",
            "title_style": {"font_size": 18.0},
            "body_style": {"font_size": 10.6, "line_height_ratio": 1.32},
        }],
    }


class ReferenceVisionAnalysisTests(unittest.TestCase):
    def test_normalizer_retains_design_semantics_but_no_visible_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "reference.png"
            reference.write_bytes(b"reference")
            report = normalize_reference_report(
                {
                    "status": "passed",
                    "confidence": 0.91,
                    "visual_language": "technical_editorial",
                    "reading_flow": "hero_then_supporting",
                    "density_style": "balanced",
                    "background_treatment": "soft_gradient",
                    "card_style": {
                        "corner_style": "rounded",
                        "border_emphasis": "defined",
                        "shadow_emphasis": "subtle",
                    },
                    "header_style": {"shape": "rounded", "accent_rule": True},
                    "panel_observations": [{
                        "panel_index": 1,
                        "visual_weight": "hero",
                        "content_alignment": "left",
                        "confidence": 0.8,
                    }],
                    "decorative_regions": [
                        {
                            "kind": "flow_line",
                            "bbox": [0.1, 0.1, 0.2, 0.1],
                            "safe_to_vectorize": True,
                            "confidence": 0.9,
                        },
                        {
                            "kind": "texture",
                            "bbox": [0.0, 0.0, 1.0, 1.0],
                            "safe_to_vectorize": True,
                            "confidence": 1.0,
                        },
                    ],
                    "title_text": "must never survive",
                    "notes": ["balanced modular rhythm"],
                },
                model="vision-test",
                reference_path=reference,
                reference_sha256=sha256_file(reference),
                expected_panel_count=1,
            )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["design_adjustments"]["card_style"]["radius"], 14.0)
        self.assertEqual(len(report["decorative_regions"]), 1)
        self.assertFalse(report["visible_text_retained"])
        self.assertTrue(report["provider_received_style_reference"])
        self.assertNotIn("title_text", report)
        self.assertNotIn("must never survive", str(report))

    def test_design_applies_only_hash_matched_content_free_adjustments(self) -> None:
        reference_sha256 = "a" * 64
        design = base_design(reference_sha256)
        report = {
            "status": "passed",
            "reference_sha256": reference_sha256,
            "scientific_content_influence": "none",
            "method": "multimodal_reference_semantic_analysis",
            "model": "vision-test",
            "visual_language": "modular_cards",
            "design_adjustments": {
                "card_style": {"radius": 14.0, "stroke_width": 1.4, "shadow_opacity": 0.12},
                "decorations": {"header_rounded": True, "accent_rule": True},
            },
        }
        self.assertTrue(apply_reference_vision_adjustments(design, report, reference_sha256))
        self.assertEqual(design["card_style"]["radius"], 14.0)
        self.assertTrue(design["decorations"]["header_rounded"])
        self.assertTrue(design["visual_semantics"]["applied_to_design"])

        mismatch = base_design(reference_sha256)
        bad_report = copy.deepcopy(report)
        bad_report["reference_sha256"] = "b" * 64
        self.assertFalse(apply_reference_vision_adjustments(mismatch, bad_report, reference_sha256))
        self.assertEqual(mismatch["card_style"]["radius"], 8.0)


class PreviewVisionReviewTests(unittest.TestCase):
    def test_review_normalizer_rejects_geometry_text_and_unbounded_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "reference.png"
            preview = Path(tmp) / "preview.png"
            reference.write_bytes(b"reference")
            preview.write_bytes(b"preview")
            design = base_design(sha256_file(reference))
            layout = {
                "section_bounding_boxes": {
                    "results": {"x": 20, "y": 100, "width": 900, "height": 500},
                }
            }
            report = normalize_preview_report(
                {
                    "status": "needs_revision",
                    "scores": {key: 0.7 for key in ["composition", "hierarchy", "spacing", "style_similarity", "readability"]},
                    "summary": "forbidden visible title text",
                    "issues": [
                        {"severity": "medium", "target": "results", "category": "density", "observation": "forbidden quote"},
                        {"severity": "high", "target": "unknown", "category": "spacing"},
                    ],
                    "patches": [
                        {"target": "card_style", "parameter": "radius", "value": 99, "confidence": 0.9},
                        {"target": "section:results", "parameter": "body_font_size", "value": 1, "confidence": 0.9},
                        {"target": "section:results", "parameter": "x", "value": 50, "confidence": 1.0},
                        {"target": "section:unknown", "parameter": "body_font_size", "value": 10, "confidence": 1.0},
                        {"target": "typography", "parameter": "body", "value": 11, "confidence": 0.2},
                    ],
                },
                model="vision-test",
                reference_path=reference,
                preview_path=preview,
                design=design,
                layout=layout,
            )
        self.assertEqual(report["status"], "needs_revision")
        self.assertEqual(report["issues"], [{"severity": "medium", "target": "results", "category": "density"}])
        self.assertEqual(len(report["approved_patches"]), 2)
        self.assertEqual(report["approved_patches"][0]["value"], 10.0)
        self.assertEqual(report["approved_patches"][1]["value"], 10.0)
        self.assertNotIn("summary", report)
        self.assertNotIn("forbidden", str(report))
        self.assertTrue(report["provider_received_rendered_preview"])

    def test_allowlisted_review_repairs_do_not_touch_content_or_geometry(self) -> None:
        reference_sha256 = "c" * 64
        design = base_design(reference_sha256)
        design["scientific_content"] = {"claim": "immutable"}
        review = {
            "status": "needs_revision",
            "reference_sha256": reference_sha256,
            "preview_sha256": "d" * 64,
            "scientific_content_influence": "none",
            "visible_text_retained": False,
            "approved_patches": [
                {
                    "target": "card_style",
                    "parameter": "radius",
                    "previous_value": 8.0,
                    "value": 10.0,
                    "confidence": 0.9,
                },
                {
                    "target": "section:results",
                    "parameter": "body_font_size",
                    "previous_value": 10.6,
                    "value": 10.0,
                    "confidence": 0.9,
                },
                {"target": "section:results", "parameter": "x", "value": 100, "confidence": 1.0},
                {
                    "target": "typography",
                    "parameter": "body",
                    "previous_value": 10.8,
                    "value": 99.0,
                    "confidence": 1.0,
                },
            ],
        }
        repaired, actions = apply_review_repairs(design, review, 1)
        self.assertEqual(len(actions), 2)
        self.assertEqual(repaired["card_style"]["radius"], 10.0)
        self.assertEqual(repaired["sections"][0]["body_style"]["font_size"], 10.0)
        self.assertEqual(repaired["scientific_content"], {"claim": "immutable"})
        self.assertNotIn("x", repaired["sections"][0])


if __name__ == "__main__":
    unittest.main()
