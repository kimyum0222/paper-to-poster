# Visual Generation Contract

Read this reference before enabling, implementing, debugging, or evaluating image-model art direction or rendered-poster visual review.

## Contents

- [Role Separation](#role-separation)
- [Asset Classes](#asset-classes)
- [Allowed Image-Model Tasks](#allowed-image-model-tasks)
- [Forbidden Image-Model Tasks](#forbidden-image-model-tasks)
- [Visual Brief](#visual-brief)
- [Right Code Adapter](#right-code-adapter)
- [Hybrid Rendering Workflow](#hybrid-rendering-workflow)
- [Rendered-Preview Review](#rendered-preview-review)
- [Required Validation](#required-validation)

## Role Separation

Treat these artifacts as authoritative scientific sources:

- `raw_pdf_extraction.json`
- verified fields and source references in `extracted_paper.json`
- `extraction_verification.json`
- verified claims in `poster_content.json`
- original figures and page crops extracted from the paper

Treat these artifacts as non-authoritative visual guidance:

- `poster_visual_brief.json`
- `poster_style_reference.png`
- `poster_style_analysis.json`
- image-model design suggestions
- generated decorative or explanatory assets
- rendered-poster aesthetic reviews

An image model may influence style and composition. It must not become the source of scientific text, numbers, evidence, or result graphics.

## Asset Classes

Assign every visual asset exactly one class:

- `source_evidence`: An unchanged figure, table image, diagram, or page crop extracted from the paper. Preserve its source page, caption, bbox, asset path, and hash.
- `generated_explanatory_non_evidence`: A conceptual illustration that explains a verified method or relationship but does not display results or support a claim. Render factual labels separately as SVG text.
- `generated_decorative`: Background texture, abstract motif, divider, icon-like accent, or other artwork with no scientific meaning.
- `style_reference_only`: A whole-poster mockup or mood board used only to derive design rules. Never place it in the final SVG.

Store generated assets under `outputs/assets/generated/`. Record class, model, prompt purpose, source inputs, and inclusion decision in `poster_visual_brief.json` or a generated-asset manifest.

## Allowed Image-Model Tasks

Use an image model to propose or generate:

- overall composition and visual rhythm;
- palette, card language, spacing mood, and background treatment;
- decorative motifs that match the paper domain;
- non-data conceptual illustrations derived from verified method relationships;
- a full-poster style reference that uses placeholders instead of authoritative final text;
- alternative visual directions for deterministic SVG implementation.

When giving source figures to the image model, use them only to understand visual balance or thematic fit. Do not accept a regenerated copy as a replacement for the original asset.

## Forbidden Image-Model Tasks

Do not use an image model to:

- transcribe or render final title, authors, affiliations, body text, citations, formulas, or metrics;
- generate, redraw, enhance, restyle, or relabel scientific plots, result figures, tables, axes, legends, or error bars;
- invent diagrams that imply unverified causal, architectural, procedural, or theoretical relationships;
- produce a raster poster that is wrapped inside SVG and delivered as the final poster;
- alter source-figure colors, annotations, aspect ratio, or crop in a way that changes meaning;
- create an asset whose scientific/evidentiary role is ambiguous.

If a requested generated asset would cross these boundaries, omit it and use deterministic SVG geometry or an unchanged source asset.

## Visual Brief

Write `outputs/poster_visual_brief.json` before calling an image model. Include:

- `status`: `planned`, `generated`, `skipped`, or `failed`;
- `visual_goal` and `paper_type`;
- `hierarchy`: title, take-home, main figure, main result, and supporting sections;
- `style_keywords` and `avoid_keywords`;
- `palette_direction` and contrast requirements;
- `composition_direction` without final geometry claims;
- `source_asset_roles` with source figure IDs and intended placement roles;
- `generated_asset_requests` with an allowed asset class for each request;
- `prohibited_content` copied from this contract;
- `model`, `prompt_version`, and failure/fallback notes when a call is made.

Do not place claim evidence, private chain-of-thought, or unnecessary full-paper text in the visual brief.

## Right Code Adapter

Use the Right Code adapter only after the user explicitly enables image art direction. The default pipeline mode is `off` to avoid unexpected image charges.

Configure a newly issued key without storing it in the skill:

```bash
export RIGHTCODE_API_KEY="..."
export RIGHTCODE_DRAW_BASE_URL="https://www.right.codes/draw/v1"
export RIGHTCODE_TASK_BASE_URL="https://www.right.codes/v1"
```

Run a required image-art-direction pass with:

```bash
python scripts/run_pipeline.py paper.pdf \
  --extraction-mode auto \
  --image-art-direction required \
  --image-model gpt-image-2 \
  --image-size 1K
```

`auto` records a skipped or failed fallback and continues with deterministic design. `required` stops when the key, permission, submission, polling, download, or image validation fails. The adapter must submit `async: true`, poll the site-level task endpoint, never log the key, never send the key to a returned CDN URL, and save provider metadata in `poster_visual_generation.json`.

If polling times out after a `task_id` was issued, treat the provider task as potentially still running. Do not submit a duplicate task. Resume the same task with `--image-resume-task-id <task_id>` and a longer `--image-timeout-seconds` value; record the task ID and resumable state in the generation report.

The generated reference is always `style_reference_only`. Analyze its pixels locally, record the reference hash and contrast-guarded palette in `poster_style_analysis.json`, and apply tokens only when analysis passes. Do not embed the reference image in `poster.svg`.

## Hybrid Rendering Workflow

1. Finish extraction, semantic verification, poster content building, and the critical claim-evidence gate.
2. Build the visual brief from verified poster content and selected source-asset roles.
3. Generate a style reference or approved non-evidence assets when image-model art direction is enabled.
4. Analyze the actual returned pixels and derive bounded palette tokens with contrast guards; retain deterministic defaults if analysis fails.
5. Build `poster_design_spec.json` from those explicit rules.
6. Render exact verified text with editable SVG elements.
7. Embed or reference unchanged `source_evidence` assets.
8. Add generated assets only when their class is recorded and their role is visibly non-evidentiary.
9. Render the final SVG to `poster_render_preview.png` with a deterministic SVG renderer.
10. Review the actual preview for hierarchy, balance, legibility, source-figure treatment, clipping, and misleading visual emphasis.
11. Convert review findings into rule-level changes, re-render, and stop after a bounded number of iterations.
12. Run structural SVG validation and claim-evidence gates again before completion.

If image generation is unavailable or fails, continue with deterministic design rules and record `status: skipped` or `failed`. Image-model art direction is an enhancement, not a requirement for scientific correctness.

## Rendered-Preview Review

Review the rendered poster image together with compact structured context. The visual reviewer may judge:

- visual hierarchy and 10-second comprehension;
- title and body readability at poster scale;
- whitespace, alignment, balance, and density;
- whether the strongest verified result receives appropriate emphasis;
- whether source figures remain readable and appear unmodified;
- whether generated assets could be mistaken for scientific evidence;
- clipping, overlap, awkward crop, low contrast, or tiny captions.

The reviewer must not rewrite scientific claims from visual inspection. Return rule-level recommendations such as changing spacing, section height, font size, figure allocation, palette contrast, or decorative intensity.

## Required Validation

Before completion, confirm or report:

- every asset has one recorded class;
- every `source_evidence` asset retains source page, caption, path, and hash when available;
- no generated asset is cited by a poster claim;
- no source plot, table, or result figure was regenerated or visually altered;
- final text and numbers come from verified poster content, not from pixels in a style reference;
- `poster_style_reference.png` is not embedded as the poster canvas;
- generated artwork does not cover or visually compete with critical evidence;
- the rendered preview was reviewed when visual review was enabled;
- failures and fallbacks are recorded in `generation_report.md`.
