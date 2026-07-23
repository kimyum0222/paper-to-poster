from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_poster_svg import build_svg
from build_typesetting_manifest import build_manifest
from run_pipeline import prepare_output_directory, script_path, write_generation_report


def verified_content() -> dict:
    text = "Alpha beta"
    return {
        "title": "Portable Poster",
        "authors": ["A. Author"],
        "affiliations": ["Example Lab"],
        "poster_claims": [{
            "id": "problem_1",
            "section": "problem",
            "claim": text,
            "evidence_status": "verified",
            "source_refs": [{
                "page": 1,
                "quote": text,
                "verification_status": "verified",
            }],
        }],
        "figures_to_use": [],
        "footer_metadata": {"source_pdf": "paper.pdf"},
    }


def explicit_design() -> dict:
    return {
        "template": "art_directed_grid",
        "layout_source": "test",
        "canvas": {"width": 1189, "height": 841},
        "grid": {"margin": 34, "gutter": 22, "header_height": 105, "footer_height": 34},
        "typography": {"font_family": "Arial, Helvetica, sans-serif", "body": 11.0},
        "card_style": {"padding_x": 20},
        "sections": [{
            "section_id": "problem",
            "heading": "Problem",
            "x": 34,
            "y": 130,
            "width": 500,
            "height": 260,
            "visual_role": "supporting",
            "bullet_budget": 1,
            "claim_ids": ["problem_1"],
            "figure_slots": [],
            "body_style": {"font_size": 11.0, "line_height_ratio": 1.3},
        }],
    }


class PipelineMaintenanceTests(unittest.TestCase):
    def test_script_paths_are_absolute_and_existing(self) -> None:
        path = Path(script_path("extract_paper.py"))
        self.assertTrue(path.is_absolute())
        self.assertTrue(path.is_file())

    def test_output_directory_rejects_cross_paper_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.pdf"
            second = root / "second.pdf"
            outputs = root / "outputs"
            first.write_bytes(b"first paper")
            second.write_bytes(b"second paper")
            prepare_output_directory(outputs, first, False)
            (outputs / "poster.svg").write_text("old", encoding="utf-8")
            (outputs / "notes.txt").write_text("preserve", encoding="utf-8")
            assets = outputs / "assets"
            assets.mkdir()
            (assets / "old.png").write_bytes(b"old")

            with self.assertRaisesRegex(ValueError, "different paper"):
                prepare_output_directory(outputs, second, False)

            manifest = prepare_output_directory(outputs, second, True)
            self.assertFalse((outputs / "poster.svg").exists())
            self.assertFalse(assets.exists())
            self.assertEqual((outputs / "notes.txt").read_text(encoding="utf-8"), "preserve")
            self.assertEqual(manifest["source_pdf"], str(second.resolve()))

    def test_stale_optional_reports_are_not_claimed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            for name in [
                "poster_faithfulness_report.json",
                "layout_repair_report.json",
                "poster_aesthetic_report.json",
                "poster_reference_vision_analysis.json",
                "poster_visual_review.json",
                "poster_visual_repair_report.json",
            ]:
                (outputs / name).write_text(json.dumps({"status": "stale_marker"}), encoding="utf-8")
            write_generation_report(outputs, "paper.pdf", [])
            report = (outputs / "generation_report.md").read_text(encoding="utf-8")
        self.assertNotIn("stale_marker", report)
        self.assertNotIn("poster_faithfulness_report.json", report)
        self.assertNotIn("layout_repair_report.json", report)
        self.assertNotIn("poster_aesthetic_report.json", report)
        self.assertNotIn("poster_reference_vision_analysis.json", report)
        self.assertNotIn("poster_visual_review.json", report)
        self.assertNotIn("poster_visual_repair_report.json", report)

    def test_typesetting_manifest_controls_svg_wrapping(self) -> None:
        content = verified_content()
        design = explicit_design()
        manifest = build_manifest(content, design)
        entry = manifest["sections"][0]["entries"][0]
        entry["wrapped_lines"] = ["Alpha", "beta"]
        with tempfile.TemporaryDirectory() as tmp:
            svg, layout = build_svg(content, Path(tmp), design, manifest)
        self.assertIn(">• Alpha</tspan>", svg)
        self.assertIn(">  beta</tspan>", svg)
        self.assertTrue(layout["typesetting_manifest"]["applied"])
        self.assertEqual(layout["font_metrics"]["status"], "resolved")
        self.assertNotIn('font-family="Helvetica" font-weight', svg)

        changed = dict(content)
        changed["title"] = "Different content"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "does not match poster content"):
                build_svg(changed, Path(tmp), design, manifest)

    def test_local_pipeline_runs_from_another_working_directory(self) -> None:
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "paper.pdf"
            outputs = root / "out"
            document = fitz.open()
            page = document.new_page()
            page.insert_text(
                (72, 72),
                "Portable Evidence Poster\nAbstract\nWe study reliable systems.\n"
                "Method\nWe use verified evidence.\nResults\nThe method improves accuracy by 12%.\n"
                "Conclusion\nThe method remains stable.",
            )
            document.save(pdf)
            document.close()
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_pipeline.py"),
                    str(pdf),
                    "--outputs-dir",
                    str(outputs),
                    "--extraction-mode",
                    "local",
                    "--narrative-planning",
                    "off",
                    "--claim-evidence-gate",
                    "off",
                    "--skip-validate",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((outputs / "poster.svg").is_file())
            run_manifest = json.loads((outputs / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(run_manifest["status"], "complete")

    def test_optional_multimodal_stages_fall_back_without_keys(self) -> None:
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "paper.pdf"
            outputs = root / "out"
            document = fitz.open()
            page = document.new_page()
            page.insert_text(
                (72, 72),
                "Visual Guidance Fallback\nAbstract\nWe test a safe optional stage.\n"
                "Method\nThe pipeline uses deterministic evidence.\nResults\nValidation remains stable.\n",
            )
            document.save(pdf)
            document.close()
            environment = dict(os.environ)
            environment.pop("OPENAI_API_KEY", None)
            environment.pop("RIGHTCODE_API_KEY", None)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_pipeline.py"),
                    str(pdf),
                    "--outputs-dir",
                    str(outputs),
                    "--extraction-mode",
                    "local",
                    "--claim-evidence-gate",
                    "off",
                    "--image-art-direction",
                    "auto",
                    "--reference-vision-analysis",
                    "auto",
                    "--preview-vision-review",
                    "auto",
                    "--decorative-vectorization",
                    "off",
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            reference_report = json.loads(
                (outputs / "poster_reference_vision_analysis.json").read_text(encoding="utf-8")
            )
            preview_report = json.loads((outputs / "poster_visual_review.json").read_text(encoding="utf-8"))
            self.assertEqual(reference_report["status"], "skipped")
            self.assertEqual(preview_report["status"], "skipped")
            self.assertTrue((outputs / "poster.svg").is_file())


if __name__ == "__main__":
    unittest.main()
