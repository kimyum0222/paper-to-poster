from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_poster_narrative_with_openai import call_model, local_plan, normalize_plan
from run_pipeline import write_generation_report


def verified_claim(claim_id: str, section: str, claim: str) -> dict:
    return {
        "id": claim_id,
        "section": section,
        "claim": claim,
        "source": section,
        "source_text": claim,
        "evidence_status": "verified",
        "source_refs": [{
            "page": 1,
            "quote": claim,
            "bbox": [10, 20, 300, 40],
            "verification_status": "verified",
        }],
    }


def sample_content() -> dict:
    return {
        "title": "Evidence-Grounded Poster Planning",
        "poster_claims": [
            verified_claim("problem_1", "problem", "Existing systems lose accuracy under shift."),
            verified_claim("take_home_message", "take_home_message", "Evidence constraints improve robustness."),
            verified_claim("method_1", "method", "The method combines calibration and evidence selection."),
            verified_claim("result_callout_1", "result_callouts", "Accuracy improves by 12%."),
            verified_claim("conclusion_1", "conclusion", "The method remains stable across three settings."),
            {
                "id": "unsupported_1",
                "section": "results",
                "claim": "This unsupported statement must not enter the plan.",
                "evidence_status": "unresolved",
                "source_refs": [],
            },
        ],
        "figures_to_use": [{
            "id": "figure_method",
            "role": "method_overview",
            "page": 2,
            "caption": "Overview of the evidence-aware method.",
            "asset_path": "assets/figure_method.png",
            "width_px": 800,
            "height_px": 400,
        }],
        "figure_candidates": [{
            "id": "figure_result",
            "role": "result_evidence",
            "page": 3,
            "caption": "Results across evaluation settings.",
            "asset_path": "assets/figure_result.png",
            "width_px": 600,
            "height_px": 600,
        }],
    }


def raw_model_plan() -> dict:
    return {
        "paper_type": "empirical_result_centered",
        "story_arc": "problem_method_evidence_implication",
        "hero_section": "results",
        "reading_order": ["problem", "method", "results"],
        "sections": [
            {
                "id": "problem",
                "heading": "An unsupported model-written heading",
                "purpose": "Frame the verified problem.",
                "priority": 3,
                "text_density": "short",
                "bullet_budget": 1,
                "visual_role": "supporting",
                "claim_ids": ["problem_1", "unsupported_1", "unknown_claim"],
                "figure_ids": [],
            },
            {
                "id": "method",
                "heading": "Approach",
                "purpose": "Explain the verified method.",
                "priority": 4,
                "text_density": "medium",
                "bullet_budget": 2,
                "visual_role": "primary",
                "claim_ids": ["method_1"],
                "figure_ids": ["figure_method", "unknown_figure"],
            },
            {
                "id": "results",
                "heading": "Evidence",
                "purpose": "Present the strongest verified result.",
                "priority": 5,
                "text_density": "short",
                "bullet_budget": 1,
                "visual_role": "hero",
                "claim_ids": ["result_callout_1"],
                "figure_ids": ["figure_result"],
            },
        ],
        "core_figure_ids": ["figure_method", "unknown_figure"],
        "omitted_sections": [{"id": "limitations", "reason": "No verified limitation claim."}],
        "planning_notes": ["Use results as the visual anchor."],
    }


