from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from openai_response_utils import json_object_from_text, response_output_text


class ResponseOutputTextTests(unittest.TestCase):
    def test_official_response_object(self) -> None:
        response = SimpleNamespace(output_text="  OK  ")
        self.assertEqual(response_output_text(response), "OK")

    def test_compatible_provider_plain_string(self) -> None:
        self.assertEqual(response_output_text("  OK  "), "OK")

    def test_json_encoded_string(self) -> None:
        self.assertEqual(response_output_text(json.dumps("OK")), "OK")

    def test_json_response_envelope(self) -> None:
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "OK"}],
                }
            ]
        }
        self.assertEqual(response_output_text(json.dumps(response)), "OK")

    def test_structured_output_string_is_preserved(self) -> None:
        response = '{"title":{"text":"Paper"}}'
        self.assertEqual(response_output_text(response), response)

    def test_sse_output_text_deltas(self) -> None:
        response = "\n".join([
            'event: response.output_text.delta',
            'data: {"type":"response.output_text.delta","delta":"O"}',
            'data: {"type":"response.output_text.delta","delta":"K"}',
            'data: [DONE]',
        ])
        self.assertEqual(response_output_text(response), "OK")

    def test_json_object_in_markdown_fence(self) -> None:
        text = 'Here is the result:\n```json\n{"title":{"text":"Paper"}}\n```'
        self.assertEqual(json_object_from_text(text)["title"]["text"], "Paper")

    def test_json_object_after_preamble(self) -> None:
        text = 'Result follows: {"title":{"text":"Paper"}} Thank you.'
        self.assertEqual(json_object_from_text(text)["title"]["text"], "Paper")


if __name__ == "__main__":
    unittest.main()
