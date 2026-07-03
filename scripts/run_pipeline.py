#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_step(command: list[str]) -> int:
    print("\n$ " + " ".join(command))
    result = subprocess.run(command)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the MVP paper-to-poster pipeline.")
    parser.add_argument("pdf_path", help="Path to one academic paper PDF.")
    parser.add_argument("--outputs-dir", default="outputs")
    parser.add_argument("--skip-validate", action="store_true")
    args = parser.parse_args()

    python = sys.executable
    outputs_dir = Path(args.outputs_dir)

    steps = [
        [python, "scripts/extract_paper.py", args.pdf_path, "--outputs-dir", str(outputs_dir)],
        [python, "scripts/build_poster_content.py", "--input-json", str(outputs_dir / "extracted_paper.json"), "--output-json", str(outputs_dir / "poster_content.json")],
        [python, "scripts/build_poster_svg.py", "--content-json", str(outputs_dir / "poster_content.json"), "--outputs-dir", str(outputs_dir), "--svg-path", str(outputs_dir / "poster.svg"), "--layout-json", str(outputs_dir / "poster_layout.json")],
    ]

    if not args.skip_validate and Path("scripts/validate_svg.py").exists():
        steps.append([python, "scripts/validate_svg.py", str(outputs_dir / "poster.svg"), "--outputs-dir", str(outputs_dir), "--layout-json", str(outputs_dir / "poster_layout.json")])

    for step in steps:
        code = run_step(step)
        if code != 0:
            print(f"Step failed with exit code {code}.", file=sys.stderr)
            return code

    print("\nDone. Open outputs/poster.svg to inspect the MVP poster.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