class NarrativePlanSafetyTests(unittest.TestCase):
    def test_local_plan_uses_only_verified_claims_and_selected_source_figures(self) -> None:
        content = sample_content()
        content["poster_claims"].append({
            **verified_claim("invalid_page_claim", "results", "A quote without a source page."),
            "source_refs": [{
                "page": None,
                "quote": "A quote without a source page.",
                "verification_status": "verified",
            }],
        })
        content["figures_to_use"].append({
            "id": "generated_figure",
            "role": "result_evidence",
            "page": 4,
            "caption": "Generated content must not become source evidence.",
            "asset_path": "assets/generated/generated_figure.png",
            "asset_class": "generated_non_evidence",
        })
        plan = local_plan(content, "offline test")
        selected_claim_ids = {
            claim_id
            for section in plan["sections"]
            for claim_id in section["claim_ids"]
        }
        self.assertNotIn("unsupported_1", selected_claim_ids)
        self.assertNotIn("invalid_page_claim", selected_claim_ids)
        self.assertEqual(plan["hero_section"], "results")
        self.assertEqual(plan["core_figure_ids"], ["figure_method"])
        selected_figure_ids = {
            figure_id
            for section in plan["sections"]
            for figure_id in section["figure_ids"]
        }
        self.assertNotIn("generated_figure", selected_figure_ids)
        self.assertFalse(plan["claim_selection_summary"]["unverified_claims_allowed"])
        self.assertFalse(plan["figure_selection_summary"]["generated_figures_allowed"])
        self.assertEqual(len(plan["source_content_sha256"]), 64)

    def test_normalizer_drops_unknown_ids_and_keeps_headings_non_scientific(self) -> None:
        plan = normalize_plan(raw_model_plan(), sample_content(), "test_model", "test-model")
        problem = next(section for section in plan["sections"] if section["id"] == "problem")
        method = next(section for section in plan["sections"] if section["id"] == "method")
        self.assertEqual(problem["claim_ids"], ["problem_1"])
        self.assertEqual(problem["heading"], "Problem")
        self.assertEqual(problem["heading_suggestion"], "An unsupported model-written heading")
        self.assertEqual(problem["purpose"], "Establish the research problem and why it is difficult.")
        self.assertEqual(problem["purpose_suggestion"], "Frame the verified problem.")
        self.assertEqual(method["figure_ids"], ["figure_method"])
        self.assertEqual(plan["core_figure_ids"], ["figure_method"])

    def test_normalizer_rejects_plan_with_fewer_than_three_evidence_sections(self) -> None:
        raw = raw_model_plan()
        raw["sections"] = raw["sections"][:2]
        with self.assertRaisesRegex(ValueError, "only 2"):
            normalize_plan(raw, sample_content(), "test_model", "test-model")

    def test_failed_pipeline_step_does_not_report_stale_narrative_plan(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            outputs_dir = Path(temp_dir)
            (outputs_dir / "poster_narrative_plan.json").write_text(
                json.dumps({"status": "planned", "hero_section": "stale_hero"}),
                encoding="utf-8",
            )
            step = ["python", "scripts/plan_poster_narrative_with_openai.py"]
            write_generation_report(
                outputs_dir,
                "paper.pdf",
                [{"command": step, "returncode": 2}],
                failed_step=step,
            )
            report = (outputs_dir / "generation_report.md").read_text(encoding="utf-8")
        self.assertIn("## Content-Driven Narrative Planning", report)
        self.assertIn("- Status: failed", report)
        self.assertNotIn("stale_hero", report)


class NarrativeModelContractTests(unittest.TestCase):
    def test_call_model_requests_strict_schema_and_excludes_unverified_claims(self) -> None:
        captured: dict = {}

        class FakeResponses:
            def create(self, **kwargs):
                captured.update(kwargs)
                return json.dumps(raw_model_plan())

        fake_module = SimpleNamespace(
            OpenAI=lambda: SimpleNamespace(responses=FakeResponses())
        )
        with patch.dict(sys.modules, {"openai": fake_module}):
            result = call_model({}, sample_content(), "test-model")

        self.assertEqual(result["hero_section"], "results")
        output_format = captured["text"]["format"]
        self.assertEqual(output_format["type"], "json_schema")
        self.assertTrue(output_format["strict"])
        user_context = captured["input"][1]["content"][0]["text"]
        self.assertIn("problem_1", user_context)
        self.assertNotIn("unsupported_1", user_context)
        self.assertNotIn("This unsupported statement", user_context)


if __name__ == "__main__":
    unittest.main()
