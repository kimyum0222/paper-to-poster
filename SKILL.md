---
name: paper-to-poster
description: Convert an academic paper PDF into a single poster-ready SVG academic poster. Use when the user asks to turn a research paper, manuscript, article, arXiv paper, or conference paper into an SVG poster, vector poster, academic poster, visual research poster, or conference poster. Do not use for general summarization, slide decks, presentation files, blog posts, translations, citation formatting, or raster-only image output unless the user explicitly wants an SVG poster.
---

# Paper to SVG Poster

## Purpose

Convert one academic paper PDF into one poster-ready SVG academic poster.

The output should be faithful to the source paper, visually organized as a conference-style research poster, and usable in standard SVG-compatible tools. The required final artifact is `outputs/poster.svg`.

## Quality Bar

A successful poster should allow a reader to understand within 10 seconds:

- What problem the paper addresses.
- What the main idea or method is.
- What the strongest result or contribution is.
- Why the work matters.

The poster should not attempt to include the whole paper. Prioritize clarity, evidence, and visual hierarchy over completeness.

## Scope

After this skill triggers, produce one SVG academic poster from one academic paper PDF. Keep the output grounded in the source paper and prioritize a usable `outputs/poster.svg` over exhaustive extraction.

If the user asks for a non-SVG deliverable after the skill has triggered, explain that this skill produces SVG posters and ask whether to continue with SVG.

## Non-Goals

Do not produce literature reviews, slide decks, blog summaries, citation formatting outputs, raster-only posters, or publication-ready redesigned figure sets.

Do not prioritize decorative complexity, full-paper completeness, or unsupported scientific reconstruction over readability and source fidelity.

## Inputs

Expected input:

- One academic paper PDF.

Optional inputs:

- Poster size or conference requirements.
- Preferred layout, language, visual style, color palette, or branding.

If multiple PDFs are present and the user does not specify one, use the most recently provided PDF and record that choice in `outputs/generation_report.md`.

## Defaults

When the user gives no poster requirements:

- Output format: SVG only.
- Poster size: A0 landscape.
- Canvas size: 1189mm x 841mm.
- SVG `viewBox`: `0 0 1189 841`.
- Coordinate system: viewBox units correspond to millimeter-like layout units.
- Layout: 3 columns.
- Style: clean academic vector poster with clear hierarchy, concise bullets, section panels, and high contrast.
- Output directory: `outputs/`.

## Outputs

Write all generated files under `outputs/`.

Required final output:

- `outputs/poster.svg`

Supporting outputs:

- `outputs/extracted_paper.json`
- `outputs/poster_content.json`
- `outputs/poster_layout.json`
- `outputs/generation_report.md`
- `outputs/assets/` for extracted figures, tables, diagrams, icons, or intermediate local assets.

Prefer making `outputs/poster.svg` self-contained by embedding required images as data URIs. If assets are too large to embed, store them under `outputs/assets/`, reference them with relative paths only, and report that in `outputs/generation_report.md`.

If `outputs/poster.svg` cannot be generated, still create the best available intermediate outputs and explain the blocking issue in `outputs/generation_report.md`.

## Workflow

1. Locate the user-provided PDF.
2. Create `outputs/` and `outputs/assets/` if needed.
3. Extract title, authors, affiliations, abstract, section headings, methods, results, conclusion, figures, tables, captions, and citation metadata when available.
4. Save source extraction as `outputs/extracted_paper.json`.
5. Convert the extracted material into concise poster sections.
6. Select the highest-value figures, tables, diagrams, result plots, or qualitative examples.
7. Save poster content as `outputs/poster_content.json`.
8. Plan the canvas, grid, section order, typography, figure placement, color tokens, and overflow handling.
9. Save layout decisions as `outputs/poster_layout.json`.
10. Generate `outputs/poster.svg` using direct SVG markup or a local SVG-generation script.
11. Validate the SVG and referenced assets.
12. Write `outputs/generation_report.md` with generated files, assumptions, omitted sections, limitations, and validation results.
13. In the final response, list generated files with `outputs/poster.svg` first and mention any limitations.

