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

- `outputs/raw_pdf_extraction.json`
- `outputs/extracted_paper.json`
- `outputs/extraction_verification.json`
- `outputs/poster_content.json`
- `outputs/poster_narrative_plan.json` when content-driven narrative planning is enabled.
- `outputs/poster_design_spec.json`
- `outputs/poster_layout.json`
- `outputs/poster_overflow_report.json`
- `outputs/layout_repair_report.json` when deterministic overflow repair runs.
- `outputs/poster_faithfulness_report.json` when semantic claim review is enabled.
- `outputs/poster_aesthetic_report.json` when layout JSON aesthetic review is enabled.
- `outputs/poster_visual_brief.json` when image-model art direction is enabled.
- `outputs/poster_visual_generation.json` with provider status and the generated asset manifest.
- `outputs/poster_style_analysis.json` with contrast-guarded design tokens derived from the generated reference pixels.
- `outputs/poster_style_reference.png` when an image model produces a non-authoritative visual reference.
- `outputs/poster_render_preview.png` and `outputs/poster_visual_review.json` when rendered-poster visual review is enabled.
- `outputs/generation_report.md`
- `outputs/assets/` for extracted figures, tables, diagrams, icons, or intermediate local assets.
- `outputs/assets/generated/` for generated decorative or explanatory assets that are explicitly classified as non-evidence.

Prefer making `outputs/poster.svg` self-contained by embedding required images as data URIs. If assets are too large to embed, store them under `outputs/assets/`, reference them with relative paths only, and report that in `outputs/generation_report.md`.

If `outputs/poster.svg` cannot be generated, still create the best available intermediate outputs and explain the blocking issue in `outputs/generation_report.md`.

## Workflow

1. Locate the user-provided PDF.
2. Create `outputs/` and `outputs/assets/` if needed.
3. Extract deterministic page text, lines, blocks, coordinates, figures, tables, captions, metadata, and hashes with local PDF tools.
4. Save this immutable evidence layer as `outputs/raw_pdf_extraction.json`.
5. In `auto` or `model` mode, structure the paper semantically with a model. Send the original PDF as a multimodal file input to the official OpenAI endpoint. For a custom OpenAI-compatible Base URL, send page-numbered deterministic PDF text unless direct PDF input is explicitly selected and supported. Use `auto` by default; fall back to local extraction when the API is unavailable.
6. Save the compatible semantic result as `outputs/extracted_paper.json`, preserving the raw pages and assets.
7. Verify model source quotes against raw page text, derive bounding boxes when possible, replace unverified critical fields with local values, and save `outputs/extraction_verification.json`.
8. Convert the verified extracted material into concise poster sections.
9. Select the highest-value figures, tables, diagrams, result plots, or qualitative examples.
10. Save poster content as `outputs/poster_content.json`.
11. Require take-home, result-callout, and result-section claims to carry at least one locally verified page-and-quote reference unless the claim evidence gate is explicitly relaxed.
12. When enabled, review poster claims against their source evidence with an OpenAI text model and save `outputs/poster_faithfulness_report.json`; stop on high-risk findings by default.
13. When content-driven narrative planning is enabled, select only verified claim IDs and source-figure IDs, plan the story arc, reading order, hero, sections, and content budgets, save `outputs/poster_narrative_plan.json`, and follow [references/narrative-planning-contract.md](references/narrative-planning-contract.md).
14. When image-model art direction is enabled, validate and compress `outputs/poster_narrative_plan.json` into content-aware, text-free layout requirements in `outputs/poster_visual_brief.json`, generate only non-authoritative references or non-evidence assets, analyze the reference into guarded design tokens, and follow [references/visual-generation-contract.md](references/visual-generation-contract.md).
15. Translate only successfully analyzed visual direction into deterministic layout, typography, palette, and shape rules; then save `outputs/poster_design_spec.json`.
16. Generate `outputs/poster.svg` with a deterministic SVG renderer using exact verified text and unchanged source figures; save `outputs/poster_layout.json`.
17. Validate the SVG, referenced assets, layout boxes, and text overflow.
18. Repair overflow deterministically for a bounded number of iterations. Do not report successful completion when overflow remains unless the user explicitly accepts it.
19. When enabled, render the SVG to `outputs/poster_render_preview.png`, review the actual preview visually, apply rule-level design repairs, and re-render for a bounded number of iterations.
20. When layout JSON aesthetic review is enabled, stop on high-risk findings by default.
21. Write `outputs/generation_report.md` with extraction mode, model, verification, claim evidence, narrative planning, visual-generation roles, assumptions, omissions, quality gates, and validation results.
22. In the final response, list generated files with `outputs/poster.svg` first and mention limitations.

