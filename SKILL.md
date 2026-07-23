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
- `outputs/poster_style_analysis.json` with contrast-guarded palette and bounded spatial design tokens derived from the generated reference pixels.
- `outputs/poster_reference_vision_analysis.json` when a multimodal model classifies reference design semantics without retaining visible text.
- `outputs/poster_style_reference.png` when an image model produces a non-authoritative visual reference.
- `outputs/poster_decorative_vectors.json` when VTracer decoration extraction is enabled.
- `outputs/poster_typesetting_manifest.json` with verified text, resolved font metadata, measured widths, and renderer-consumed wrapping decisions.
- `outputs/poster_style_conformance_report.json` checking that analyzed style tokens reached executable SVG geometry; this is not pixel similarity.
- `outputs/poster_render_preview.png` when image-model art direction is enabled.
- `outputs/poster_visual_review.json` when a multimodal model actually compares the reference and rendered preview.
- `outputs/poster_visual_repair_report.json` when allowlisted preview-review patches are tested as a candidate design.
- `outputs/run_manifest.json` with source hash, output ownership, timestamps, and run status.
- `outputs/generation_report.md`
- `outputs/assets/` for extracted figures, tables, diagrams, icons, or intermediate local assets.
- `outputs/assets/generated/` for generated decorative or explanatory assets that are explicitly classified as non-evidence.

Prefer making `outputs/poster.svg` self-contained by embedding required images as data URIs. If assets are too large to embed, store them under `outputs/assets/`, reference them with relative paths only, and report that in `outputs/generation_report.md`. If the SVG cannot be generated, create the best available intermediate outputs and explain the blocker there.

## Workflow

1. Locate the user-provided PDF.
2. Create or verify `outputs/`; refuse to mix different paper hashes unless `--fresh-output` or a different output directory is selected.
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
14. When image-model art direction is enabled, validate and compress `outputs/poster_narrative_plan.json` into content-aware, text-free layout requirements in `outputs/poster_visual_brief.json`, generate only non-authoritative references or non-evidence assets, analyze the reference into guarded palette and spatial design tokens, and follow [references/visual-generation-contract.md](references/visual-generation-contract.md). Optionally add multimodal semantic classification after hash-matched local pixel analysis; retain no visible text and accept only allowlisted categorical style adjustments.
15. Translate only successfully analyzed, hash-matched visual direction into deterministic layout, typography, palette, section coordinates, source-figure slots, and shape rules; optionally use VTracer only on isolated non-scientific decorative crops; then save `outputs/poster_design_spec.json`. Map section identities only from the validated narrative plan, never from text-like pixels in the reference.
    Require one confidently detected content panel per validated narrative section before applying reference geometry. Preserve detected cross-row and cross-column spans; do not silently replace failed panel detection with an equal-column grid while reporting success.
16. Resolve one local font, create the typesetting manifest, and generate `outputs/poster.svg` from those exact verified wrapping decisions and unchanged source figures; save `outputs/poster_layout.json`.
17. Validate the SVG, referenced assets, layout boxes, and text overflow.
18. Repair overflow deterministically for a bounded number of iterations. Do not report successful completion when overflow remains unless the user explicitly accepts it.
19. When image art direction is enabled, render the SVG to `outputs/poster_render_preview.png`; inspect it visually before delivery. When multimodal preview review is explicitly enabled, compare reference and preview without retaining visible text, accept only bounded design-parameter patches, validate a candidate SVG, and replace the final files only when the candidate passes. The style-conformance report still checks token execution rather than pixel similarity.
20. When layout JSON aesthetic review is enabled, stop on high-risk structured-layout findings by default.
21. Write `outputs/generation_report.md` with extraction mode, model, verification, claim evidence, narrative planning, visual-generation roles, assumptions, omissions, quality gates, and validation results.
22. In the final response, list generated files with `outputs/poster.svg` first and mention limitations.

Run the complete pipeline with:

```bash
python scripts/run_pipeline.py paper.pdf --extraction-mode auto --narrative-planning auto
```

Use `--fresh-output` when intentionally replacing artifacts from a different paper. The pipeline records the source hash in `outputs/run_manifest.json` and otherwise refuses cross-paper reuse.

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

Treat `outputs/raw_pdf_extraction.json` as the immutable evidence layer. Carry verified page, exact quote, bbox, source-figure metadata, and source hashes through poster content and final validation. Follow [references/extraction-contract.md](references/extraction-contract.md) for extraction and evidence schemas, [references/narrative-planning-contract.md](references/narrative-planning-contract.md) for claim/figure selection, and [references/visual-generation-contract.md](references/visual-generation-contract.md) for design, layout, generated assets, and rendering boundaries.

Critical claims without locally verified page-and-quote evidence fail the default quality gate. Keep generated visual assets non-evidentiary and preserve source figures unchanged.

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

Use a multimodal model only as an optional semantic analyzer or rendered-preview reviewer. Keep local pixel measurements authoritative for coordinates. Discard model-returned visible text, arbitrary geometry, colors, SVG code, content changes, and source-figure edits; apply only locally allowlisted and bounded style parameters through a candidate SVG that must pass validation.

Treat preview review as a separate privacy decision: it sends the rendered poster image, including visible verified text and source figures, to the configured multimodal provider. Enable it only when the user authorizes that disclosure. The normalized local report retains no transcribed visible text.

Enable both guarded multimodal stages only when the user accepts the additional model calls:

```bash
python scripts/run_pipeline.py paper.pdf --extraction-mode auto --narrative-planning auto --image-art-direction required --reference-vision-analysis auto --preview-vision-review auto --poster-vision-model <vision-model>
```

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

Use `scripts/run_pipeline.py` for the complete workflow. It invokes the bundled extraction, semantic verification, narrative, visual-reference, optional multimodal guidance, VTracer, design, typesetting, SVG, repair, preview, conformance, and validation stages with absolute script paths. Multimodal guidance is off by default; enable it explicitly with `--reference-vision-analysis` and/or `--preview-vision-review`. Use individual scripts only when debugging a recorded stage.

Install required local dependencies from `requirements.txt`; install `requirements-optional.txt` only for model-backed or VTracer stages and only with user approval. Scripts should write outputs only under the selected output directory.

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
- When a rendered preview is produced, inspect that image before delivery rather than treating layout JSON or the style-conformance score as visual proof.
- When multimodal visual guidance is enabled, verify reference/preview hashes, confirm that reports retain no visible text, and accept a repaired candidate only after SVG and overflow validation pass.
- The final poster remains deterministic editable SVG text and geometry, not a generated full-poster raster.
- Figures, tables, captions, and claims remain faithful to the paper.
- Omitted or unavailable sections are reported in `outputs/generation_report.md`.

Run the bundled validator. If validation cannot run, explain why in `outputs/generation_report.md` instead of claiming success.

## Final Response

Tell the user:

- Which files were generated, with `outputs/poster.svg` first.
- Whether semantic extraction used a model or the local fallback, and the verification status.
- Whether image-model art direction was used, which generated assets were included, and their non-evidence classifications.
- Whether the SVG is self-contained or uses local assets.
- Any extraction, layout, rendering, missing-asset, or scientific-fidelity limitations.

Do not claim unsupported visual fidelity or scientific results.
