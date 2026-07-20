#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


DEFAULT_DRAW_BASE_URL = "https://www.right.codes/draw/v1"
DEFAULT_TASK_BASE_URL = "https://www.right.codes/v1"
MAX_IMAGE_BYTES = 25 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

JsonRequester = Callable[[str, str, str, dict[str, Any] | None, float], dict[str, Any]]
ByteDownloader = Callable[[str, float], bytes]


class ImageTaskTimeout(TimeoutError):
    def __init__(self, task_id: str, timeout_seconds: float) -> None:
        self.task_id = task_id
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Right Code image task {task_id} did not complete within {timeout_seconds:g} seconds"
        )


def clean_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read JSON from {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_https_base_url(value: str, name: str) -> str:
    url = value.rstrip("/")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute https URL")
    return url


def api_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return clean_space(error.get("message") or error.get("code")) or "unknown provider error"
        if isinstance(error, str):
            return clean_space(error)
        return clean_space(payload.get("message")) or "unknown provider error"
    return clean_space(payload) or "unknown provider error"


def request_json(method: str, url: str, api_key: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "paper-to-poster/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read(8192)
        try:
            parsed = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            parsed = body.decode("utf-8", errors="replace")
        raise RuntimeError(f"Right Code HTTP {exc.code}: {api_error_message(parsed)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Right Code request failed: {clean_space(exc.reason)}") from exc

    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Right Code returned a non-JSON response") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Right Code returned a JSON value that is not an object")
    return parsed


def download_bytes(url: str, timeout: float) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("Generated image URL must use https")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "image/*", "User-Agent": "paper-to-poster/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(MAX_IMAGE_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Could not download generated image: {clean_space(exc)}") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise RuntimeError("Generated image exceeds the 25 MB safety limit")
    return data


