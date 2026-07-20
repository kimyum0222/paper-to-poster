from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_poster_content import (
    build_poster_content,
    label_for_result_sentence,
    make_bullets,
    result_value,
)
from build_poster_design import build_design_spec
from build_poster_svg import build_svg
from run_pipeline import unresolved_claims_for_gate
from validate_svg import validate_svg


class PosterEvidenceTests(unittest.TestCase):
    def local_paper(self) -> dict:
        abstract = (
            "This paper studies reliable classification under distribution shift. "
            "We propose an evidence-aware training method for robust prediction."
        )
        methods = (
            "The method combines calibrated representations with a deterministic "
            "selection rule during training."
        )
        results = (
            "The approach improves accuracy by 12% compared with the strongest baseline. "
            "The improvement remains consistent across three evaluation settings."
        )
        conclusion = (
            "The results show that evidence-aware training improves robustness without "
            "changing the evaluation protocol."
        )
        page_text = " ".join([abstract, methods, results, conclusion])
        return {
            "title": "Evidence-Aware Training",
            "authors": ["A. Author"],
            "affiliations": ["Example University"],
            "abstract": abstract,
            "methods": methods,
            "results": results,
            "conclusion": conclusion,
            "sections": [],
            "figures": [],
            "pages": [{
                "page_number": 1,
                "text": page_text,
                "lines": [{"text": page_text, "bbox": [10, 20, 500, 120]}],
            }],
            "page_count": 1,
            "source_pdf": "paper.pdf",
        }

    def test_local_claims_receive_page_quote_and_bbox(self) -> None:
        content = build_poster_content(self.local_paper())
        claims = content["poster_claims"]
        self.assertTrue(claims)
        self.assertEqual(content["claim_evidence_summary"]["unresolved_claim_count"], 0)
        self.assertFalse(unresolved_claims_for_gate(content, "critical"))
        for claim in claims:
            self.assertEqual(claim["evidence_status"], "verified")
            self.assertTrue(claim["source_refs"])
            self.assertEqual(claim["source_refs"][0]["page"], 1)
            self.assertIn("bbox", claim["source_refs"][0])

    def test_verified_model_field_reference_survives_content_build(self) -> None:
        data = self.local_paper()
        quote = "The approach improves accuracy by 12% compared with the strongest baseline."
        data["abstract"] = "The proposed method improves robust classification performance."
        data["field_evidence"] = {
            "abstract": {
                "text": data["abstract"],
                "confidence": 0.9,
                "verification_status": "verified",
                "source_refs": [{
                    "page": 1,
                    "quote": quote,
                    "verification_status": "verified",
                    "bbox": [10, 20, 500, 120],
                }],
            }
        }
        content = build_poster_content(data)
        abstract_claims = [
            claim for claim in content["poster_claims"]
            if claim.get("source") == "abstract"
        ]
        self.assertTrue(abstract_claims)
        self.assertTrue(all(claim["evidence_status"] == "verified" for claim in abstract_claims))
        self.assertTrue(any(claim["evidence_mapping"] == "verified_field_reference" for claim in abstract_claims))
        self.assertTrue(any(claim["evidence_text"] == quote for claim in abstract_claims))

    def test_content_design_svg_validation_chain(self) -> None:
        content = build_poster_content(self.local_paper())
        design = build_design_spec(content)
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs_dir = Path(temp_dir)
            svg_text, layout = build_svg(content, outputs_dir, design)
            svg_path = outputs_dir / "poster.svg"
            layout_path = outputs_dir / "poster_layout.json"
            svg_path.write_text(svg_text, encoding="utf-8")
            layout_path.write_text(json.dumps(layout), encoding="utf-8")
            ok, errors, _, overflow_checks = validate_svg(
                svg_path,
                outputs_dir,
                layout_path,
            )
        self.assertTrue(ok, errors)
        self.assertTrue(overflow_checks)
        self.assertFalse([item for item in overflow_checks if item.get("has_overflow")])


class GenericContentRulesTests(unittest.TestCase):
    def test_chinese_sentences_are_kept_and_deduplicated(self) -> None:
        text = (
            "本研究提出一种基于证据约束的稳健学习方法，用于处理复杂分布变化问题。"
            "实验结果显示该方法在三个测试环境中均保持稳定性能并降低预测误差。"
        )
        bullets = make_bullets(text, max_bullets=3)
        self.assertEqual(len(bullets), 2)
        self.assertTrue(all(bullet.endswith("。") for bullet in bullets))

    def test_result_callout_rules_are_domain_neutral(self) -> None:
        sentence = "The intervention improves accuracy by 12% compared with the baseline."
        self.assertEqual(label_for_result_sentence(sentence), "Performance")
        self.assertEqual(result_value(sentence), "12%")


if __name__ == "__main__":
    unittest.main()