Run the complete pipeline with:

```bash
python scripts/run_pipeline.py paper.pdf --extraction-mode auto --narrative-planning auto
```

Quality gates default to verified evidence for critical poster claims, high-risk semantic/aesthetic findings when those reviews are enabled, and no remaining estimated text overflow. Relax them only with the corresponding explicit CLI options when the user accepts the limitation.

## Extraction Guidance

Use a hybrid evidence-first extraction process:

- Use local PDF tools for exact text, page numbers, coordinates, images, captions, metadata, and source hashing.
- Use a multimodal model with the original PDF when the provider supports it. For compatible endpoints without reliable PDF `input_file` support, give the model complete page-numbered local text for cover-page disambiguation, semantic sections, author and affiliation grouping, and identification of methods, results, conclusions, and limitations.
- Require one-indexed page references and short exact source quotes for every non-empty model field.
- Verify source quotes locally before downstream use. Never treat model output alone as source evidence.
- Use `auto` mode by default. It uses direct PDF model input for `api.openai.com`, page-numbered text model input for custom compatible Base URLs, and otherwise records a local fallback without failing the poster pipeline.
- Reject effectively empty model payloads or payloads without source references instead of labeling the model stage successful.
- Use `model` mode when model extraction is mandatory and failure should stop the pipeline. Use `local` only for offline or deterministic-only runs.

Read [references/extraction-contract.md](references/extraction-contract.md) when changing, debugging, or evaluating the extraction stages.

## Structured Content

`outputs/raw_pdf_extraction.json` is the immutable evidence layer. Preserve source PDF hash, raw pages, lines, blocks, coordinates, figures, tables, captions, metadata, extraction quality, and tool notes.

`outputs/extracted_paper.json` should preserve source material and enough context to support poster claims. Include these fields when available:

- `title`
- `title_candidates`
- `title_confidence`
- `authors`
- `affiliations`
- `abstract`
- `section_headings`
- `sections`
- `methods`
- `results`
- `conclusion`
- `figures`
- `tables`
- `captions`
- `references_or_citation_metadata`
- `text_extraction_quality`
- `extraction_notes`
- `pages`
- `field_evidence`
- `semantic_extraction`
- `extraction_method`
- `extraction_model`
- `extraction_verification`

Each non-empty model-derived field should include `source_refs` with `page`, exact `quote`, local `verification_status`, and derived `bbox` when available. Keep top-level strings and lists compatible with the deterministic content builder.

`outputs/extraction_verification.json` should report verified and unverified field counts, per-field statuses, model metadata, and critical fields replaced with deterministic local values.

For text extraction, prefer layout-aware records when available:

- `pages[].text` for page-level reading-order text.
- `pages[].lines` for line text with page number, bounding box, font size, bold flag, reading order, and column hint.
- `pages[].blocks` for source layout blocks.
- `sections[]` for structured paper sections with heading, normalized heading, page range, text, line count, and confidence.
- `text_extraction_quality` for character count, pages with text, detected column mode, section count, missing required sections, title confidence, and likely cover-page/template signals.

For figure extraction, preserve enough metadata for selection and faithful placement:

- `figures[].kind` as `raster_xref`, `page_crop`, or another explicit extraction mode.
- `figures[].asset_path`, `page`, `bbox`, `width_px`, `height_px`, and `area_ratio`.
- `figures[].caption`, `caption_id`, `caption_bbox`, and `caption_confidence` when matched.
- `figures[].quality_score` and `selection_reason` for downstream figure prioritization.
- When visual model review is available, record figure judgments under `figure_reviews` with `figure_id`, `role`, `importance_score`, `readability_score`, and `selection_reason`; scripts should fall back to caption/layout heuristics when no visual review is available.

