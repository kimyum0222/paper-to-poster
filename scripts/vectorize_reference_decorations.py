#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, deque
from pathlib import Path
from typing import Any, Callable


SVG_NS = "http://www.w3.org/2000/svg"
ALLOWED_ELEMENTS = {"g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
ALLOWED_ATTRIBUTES = {
    "d", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-width", "stroke-opacity",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "opacity", "transform",
    "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r", "rx", "ry",
    "width", "height", "points",
}


class VectorizationError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VectorizationError(f"Could not read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VectorizationError(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def finite_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    return number if math.isfinite(number) else default


def manifest_asset_path(output_dir: Path, path: Path) -> str:
    if len(output_dir.parts) >= 2 and output_dir.parts[-2:] == ("assets", "generated"):
        return f"assets/generated/{path.name}"
    return path.as_posix()


def parse_svg_number(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = "".join(character for character in value.strip() if character in "0123456789+-.eE")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if math.isfinite(number) and number > 0 else None


def safe_attribute(name: str, value: str) -> bool:
    lower = value.lower()
    if name not in ALLOWED_ATTRIBUTES or "url(" in lower or "javascript:" in lower:
        return False
    if name == "transform" and not all(character in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-.eE(), \t" for character in value):
        return False
    return True


def sanitize_vector_svg(input_path: Path, output_path: Path, max_elements: int = 5000) -> dict[str, Any]:
    if not input_path.is_file():
        raise VectorizationError(f"VTracer output does not exist: {input_path}")
    if input_path.stat().st_size > 5 * 1024 * 1024:
        raise VectorizationError("VTracer output exceeds the 5 MB decorative-asset limit")
    try:
        source_root = ET.parse(input_path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise VectorizationError(f"VTracer output is not valid SVG XML: {exc}") from exc
    if local_name(source_root.tag) != "svg":
        raise VectorizationError("VTracer output root is not <svg>")

    view_box = str(source_root.attrib.get("viewBox", "")).strip()
    values: list[float] = []
    if view_box:
        try:
            values = [float(value) for value in view_box.replace(",", " ").split()]
        except ValueError:
            values = []
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0 or not all(math.isfinite(value) for value in values):
        width = parse_svg_number(source_root.attrib.get("width"))
        height = parse_svg_number(source_root.attrib.get("height"))
        if width is None or height is None:
            raise VectorizationError("VTracer SVG has no usable viewBox or dimensions")
        values = [0.0, 0.0, width, height]

    element_count = 0
    path_count = 0

    def clone(source: ET.Element) -> ET.Element | None:
        nonlocal element_count, path_count
        tag = local_name(source.tag)
        if tag not in ALLOWED_ELEMENTS:
            return None
        if tag == "path" and not str(source.attrib.get("d", "")).strip():
            return None
        element_count += 1
        if element_count > max_elements:
            raise VectorizationError(f"VTracer SVG exceeds the {max_elements}-element safety limit")
        if tag == "path":
            path_count += 1
        target = ET.Element(tag)
        for raw_name, raw_value in source.attrib.items():
            name = local_name(raw_name)
            if safe_attribute(name, raw_value):
                target.set(name, raw_value)
        for child in source:
            cloned = clone(child)
            if cloned is not None:
                target.append(cloned)
        return target

    output_root = ET.Element("svg", {
        "xmlns": SVG_NS,
        "viewBox": " ".join(f"{value:.6g}" for value in values),
        "width": f"{values[2]:.6g}",
        "height": f"{values[3]:.6g}",
        "preserveAspectRatio": "xMidYMid meet",
    })
    for child in source_root:
        cloned = clone(child)
        if cloned is not None:
            output_root.append(cloned)
    if element_count == 0:
        raise VectorizationError("VTracer SVG contains no allowed vector geometry")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(output_root).write(output_path, encoding="utf-8", xml_declaration=True)
    return {
        "viewBox": values,
        "element_count": element_count,
        "path_count": path_count,
        "sanitization": "allowlisted_inline_svg_geometry",
    }


def color_distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)))


def dominant_border_color(image: Any) -> tuple[int, int, int]:
    width, height = image.size
    depth = max(1, min(width, height) // 20)
    colors = []
    for y in range(height):
        for x in range(width):
            if x < depth or x >= width - depth or y < depth or y >= height - depth:
                red, green, blue, _alpha = image.getpixel((x, y))
                colors.append((red // 8 * 8, green // 8 * 8, blue // 8 * 8))
    return Counter(colors).most_common(1)[0][0]


def connected_component_boxes(mask: list[bool], width: int, height: int) -> list[dict[str, int]]:
    visited = bytearray(width * height)
    boxes: list[dict[str, int]] = []
    for start in range(width * height):
        if visited[start] or not mask[start]:
            continue
        queue = deque([start])
        visited[start] = 1
        xs: list[int] = []
        ys: list[int] = []
        while queue:
            index = queue.popleft()
            y, x = divmod(index, width)
            xs.append(x)
            ys.append(y)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    nx, ny = x + dx, y + dy
                    neighbor = ny * width + nx
                    if 0 <= nx < width and 0 <= ny < height and not visited[neighbor] and mask[neighbor]:
                        visited[neighbor] = 1
                        queue.append(neighbor)
        boxes.append({
            "x0": min(xs), "y0": min(ys), "x1": max(xs) + 1, "y1": max(ys) + 1,
            "pixels": len(xs),
        })
    return boxes


def find_header_decorative_box(image: Any, header_fraction: float) -> dict[str, float] | None:
    width, height = image.size
    header_end = max(1, min(height, round(height * header_fraction)))
    x0 = round(width * 0.58)
    x1 = round(width * 0.985)
    y0 = max(1, round(height * 0.015))
    y1 = max(y0 + 1, header_end - round(height * 0.012))
    search = image.crop((x0, y0, x1, y1)).convert("RGBA")
    background = dominant_border_color(search)
    search_width, search_height = search.size
    mask: list[bool] = []
    for red, green, blue, alpha in search.getdata():
        mask.append(alpha > 24 and color_distance((red, green, blue), background) >= 42)
    boxes = connected_component_boxes(mask, search_width, search_height)
    tall = [
        box for box in boxes
        if box["y1"] - box["y0"] >= search_height * 0.24 and box["pixels"] >= 18
    ]
    if not tall:
        return None
    left = max(0, min(box["x0"] for box in tall) - round(width * 0.012))
    right = min(search_width, max(box["x1"] for box in tall) + round(width * 0.012))
    top = max(0, min(box["y0"] for box in tall) - round(height * 0.008))
    bottom = min(search_height, max(box["y1"] for box in tall) + round(height * 0.008))
    if right - left < width * 0.12 or bottom - top < header_end * 0.25:
        return None
    return {
        "x": (x0 + left) / width,
        "y": (y0 + top) / height,
        "width": (right - left) / width,
        "height": (bottom - top) / height,
    }


def decoration_regions(reference_path: Path, analysis: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise VectorizationError("Pillow is required to crop decorative reference regions") from exc
    if analysis.get("status") != "passed":
        return []
    spatial = analysis.get("spatial_design") if isinstance(analysis.get("spatial_design"), dict) else {}
    if spatial.get("status") != "passed":
        return []
    measurements = spatial.get("measurements") if isinstance(spatial.get("measurements"), dict) else {}
    decorations = spatial.get("decorations") if isinstance(spatial.get("decorations"), dict) else {}
    with Image.open(reference_path) as source:
        image = source.convert("RGBA")
        header_box = find_header_decorative_box(
            image,
            max(0.08, min(0.24, finite_float(measurements.get("header_fraction"), 0.14))),
        )
    regions: list[dict[str, Any]] = []
    if header_box and (decorations.get("header_process") or {}).get("enabled"):
        regions.append({"id": "header-process-icons", "target": "header_process", "box": header_box})
    panel_detection = measurements.get("panel_detection") if isinstance(measurements.get("panel_detection"), dict) else {}
    strips = [item for item in panel_detection.get("decorative_strips", []) if isinstance(item, dict)]
    if strips and (decorations.get("body_flow") or {}).get("enabled"):
        strip = max(strips, key=lambda item: finite_float(item.get("width")) * finite_float(item.get("height")))
        box = {key: finite_float(strip.get(key)) for key in ["x", "y", "width", "height"]}
        if box["width"] > 0 and box["height"] > 0:
            regions.append({"id": "body-process-strip", "target": "body_flow", "box": box})
    return regions


def crop_transparent_region(reference_path: Path, box: dict[str, float], output_path: Path) -> dict[str, Any]:
    try:
        from PIL import Image
    except ImportError as exc:
        raise VectorizationError("Pillow is required to crop decorative reference regions") from exc
    with Image.open(reference_path) as source:
        image = source.convert("RGBA")
        width, height = image.size
        left = max(0, min(width - 1, round(box["x"] * width)))
        top = max(0, min(height - 1, round(box["y"] * height)))
        right = max(left + 1, min(width, round((box["x"] + box["width"]) * width)))
        bottom = max(top + 1, min(height, round((box["y"] + box["height"]) * height)))
        crop = image.crop((left, top, right, bottom))
    background = dominant_border_color(crop)
    pixels = []
    visible = 0
    for red, green, blue, alpha in crop.getdata():
        if alpha <= 24 or color_distance((red, green, blue), background) < 34:
            pixels.append((255, 255, 255, 0))
        else:
            pixels.append((red, green, blue, alpha))
            visible += 1
    coverage = visible / max(1, crop.width * crop.height)
    if coverage < 0.002:
        raise VectorizationError("Decorative crop contains too little foreground geometry")
    if coverage > 0.72:
        raise VectorizationError("Decorative crop background removal was not reliable")
    crop.putdata(pixels)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(output_path, format="PNG")
    return {
        "pixel_box": [left, top, right, bottom],
        "width_px": crop.width,
        "height_px": crop.height,
        "foreground_coverage": round(coverage, 5),
        "background_key": "#" + "".join(f"{channel:02x}" for channel in background),
    }


def find_vtracer(command: str) -> dict[str, str] | None:
    path = Path(command).expanduser()
    if (path.is_absolute() or "/" in command) and path.is_file():
        return {"kind": "cli", "executable": str(path)}
    executable = shutil.which(command)
    if executable:
        return {"kind": "cli", "executable": executable, "version": "reported_by_cli_at_runtime"}
    if command == "vtracer" and importlib.util.find_spec("vtracer") is not None:
        try:
            version = importlib.metadata.version("vtracer")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        return {"kind": "python_binding", "executable": sys.executable, "version": version}
    return None


def invoke_vtracer(
    backend: dict[str, str],
    input_path: Path,
    output_path: Path,
    timeout_seconds: float,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    executable = backend["executable"]
    if backend.get("kind") == "python_binding":
        command = [
            executable,
            "-c",
            (
                "import sys, vtracer; "
                "vtracer.convert_image_to_svg_py(sys.argv[1], sys.argv[2], "
                "colormode='color', hierarchical='stacked', mode='spline', "
                "filter_speckle=4, color_precision=6, layer_difference=16, path_precision=3)"
            ),
            str(input_path),
            str(output_path),
        ]
    else:
        command = [executable, "--input", str(input_path), "--output", str(output_path), "--preset", "poster"]
    result = runner(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown VTracer failure").strip()
        raise VectorizationError(f"VTracer exited with {result.returncode}: {detail[:300]}")


def vectorize_reference(
    reference_path: Path,
    analysis: dict[str, Any],
    output_dir: Path,
    command: str,
    mode: str,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    base = {
        "version": 1,
        "status": "skipped",
        "mode": mode,
        "vectorizer": "vtracer",
        "asset_class": "generated_decorative",
        "reference_path": str(reference_path),
        "reference_sha256": sha256_file(reference_path) if reference_path.is_file() else None,
        "scientific_meaning": "none",
        "assets": [],
    }
    if mode == "off":
        return {**base, "reason": "Decorative vectorization is disabled."}
    if not reference_path.is_file():
        raise VectorizationError(f"Style reference does not exist: {reference_path}")
    analysis_sha256 = str(analysis.get("source_sha256", "") or "").strip().lower()
    if analysis_sha256 and analysis_sha256 != base["reference_sha256"]:
        raise VectorizationError("Style-reference hash does not match the analyzed image")
    backend = find_vtracer(command)
    if not backend:
        availability = (
            "Neither the default VTracer executable nor its Python binding was found."
            if command == "vtracer"
            else f"The explicitly configured VTracer executable was not found: {command}"
        )
        return {
            **base,
            "reason": availability,
            "requested_asset_count": 0,
            "generated_asset_count": 0,
            "fallback": "deterministic_vector_substitute",
        }
    regions = decoration_regions(reference_path, analysis)
    if not regions:
        return {
            **base,
            "reason": "No safely isolated decorative regions were detected.",
            "fallback": "deterministic_vector_substitute",
            "requested_asset_count": 0,
            "generated_asset_count": 0,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    for region in regions:
        asset_id = str(region["id"])
        crop_path = output_dir / f"{asset_id}.png"
        raw_svg = output_dir / f"{asset_id}.raw.svg"
        vector_path = output_dir / f"{asset_id}.svg"
        entry: dict[str, Any] = {
            "id": asset_id,
            "target": region["target"],
            "asset_class": "generated_decorative",
            "scientific_meaning": "none",
            "source_kind": "style_reference_crop",
            "reference_crop_normalized": region["box"],
            "crop_path": manifest_asset_path(output_dir, crop_path),
            "vector_path": manifest_asset_path(output_dir, vector_path),
            "status": "failed",
        }
        try:
            crop_metadata = crop_transparent_region(reference_path, region["box"], crop_path)
            invoke_vtracer(backend, crop_path, raw_svg, timeout_seconds)
            svg_metadata = sanitize_vector_svg(raw_svg, vector_path)
            entry.update({
                "status": "generated",
                "render_mode": "vtracer_inline",
                "crop_sha256": sha256_file(crop_path),
                "vector_sha256": sha256_file(vector_path),
                **crop_metadata,
                **svg_metadata,
            })
        except (OSError, subprocess.SubprocessError, VectorizationError) as exc:
            entry["failure"] = str(exc)
        finally:
            if raw_svg.exists():
                raw_svg.unlink()
        assets.append(entry)
    generated = [asset for asset in assets if asset.get("status") == "generated"]
    status = "generated" if len(generated) == len(regions) else "partial" if generated else "failed"
    return {
        **base,
        "status": status,
        "backend": backend,
        "assets": assets,
        "generated_asset_count": len(generated),
        "requested_asset_count": len(regions),
        "fallback": "deterministic_vector_substitute" if status != "generated" else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Vectorize safely isolated decorative regions from a poster style reference with VTracer.")
    parser.add_argument("--reference", default="outputs/poster_style_reference.png")
    parser.add_argument("--analysis-json", default="outputs/poster_style_analysis.json")
    parser.add_argument("--output-dir", default="outputs/assets/generated")
    parser.add_argument("--report-json", default="outputs/poster_decorative_vectors.json")
    parser.add_argument("--mode", choices=["off", "auto", "required"], default="auto")
    parser.add_argument("--command", default="vtracer")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args()
    report_path = Path(args.report_json)
    try:
        report = vectorize_reference(
            Path(args.reference),
            read_json(Path(args.analysis_json)),
            Path(args.output_dir),
            args.command,
            args.mode,
            args.timeout_seconds,
        )
    except VectorizationError as exc:
        report = {
            "version": 1,
            "status": "failed",
            "mode": args.mode,
            "vectorizer": "vtracer",
            "asset_class": "generated_decorative",
            "scientific_meaning": "none",
            "failure": str(exc),
            "assets": [],
        }
    write_json(report_path, report)
    print(f"Wrote {report_path}")
    print(f"Decorative vectorization: {report.get('status')}")
    if report.get("reason"):
        print(report["reason"])
    if args.mode == "required" and report.get("status") != "generated":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
