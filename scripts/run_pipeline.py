#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
MANAGED_OUTPUT_FILES = {
    "raw_pdf_extraction.json",
    "extracted_paper.json",
    "extraction_verification.json",
    "poster_content.json",
    "poster_narrative_plan.json",
    "poster_design_spec.json",
    "poster_layout.json",
    "poster_overflow_report.json",
    "layout_repair_report.json",
    "poster_faithfulness_report.json",
    "poster_aesthetic_report.json",
    "poster_visual_brief.json",
    "poster_visual_generation.json",
    "poster_style_analysis.json",
    "poster_reference_vision_analysis.json",
    "poster_style_reference.png",
    "poster_decorative_vectors.json",
    "poster_typesetting_manifest.json",
    "poster_style_conformance_report.json",
    "poster_visual_fidelity_report.json",
    "poster_render_preview.png",
    "poster_diagnostic_preview.png",
    "poster_visual_review.json",
    "poster_visual_repair_report.json",
    "poster_design_spec.visual-candidate.json",
    "poster_typesetting_manifest.visual-candidate.json",
    "poster.visual-candidate.svg",
    "poster_layout.visual-candidate.json",
    "poster_overflow_report.visual-candidate.json",
    "poster_render_preview.visual-candidate.png",
    "poster.svg",
    "generation_report.md",
    "run_manifest.json",
}


def script_path(name: str) -> str:
    return str(SCRIPT_DIR / name)


def command_has_script(command: Any, name: str) -> bool:
    return isinstance(command, list) and any(Path(str(part)).name == name for part in command)


def command_references_file(command: Any, name: str) -> bool:
    return isinstance(command, list) and any(Path(str(part)).name == name for part in command)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_output_directory(outputs_dir: Path, pdf_path: Path, fresh_output: bool) -> dict[str, Any]:
    if not pdf_path.is_file():
        raise ValueError(f"Paper PDF does not exist: {pdf_path}")
    source_sha256 = sha256_file(pdf_path)
    if fresh_output and outputs_dir.exists():
        for name in MANAGED_OUTPUT_FILES:
            target = outputs_dir / name
            if target.is_file() or target.is_symlink():
                target.unlink()
        assets = outputs_dir / "assets"
        if assets.exists():
            shutil.rmtree(assets)
    elif outputs_dir.exists():
        previous = read_json(outputs_dir / "run_manifest.json")
        if not previous:
            previous = read_json(outputs_dir / "raw_pdf_extraction.json")
        previous_sha256 = str(
            previous.get("source_pdf_sha256") or previous.get("source_sha256") or ""
        ).strip().lower()
        if previous_sha256 and previous_sha256 != source_sha256:
            raise ValueError(
                "Output directory belongs to a different paper; use --fresh-output or a different --outputs-dir"
            )
        if not previous_sha256 and any((outputs_dir / name).exists() for name in MANAGED_OUTPUT_FILES):
            raise ValueError(
                "Output directory contains an unidentifiable prior run; use --fresh-output or a different --outputs-dir"
            )
    outputs_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": 1,
        "status": "running",
        "source_pdf": str(pdf_path.resolve()),
        "source_pdf_sha256": source_sha256,
        "outputs_dir": str(outputs_dir.resolve()),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "fresh_output": fresh_output,
    }
    write_json(outputs_dir / "run_manifest.json", manifest)
    return manifest


def finish_run_manifest(
    outputs_dir: Path,
    status: str,
    step_results: list[dict[str, Any]],
    failed_step: list[str] | None,
) -> None:
    manifest = read_json(outputs_dir / "run_manifest.json")
    if not manifest:
        return
    manifest.update({
        "status": status,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "step_count": len(step_results),
        "failed_step": failed_step,
    })
    write_json(outputs_dir / "run_manifest.json", manifest)