`outputs/poster_content.json` should contain concise poster-ready sections. Use these sections when supported by the paper:

- `title`
- `authors`
- `affiliations`
- `take_home_message`
- `take_home_evidence`
- `result_callouts`
- `result_callout_evidence`
- `poster_claims`
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
- `figure_candidates`
- `figure_selection_policy`
- `footer_metadata`
- `omitted_sections`

Each poster claim, bullet, and callout should preserve source evidence when available. Prefer adding `evidence` arrays next to rendered bullet lists instead of replacing the bullet strings, so deterministic renderers remain simple while faithfulness review can audit each claim.

Each entry in `poster_claims` should include:

- `id`
- `section`
- `claim`
- `source`
- `source_text`
- `evidence_text`
- `source_refs` with locally verified `page`, exact `quote`, and `bbox` when available
- `evidence_status`
- `evidence_mapping`

`claim_evidence_summary` should report verified and unresolved poster claim counts. Critical claims without verified page-and-quote evidence fail the default pipeline quality gate.

`outputs/poster_faithfulness_report.json`, when produced, should include:

- `status`
- `model`
- `summary`
- `claim_count`
- `review_count`
- `high_risk_count`
- `medium_risk_count`
- `reviews`
- `claims`

`outputs/poster_layout.json` should describe layout decisions in the same coordinate system as the SVG `viewBox`:

- `canvas_width`
- `canvas_height`
- `viewBox`
- `column_count`
- `margin`
- `gutter`
- `section_order`
- `section_bounding_boxes`
- `component_bounding_boxes`
- `typography_scale`
- `figure_placements`
- `color_tokens`
- `overflow_handling_decisions`
- `asset_embedding_mode`

`outputs/poster_design_spec.json` should describe the intended poster design before rendering:

- `template`
- `theme`
- `hero_message`
- `callouts`
- `canvas`
- `grid`
- `visual_hierarchy`
- `typography`
- `color_palette`
- `card_style`
- `card_variants`
- `image_placement`
- `section_density`
- `overflow_rules`

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

## Optional Image-Model Art Direction

Use an image model as a visual director, not as the authoritative renderer. Let it propose composition, palette, background motifs, card language, and clearly non-evidentiary explanatory artwork. Keep final text, numbers, citations, source figures, charts, tables, and geometry under deterministic SVG control.

Never use a generated full-poster raster as `outputs/poster.svg` or as a full-canvas image inside it. Treat `poster_style_reference.png` as design guidance only. Read [references/visual-generation-contract.md](references/visual-generation-contract.md) before enabling, implementing, or evaluating this stage.

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
- Do not ask an image model to redraw scientific plots, tables, result figures, metrics, author names, citations, or final poster body text.
- Classify every generated asset as `decorative` or `explanatory_non_evidence`; never use it as support for a scientific claim.
- Preserve source figures as immutable evidence assets and place them unchanged in the final SVG.
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

- In `auto` mode, fall back to local extraction when the API key, OpenAI package, supported input strategy, or model response is unavailable; record the exact reason.
- In `model` mode, stop with a report when semantic extraction or verification cannot complete.
- Reject a single model file input at 50 MB or larger and use the selected mode's fallback behavior.
- Create a text-focused SVG poster when figures cannot be extracted.
- Omit low-resolution or unreadable figures, or include them with a limitation note.
- Stop after writing a report if the PDF is encrypted or unreadable.
- Do not install missing packages automatically unless the user approves it.

## Scripts

This skill can work without scripts, but prefer local scripts when available for repeatable extraction, generation, and validation.

Recommended script structure:

