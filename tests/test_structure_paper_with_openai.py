from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from structure_paper_with_openai import (
    call_model,
    merge_model_extraction,
    page_text_context,
    resolve_model_input_mode,
    validate_model_payload,
)
import verify_paper_extraction


class ModelInputModeTests(unittest.TestCase):
    def test_default_openai_endpoint_uses_pdf(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_model_input_mode("auto"), "pdf")

    def test_custom_endpoint_uses_page_text(self) -> None:
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://right.codes/codex/v1"}, clear=True):
            self.assertEqual(resolve_model_input_mode("auto"), "text")

    def test_explicit_mode_wins(self) -> None:
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://right.codes/codex/v1"}, clear=True):
            self.assertEqual(resolve_model_input_mode("pdf"), "pdf")


class PageTextContextTests(unittest.TestCase):
    def test_page_markers_are_preserved(self) -> None:
        raw = {"pages": [
            {"page_number": 1, "text": "First page"},
            {"page_number": 2, "text": "Second page"},
        ]}
        text, truncated = page_text_context(raw)
        self.assertIn("===== PAGE 1 =====", text)
        self.assertIn("===== PAGE 2 =====", text)
        self.assertFalse(truncated)


class ModelPayloadGateTests(unittest.TestCase):
    def valid_payload(self) -> dict:
        return {
            "title": {"text": "Paper", "confidence": 0.9, "source_refs": [{"page": 1, "quote": "Paper"}]},
            "authors": [],
            "affiliations": [],
            "abstract": {"text": "Abstract", "confidence": 0.8, "source_refs": [{"page": 1, "quote": "Abstract"}]},
            "sections": [],
            "methods": {"text": "", "confidence": 0.0, "source_refs": []},
            "results": {"text": "", "confidence": 0.0, "source_refs": []},
            "conclusion": {"text": "", "confidence": 0.0, "source_refs": []},
            "research_question": {"text": "", "confidence": 0.0, "source_refs": []},
            "key_contributions": [],
            "key_results": [],
            "limitations": [],
            "paper_language": "English",
            "paper_type": "research paper",
            "extraction_notes": [],
        }

    def test_empty_payload_is_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_model_payload({"title": {"text": "", "source_refs": []}})

    def test_evidence_bearing_payload_is_accepted(self) -> None:
        payload = self.valid_payload()
        stats = validate_model_payload(payload)
        self.assertEqual(stats["nonempty_evidence_fields"], 2)
        self.assertEqual(stats["source_ref_count"], 2)

    def test_text_mode_call_and_merge(self) -> None:
        payload = self.valid_payload()
        captured: dict = {}

        class FakeResponses:
            def create(self, **kwargs):
                captured.update(kwargs)
                import json
                return json.dumps(payload)

        fake_module = SimpleNamespace(
            OpenAI=lambda: SimpleNamespace(responses=FakeResponses())
        )
        raw = {
            "pages": [{"page_number": 1, "text": "Paper\nAbstract"}],
            "page_count": 1,
            "title": "Local title",
            "extraction_notes": [],
        }
        with patch.dict(sys.modules, {"openai": fake_module}):
            result = call_model(Path("paper.pdf"), raw, "test-model", "auto", "text")
        user_text = captured["input"][1]["content"][0]["text"]
        self.assertIn("===== PAGE 1 =====", user_text)
        self.assertNotIn("input_file", user_text)
        merged = merge_model_extraction(
            raw, result, Path("raw.json"), "test-model", "auto", "text"
        )
        self.assertEqual(merged["extraction_method"], "openai_compatible_page_text_hybrid")
        self.assertEqual(merged["model_input_mode"], "text")
        self.assertEqual(merged["title"], "Paper")

    def test_text_mode_output_enters_evidence_verification(self) -> None:
        payload = self.valid_payload()
        raw = {
            "pages": [{
                "page_number": 1,
                "text": "Paper\nAbstract",
                "lines": [
                    {"text": "Paper", "bbox": [0, 0, 10, 10]},
                    {"text": "Abstract", "bbox": [0, 10, 20, 20]},
                ],
            }],
            "page_count": 1,
            "title": "Local title",
            "extraction_notes": [],
        }
        merged = merge_model_extraction(
            raw, payload, Path("raw.json"), "test-model", "auto", "text"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            raw_path = temp / "raw.json"
            extracted_path = temp / "extracted.json"
            report_path = temp / "report.json"
            raw_path.write_text(json.dumps(raw), encoding="utf-8")
            extracted_path.write_text(json.dumps(merged), encoding="utf-8")
            argv = [
                "verify_paper_extraction.py",
                "--raw-json", str(raw_path),
                "--extracted-json", str(extracted_path),
                "--report-json", str(report_path),
            ]
            with patch.object(sys, "argv", argv):
                self.assertEqual(verify_paper_extraction.main(), 0)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["verified_count"], 2)


if __name__ == "__main__":
    unittest.main()
