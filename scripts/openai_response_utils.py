#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from typing import Any


def _text_from_mapping(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    parts: list[str] = []
    output = data.get("output", [])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
    return "\n".join(parts).strip()


def _text_from_sse(text: str) -> str:
    deltas: list[str] = []
    completed_text = ""
    saw_data_line = False
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        saw_data_line = True
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type", ""))
        delta = event.get("delta")
        if event_type.endswith("output_text.delta") and isinstance(delta, str):
            deltas.append(delta)
        response = event.get("response")
        if isinstance(response, dict):
            extracted = _text_from_mapping(response)
            if extracted:
                completed_text = extracted
        extracted = _text_from_mapping(event)
        if extracted:
            completed_text = extracted
    if not saw_data_line:
        return ""
    return completed_text or "".join(deltas).strip()


def response_output_text(response: Any) -> str:
    """Normalize official OpenAI and OpenAI-compatible response bodies."""
    if response is None:
        return ""
    if isinstance(response, bytes):
        response = response.decode("utf-8", errors="replace")
    if isinstance(response, str):
        text = response.strip()
        if not text:
            return ""
        sse_text = _text_from_sse(text)
        if sse_text:
            return sse_text
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return text
        if isinstance(decoded, str):
            return decoded.strip()
        if isinstance(decoded, dict):
            envelope_text = _text_from_mapping(decoded)
            return envelope_text or text
        return text
    if isinstance(response, dict):
        return _text_from_mapping(response)

    direct = getattr(response, "output_text", None)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, dict):
            return _text_from_mapping(dumped)
    return ""


def json_object_from_text(text: str) -> dict[str, Any]:
    """Parse a JSON object even when a compatible provider adds prose/fences."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("The model returned an empty response.")

    candidates = [stripped]
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*(.*?)```", stripped, re.IGNORECASE | re.DOTALL)
    )
    decoder = json.JSONDecoder()
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
        else:
            if isinstance(decoded, dict):
                return decoded

        for match in re.finditer(r"\{", candidate):
            try:
                decoded, _ = decoder.raw_decode(candidate[match.start():])
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(decoded, dict):
                return decoded

    detail = str(last_error) if last_error else "top-level value was not an object"
    raise ValueError(f"Could not find a valid JSON object: {detail}")