- `scripts/run_pipeline.py`: run the complete extraction, verification, content, design, rendering, repair, and validation workflow.
- `scripts/extract_paper.py`: write deterministic text, layout, metadata, figures, tables, captions, and hashes to `raw_pdf_extraction.json`.
- `scripts/structure_paper_with_openai.py`: interpret the original PDF with multimodal file input and structured output while preserving local evidence.
- `scripts/verify_paper_extraction.py`: match model quotes to raw pages, derive bounding boxes, downgrade unsupported fields, and write the verification report.
- `scripts/review_figures_with_openai.py`: optionally use an OpenAI vision model to classify figure importance, readability, and poster role.
- `scripts/build_poster_content.py`: map extracted content into semantic poster sections.
- `scripts/plan_poster_narrative_with_openai.py`: select verified claim and source-figure IDs into a structured, content-driven poster narrative plan.
- `scripts/review_poster_faithfulness_with_openai.py`: optionally use an OpenAI text model to check poster claims against source evidence.
- `scripts/review_poster_aesthetics_with_openai.py`: optionally use an OpenAI text model to review layout aesthetics from structured JSON.
- `scripts/build_poster_visual_brief.py`: validate the narrative plan and build a content-aware, text-free layout prompt plus safe deterministic design tokens.
- `scripts/generate_poster_style_with_rightcode.py`: submit, resume, and poll Right Code asynchronous image tasks without embedding the reference raster or duplicating timed-out jobs.
- `scripts/analyze_poster_style_reference.py`: derive a bounded color palette from the returned image pixels with contrast guards and no scientific-content influence.
- `scripts/build_poster_design.py`: build `outputs/poster_design_spec.json` with template, hierarchy, grid, typography, palette, density, and overflow parameters.
- `scripts/build_poster_svg.py`: generate `outputs/poster.svg` from poster content and design spec.
- `scripts/repair_poster_layout.py`: deterministically adjust design parameters after overflow validation and before re-rendering.
- `scripts/validate_svg.py`: check XML validity, missing assets, canvas metadata, unsupported SVG features, remote dependencies, basic layout issues, and estimated text overflow per block.

Scripts should write outputs only under `outputs/` unless the user requests otherwise.


## Validation

Before finishing, confirm or report:

- `outputs/raw_pdf_extraction.json` preserves local page evidence and the source PDF hash.
- `outputs/extracted_paper.json` records whether model or local extraction was used.
- `outputs/extraction_verification.json` exists and reports verified, unverified, and fallback fields.
- Critical model fields used downstream have verified source quotes or were replaced with local extraction.
- `outputs/poster.svg` exists.
- The SVG parses as XML.
- The root has explicit `width`, `height`, and `viewBox`.
- The SVG contains `<title>` and `<desc>`.
- Text is mostly editable SVG text, not a full-canvas raster image.
- There are no `<script>` elements, remote URLs, remote fonts, remote stylesheets, or unsupported `<foreignObject>` elements.
- Referenced local assets exist under `outputs/assets/`.
- Major sections do not overlap, overflow, or fall off the canvas.
- Poster text lines stay inside their assigned section bounding boxes, with any estimated overflow reported in `outputs/poster_overflow_report.json`.
- Text inside nested components such as result callout boxes should stay inside `component_bounding_boxes`, not just inside the larger parent section.
- When semantic review is enabled, poster claims are reviewed against extracted source evidence and reported in `outputs/poster_faithfulness_report.json`.
- Critical take-home and result claims have locally verified page-and-quote evidence, or the generation report explicitly records that the evidence gate was relaxed.
- When narrative planning and image art direction are enabled together, the Visual Brief validates the content hash, consumes only verified claim IDs, and represents source figures only as aspect-ratio-matched blank slots.
- High-risk faithfulness or aesthetic review findings stop the pipeline by default when those reviews are enabled.
- Remaining text overflow after bounded repair stops the pipeline by default; `--allow-overflow` is an explicit acceptance of that limitation.
- Any generated asset is classified as non-evidence and does not replace, redraw, or modify a source figure.
- When visual review is enabled, it examines a rendered preview of the final SVG rather than layout JSON alone.
- The final poster remains deterministic editable SVG text and geometry, not a generated full-poster raster.
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
- Whether semantic extraction used a model or the local fallback, and the verification status.
- Whether image-model art direction was used, which generated assets were included, and their non-evidence classifications.
- Whether the SVG is self-contained or uses local assets.
- Any extraction, layout, rendering, missing-asset, or scientific-fidelity limitations.

Do not claim unsupported visual fidelity or scientific results.
