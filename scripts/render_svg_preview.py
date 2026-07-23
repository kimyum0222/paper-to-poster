#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the deterministic SVG poster for visual review.")
    parser.add_argument("svg_path", nargs="?", default="outputs/poster.svg")
    parser.add_argument("--output", default="outputs/poster_render_preview.png")
    parser.add_argument("--scale", type=float, default=1.6)
    args = parser.parse_args()
    svg_path = Path(args.svg_path)
    output = Path(args.output)
    if not svg_path.is_file():
        print(f"Error: SVG does not exist: {svg_path}", file=sys.stderr)
        return 1
    try:
        import fitz
        document = fitz.open(str(svg_path))
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(args.scale, args.scale), alpha=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(str(output))
    except Exception as exc:
        print(f"Error: could not render SVG preview: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
