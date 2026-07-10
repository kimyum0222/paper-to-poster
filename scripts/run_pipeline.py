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


def write_generation_report(
    outputs_dir: Path,
    pdf_path: str,
    step_results: list[dict[str, Any]],
    failed_step: list[str] | None = None,
) -> None:
    extracted = read_json(outputs_dir / "extracted_paper.json")
    content = read_json(outputs_dir / "poster_content.json")
    layout = read_json(outputs_dir / "poster_layout.json")

    generated_files = [
        "poster.svg",
        "extracted_paper.json",
        "poster_content.json",
        "poster_design_spec.json",
        "poster_layout.json",
    ]
    existing_files = [name for name in generated_files if (outputs_dir / name).exists()]
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
        "",
        "## Validation",
        "",
        f"- SVG validation: {validation_status}",
    ])
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
    parser.add_argument("--skip-validate", action="store_true")
    parser.add_argument("--use-vision-review", action="store_true", help="Use an OpenAI vision model to review figure candidates before content selection.")
    parser.add_argument("--vision-model", default=None, help="OpenAI vision-capable model for --use-vision-review.")
    args = parser.parse_args()

    python = sys.executable
    outputs_dir = Path(args.outputs_dir)

    steps = [
        [python, "scripts/extract_paper.py", args.pdf_path, "--outputs-dir", str(outputs_dir)],
    ]
    if args.use_vision_review:
        review_step = [
            python,
            "scripts/review_figures_with_openai.py",
            "--input-json",
            str(outputs_dir / "extracted_paper.json"),
            "--output-json",
            str(outputs_dir / "extracted_paper.json"),
            "--outputs-dir",
            str(outputs_dir),
        ]
        if args.vision_model:
            review_step.extend(["--model", args.vision_model])
        steps.append(review_step)
    steps.extend(
        [
            [python, "scripts/build_poster_content.py", "--input-json", str(outputs_dir / "extracted_paper.json"), "--output-json", str(outputs_dir / "poster_content.json")],
            [python, "scripts/build_poster_design.py", "--content-json", str(outputs_dir / "poster_content.json"), "--output-json", str(outputs_dir / "poster_design_spec.json")],
            [python, "scripts/build_poster_svg.py", "--content-json", str(outputs_dir / "poster_content.json"), "--design-json", str(outputs_dir / "poster_design_spec.json"), "--outputs-dir", str(outputs_dir), "--svg-path", str(outputs_dir / "poster.svg"), "--layout-json", str(outputs_dir / "poster_layout.json")],
        ]
    )

    if not args.skip_validate and Path("scripts/validate_svg.py").exists():
        steps.append([python, "scripts/validate_svg.py", str(outputs_dir / "poster.svg"), "--outputs-dir", str(outputs_dir), "--layout-json", str(outputs_dir / "poster_layout.json")])

    step_results: list[dict[str, Any]] = []
    for step in steps:
        result = run_step(step)
        step_results.append(result)
        code = int(result["returncode"])
        if code != 0:
            write_generation_report(outputs_dir, args.pdf_path, step_results, failed_step=step)
            print(f"Step failed with exit code {code}.", file=sys.stderr)
            return code

    write_generation_report(outputs_dir, args.pdf_path, step_results)

    print("\nDone. Open outputs/poster.svg to inspect the MVP poster.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
