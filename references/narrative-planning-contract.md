# Evidence-Grounded Poster Narrative Planning

Use this contract when creating, changing, or evaluating `outputs/poster_narrative_plan.json`.

## Purpose

This stage turns verified poster content into a reviewable narrative plan before any image-model layout generation. It decides which scientific blocks belong on the poster, their reading order, relative importance, text budgets, and source-figure assignments.

It does not write final poster prose, redraw scientific figures, generate an SVG, or authorize unsupported scientific content.

## Inputs

Read:

- `outputs/poster_content.json` for stable poster claim IDs and source-figure records.
- `outputs/extracted_paper.json` for paper-level extraction metadata and semantic context.

Scientific text may enter the plan only through `poster_claims[]` records that have:

- `evidence_status: verified`
- At least one `source_refs[]` record with `verification_status: verified`
- A positive integer source page number
- A non-empty exact source quote

Images may enter the plan only through IDs already present in `figures_to_use[]` or `figure_candidates[]`, with a positive source page and a non-empty local asset path. Reject generated, decorative, style-reference, remote, and non-evidence asset classifications or paths. Accepted images remain `source_evidence`.

## Model Contract

When model planning is enabled, give the model a catalog of verified claim IDs and source-figure IDs. Ask it to select IDs and planning metadata only.

The model may decide:

- Paper type and story arc
- Three to seven poster sections
- Reading order and one hero section
- Section priority, text-density budget, and bullet budget
- Assignment of verified claim IDs and source-figure IDs
- Concise omission reasons and non-scientific planning notes

The model must not create new claims, metrics, comparisons, methods, conclusions, captions, or figure content. Use strict JSON Schema structured output, then validate again locally; schema compliance alone is not a scientific-evidence check.

## Local Normalization

After model output:

1. Drop every unknown, unresolved, or duplicate claim ID.
2. Drop every unknown figure ID.
3. Limit each section to five claim IDs and two figure IDs.
4. Require three to seven evidence-bearing sections.
5. Resolve selected IDs back to their verified claim records and source references.
6. Keep canonical generic section headings and purposes authoritative; store model wording only as non-authoritative suggestions.
7. Ensure exactly one active hero section.
8. Record a SHA-256 digest of the source poster content.
9. Mark generated scientific figures and unverified claims as disallowed.

## Modes

- `off`: do not run narrative planning.
- `auto`: use the configured OpenAI-compatible endpoint when an API key exists; otherwise use the deterministic fallback. If the model call fails, record the reason and fall back.
- `model`: require successful model planning and stop on API, schema, or normalization failure.
- `local`: use deterministic evidence-preserving section grouping only.

For custom compatible endpoints, standard `OPENAI_API_KEY` and `OPENAI_BASE_URL` environment variables apply. `--narrative-model` selects the model; the main pipeline reuses `--extraction-model` when no separate narrative model is supplied.

## Output

`outputs/poster_narrative_plan.json` must record:

- Planning method, model, source policy, and content hash
- Paper type, story arc, hero section, and reading order
- Planned sections with priorities and content budgets
- Selected verified claim IDs plus fully resolved evidence records
- Selected source-figure IDs plus resolved figure records
- Core source figures and omitted sections
- Claim and figure selection summaries

## Current Integration Boundary

When narrative planning and image art direction are both enabled, the visual-brief stage must validate the content hash and selected IDs, then transform this plan into content-aware but text-free layout requirements. It may pass section count, reading order, hero, priority, text density, bullet budget, relative area weight, and blank source-image slot proportions to the image model.

The generated reference remains non-authoritative. Exact text and unchanged source figures stay under deterministic SVG control, and the current pixel-analysis stage does not yet claim to recover authoritative panel geometry from the reference image.

## Acceptance Checks

- Every resolved scientific claim has verified page-and-quote evidence.
- No unverified or unknown claim ID appears in a section.
- Every resolved image is an unchanged source-figure record.
- No generated asset is labeled as evidence.
- The plan has one hero and at least three evidence-bearing sections.
- Reading order contains every planned section exactly once after normalization.
- A Visual Brief consuming this plan rejects content-hash mismatches and unknown or repeated claim/figure IDs.
- The generation report states whether model or local planning was used.
