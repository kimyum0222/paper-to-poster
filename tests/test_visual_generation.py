from __future__ import annotations

import base64
import binascii
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
from build_poster_design import build_design_spec
from build_poster_svg import build_svg
from build_poster_visual_brief import build_visual_brief
from generate_poster_style_with_rightcode import (
    ImageTaskTimeout,
    generate_style_reference,
    poll_for_result,
    resume_style_reference,
)
from run_pipeline import write_generation_report


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
    return {
        "title": "Agent Planning with Verified Tools",
        "take_home_message": "The method improves accuracy by 12%.",
        "result_callouts": [{"label": "Accuracy", "value": "12%", "detail": "Verified result"}],
        "results": {"bullets": ["A verified result"]},
        "method": {"bullets": ["A verified method"]},
        "figures_to_use": [{"id": "figure_1", "role": "result_evidence", "page": 4}],
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
    def test_brief_excludes_claim_metrics_from_image_prompt(self) -> None:
        brief = build_visual_brief(sample_content(), "gpt-image-2", "custom/reference.png")
        self.assertEqual(brief["status"], "planned")
        self.assertEqual(brief["generated_asset_requests"][0]["asset_class"], "style_reference_only")
        self.assertNotIn("12%", brief["prompt"])
        self.assertNotIn(sample_content()["title"], brief["prompt"])
        self.assertIn("Do not render any legible text", brief["prompt"])
        self.assertEqual(brief["source_asset_roles"][0]["asset_class"], "source_evidence")
        self.assertEqual(brief["generated_asset_requests"][0]["output_path"], "custom/reference.png")

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
            steps = [
                {"command": ["python", "scripts/build_poster_visual_brief.py"], "returncode": 0},
                {"command": ["python", "scripts/generate_poster_style_with_rightcode.py"], "returncode": 2},
            ]
            write_generation_report(outputs, "paper.pdf", steps, failed_step=steps[-1]["command"])
            report = (outputs / "generation_report.md").read_text(encoding="utf-8")

        self.assertIn("Reference-pixel analysis: not run", report)
        self.assertIn("Derived design tokens applied: False", report)
        self.assertNotIn("stale_analysis", report)


class RightCodeAsyncGenerationTests(unittest.TestCase):
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

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "poster_style_reference.png"
            metadata = generate_style_reference(
                {"prompt": "Safe style-only placeholder poster"},
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
