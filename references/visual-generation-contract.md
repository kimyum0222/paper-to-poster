# Visual Generation Contract

Read this reference before enabling, implementing, debugging, or evaluating image-model art direction or rendered-poster inspection.

## Contents

- [Role Separation](#role-separation)
- [Asset Classes](#asset-classes)
- [Allowed Image-Model Tasks](#allowed-image-model-tasks)
- [Forbidden Image-Model Tasks](#forbidden-image-model-tasks)
- [Visual Brief](#visual-brief)
- [Right Code Adapter](#right-code-adapter)
- [VTracer Decorative Vectorization](#vtracer-decorative-vectorization)
- [Multimodal Design Guidance](#multimodal-design-guidance)
- [Hybrid Rendering Workflow](#hybrid-rendering-workflow)
- [Rendered-Preview Inspection](#rendered-preview-inspection)
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
- `narrative_plan_linkage` with content-hash validation status;
- `layout_requirements` with body-section count, reading order, one hero, priority, text density, bullet budget, relative area weight, and source-image placeholder ratios;
- `source_asset_roles` with source figure IDs and intended placement roles;
- `generated_asset_requests` with an allowed asset class for each request;
- `prohibited_content` copied from this contract;
- `model`, `prompt_version`, and failure/fallback notes when a call is made.

When `poster_narrative_plan.json` is supplied, resolve its claim IDs and figure IDs against `poster_content.json`, reject a content-hash mismatch, and keep claim text, metrics, captions, title text, and figure pixels out of the image prompt. Pass only fixed semantic section roles, structural budgets, and blank source-image slot proportions. Do not place claim evidence, private chain-of-thought, or unnecessary full-paper text in the visual brief.

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

Treat operations according to their billing safety:

- Never automatically retry the billable POST submission. If the connection closes before a task ID is received, record `failure_stage: post_submission`, `submission_outcome: unknown`, and `safe_to_retry: false`. Tell the user to inspect the provider task or billing dashboard before submitting again.
- Retry GET status polling with a small bound and backoff. A GET failure is safe to retry and should retain the known task ID.
- Retry returned-image downloads with a small bound and backoff. Strip query parameters before recording CDN endpoints and never attach the provider API key to CDN requests.
- Record the endpoint, task ID, failure stage, submission outcome, retry safety, and recommended action in the provider report and generation report.

Use `--image-request-timeout` for each individual POST, GET, or download request and `--image-timeout-seconds` for the overall post-submission polling window. Increasing the request timeout does not authorize resubmitting an unknown POST outcome.

If polling times out after a `task_id` was issued, treat the provider task as potentially still running. Do not submit a duplicate task. Resume the same task with `--image-resume-task-id <task_id>` and a longer `--image-timeout-seconds` value; record the task ID and resumable state in the generation report.

The generated reference is always `style_reference_only`. Analyze its pixels locally, record the reference hash, contrast-guarded palette, and guarded spatial composition in `poster_style_analysis.json`, and apply tokens only when analysis passes. Spatial analysis may measure the header proportion, margins, gutters, panel rectangles, cross-row or cross-column spans, panel gaps, and visual density. It must combine those measurements with validated narrative section IDs and budgets; it must not OCR, transcribe, or infer scientific content from pixels. Require one confidently detected content panel per validated narrative section before applying reference geometry. A missing or ambiguous panel set is `degraded` or `failed`, never a successful equal-column fallback. Do not embed the reference image in `poster.svg`.

Simple generated icon motifs may be replaced with deterministic local SVG geometry when they are recorded as `generated_decorative`, carry no scientific meaning, and are never referenced by a claim. Record each included decoration in the design specification or generated-asset manifest.

## VTracer Decorative Vectorization

Use VTracer only after local reference analysis isolates a region that is unambiguously decorative. Never trace the whole poster, a content panel, source-image slot, title, body text, metric, caption, table, or scientific figure.

Run decorative vectorization in `off`, `auto`, or `required` mode. In `auto`, record a skipped result and retain the deterministic SVG substitute when VTracer is unavailable or a crop cannot be isolated safely. In `required`, stop unless every requested decorative crop is vectorized and validated.

Prefer the official `vtracer` Python binding when no CLI binary is present. Install it only after user approval, and invoke it in a bounded subprocess so failures cannot corrupt the deterministic renderer.

Before invoking VTracer:

- verify that the reference hash matches `poster_style_analysis.json`;
- crop only an approved header-icon or decorative-strip region;
- remove the locally estimated background to transparent pixels;
- store the crop under `outputs/assets/generated/` and classify it as `generated_decorative`.

After invoking VTracer, parse and rewrite its output through an allowlist. Keep only local SVG geometry such as `g`, `path`, `rect`, `circle`, `ellipse`, `line`, `polyline`, and `polygon`; remove text, images, scripts, links, external references, event handlers, styles, and unsupported definitions. Bound file size and element count, record the sanitized SVG hash, and inline the verified paths into the final poster. If the file is missing, its hash changes, or validation fails, use the deterministic decorative substitute.

Do not treat tracing as semantic reconstruction. VTracer paths remain non-evidence artwork and must not supply editable poster text, layout identities, scientific labels, or source figures.

## Multimodal Design Guidance

Keep multimodal guidance `off` by default because it creates additional model calls. Enable reference semantics with `--reference-vision-analysis auto|required`, rendered-preview review with `--preview-vision-review auto|required`, and select a model with `--poster-vision-model`. Use `OPENAI_API_KEY` and the optional OpenAI-compatible base URL already supported by the other semantic stages.

Run multimodal reference analysis only after local pixel analysis passes and both stages match the recorded generated-reference SHA-256. Send only the style reference plus structural section IDs, reading order, density budgets, figure-slot aspect ratios, and local design measurements. Do not send claim text, metrics, captions, title text, source-figure pixels, or full-paper text. Save only categorical visual language, reading flow, density, card/header style, panel observations, and small high-confidence decorative boxes in `poster_reference_vision_analysis.json`. Do not retain OCR, quoted pixels, arbitrary coordinates, colors, paths, or SVG code.

Treat local pixel analysis as the geometry authority. Multimodal reference analysis may adjust only allowlisted card radius, border width, shadow opacity, header rounding, and accent-rule presence. Revalidate the reference hash and `scientific_content_influence: none` before applying any value.

Treat detected reference panels as anonymous geometry. Match them to validated narrative sections by relative area demand, assign the unique hero to the largest content panel, and use geometric reading order only as a tie-breaker. Record the assignment method and weights so a visually plausible but semantically inverted mapping cannot pass silently.

Run rendered-preview review only after overflow validation passes and the user authorizes sending the rendered poster image to the configured provider. The preview contains visible verified text and source figures even though the prompt forbids transcription; do not enable this stage for confidential material without explicit disclosure approval. Compare the reference and actual preview for composition, hierarchy, spacing, style similarity, and visual readability. Save `poster_visual_review.json` only after a real two-image model call. Normalize the response to scores, enumerated issue categories, and at most eight bounded patches; discard all free-form visible text from the local report.

Allow preview review to patch only global card style, bounded typography, header decoration booleans, and per-section title/body font sizes or line height. Reject coordinates, dimensions, colors, content edits, new sections, figure changes, image crops, arbitrary code, and low-confidence patches. Build candidate design, typesetting, SVG, layout, overflow, and preview artifacts; replace final files only when the candidate validates. Record accepted or rejected actions in `poster_visual_repair_report.json`. Limit repair iterations to 0-3, and state whether the final preview hash is the same image the model reviewed.

## Hybrid Rendering Workflow

1. Finish extraction, semantic verification, poster content building, and the critical claim-evidence gate.
2. Validate the narrative plan against poster content, then build a content-aware but text-free visual brief from section budgets and selected source-asset roles.
3. Generate a style reference or approved non-evidence assets when image-model art direction is enabled.
4. Analyze the actual returned pixels and derive bounded palette and spatial tokens with contrast and canvas guards; retain deterministic defaults if analysis fails. Optionally classify hash-matched design semantics with a multimodal model while retaining no visible text.
5. Combine spatial tokens, allowlisted semantic style adjustments, and the validated narrative plan to build `poster_design_spec.json` containing executable section boxes and source-figure slots. Reject out-of-canvas, overlapping, unknown-ID, generated-asset, or unverified-claim mappings.
6. Render only exact locally verified claim text with editable SVG elements, respecting section bullet budgets and density-specific typography.
7. Map figure IDs to unchanged `source_evidence` assets and preserve their aspect ratios.
8. Add generated assets only when their class is recorded and their role is visibly non-evidentiary.
9. Render the final SVG to `poster_render_preview.png` with a deterministic SVG renderer.
10. Write `poster_style_conformance_report.json` to verify that analyzed geometry, palette, hero priority, and decorations reached the executable layout. Treat this as token-execution conformance, not pixel similarity.
11. Have the calling agent inspect the actual preview for hierarchy, balance, legibility, source-figure treatment, clipping, and misleading visual emphasis. When explicitly enabled, a multimodal review may add a real two-image report, but it does not replace human inspection or establish pixel fidelity.
12. Convert confirmed inspection findings or allowlisted multimodal patches into rule-level changes, re-render for a bounded number of iterations, and run structural SVG validation and claim-evidence gates again. Test multimodal changes as candidates before replacing final artifacts.

If image generation is unavailable or fails, continue with deterministic design rules and record `status: skipped` or `failed`. Image-model art direction is an enhancement, not a requirement for scientific correctness.

## Rendered-Preview Inspection

Inspect the rendered poster image together with compact structured context. The calling agent may judge:

- visual hierarchy and 10-second comprehension;
- title and body readability at poster scale;
- whitespace, alignment, balance, and density;
- whether the strongest verified result receives appropriate emphasis;
- whether source figures remain readable and appear unmodified;
- whether generated assets could be mistaken for scientific evidence;
- clipping, overlap, awkward crop, low contrast, or tiny captions.

The inspector must not rewrite scientific claims from visual inspection. Apply only rule-level recommendations such as changing spacing, section height, font size, figure allocation, palette contrast, or decorative intensity. Do not emit `poster_visual_review.json` unless a real preview-inspection implementation produced it. For automated multimodal review, retain no visible text or free-form OCR-like response and apply only the narrower allowlist defined above.

## Required Validation

Before completion, confirm or report:

- every asset has one recorded class;
- every `source_evidence` asset retains source page, caption, path, and hash when available;
- no generated asset is cited by a poster claim;
- no source plot, table, or result figure was regenerated or visually altered;
- final text and numbers come from verified poster content, not from pixels in a style reference;
- `poster_style_reference.png` is not embedded as the poster canvas;
- generated artwork does not cover or visually compete with critical evidence;
- the calling agent inspected the rendered preview before delivery when one was produced;
- `poster_style_conformance_report.json` is described as token-execution conformance rather than visual or pixel fidelity;
- failures and fallbacks are recorded in `generation_report.md`.
- multimodal reference/review reports match the reference and preview hashes they claim to analyze;
- a model-guided candidate never replaces the final SVG unless candidate validation passes.