def unwrap_result(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    return result if isinstance(result, dict) else payload


def image_record(payload: dict[str, Any]) -> dict[str, Any] | None:
    payload = unwrap_result(payload)
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and (item.get("b64_json") or item.get("url")):
                return item
    return None


def image_bytes_from_record(record: dict[str, Any], downloader: ByteDownloader, timeout: float) -> tuple[bytes, str]:
    encoded = clean_space(record.get("b64_json"))
    if encoded:
        if encoded.startswith("data:"):
            if "," not in encoded:
                raise RuntimeError("Generated image data URL is malformed")
            encoded = encoded.split(",", 1)[1]
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise RuntimeError("Generated image base64 is invalid") from exc
        return data, "base64"
    url = clean_space(record.get("url"))
    if url:
        return downloader(url, timeout), "url"
    raise RuntimeError("Completed image task did not contain a URL or base64 image")


def normalize_png(data: bytes) -> bytes:
    if len(data) > MAX_IMAGE_BYTES:
        raise RuntimeError("Generated image exceeds the 25 MB safety limit")
    if data.startswith(PNG_SIGNATURE):
        return data
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Right Code returned a non-PNG image and Pillow is unavailable for conversion") from exc
    try:
        with Image.open(io.BytesIO(data)) as image:
            output = io.BytesIO()
            image.convert("RGB").save(output, format="PNG")
            converted = output.getvalue()
    except Exception as exc:
        raise RuntimeError("Right Code returned unsupported or corrupt image bytes") from exc
    if not converted.startswith(PNG_SIGNATURE):
        raise RuntimeError("Could not normalize generated image to PNG")
    return converted


def poll_for_result(
    task_id: str,
    task_base_url: str,
    api_key: str,
    timeout_seconds: float,
    request_timeout: float,
    poll_interval: float,
    requester: JsonRequester,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    encoded_task_id = urllib.parse.quote(task_id, safe="")
    task_url = f"{task_base_url}/tasks/{encoded_task_id}"
    deadline = clock() + timeout_seconds
    last_progress: Any = None
    while clock() < deadline:
        payload = requester("GET", task_url, api_key, None, request_timeout)
        record = image_record(payload)
        if record:
            return payload
        normalized = unwrap_result(payload)
        status = clean_space(normalized.get("status")).lower()
        if status == "failed":
            raise RuntimeError(f"Right Code image task failed: {api_error_message(normalized)}")
        if status in {"cancelled", "canceled", "expired"}:
            raise RuntimeError(f"Right Code image task ended with status {status}")
        progress = normalized.get("progress")
        if progress != last_progress:
            print(f"Right Code image task {task_id}: {status or 'processing'} ({progress if progress is not None else '?'}%)", flush=True)
            last_progress = progress
        sleeper(poll_interval)
    raise ImageTaskTimeout(task_id, timeout_seconds)


def save_completed_result(
    final_payload: dict[str, Any],
    output_path: Path,
    task_id: str | None,
    model: str,
    request_metadata: dict[str, Any],
    request_timeout: float,
    downloader: ByteDownloader,
) -> dict[str, Any]:
    record = image_record(final_payload)
    if not record:
        raise RuntimeError("Right Code image task completed without an image result")
    raw_bytes, result_transport = image_bytes_from_record(record, downloader, request_timeout)
    png_bytes = normalize_png(raw_bytes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    temporary.write_bytes(png_bytes)
    temporary.replace(output_path)
    return {
        "status": "generated",
        "provider": "rightcode",
        "model": model,
        "task_id": task_id or None,
        "request": request_metadata,
        "output_path": str(output_path),
        "asset_class": "style_reference_only",
        "result_transport": result_transport,
        "byte_count": len(png_bytes),
        "sha256": hashlib.sha256(png_bytes).hexdigest(),
        "included_in_final_svg": False,
    }


def generate_style_reference(
    brief: dict[str, Any],
    output_path: Path,
    api_key: str,
    draw_base_url: str,
    task_base_url: str,
    model: str,
    size: str,
    image_size: str,
    timeout_seconds: float,
    request_timeout: float,
    poll_interval: float,
    requester: JsonRequester = request_json,
    downloader: ByteDownloader = download_bytes,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    prompt = clean_space(brief.get("prompt"))
    if not prompt:
        raise ValueError("Visual brief does not contain a generation prompt")
    submit_url = f"{draw_base_url}/images/generations"
    request_payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "async": True,
    }
    supports_explicit_image_size = "vip" in model.casefold() or model.casefold().startswith("nano-banana")
    if supports_explicit_image_size:
        request_payload["imageSize"] = image_size
    elif image_size != "1K":
        raise ValueError(f"{model} does not advertise {image_size}; use 1K or an image-size-capable model")
    submitted = requester("POST", submit_url, api_key, request_payload, request_timeout)
    task_id = clean_space(submitted.get("task_id"))
    final_payload = submitted
    if not image_record(final_payload):
        if not task_id:
            raise RuntimeError(f"Right Code did not return task_id: {api_error_message(submitted)}")
        final_payload = poll_for_result(
            task_id,
            task_base_url,
            api_key,
            timeout_seconds,
            request_timeout,
            poll_interval,
            requester,
            sleeper=sleeper,
            clock=clock,
        )
    return save_completed_result(
        final_payload,
        output_path,
        task_id or None,
        model,
        {"size": size, "image_size": image_size, "n": 1, "async": True, "resumed": False},
        request_timeout,
        downloader,
    )


def resume_style_reference(
    output_path: Path,
    api_key: str,
    task_base_url: str,
    task_id: str,
    model: str,
    timeout_seconds: float,
    request_timeout: float,
    poll_interval: float,
    requester: JsonRequester = request_json,
    downloader: ByteDownloader = download_bytes,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    normalized_task_id = clean_space(task_id)
    if not re.fullmatch(r"task_[A-Za-z0-9_-]{8,128}", normalized_task_id):
        raise ValueError("--resume-task-id must be a valid Right Code task ID")
    final_payload = poll_for_result(
        normalized_task_id,
        task_base_url,
        api_key,
        timeout_seconds,
        request_timeout,
        poll_interval,
        requester,
        sleeper=sleeper,
        clock=clock,
    )
    return save_completed_result(
        final_payload,
        output_path,
        normalized_task_id,
        model,
        {"async": True, "resumed": True},
        request_timeout,
        downloader,
    )


def update_brief(brief: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    updated = dict(brief)
    updated["status"] = metadata.get("status", "failed")
    updated["provider"] = metadata.get("provider", updated.get("provider", "rightcode"))
    updated["model"] = metadata.get("model", updated.get("model"))
    updated["generation"] = metadata
    notes = updated.get("failure_or_fallback_notes", [])
    if not isinstance(notes, list):
        notes = []
    failure = clean_space(metadata.get("failure"))
    if failure:
        notes.append(failure)
    updated["failure_or_fallback_notes"] = notes
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a style-only poster reference through Right Code's asynchronous Images API.")
    parser.add_argument("--brief-json", default="outputs/poster_visual_brief.json")
    parser.add_argument("--output-image", default="outputs/poster_style_reference.png")
    parser.add_argument("--report-json", default="outputs/poster_visual_generation.json")
    parser.add_argument("--mode", choices=["auto", "required"], default="auto")
    parser.add_argument(
        "--resume-task-id",
        default=None,
        help="Resume polling an existing Right Code task instead of submitting and charging for a new generation.",
    )
    parser.add_argument("--model", default=os.environ.get("RIGHTCODE_IMAGE_MODEL", "gpt-image-2"))
    parser.add_argument("--size", default="16:9")
    parser.add_argument("--image-size", choices=["1K", "2K", "4K"], default="1K")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=45.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    args = parser.parse_args()

    brief_path = Path(args.brief_json)
    report_path = Path(args.report_json)
    try:
        brief = read_json(brief_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    api_key = os.environ.get("RIGHTCODE_API_KEY", "").strip()
    if not api_key:
        metadata = {
            "status": "skipped" if args.mode == "auto" else "failed",
            "provider": "rightcode",
            "model": args.model,
            "asset_class": "style_reference_only",
            "included_in_final_svg": False,
            "failure": "RIGHTCODE_API_KEY is not configured",
        }
        write_json(report_path, metadata)
        write_json(brief_path, update_brief(brief, metadata))
        outcome = "skipped" if args.mode == "auto" else "failed"
        message = f"Right Code image art direction {outcome}: RIGHTCODE_API_KEY is not configured."
        print(message, file=sys.stderr)
        return 0 if args.mode == "auto" else 2

    try:
        task_base_url = validate_https_base_url(
            os.environ.get("RIGHTCODE_TASK_BASE_URL", DEFAULT_TASK_BASE_URL),
            "RIGHTCODE_TASK_BASE_URL",
        )
        if args.timeout_seconds <= 0 or args.request_timeout <= 0 or args.poll_interval <= 0:
            raise ValueError("Timeout and poll interval values must be positive")
        if not re.fullmatch(r"(?:1:1|16:9|9:16|4:3|\d{3,4}x\d{3,4})", args.size):
            raise ValueError("--size must be 1:1, 16:9, 9:16, 4:3, or a pixel size such as 1024x1024")
        model = clean_space(args.model) or "gpt-image-2"
        if args.resume_task_id:
            metadata = resume_style_reference(
                Path(args.output_image),
                api_key,
                task_base_url,
                args.resume_task_id,
                model,
                args.timeout_seconds,
                args.request_timeout,
                args.poll_interval,
            )
        else:
            draw_base_url = validate_https_base_url(
                os.environ.get("RIGHTCODE_DRAW_BASE_URL", DEFAULT_DRAW_BASE_URL),
                "RIGHTCODE_DRAW_BASE_URL",
            )
            metadata = generate_style_reference(
                brief,
                Path(args.output_image),
                api_key,
                draw_base_url,
                task_base_url,
                model,
                args.size,
                args.image_size,
                args.timeout_seconds,
                args.request_timeout,
                args.poll_interval,
            )
    except Exception as exc:
        metadata = {
            "status": "failed",
            "provider": "rightcode",
            "model": args.model,
            "asset_class": "style_reference_only",
            "included_in_final_svg": False,
            "failure": clean_space(exc),
        }
        failed_task_id = clean_space(args.resume_task_id or getattr(exc, "task_id", ""))
        if failed_task_id:
            metadata["task_id"] = failed_task_id
            metadata["resumable"] = isinstance(exc, ImageTaskTimeout)
        write_json(report_path, metadata)
        write_json(brief_path, update_brief(brief, metadata))
        print(f"Right Code image art direction failed: {exc}", file=sys.stderr)
        return 0 if args.mode == "auto" else 2

    write_json(report_path, metadata)
    write_json(brief_path, update_brief(brief, metadata))
    print(f"Wrote {args.output_image}")
    print(f"Wrote {args.report_json}")
    print("Generated asset class: style_reference_only (never embedded in the final SVG)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