def run_step(command: list[str]) -> dict[str, Any]:
    print("\n$ " + " ".join(command), flush=True)
    result = subprocess.run(command)
    return {
        "command": command,
        "returncode": result.returncode,
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def report_fails_gate(report: dict[str, Any], gate: str) -> bool:
    if gate == "off":
        return False
    if not report:
        return True
    status = str(report.get("status", "")).strip().lower()
    high_risk = int(report.get("high_risk_count", 0) or 0)
    medium_risk = int(report.get("medium_risk_count", 0) or 0)
    if gate == "high":
        return status == "failed" or high_risk > 0
    return status != "passed" or high_risk > 0 or medium_risk > 0


def quality_gate_result(name: str, detail: str) -> dict[str, Any]:
    return {
        "command": ["quality-gate", name, detail],
        "returncode": 3,
    }


def unresolved_claims_for_gate(content: dict[str, Any], gate: str) -> list[dict[str, Any]]:
    if gate == "off":
        return []
    claims = content.get("poster_claims", [])
    if not isinstance(claims, list):
        return [{"id": "missing_poster_claims", "section": "unknown"}]
    if not claims:
        return [{"id": "empty_poster_claims", "section": "unknown"}]
    unresolved = [
        claim for claim in claims
        if isinstance(claim, dict)
        and (
            claim.get("evidence_status") != "verified"
            or not isinstance(claim.get("source_refs"), list)
            or not any(
                isinstance(ref, dict) and ref.get("verification_status") == "verified"
                for ref in claim.get("source_refs", [])
            )
        )
    ]
    if gate == "all":
        return unresolved
    critical_sections = {"take_home_message", "result_callouts", "results"}
    return [
        claim for claim in unresolved
        if str(claim.get("section", "")) in critical_sections
    ]


def write_generation_report(
    outputs_dir: Path,
    pdf_path: str,
    step_results: list[dict[str, Any]],
    failed_step: list[str] | None = None,
) -> None:
    def attempted(script_name: str) -> bool:
        return any(
            command_has_script(result.get("command"), script_name)
            for result in step_results
        )

    def completed(script_name: str) -> bool:
        return any(
            result.get("returncode") == 0 and command_has_script(result.get("command"), script_name)
            for result in step_results
        )

    raw_extraction = read_json(outputs_dir / "raw_pdf_extraction.json") if attempted("extract_paper.py") else {}
    extracted = read_json(outputs_dir / "extracted_paper.json") if attempted("structure_paper_with_openai.py") else {}
    extraction_verification = read_json(outputs_dir / "extraction_verification.json") if attempted("verify_paper_extraction.py") else {}
    content = read_json(outputs_dir / "poster_content.json") if attempted("build_poster_content.py") else {}
    design = read_json(outputs_dir / "poster_design_spec.json") if attempted("build_poster_design.py") else {}
    layout = read_json(outputs_dir / "poster_layout.json") if attempted("build_poster_svg.py") else {}
    overflow_report = read_json(outputs_dir / "poster_overflow_report.json") if attempted("validate_svg.py") else {}
    run_manifest = read_json(outputs_dir / "run_manifest.json")

    faithfulness_completed = completed("review_poster_faithfulness_with_openai.py")
    repair_completed = completed("repair_poster_layout.py")
    aesthetic_completed = completed("review_poster_aesthetics_with_openai.py")
    typesetting_completed = completed("build_typesetting_manifest.py")
    render_completed = completed("render_svg_preview.py")
    conformance_completed = completed("check_poster_style_conformance.py")
    reference_vision_completed = completed("analyze_reference_with_vision.py")
    preview_vision_completed = completed("review_rendered_poster_with_vision.py")
    visual_repair_completed = completed("apply_visual_review_repairs.py")
    faithfulness_report = read_json(outputs_dir / "poster_faithfulness_report.json") if faithfulness_completed else {}
    repair_report = read_json(outputs_dir / "layout_repair_report.json") if repair_completed else {}
    aesthetic_report = read_json(outputs_dir / "poster_aesthetic_report.json") if aesthetic_completed else {}
    typesetting_manifest = read_json(outputs_dir / "poster_typesetting_manifest.json") if typesetting_completed else {}
    style_conformance_report = read_json(outputs_dir / "poster_style_conformance_report.json") if conformance_completed else {}
    reference_vision_report = read_json(outputs_dir / "poster_reference_vision_analysis.json") if reference_vision_completed else {}
    preview_vision_report = read_json(outputs_dir / "poster_visual_review.json") if preview_vision_completed else {}
    visual_repair_report = read_json(outputs_dir / "poster_visual_repair_report.json") if visual_repair_completed else {}
    narrative_results = [
        result for result in step_results
        if command_has_script(result.get("command"), "plan_poster_narrative_with_openai.py")
    ]
    narrative_requested = bool(narrative_results)
    narrative_completed = any(result.get("returncode") == 0 for result in narrative_results)
    narrative_plan = read_json(outputs_dir / "poster_narrative_plan.json") if narrative_completed else {}
    visual_requested = any(
        command_has_script(result.get("command"), "build_poster_visual_brief.py")
        for result in step_results
    )
    visual_analyzed = any(
        command_has_script(result.get("command"), "analyze_poster_style_reference.py")
        for result in step_results
    )
    vectorization_requested = any(
        command_has_script(result.get("command"), "vectorize_reference_decorations.py")
        for result in step_results
    )
    visual_brief = read_json(outputs_dir / "poster_visual_brief.json") if visual_requested else {}
    visual_generation = read_json(outputs_dir / "poster_visual_generation.json") if visual_requested else {}
    visual_analysis = read_json(outputs_dir / "poster_style_analysis.json") if visual_analyzed else {}
    decorative_vectors = read_json(outputs_dir / "poster_decorative_vectors.json") if vectorization_requested else {}

    generated_files = [
        "poster.svg",
        "raw_pdf_extraction.json",
        "extracted_paper.json",
        "extraction_verification.json",
        "poster_content.json",
        "poster_design_spec.json",
        "poster_layout.json",
        "poster_overflow_report.json",
        "run_manifest.json",
        "generation_report.md",
    ]
    if faithfulness_completed:
        generated_files.append("poster_faithfulness_report.json")
    if repair_completed:
        generated_files.append("layout_repair_report.json")
    if aesthetic_completed:
        generated_files.append("poster_aesthetic_report.json")
    if typesetting_completed:
        generated_files.append("poster_typesetting_manifest.json")
    if narrative_completed:
        generated_files.append("poster_narrative_plan.json")
    if visual_requested:
        generated_files.extend([
            "poster_visual_brief.json",
            "poster_visual_generation.json",
        ])
        if visual_analyzed:
            generated_files.append("poster_style_analysis.json")
        if visual_generation.get("status") == "generated":
            generated_files.append("poster_style_reference.png")
        if render_completed:
            generated_files.append("poster_render_preview.png")
        if conformance_completed:
            generated_files.append("poster_style_conformance_report.json")
        if reference_vision_completed:
            generated_files.append("poster_reference_vision_analysis.json")
        if preview_vision_completed:
            generated_files.append("poster_visual_review.json")
        if visual_repair_completed:
            generated_files.append("poster_visual_repair_report.json")
        if vectorization_requested:
            generated_files.append("poster_decorative_vectors.json")
    existing_files = [name for name in generated_files if (outputs_dir / name).exists()]
    if "generation_report.md" not in existing_files:
        existing_files.append("generation_report.md")
    if (outputs_dir / "assets").exists():
        existing_files.append("assets/")

    figures = content.get("figures_to_use", [])
    figure_lines: list[str] = []
    if isinstance(figures, list):
        for figure in figures:
            if not isinstance(figure, dict):
                continue
            caption = str(figure.get("caption", "") or figure.get("text", "")).strip()
            if len(caption) > 180:
                caption = caption[:177].rstrip() + "..."
            figure_lines.append(
                f"- `{figure.get('id', 'figure')}` as `{figure.get('role', 'unspecified')}` "
                f"from page {figure.get('page', '?')}: {caption}"
            )

    validation_status = "skipped"
    for result in step_results:
        command = result.get("command", [])
        if command_has_script(command, "validate_svg.py") and command_references_file(command, "poster.svg"):
            validation_status = "passed" if result.get("returncode") == 0 else "failed"

    report = [
        "# Generation Report",
        "",
        "## Source",
        "",
        f"- PDF: `{pdf_path}`",
        f"- Source SHA-256: `{run_manifest.get('source_pdf_sha256', raw_extraction.get('source_pdf_sha256', 'unknown'))}`",
        f"- Output directory: `{outputs_dir}`",
        "",
        "## Generated Files",
        "",
    ]
    report.extend(f"- `{outputs_dir / name}`" for name in existing_files)
    if not existing_files:
        report.append("- No output files were completed.")

    report.extend([
        "",
        "## Extraction Summary",
        "",
        f"- Title: {extracted.get('title', content.get('title', 'unknown'))}",
        f"- Pages: {extracted.get('page_count', content.get('footer_metadata', {}).get('page_count', 'unknown'))}",
        f"- Raw evidence backend: {(raw_extraction.get('extraction_notes') or ['unknown'])[-1]}",
        f"- Semantic extraction method: {extracted.get('extraction_method', 'unknown')}",
        f"- Semantic extraction model: {extracted.get('extraction_model') or 'not used'}",
        f"- Evidence verification: {extraction_verification.get('status', 'not run')}",
        f"- Verified semantic fields: {extraction_verification.get('verified_count', 0)}",
        f"- Unverified semantic fields: {extraction_verification.get('unverified_count', 0)}",
        f"- Poster claims with verified evidence: {(content.get('claim_evidence_summary') or {}).get('verified_claim_count', 0)}",
        f"- Poster claims with unresolved evidence: {(content.get('claim_evidence_summary') or {}).get('unresolved_claim_count', 0)}",
        f"- Extracted figures/images: {len(extracted.get('figures', []) or [])}",
        f"- Extracted captions: {len(extracted.get('captions', []) or [])}",
        f"- Extracted tables/caption refs: {len(extracted.get('tables', []) or [])}",
        "",
        "## Figure Selection",
        "",
        f"- Policy: {(content.get('figure_selection_policy') or {}).get('strategy', 'default')}",
    ])
    report.extend(figure_lines or ["- No usable figures were selected."])

    if narrative_requested:
        claim_summary = narrative_plan.get("claim_selection_summary") or {}
        report.extend([
            "",
            "## Content-Driven Narrative Planning",
            "",
            f"- Status: {narrative_plan.get('status', 'failed')}",
            f"- Method: {narrative_plan.get('planning_method', 'unknown')}",
            f"- Model: {narrative_plan.get('model') or 'not used'}",
            f"- Paper type: {narrative_plan.get('paper_type', 'unknown')}",
            f"- Story arc: {narrative_plan.get('story_arc', 'unknown')}",
            f"- Hero section: {narrative_plan.get('hero_section', 'unknown')}",
            f"- Reading order: {', '.join(narrative_plan.get('reading_order', []) or []) or 'not available'}",
            f"- Planned sections: {len(narrative_plan.get('sections', []) or [])}",
            f"- Selected verified claims: {claim_summary.get('selected_verified_claim_count', 0)} of {claim_summary.get('available_verified_claim_count', 0)}",
            f"- Core source figures: {', '.join(narrative_plan.get('core_figure_ids', []) or []) or 'none'}",
            f"- Consumed by Visual Brief: {bool((visual_brief.get('narrative_plan_linkage') or {}).get('consumed'))}",
            (
                "- The plan constrains the text-free image reference and supplies verified IDs to guarded deterministic SVG geometry."
                if (visual_brief.get("narrative_plan_linkage") or {}).get("consumed")
                else "- Image art direction linkage was not used; the final SVG retained the deterministic fallback template."
            ),
        ])

    omitted = content.get("omitted_sections", [])
    report.extend([
        "",
        "## Layout And Assets",
        "",
        f"- Template: {layout.get('template', 'unknown')}",
        f"- Layout source: {layout.get('layout_source', 'deterministic_template')}",
        f"- Template rationale: {layout.get('template_rationale', '') or 'not recorded'}",
        f"- Canvas: {layout.get('canvas_width', 1189)} x {layout.get('canvas_height', 841)}",
        f"- Asset embedding mode: {layout.get('asset_embedding_mode', 'unknown')}",
        f"- Included source-evidence assets: {len(layout.get('source_assets', []) or [])}",
        f"- Source assets with SHA-256 records: {sum(1 for asset in (layout.get('source_assets', []) or []) if isinstance(asset, dict) and asset.get('sha256'))}",
        f"- Declared decorative assets: {len(layout.get('decorative_assets', []) or [])}",
        f"- VTracer-inline decorative assets: {sum(1 for asset in (layout.get('decorative_assets', []) or []) if isinstance(asset, dict) and asset.get('render_mode') == 'vtracer_inline')}",
        "- SVG images are embedded as data URIs when local assets can be read.",
        "- Generated decorative vectors carry no scientific meaning; source figures remain separate evidence assets.",
    ])
    if visual_requested:
        visual_linkage = visual_brief.get("narrative_plan_linkage") or {}
        layout_requirements = visual_brief.get("layout_requirements") or {}
        spatial_design = visual_analysis.get("spatial_design") or {}
        measurements = spatial_design.get("measurements") or {}
        panel_detection = measurements.get("panel_detection") or {}
        vector_backend = decorative_vectors.get("backend") if isinstance(decorative_vectors.get("backend"), dict) else {}
        report.extend([
            "",
            "## Image-Model Art Direction",
            "",
            f"- Status: {visual_brief.get('status', visual_generation.get('status', 'unknown'))}",
            f"- Provider: {visual_brief.get('provider', visual_generation.get('provider', 'rightcode'))}",
            f"- Model: {visual_brief.get('model', visual_generation.get('model', 'unknown'))}",
            f"- Prompt version: {visual_brief.get('prompt_version', 'unknown')}",
            f"- Narrative plan consumed: {visual_linkage.get('consumed', False)}",
            f"- Narrative-layout validation: {visual_linkage.get('validation_status', 'not provided')}",
            f"- Planned body zones: {layout_requirements.get('section_count', 'not constrained')}",
            f"- Planned hero zone: {layout_requirements.get('hero_section', 'not constrained')}",
            f"- Planned source-image slots: {layout_requirements.get('figure_slot_count', 'not constrained')}",
            f"- Provider task ID: {visual_generation.get('task_id', 'not recorded')}",
            f"- Existing task resumable: {visual_generation.get('resumable', False)}",
            f"- Submission outcome: {visual_generation.get('submission_outcome', 'not recorded')}",
            f"- Failure stage: {visual_generation.get('failure_stage', 'none')}",
            f"- Endpoint: {visual_generation.get('endpoint') or (visual_generation.get('request') or {}).get('submission_endpoint') or 'not recorded'}",
            f"- Safe to retry current operation: {visual_generation.get('safe_to_retry', False)}",
            f"- Generated asset class: {visual_generation.get('asset_class', 'style_reference_only')}",
            f"- Style reference included in final SVG: {visual_generation.get('included_in_final_svg', False)}",
            f"- Reference-pixel analysis: {visual_analysis.get('status', 'not run')}",
            f"- Analysis method: {visual_analysis.get('method', 'not run')}",
            f"- Derived design tokens applied: {visual_analysis.get('status') == 'passed'}",
            f"- Multimodal reference analysis: {reference_vision_report.get('status', 'not requested')}",
            f"- Multimodal reference model: {reference_vision_report.get('model', 'not used')}",
            f"- Style reference sent to multimodal provider: {reference_vision_report.get('provider_received_style_reference', False)}",
            f"- Multimodal design semantics applied: {bool((design.get('visual_semantics') or {}).get('applied_to_design'))}",
            f"- Spatial design status: {spatial_design.get('status', 'not run')}",
            f"- Detected content panels: {panel_detection.get('detected_content_panel_count', 'not run')} / {panel_detection.get('expected_section_count', 'not constrained')}",
            f"- Detected decorative strips: {panel_detection.get('detected_decorative_strip_count', 'not run')}",
            f"- Decorative vectorization: {decorative_vectors.get('status', 'not requested')}",
            f"- VTracer backend: {vector_backend.get('kind', 'not available')}",
            f"- VTracer version: {vector_backend.get('version', 'not available')}",
            f"- VTracer assets generated: {decorative_vectors.get('generated_asset_count', 0)} / {decorative_vectors.get('requested_asset_count', 0)}",
            f"- Decorative-vector fallback: {decorative_vectors.get('fallback') or 'none'}",
            f"- Spatial geometry applied to SVG: {layout.get('layout_source') == 'reference_pixels_plus_verified_narrative_constraints'}",
            f"- Style-token conformance check: {style_conformance_report.get('status', 'not run')}",
            f"- Style-token conformance score: {style_conformance_report.get('overall_score', 'not run')}",
            f"- Rendered-preview multimodal review: {preview_vision_report.get('status', 'not requested')}",
            f"- Rendered-preview review model: {preview_vision_report.get('model', 'not used')}",
            f"- Rendered poster preview sent to multimodal provider: {preview_vision_report.get('provider_received_rendered_preview', False)}",
            f"- Approved bounded visual patches: {len(preview_vision_report.get('approved_patches', []) or [])}",
            f"- Visual repair candidate: {visual_repair_report.get('status', 'not requested')}",
            "- This score checks execution of analyzed tokens; it is not a pixel-similarity score.",
            "- Multimodal stages retain no visible text and cannot modify scientific content or source figures.",
            "- Scientific text, metrics, and source figures remain under deterministic SVG control.",
        ])
        if visual_generation.get("failure"):
            report.append(f"- Failure/fallback: {visual_generation.get('failure')}")
        if visual_generation.get("recommended_action"):
            report.append(f"- Recommended action: {visual_generation.get('recommended_action')}")
        if visual_analysis.get("failure"):
            report.append(f"- Analysis fallback: {visual_analysis.get('failure')}")
    report.extend([
        "",
        "## Validation",
        "",
        f"- SVG validation: {validation_status}",
    ])
    if overflow_report:
        report.append(f"- Text overflow check: {overflow_report.get('status', 'unknown')}")
        report.append(f"- Text lines checked: {overflow_report.get('total_text_lines_checked', 0)}")
        report.append(f"- Overflowing text lines: {overflow_report.get('overflow_line_count', 0)}")
    if typesetting_manifest:
        measured_sections = typesetting_manifest.get("sections", []) or []
        measured_entries = sum(
            len(section.get("entries", []) or [])
            for section in measured_sections
            if isinstance(section, dict)
        )
        report.append(f"- Typesetting measurement backend: {typesetting_manifest.get('measurement_backend', 'unknown')}")
        font = typesetting_manifest.get("font") if isinstance(typesetting_manifest.get("font"), dict) else {}
        report.append(f"- Resolved SVG font: {font.get('resolved_font_family', 'not resolved')}")
        report.append(f"- Typesetting sections measured: {len(measured_sections)}")
        report.append(f"- Verified claim entries measured: {measured_entries}")
    if style_conformance_report and visual_requested:
        report.append(f"- Style-token conformance: {style_conformance_report.get('status', 'unknown')}")
        report.append(f"- Style-token conformance scope: {style_conformance_report.get('conformance_scope', 'not recorded')}")
    if preview_vision_report:
        final_preview_path = outputs_dir / "poster_render_preview.png"
        reviewed_hash = str(preview_vision_report.get("preview_sha256", "") or "")
        final_hash = sha256_file(final_preview_path) if final_preview_path.is_file() else ""
        report.append(f"- Rendered-preview vision review: {preview_vision_report.get('status', 'unknown')}")
        report.append(f"- Vision-reviewed preview is final preview: {bool(reviewed_hash and reviewed_hash == final_hash)}")
        report.append(f"- Vision review retained visible text: {preview_vision_report.get('visible_text_retained', False)}")
    if visual_repair_report:
        report.append(f"- Bounded visual repair: {visual_repair_report.get('status', 'unknown')}")
        report.append(f"- Bounded visual repair actions: {len(visual_repair_report.get('actions', []) or [])}")
    if faithfulness_report:
        report.append(f"- Faithfulness review: {faithfulness_report.get('status', 'unknown')}")
        report.append(f"- Faithfulness claims reviewed: {faithfulness_report.get('review_count', 0)}")
        report.append(f"- High-risk claim count: {faithfulness_report.get('high_risk_count', 0)}")
        report.append(f"- Medium-risk claim count: {faithfulness_report.get('medium_risk_count', 0)}")
    if repair_report:
        report.append(f"- Layout repair: {repair_report.get('status', 'unknown')}")
        report.append(f"- Layout repair iteration: {repair_report.get('iteration', 0)}")
        report.append(f"- Layout repair actions: {len(repair_report.get('actions', []) or [])}")
    if aesthetic_report:
        report.append(f"- Aesthetic review: {aesthetic_report.get('status', 'unknown')}")
        report.append(f"- Aesthetic high-risk issues: {aesthetic_report.get('high_risk_count', 0)}")
        report.append(f"- Aesthetic medium-risk issues: {aesthetic_report.get('medium_risk_count', 0)}")
    if failed_step:
        report.append(f"- Failed step: `{' '.join(failed_step)}`")

    notes = extracted.get("extraction_notes", [])
    report.extend([
        "",
        "## Limitations And Omissions",
        "",
    ])
    if omitted:
        report.append("- Omitted or weak source sections: " + ", ".join(str(item) for item in omitted))
    else:
        report.append("- Omitted or weak source sections: none reported by content builder.")
    if notes:
        for note in notes[:8]:
            report.append(f"- {note}")
    if not notes:
        report.append("- No extraction limitations were reported by the extractor.")

    report.extend([
        "",
        "## Pipeline Steps",
        "",
    ])
    for result in step_results:
        command = result.get("command", [])
        code = result.get("returncode")
        report.append(f"- `{ ' '.join(command) }` -> exit `{code}`")

    report_path = outputs_dir / "generation_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    finish_run_manifest(
        outputs_dir,
        "failed" if failed_step else "complete",
        step_results,
        failed_step,
    )
    print(f"Wrote {report_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the paper-to-poster pipeline.")
    parser.add_argument("pdf_path", help="Path to one academic paper PDF.")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument(
        "--fresh-output",
        action="store_true",
        help="Remove only managed prior-run artifacts from --outputs-dir before starting.",
    )
    parser.add_argument(
        "--extraction-mode",
        choices=["auto", "model", "local"],
        default="auto",
        help="auto uses model extraction when configured and otherwise falls back locally.",
    )
    parser.add_argument("--extraction-model", default=None, help="OpenAI model for semantic PDF extraction.")
    parser.add_argument(
        "--model-input-mode",
        choices=["auto", "pdf", "text"],
        default="auto",
        help="auto uses direct PDF input for OpenAI and page-numbered text for custom compatible endpoints.",
    )
    parser.add_argument(
        "--pdf-detail",
        choices=["auto", "low", "high"],
        default="auto",
        help="Visual detail used for PDF page images in model extraction.",
    )
    parser.add_argument("--skip-validate", action="store_true")
    parser.add_argument("--use-vision-review", action="store_true", help="Use an OpenAI vision model to review figure candidates before content selection.")
    parser.add_argument("--vision-model", default=None, help="OpenAI vision-capable model for --use-vision-review.")
    parser.add_argument("--use-faithfulness-review", action="store_true", help="Use an OpenAI text model to review poster claims against source evidence.")
    parser.add_argument("--faithfulness-model", default=None, help="OpenAI model for --use-faithfulness-review.")
    parser.add_argument(
        "--narrative-planning",
        choices=["off", "auto", "model", "local"],
        default="off",
        help="Plan poster sections from verified claim and source-figure IDs. auto uses a model when configured and otherwise falls back locally.",
    )
    parser.add_argument(
        "--narrative-model",
        default=None,
        help="OpenAI-compatible text model for poster narrative planning; defaults to --extraction-model when supplied.",
    )
    parser.add_argument(
        "--claim-evidence-gate",
        choices=["off", "critical", "all"],
        default="critical",
        help="Require page-and-quote evidence for take-home/result claims by default; all requires it for every poster claim.",
    )
    parser.add_argument(
        "--faithfulness-gate",
        choices=["off", "high", "medium"],
        default="high",
        help="When faithfulness review is enabled, stop on high-risk issues by default; medium also stops on needs_revision.",
    )
    parser.add_argument("--max-repair-iterations", type=int, default=2, help="Maximum deterministic layout repair attempts after overflow validation.")
    parser.add_argument(
        "--allow-overflow",
        action="store_true",
        help="Allow completion when estimated text overflow remains after repair attempts.",
    )
    parser.add_argument("--use-aesthetic-review", action="store_true", help="Use an OpenAI text model to review layout aesthetics from JSON after validation/repair.")
    parser.add_argument("--aesthetic-model", default=None, help="OpenAI model for --use-aesthetic-review.")
    parser.add_argument(
        "--aesthetic-gate",
        choices=["off", "high", "medium"],
        default="high",
        help="When aesthetic review is enabled, stop on high-risk issues by default; medium also stops on needs_revision.",
    )
    parser.add_argument(
        "--image-art-direction",
        choices=["off", "auto", "required"],
        default="off",
        help="Generate a style-reference image through Right Code. off avoids image charges; auto falls back; required stops on failure.",
    )
    parser.add_argument("--image-model", default=None, help="Right Code image model, defaulting to RIGHTCODE_IMAGE_MODEL or gpt-image-2.")
    parser.add_argument(
        "--image-aspect-ratio",
        choices=["1:1", "16:9", "9:16", "4:3"],
        default="4:3",
        help="Aspect ratio for the non-authoritative style reference.",
    )
    parser.add_argument("--image-size", choices=["1K", "2K", "4K"], default="1K")
    parser.add_argument(
        "--image-resume-task-id",
        default=None,
        help="Resume an existing Right Code image task instead of submitting a new billable task.",
    )
    parser.add_argument("--image-timeout-seconds", type=float, default=180.0)
    parser.add_argument(
        "--image-request-timeout",
        type=float,
        default=45.0,
        help="Timeout for each Right Code POST, GET, or image-download request. POST is never retried automatically.",
    )
    parser.add_argument("--image-poll-interval", type=float, default=2.0)
    parser.add_argument(
        "--reference-vision-analysis",
        choices=["off", "auto", "required"],
        default="off",
        help="Use a multimodal model to classify reference design semantics after local pixel analysis.",
    )
    parser.add_argument(
        "--preview-vision-review",
        choices=["off", "auto", "required"],
        default="off",
        help="Compare the rendered SVG preview with the style reference using a multimodal model.",
    )
    parser.add_argument(
        "--poster-vision-model",
        default=None,
        help="OpenAI-compatible multimodal model for reference analysis and rendered-preview review.",
    )
    parser.add_argument(
        "--max-preview-vision-repairs",
        type=int,
        default=1,
        help="Maximum bounded candidate-design repair passes after multimodal preview review (0-3).",
    )
    parser.add_argument(
        "--decorative-vectorization",
        choices=["off", "auto", "required"],
        default="auto",
        help="Use local VTracer only for safely isolated non-scientific reference decorations. auto falls back to deterministic SVG icons.",
    )
    parser.add_argument("--vtracer-command", default="vtracer", help="VTracer executable name or path.")
    parser.add_argument("--decorative-vectorization-timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.image_resume_task_id and args.image_art_direction == "off":
        parser.error("--image-resume-task-id requires --image-art-direction auto or required")
    if args.decorative_vectorization == "required" and args.image_art_direction == "off":
        parser.error("--decorative-vectorization required needs --image-art-direction auto or required")
    if args.reference_vision_analysis != "off" and args.image_art_direction == "off":
        parser.error("--reference-vision-analysis requires --image-art-direction auto or required")
    if args.preview_vision_review != "off" and args.image_art_direction == "off":
        parser.error("--preview-vision-review requires --image-art-direction auto or required")
    if args.preview_vision_review != "off" and args.skip_validate:
        parser.error("--preview-vision-review requires SVG overflow validation; remove --skip-validate")
    if not 0 <= args.max_preview_vision_repairs <= 3:
        parser.error("--max-preview-vision-repairs must be between 0 and 3")

    python = sys.executable
    outputs_dir = Path(args.outputs_dir)
    pdf_path = Path(args.pdf_path).expanduser()
    try:
        prepare_output_directory(outputs_dir, pdf_path, args.fresh_output)
    except ValueError as exc:
        parser.error(str(exc))
    args.pdf_path = str(pdf_path.resolve())

    raw_json = outputs_dir / "raw_pdf_extraction.json"
    extracted_json = outputs_dir / "extracted_paper.json"
    verification_json = outputs_dir / "extraction_verification.json"
    content_json = outputs_dir / "poster_content.json"
    narrative_plan_json = outputs_dir / "poster_narrative_plan.json"
    visual_brief_json = outputs_dir / "poster_visual_brief.json"
    visual_generation_json = outputs_dir / "poster_visual_generation.json"
    style_analysis_json = outputs_dir / "poster_style_analysis.json"
    reference_vision_analysis_json = outputs_dir / "poster_reference_vision_analysis.json"
    style_reference_path = outputs_dir / "poster_style_reference.png"
    decorative_vectors_json = outputs_dir / "poster_decorative_vectors.json"
    semantic_step = [
        python,
        script_path("structure_paper_with_openai.py"),
        args.pdf_path,
        "--raw-json",
        str(raw_json),
        "--output-json",
        str(extracted_json),
        "--mode",
        args.extraction_mode,
        "--detail",
        args.pdf_detail,
        "--input-mode",
        args.model_input_mode,
    ]
    if args.extraction_model:
        semantic_step.extend(["--model", args.extraction_model])

    steps = [
        [
            python,
            script_path("extract_paper.py"),
            args.pdf_path,
            "--outputs-dir",
            str(outputs_dir),
            "--output-json",
            str(raw_json),
        ],
        semantic_step,
        [
            python,
            script_path("verify_paper_extraction.py"),
            "--raw-json",
            str(raw_json),
            "--extracted-json",
            str(extracted_json),
            "--report-json",
            str(verification_json),
        ],
    ]
    if args.use_vision_review:
        review_step = [
            python,
            script_path("review_figures_with_openai.py"),
            "--input-json",
            str(extracted_json),
            "--output-json",
            str(extracted_json),
            "--outputs-dir",
            str(outputs_dir),
        ]
        if args.vision_model:
            review_step.extend(["--model", args.vision_model])
        steps.append(review_step)
    steps.extend(
        [
            [python, script_path("build_poster_content.py"), "--input-json", str(extracted_json), "--output-json", str(content_json)],
        ]
    )
    if args.use_faithfulness_review:
        faithfulness_step = [
            python,
            script_path("review_poster_faithfulness_with_openai.py"),
            "--content-json",
            str(content_json),
            "--extracted-json",
            str(extracted_json),
            "--output-json",
            str(outputs_dir / "poster_faithfulness_report.json"),
        ]
        if args.faithfulness_model:
            faithfulness_step.extend(["--model", args.faithfulness_model])
        steps.append(faithfulness_step)
    if args.narrative_planning != "off":
        narrative_step = [
            python,
            script_path("plan_poster_narrative_with_openai.py"),
            "--content-json",
            str(content_json),
            "--extracted-json",
            str(extracted_json),
            "--output-json",
            str(narrative_plan_json),
            "--mode",
            args.narrative_planning,
        ]
        narrative_model = args.narrative_model or args.extraction_model
        if narrative_model:
            narrative_step.extend(["--model", narrative_model])
        steps.append(narrative_step)
    if args.image_art_direction != "off":
        visual_brief_step = [
            python,
            script_path("build_poster_visual_brief.py"),
            "--content-json",
            str(content_json),
            "--output-json",
            str(visual_brief_json),
            "--style-reference-path",
            str(style_reference_path),
            "--aspect-ratio",
            args.image_aspect_ratio,
        ]
        if args.narrative_planning != "off":
            visual_brief_step.extend(["--narrative-plan-json", str(narrative_plan_json)])
        visual_generation_step = [
            python,
            script_path("generate_poster_style_with_rightcode.py"),
            "--brief-json",
            str(visual_brief_json),
            "--output-image",
            str(style_reference_path),
            "--report-json",
            str(visual_generation_json),
            "--mode",
            args.image_art_direction,
            "--size",
            args.image_aspect_ratio,
            "--image-size",
            args.image_size,
            "--timeout-seconds",
            str(args.image_timeout_seconds),
            "--request-timeout",
            str(args.image_request_timeout),
            "--poll-interval",
            str(args.image_poll_interval),
        ]
        visual_analysis_step = [
            python,
            script_path("analyze_poster_style_reference.py"),
            "--brief-json",
            str(visual_brief_json),
            "--image",
            str(style_reference_path),
            "--output-json",
            str(style_analysis_json),
            "--mode",
            args.image_art_direction,
        ]
        if args.narrative_planning != "off":
            visual_analysis_step.extend([
                "--content-json",
                str(content_json),
                "--narrative-plan-json",
                str(narrative_plan_json),
            ])
        if args.image_model:
            visual_brief_step.extend(["--model", args.image_model])
            visual_generation_step.extend(["--model", args.image_model])
        if args.image_resume_task_id:
            visual_generation_step.extend(["--resume-task-id", args.image_resume_task_id])
        steps.extend([visual_brief_step, visual_generation_step, visual_analysis_step])
        if args.reference_vision_analysis != "off":
            reference_vision_step = [
                python,
                script_path("analyze_reference_with_vision.py"),
                "--reference",
                str(style_reference_path),
                "--style-analysis-json",
                str(style_analysis_json),
                "--visual-brief-json",
                str(visual_brief_json),
                "--narrative-plan-json",
                str(narrative_plan_json),
                "--output-json",
                str(reference_vision_analysis_json),
                "--mode",
                args.reference_vision_analysis,
            ]
            if args.poster_vision_model:
                reference_vision_step.extend(["--model", args.poster_vision_model])
            steps.append(reference_vision_step)
        if args.decorative_vectorization != "off":
            steps.append([
                python,
                script_path("vectorize_reference_decorations.py"),
                "--reference",
                str(style_reference_path),
                "--analysis-json",
                str(style_analysis_json),
                "--output-dir",
                str(outputs_dir / "assets" / "generated"),
                "--report-json",
                str(decorative_vectors_json),
                "--mode",
                args.decorative_vectorization,
                "--command",
                args.vtracer_command,
                "--timeout-seconds",
                str(args.decorative_vectorization_timeout),
            ])

    design_step = [
        python,
        script_path("build_poster_design.py"),
        "--content-json",
        str(content_json),
        "--output-json",
        str(outputs_dir / "poster_design_spec.json"),
    ]
    if args.image_art_direction != "off":
        design_step.extend(["--visual-brief-json", str(visual_brief_json)])
        if args.decorative_vectorization != "off":
            design_step.extend(["--decorative-vectors-json", str(decorative_vectors_json)])
    steps.extend([
        design_step,
        [python, script_path("build_typesetting_manifest.py"), "--content-json", str(content_json), "--design-json", str(outputs_dir / "poster_design_spec.json"), "--output-json", str(outputs_dir / "poster_typesetting_manifest.json")],
        [python, script_path("build_poster_svg.py"), "--content-json", str(content_json), "--design-json", str(outputs_dir / "poster_design_spec.json"), "--typesetting-manifest-json", str(outputs_dir / "poster_typesetting_manifest.json"), "--outputs-dir", str(outputs_dir), "--svg-path", str(outputs_dir / "poster.svg"), "--layout-json", str(outputs_dir / "poster_layout.json")],
    ])

    if not args.skip_validate and Path(script_path("validate_svg.py")).exists():
        steps.append([
            python,
            script_path("validate_svg.py"),
            str(outputs_dir / "poster.svg"),
            "--outputs-dir",
            str(outputs_dir),
            "--layout-json",
            str(outputs_dir / "poster_layout.json"),
            "--overflow-report",
            str(outputs_dir / "poster_overflow_report.json"),
        ])

    step_results: list[dict[str, Any]] = []
    for step in steps:
        result = run_step(step)
        step_results.append(result)
        code = int(result["returncode"])
        if code != 0:
            write_generation_report(outputs_dir, args.pdf_path, step_results, failed_step=step)
            print(f"Step failed with exit code {code}.", file=sys.stderr)
            return code
        if command_has_script(step, "review_poster_faithfulness_with_openai.py"):
            faithfulness_report = read_json(outputs_dir / "poster_faithfulness_report.json")
            if report_fails_gate(faithfulness_report, args.faithfulness_gate):
                gate = quality_gate_result(
                    "faithfulness",
                    str(faithfulness_report.get("status", "missing_report")),
                )
                step_results.append(gate)
                write_generation_report(
                    outputs_dir,
                    args.pdf_path,
                    step_results,
                    failed_step=gate["command"],
                )
                print(
                    "Faithfulness quality gate failed; see poster_faithfulness_report.json.",
                    file=sys.stderr,
                )
                return 3
        if command_has_script(step, "build_poster_content.py"):
            content = read_json(outputs_dir / "poster_content.json")
            unresolved_claims = unresolved_claims_for_gate(content, args.claim_evidence_gate)
            if unresolved_claims:
                gate = quality_gate_result(
                    "claim-evidence",
                    f"unresolved={len(unresolved_claims)}",
                )
                step_results.append(gate)
                write_generation_report(
                    outputs_dir,
                    args.pdf_path,
                    step_results,
                    failed_step=gate["command"],
                )
                print(
                    "Claim evidence quality gate failed; critical poster claims lack verified page-and-quote evidence.",
                    file=sys.stderr,
                )
                return 3

    if not args.skip_validate and args.max_repair_iterations > 0:
        for iteration in range(1, args.max_repair_iterations + 1):
            overflow = read_json(outputs_dir / "poster_overflow_report.json")
            if overflow.get("status") == "passed":
                break
            repair_step = [
                python,
                script_path("repair_poster_layout.py"),
                "--design-json",
                str(outputs_dir / "poster_design_spec.json"),
                "--overflow-json",
                str(outputs_dir / "poster_overflow_report.json"),
                "--repair-report",
                str(outputs_dir / "layout_repair_report.json"),
                "--iteration",
                str(iteration),
            ]
            remeasure_step = [
                python,
                script_path("build_typesetting_manifest.py"),
                "--content-json",
                str(outputs_dir / "poster_content.json"),
                "--design-json",
                str(outputs_dir / "poster_design_spec.json"),
                "--output-json",
                str(outputs_dir / "poster_typesetting_manifest.json"),
            ]
            rerender_step = [
                python,
                script_path("build_poster_svg.py"),
                "--content-json",
                str(outputs_dir / "poster_content.json"),
                "--design-json",
                str(outputs_dir / "poster_design_spec.json"),
                "--typesetting-manifest-json",
                str(outputs_dir / "poster_typesetting_manifest.json"),
                "--outputs-dir",
                str(outputs_dir),
                "--svg-path",
                str(outputs_dir / "poster.svg"),
                "--layout-json",
                str(outputs_dir / "poster_layout.json"),
            ]
            revalidate_step = [
                python,
                script_path("validate_svg.py"),
                str(outputs_dir / "poster.svg"),
                "--outputs-dir",
                str(outputs_dir),
                "--layout-json",
                str(outputs_dir / "poster_layout.json"),
                "--overflow-report",
                str(outputs_dir / "poster_overflow_report.json"),
            ]
            for step in [repair_step, remeasure_step, rerender_step, revalidate_step]:
                result = run_step(step)
                step_results.append(result)
                code = int(result["returncode"])
                if code != 0:
                    write_generation_report(outputs_dir, args.pdf_path, step_results, failed_step=step)
                    print(f"Step failed with exit code {code}.", file=sys.stderr)
                    return code

    if not args.skip_validate:
        final_overflow = read_json(outputs_dir / "poster_overflow_report.json")
        if final_overflow.get("status") != "passed" and not args.allow_overflow:
            gate = quality_gate_result(
                "text-overflow",
                str(final_overflow.get("status", "missing_report")),
            )
            step_results.append(gate)
            write_generation_report(
                outputs_dir,
                args.pdf_path,
                step_results,
                failed_step=gate["command"],
            )
            print(
                "Text overflow remains after repair; use --allow-overflow only when this limitation is acceptable.",
                file=sys.stderr,
            )
            return 3

    if args.image_art_direction != "off":
        initial_render_step = [
            python,
            script_path("render_svg_preview.py"),
            str(outputs_dir / "poster.svg"),
            "--output",
            str(outputs_dir / "poster_render_preview.png"),
        ]
        result = run_step(initial_render_step)
        step_results.append(result)
        code = int(result["returncode"])
        if code != 0:
            write_generation_report(outputs_dir, args.pdf_path, step_results, failed_step=initial_render_step)
            print(f"Step failed with exit code {code}.", file=sys.stderr)
            return code

        if args.preview_vision_review != "off":
            visual_review_json = outputs_dir / "poster_visual_review.json"
            visual_repair_report_json = outputs_dir / "poster_visual_repair_report.json"
            candidate_paths = {
                "design": outputs_dir / "poster_design_spec.visual-candidate.json",
                "typesetting": outputs_dir / "poster_typesetting_manifest.visual-candidate.json",
                "svg": outputs_dir / "poster.visual-candidate.svg",
                "layout": outputs_dir / "poster_layout.visual-candidate.json",
                "overflow": outputs_dir / "poster_overflow_report.visual-candidate.json",
                "preview": outputs_dir / "poster_render_preview.visual-candidate.png",
            }

            def discard_visual_candidate() -> None:
                for path in candidate_paths.values():
                    path.unlink(missing_ok=True)

            review_passes = max(1, args.max_preview_vision_repairs)
            for iteration in range(1, review_passes + 1):
                visual_review_step = [
                    python,
                    script_path("review_rendered_poster_with_vision.py"),
                    "--reference",
                    str(style_reference_path),
                    "--preview",
                    str(outputs_dir / "poster_render_preview.png"),
                    "--design-json",
                    str(outputs_dir / "poster_design_spec.json"),
                    "--layout-json",
                    str(outputs_dir / "poster_layout.json"),
                    "--overflow-json",
                    str(outputs_dir / "poster_overflow_report.json"),
                    "--output-json",
                    str(visual_review_json),
                    "--mode",
                    args.preview_vision_review,
                ]
                if args.poster_vision_model:
                    visual_review_step.extend(["--model", args.poster_vision_model])
                result = run_step(visual_review_step)
                step_results.append(result)
                code = int(result["returncode"])
                if code != 0:
                    write_generation_report(outputs_dir, args.pdf_path, step_results, failed_step=visual_review_step)
                    print(f"Step failed with exit code {code}.", file=sys.stderr)
                    return code

                visual_review = read_json(visual_review_json)
                approved_patches = visual_review.get("approved_patches", [])
                if (
                    args.max_preview_vision_repairs == 0
                    or not isinstance(approved_patches, list)
                    or not approved_patches
                ):
                    break

                discard_visual_candidate()
                candidate_steps = [
                    [
                        python,
                        script_path("apply_visual_review_repairs.py"),
                        "--design-json",
                        str(outputs_dir / "poster_design_spec.json"),
                        "--review-json",
                        str(visual_review_json),
                        "--output-json",
                        str(candidate_paths["design"]),
                        "--report-json",
                        str(visual_repair_report_json),
                        "--iteration",
                        str(iteration),
                    ],
                    [
                        python,
                        script_path("build_typesetting_manifest.py"),
                        "--content-json",
                        str(content_json),
                        "--design-json",
                        str(candidate_paths["design"]),
                        "--output-json",
                        str(candidate_paths["typesetting"]),
                    ],
                    [
                        python,
                        script_path("build_poster_svg.py"),
                        "--content-json",
                        str(content_json),
                        "--design-json",
                        str(candidate_paths["design"]),
                        "--typesetting-manifest-json",
                        str(candidate_paths["typesetting"]),
                        "--outputs-dir",
                        str(outputs_dir),
                        "--svg-path",
                        str(candidate_paths["svg"]),
                        "--layout-json",
                        str(candidate_paths["layout"]),
                    ],
                    [
                        python,
                        script_path("validate_svg.py"),
                        str(candidate_paths["svg"]),
                        "--outputs-dir",
                        str(outputs_dir),
                        "--layout-json",
                        str(candidate_paths["layout"]),
                        "--overflow-report",
                        str(candidate_paths["overflow"]),
                    ],
                    [
                        python,
                        script_path("render_svg_preview.py"),
                        str(candidate_paths["svg"]),
                        "--output",
                        str(candidate_paths["preview"]),
                    ],
                ]
                candidate_ok = True
                rejection_reason = ""
                for candidate_step in candidate_steps:
                    result = run_step(candidate_step)
                    step_results.append(result)
                    if int(result["returncode"]) != 0:
                        candidate_ok = False
                        rejection_reason = f"candidate step failed: {Path(candidate_step[1]).name}"
                        break
                candidate_overflow = read_json(candidate_paths["overflow"])
                repair_report = read_json(visual_repair_report_json)
                if not repair_report.get("actions"):
                    candidate_ok = False
                    rejection_reason = rejection_reason or "no allowlisted repair actions were applicable"
                if candidate_overflow.get("status") != "passed":
                    candidate_ok = False
                    rejection_reason = rejection_reason or "candidate SVG did not pass overflow validation"

                if not candidate_ok:
                    repair_report.update({
                        "status": "rejected",
                        "rejection_reason": rejection_reason,
                        "final_design_unchanged": True,
                    })
                    write_json(visual_repair_report_json, repair_report)
                    discard_visual_candidate()
                    break

                accepted = {
                    "design": outputs_dir / "poster_design_spec.json",
                    "typesetting": outputs_dir / "poster_typesetting_manifest.json",
                    "svg": outputs_dir / "poster.svg",
                    "layout": outputs_dir / "poster_layout.json",
                    "overflow": outputs_dir / "poster_overflow_report.json",
                    "preview": outputs_dir / "poster_render_preview.png",
                }
                for key, candidate_path in candidate_paths.items():
                    candidate_path.replace(accepted[key])
                repair_report.update({
                    "status": "accepted",
                    "final_design_unchanged": False,
                    "accepted_preview_sha256": sha256_file(accepted["preview"]),
                    "accepted_candidate_passed_validation": True,
                })
                write_json(visual_repair_report_json, repair_report)

        conformance_step = [
            python,
            script_path("check_poster_style_conformance.py"),
            "--analysis-json",
            str(outputs_dir / "poster_style_analysis.json"),
            "--design-json",
            str(outputs_dir / "poster_design_spec.json"),
            "--layout-json",
            str(outputs_dir / "poster_layout.json"),
            "--output-json",
            str(outputs_dir / "poster_style_conformance_report.json"),
        ]
        for step in [conformance_step]:
            result = run_step(step)
            step_results.append(result)
            code = int(result["returncode"])
            if code != 0:
                write_generation_report(outputs_dir, args.pdf_path, step_results, failed_step=step)
                print(f"Step failed with exit code {code}.", file=sys.stderr)
                return code

    if args.use_aesthetic_review:
        aesthetic_step = [
            python,
            script_path("review_poster_aesthetics_with_openai.py"),
            "--content-json",
            str(outputs_dir / "poster_content.json"),
            "--design-json",
            str(outputs_dir / "poster_design_spec.json"),
            "--layout-json",
            str(outputs_dir / "poster_layout.json"),
            "--overflow-json",
            str(outputs_dir / "poster_overflow_report.json"),
            "--output-json",
            str(outputs_dir / "poster_aesthetic_report.json"),
        ]
        if args.aesthetic_model:
            aesthetic_step.extend(["--model", args.aesthetic_model])
        result = run_step(aesthetic_step)
        step_results.append(result)
        code = int(result["returncode"])
        if code != 0:
            write_generation_report(outputs_dir, args.pdf_path, step_results, failed_step=aesthetic_step)
            print(f"Step failed with exit code {code}.", file=sys.stderr)
            return code
        aesthetic_report = read_json(outputs_dir / "poster_aesthetic_report.json")
        if report_fails_gate(aesthetic_report, args.aesthetic_gate):
            gate = quality_gate_result(
                "aesthetics",
                str(aesthetic_report.get("status", "missing_report")),
            )
            step_results.append(gate)
            write_generation_report(
                outputs_dir,
                args.pdf_path,
                step_results,
                failed_step=gate["command"],
            )
            print(
                "Aesthetic quality gate failed; see poster_aesthetic_report.json.",
                file=sys.stderr,
            )
            return 3

    write_generation_report(outputs_dir, args.pdf_path, step_results)

    print(f"\nDone. Open {outputs_dir / 'poster.svg'} to inspect the poster.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