## Extraction Guidance

Use available local PDF tooling before manual reconstruction. Prefer structured extraction of text, metadata, figures, tables, and captions. If multiple tools are available, compare extracted title, section headings, and figure captions against the PDF before trusting the output.

## Structured Content

`outputs/extracted_paper.json` should preserve source material and enough context to support poster claims. Include these fields when available:

- `title`
- `authors`
- `affiliations`
- `abstract`
- `section_headings`
- `methods`
- `results`
- `conclusion`
- `figures`
- `tables`
- `captions`
- `references_or_citation_metadata`
- `extraction_notes`

`outputs/poster_content.json` should contain concise poster-ready sections. Use these sections when supported by the paper:

- `title`
- `authors`
- `affiliations`
- `problem`
- `motivation`
- `core_idea`
- `method`
- `theoretical_foundation`
- `results`
- `conclusion`
- `contribution`
- `innovation`
- `significance`
- `limitations`
- `figures_to_use`
- `footer_metadata`
- `omitted_sections`

`outputs/poster_layout.json` should describe layout decisions in the same coordinate system as the SVG `viewBox`:

- `canvas_width`
- `canvas_height`
- `viewBox`
- `column_count`
- `margin`
- `gutter`
- `section_order`
- `section_bounding_boxes`
- `typography_scale`
- `figure_placements`
- `color_tokens`
- `overflow_handling_decisions`
- `asset_embedding_mode`

## Poster Structure

Organize the paper into relevant semantic sections:

- Problem / Research Question
- Motivation
- Core Idea / Approach
- Method
- Theoretical Foundation
- Results
- Conclusion
- Contribution
- Innovation / Novelty
- Significance / Impact
- Limitations

These do not all need separate visual boxes. Combine related sections when space is tight, such as `Problem + Motivation`, `Idea + Method`, `Contribution + Innovation`, `Conclusion + Significance`, or `Results + Limitations`.

Omit sections that are not applicable or not verifiable from the paper, and record omissions in `outputs/generation_report.md`.

## Default Layout Plan

When no layout is specified, use this A0 landscape baseline:

- Header: title, authors, affiliations, and optional venue or citation metadata.
- Column 1: Problem / Motivation, Core Idea / Approach.
- Column 2: Method, Theoretical Foundation if needed, and the most important method or overview figure.
- Column 3: Results, Contributions, Conclusion, Limitations.
- Footer: source paper metadata, extraction notes, omitted-section notes, and asset notes.

Give the Results area visual priority when the paper reports concrete outcomes. Give the Core Idea or Method area visual priority when the paper is primarily conceptual, theoretical, or methodological.

## Content Budget

Unless the user requests otherwise:

- Title: maximum 18 words.
- Subtitle or venue metadata: maximum 1 line.
- Each section title: maximum 4 words.
- Each section: 3-5 bullets.
- Each bullet: maximum 16 words.
- Total poster body bullets: 20-32.
- Prefer 1-3 key figures over many small figures.
- Results section gets priority over background when space is limited.

## Figure Selection Priority

Prefer figures in this order:

1. Main result figures with reported quantitative outcomes.
2. Architecture, pipeline, framework, or method overview diagrams.
3. Qualitative examples directly supporting the paper's claim.
4. Tables comparing methods, benchmarks, or ablations.
5. Background or illustrative figures only if space remains.

Avoid figures that are unreadable, purely decorative, duplicated, or not referenced by selected poster claims.

## Overflow Strategy

If content does not fit:

1. Shorten bullets before reducing font size.
2. Merge related sections.
3. Drop lower-priority background sections.
4. Reduce figure count.
5. Move limitations or metadata to footer.
6. Use smaller body text only within the allowed typography scale.
7. Never allow text to overflow panels or canvas.

## Content Fidelity

Do not invent or visually fabricate scientific evidence.

