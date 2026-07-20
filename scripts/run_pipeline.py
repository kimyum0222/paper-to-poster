#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


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
    raw_extraction = read_json(outputs_dir / "raw_pdf_extraction.json")
    extracted = read_json(outputs_dir / "extracted_paper.json")
    extraction_verification = read_json(outputs_dir / "extraction_verification.json")
    content = read_json(outputs_dir / "poster_content.json")
    layout = read_json(outputs_dir / "poster_layout.json")
    overflow_report = read_json(outputs_dir / "poster_overflow_report.json")
    faithfulness_report = read_json(outputs_dir / "poster_faithfulness_report.json")
    repair_report = read_json(outputs_dir / "layout_repair_report.json")
    aesthetic_report = read_json(outputs_dir / "poster_aesthetic_report.json")
    visual_requested = any(
        "scripts/build_poster_visual_brief.py" in result.get("command", [])
        for result in step_results
        if isinstance(result.get("command"), list)
    )
    visual_analyzed = any(
        "scripts/analyze_poster_style_reference.py" in result.get("command", [])
        for result in step_results
        if isinstance(result.get("command"), list)
    )
    visual_brief = read_json(outputs_dir / "poster_visual_brief.json") if visual_requested else {}
    visual_generation = read_json(outputs_dir / "poster_visual_generation.json") if visual_requested else {}
    visual_analysis = read_json(outputs_dir / "poster_style_analysis.json") if visual_analyzed else {}

    generated_files = [
        "poster.svg",
        "raw_pdf_extraction.json",
        "extracted_paper.json",
        "extraction_verification.json",
        "poster_content.json",
        "poster_design_spec.json",
        "poster_layout.json",
        "poster_overflow_report.json",
        "poster_faithfulness_report.json",
        "layout_repair_report.json",
        "poster_aesthetic_report.json",
        "generation_report.md",
    ]
    if visual_requested:
        generated_files.extend([
            "poster_visual_brief.json",
            "poster_visual_generation.json",
        ])
        if visual_analyzed:
            generated_files.append("poster_style_analysis.json")
        if visual_generation.get("status") == "generated":
            generated_files.append("poster_style_reference.png")
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
        if isinstance(command, list) and "scripts/validate_svg.py" in command:
            validation_status = "passed" if result.get("returncode") == 0 else "failed"

    report = [
        "# Generation Report",
        "",
        "## Source",
        "",
        f"- PDF: `{pdf_path}`",
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

    omitted = content.get("omitted_sections", [])
    report.extend([
        "",
        "## Layout And Assets",
        "",
        f"- Template: {layout.get('template', 'unknown')}",
        f"- Template rationale: {layout.get('template_rationale', '') or 'not recorded'}",
        f"- Canvas: {layout.get('canvas_width', 1189)} x {layout.get('canvas_height', 841)}",
        f"- Asset embedding mode: {layout.get('asset_embedding_mode', 'unknown')}",
        "- SVG images are embedded as data URIs when local assets can be read.",
    ])
    if visual_requested:
        report.extend([
            "",
            "## Image-Model Art Direction",
            "",
            f"- Status: {visual_brief.get('status', visual_generation.get('status', 'unknown'))}",
            f"- Provider: {visual_brief.get('provider', visual_generation.get('provider', 'rightcode'))}",
            f"- Model: {visual_brief.get('model', visual_generation.get('model', 'unknown'))}",
            f"- Provider task ID: {visual_generation.get('task_id', 'not recorded')}",
            f"- Existing task resumable: {visual_generation.get('resumable', False)}",
            f"- Generated asset class: {visual_generation.get('asset_class', 'style_reference_only')}",
            f"- Style reference included in final SVG: {visual_generation.get('included_in_final_svg', False)}",
            f"- Reference-pixel analysis: {visual_analysis.get('status', 'not run')}",
            f"- Analysis method: {visual_analysis.get('method', 'not run')}",
            f"- Derived design tokens applied: {visual_analysis.get('status') == 'passed'}",
            "- Scientific text, metrics, and source figures remain under deterministic SVG control.",
        ])
        if visual_generation.get("failure"):
            report.append(f"- Failure/fallback: {visual_generation.get('failure')}")
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
    print(f"Wrote {report_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the MVP paper-to-poster pipeline.")
    parser.add_argument("pdf_path", help="Path to one academic paper PDF.")
    parser.add_argument("--outputs-dir", default="outputs")
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
        default="16:9",
        help="Aspect ratio for the non-authoritative style reference.",
    )
    parser.add_argument("--image-size", choices=["1K", "2K", "4K"], default="1K")
    parser.add_argument(
        "--image-resume-task-id",
        default=None,
        help="Resume an existing Right Code image task instead of submitting a new billable task.",
    )
    parser.add_argument("--image-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--image-poll-interval", type=float, default=2.0)
    args = parser.parse_args()
    if args.image_resume_task_id and args.image_art_direction == "off":
        parser.error("--image-resume-task-id requires --image-art-direction auto or required")

    python = sys.executable
    outputs_dir = Path(args.outputs_dir)

    raw_json = outputs_dir / "raw_pdf_extraction.json"
    extracted_json = outputs_dir / "extracted_paper.json"
    verification_json = outputs_dir / "extraction_verification.json"
    content_json = outputs_dir / "poster_content.json"
    visual_brief_json = outputs_dir / "poster_visual_brief.json"
    visual_generation_json = outputs_dir / "poster_visual_generation.json"
    style_analysis_json = outputs_dir / "poster_style_analysis.json"
    style_reference_path = outputs_dir / "poster_style_reference.png"
    semantic_step = [
        python,
        "scripts/structure_paper_with_openai.py",
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
            "scripts/extract_paper.py",
            args.pdf_path,
            "--outputs-dir",
            str(outputs_dir),
            "--output-json",
            str(raw_json),
        ],
        semantic_step,
        [
            python,
            "scripts/verify_paper_extraction.py",
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
            "scripts/review_figures_with_openai.py",
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
            [python, "scripts/build_poster_content.py", "--input-json", str(extracted_json), "--output-json", str(content_json)],
        ]
    )
    if args.use_faithfulness_review:
        faithfulness_step = [
            python,
            "scripts/review_poster_faithfulness_with_openai.py",
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
    if args.image_art_direction != "off":
        visual_brief_step = [
            python,
            "scripts/build_poster_visual_brief.py",
            "--content-json",
            str(content_json),
            "--output-json",
            str(visual_brief_json),
            "--style-reference-path",
            str(style_reference_path),
        ]
        visual_generation_step = [
            python,
            "scripts/generate_poster_style_with_rightcode.py",
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
            "--poll-interval",
            str(args.image_poll_interval),
        ]
        visual_analysis_step = [
            python,
            "scripts/analyze_poster_style_reference.py",
            "--brief-json",
            str(visual_brief_json),
            "--image",
            str(style_reference_path),
            "--output-json",
            str(style_analysis_json),
            "--mode",
            args.image_art_direction,
        ]
        if args.image_model:
            visual_brief_step.extend(["--model", args.image_model])
            visual_generation_step.extend(["--model", args.image_model])
        if args.image_resume_task_id:
            visual_generation_step.extend(["--resume-task-id", args.image_resume_task_id])
        steps.extend([visual_brief_step, visual_generation_step, visual_analysis_step])

    design_step = [
        python,
        "scripts/build_poster_design.py",
        "--content-json",
        str(content_json),
        "--output-json",
        str(outputs_dir / "poster_design_spec.json"),
    ]
    if args.image_art_direction != "off":
        design_step.extend(["--visual-brief-json", str(visual_brief_json)])
    steps.extend([
        design_step,
        [python, "scripts/build_poster_svg.py", "--content-json", str(content_json), "--design-json", str(outputs_dir / "poster_design_spec.json"), "--outputs-dir", str(outputs_dir), "--svg-path", str(outputs_dir / "poster.svg"), "--layout-json", str(outputs_dir / "poster_layout.json")],
    ])

    if not args.skip_validate and Path("scripts/validate_svg.py").exists():
        steps.append([
            python,
            "scripts/validate_svg.py",
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
        if "scripts/review_poster_faithfulness_with_openai.py" in step:
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
        if "scripts/build_poster_content.py" in step:
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
                "scripts/repair_poster_layout.py",
                "--design-json",
                str(outputs_dir / "poster_design_spec.json"),
                "--overflow-json",
                str(outputs_dir / "poster_overflow_report.json"),
                "--repair-report",
                str(outputs_dir / "layout_repair_report.json"),
                "--iteration",
                str(iteration),
            ]
            rerender_step = [
                python,
                "scripts/build_poster_svg.py",
                "--content-json",
                str(outputs_dir / "poster_content.json"),
                "--design-json",
                str(outputs_dir / "poster_design_spec.json"),
                "--outputs-dir",
                str(outputs_dir),
                "--svg-path",
                str(outputs_dir / "poster.svg"),
                "--layout-json",
                str(outputs_dir / "poster_layout.json"),
            ]
            revalidate_step = [
                python,
                "scripts/validate_svg.py",
                str(outputs_dir / "poster.svg"),
                "--outputs-dir",
                str(outputs_dir),
                "--layout-json",
                str(outputs_dir / "poster_layout.json"),
                "--overflow-report",
                str(outputs_dir / "poster_overflow_report.json"),
            ]
            for step in [repair_step, rerender_step, revalidate_step]:
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

    if args.use_aesthetic_review:
        aesthetic_step = [
            python,
            "scripts/review_poster_aesthetics_with_openai.py",
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

    print(f"\nDone. Open {outputs_dir / 'poster.svg'} to inspect the MVP poster.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
