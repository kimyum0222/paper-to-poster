# Hybrid Extraction Contract

Read this reference when changing, debugging, or evaluating the PDF extraction
stages.

## Stage 1: Raw evidence

`scripts/extract_paper.py` writes `outputs/raw_pdf_extraction.json`.

Treat this file as immutable evidence. Preserve:

- Source PDF path and SHA-256 hash.
- Page text, lines, blocks, reading order, page numbers, and bounding boxes.
- Font and column hints when available.
- Extracted raster images, page crops, tables, captions, and asset paths.
- Local heuristic title and section candidates.
- Extraction backend, quality metrics, and limitations.

Local title and section classifications are candidates, not final semantic truth.

## Stage 2: Semantic interpretation

`scripts/structure_paper_with_openai.py` writes
`outputs/extracted_paper.json`.

Use the original PDF as a multimodal file input when the endpoint reliably
supports it, so the model receives PDF text and page images. For a custom
OpenAI-compatible endpoint without reliable PDF input, send the complete
deterministic page text with explicit one-indexed page markers. Require strict
structured output in either path. Preserve the raw evidence fields while
replacing compatible top-level semantic fields only when the model returns
non-empty values with source references. Reject effectively empty model
payloads rather than labeling the semantic stage successful.

For every non-empty claim-bearing field, require:

```json
{
  "text": "Faithful extracted or synthesized content",
  "confidence": 0.9,
  "source_refs": [
    {
      "page": 4,
      "quote": "Short exact passage copied from page 4"
    }
  ]
}
```

Use one-indexed pages. Keep quotes short and exact. Return empty fields instead
of guessing.

Modes:

- `auto`: use the model when configured; otherwise write a local fallback and
  continue.
- `model`: require model extraction; fail on missing configuration, oversized
  PDF, SDK error, API error, refusal, or invalid output.
- `local`: skip the model and copy deterministic extraction forward.

Model input modes:

- `auto`: direct PDF for `api.openai.com`; page-numbered deterministic text for
  custom compatible Base URLs.
- `pdf`: require direct PDF `input_file` behavior.
- `text`: use page-numbered deterministic PDF text for semantic structuring.

## Stage 3: Evidence verification

`scripts/verify_paper_extraction.py` writes
`outputs/extraction_verification.json` and updates
`outputs/extracted_paper.json`.

For each source reference:

1. Confirm that the cited page exists.
2. Normalize Unicode, whitespace, and common dash variants.
3. Match the exact quote against raw page text or layout lines.
4. Derive a bounding box from the smallest matching line window when possible.
5. Mark the reference `verified`, `page_not_found`, `quote_missing`, or
   `quote_not_found`.

Cap confidence for unsupported model fields. Replace unverified title, abstract,
methods, results, and conclusion with deterministic local values when available.
Keep verification metadata for audit and report every replacement.

## Downstream rule

Build poster content only from the verified `outputs/extracted_paper.json`.
Never read model output directly from an API response or treat model confidence
as evidence. Poster bullets, take-home messages, and result callouts must carry
their locally verified page-and-quote references into `poster_content.json`.
When a locally extracted source sentence is matched exactly against a raw page,
record that page, exact sentence, verification status, and derived bounding box
when available. When poster wording comes from a verified semantic field,
preserve its verified source references and keep the semantic source text
separate from the exact quote. Keep the raw evidence and verification report
available through final poster validation.
