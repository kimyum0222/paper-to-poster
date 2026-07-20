from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from review_poster_faithfulness_with_openai import normalize_review_report
from run_pipeline import report_fails_gate, unresolved_claims_for_gate


class PipelineQualityGateTests(unittest.TestCase):
    def test_risk_gate_levels(self) -> None:
        report = {"status": "needs_revision", "high_risk_count": 0, "medium_risk_count": 2}
        self.assertFalse(report_fails_gate(report, "off"))
        self.assertFalse(report_fails_gate(report, "high"))
        self.assertTrue(report_fails_gate(report, "medium"))

    def test_missing_report_fails_enabled_gate(self) -> None:
        self.assertTrue(report_fails_gate({}, "high"))

    def test_empty_claim_collection_fails_evidence_gate(self) -> None:
        self.assertTrue(unresolved_claims_for_gate({"poster_claims": []}, "critical"))

    def test_critical_claim_gate_ignores_noncritical_unresolved_claim(self) -> None:
        content = {"poster_claims": [
            {"id": "problem_1", "section": "problem", "evidence_status": "unresolved", "source_refs": []},
            {"id": "results_1", "section": "results", "evidence_status": "verified", "source_refs": [{"page": 1, "verification_status": "verified"}]},
        ]}
        self.assertFalse(unresolved_claims_for_gate(content, "critical"))
        self.assertEqual(len(unresolved_claims_for_gate(content, "all")), 1)


class FaithfulnessEvidenceGateTests(unittest.TestCase):
    def test_numeric_claim_without_verified_ref_is_high_risk(self) -> None:
        claims = [{
            "id": "results_1",
            "section": "results",
            "claim": "Accuracy improves by 12%.",
            "evidence_text": "",
            "source_refs": [],
            "evidence_status": "unresolved",
        }]
        raw = {
            "overall_status": "passed",
            "summary": "Looks supported.",
            "reviews": [{
                "claim_id": "results_1",
                "status": "supported",
                "risk": "low",
                "support_score": 0.95,
                "issue": "",
                "suggested_revision": None,
            }],
        }
        report = normalize_review_report(raw, claims, "test-model")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["high_risk_count"], 1)
        self.assertEqual(report["unresolved_evidence_claim_count"], 1)
        self.assertIn("No locally verified", report["reviews"][0]["issue"])


if __name__ == "__main__":
    unittest.main()