- Preserve claims, uncertainty, terminology, author names, affiliations, citations, figure captions, and reported results from the paper.
- Do not invent metrics, p-values, confidence intervals, error bars, benchmarks, comparisons, novelty claims, theoretical claims, or significance claims.
- Do not redraw plots, charts, or tables unless the underlying data is available and verified.
- Do not alter axis labels, legends, scale, colors, or annotations in a way that changes meaning.
- If text extraction is partial, use only verified extracted text and report missing sections.
- If the PDF is scanned, image-only, encrypted, or unreadable, report the limitation instead of guessing.
- Prefer cautious wording over unsupported strengthening.

## SVG Requirements

Generate a real SVG poster, not a full-poster screenshot wrapped inside an SVG.

The SVG must:

- Use a single `<svg>` root with explicit `width`, `height`, and `viewBox`.
- Include `<title>` and `<desc>`.
- Use editable SVG text with `<text>` and `<tspan>` whenever possible.
- Manually wrap multiline text with `<tspan>` elements.
- Escape XML-sensitive characters such as `&`, `<`, `>`, and quotes.
- Use short bullets, normally 3-6 per section.
- Keep text inside its section and inside the canvas.
- Use semantic group IDs such as `header`, `column-1`, `problem`, `method`, `results`, and `footer`.
- Use vector shapes for panels, dividers, arrows, icons, and callouts.
- Use `<image>` elements for raster figures extracted from the paper.
- Preserve image aspect ratios.
- Avoid `<script>`, remote URLs, remote fonts, remote stylesheets, and network-dependent assets.
- Avoid `<foreignObject>` unless the user explicitly requests it and the target renderer supports it.

Visual style should read as a complete academic poster: light background, clear title area, consistent spacing, 2-4 accent colors unless specified, minimal shadows or gradients, and strong contrast.

## Extraction Fallbacks

If extraction is incomplete:

- Create a text-focused SVG poster when figures cannot be extracted.
- Omit low-resolution or unreadable figures, or include them with a limitation note.
- Stop after writing a report if the PDF is encrypted or unreadable.
- Do not install missing packages automatically unless the user approves it.

## Scripts

This skill can work without scripts, but prefer local scripts when available for repeatable extraction, generation, and validation.

Recommended script structure:

- `scripts/extract_paper.py`: extract text, metadata, figures, tables, and captions.
- `scripts/build_poster_content.py`: map extracted content into semantic poster sections.
- `scripts/build_poster_svg.py`: generate `outputs/poster.svg`.
- `scripts/validate_svg.py`: check XML validity, missing assets, canvas metadata, unsupported SVG features, remote dependencies, and basic layout issues.

Scripts should write outputs only under `outputs/` unless the user requests otherwise.


## Validation

Before finishing, confirm or report:

- `outputs/poster.svg` exists.
- The SVG parses as XML.
- The root has explicit `width`, `height`, and `viewBox`.
- The SVG contains `<title>` and `<desc>`.
- Text is mostly editable SVG text, not a full-canvas raster image.
- There are no `<script>` elements, remote URLs, remote fonts, remote stylesheets, or unsupported `<foreignObject>` elements.
- Referenced local assets exist under `outputs/assets/`.
- Major sections do not overlap, overflow, or fall off the canvas.
- Figures, tables, captions, and claims remain faithful to the paper.
- Omitted or unavailable sections are reported in `outputs/generation_report.md`.

When no validation script exists, run a basic XML and dependency check equivalent to:

```bash
python - <<'PY'
from pathlib import Path
import re
import xml.etree.ElementTree as ET

svg_path = Path('outputs/poster.svg')
assert svg_path.exists(), 'outputs/poster.svg does not exist'
text = svg_path.read_text(encoding='utf-8')
ET.fromstring(text)
assert '<svg' in text and 'viewBox' in text, 'missing SVG root or viewBox'
assert '<script' not in text.lower(), 'SVG contains script element'
assert not re.search(r'https?://', text), 'SVG contains remote URL'
print('SVG basic validation passed')
PY
```

If validation cannot be run, explain why in `outputs/generation_report.md`.

## Final Response

Tell the user:

- Which files were generated, with `outputs/poster.svg` first.
- Whether the SVG is self-contained or uses local assets.
- Any extraction, layout, rendering, missing-asset, or scientific-fidelity limitations.

Do not claim unsupported visual fidelity or scientific results.
