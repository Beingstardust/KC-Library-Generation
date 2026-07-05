# Step 5x source-overlay target supplement lane

This patch operationalizes the successful target13 precise source supplement replay as a generic candidate-discovery supplement lane.

## Contract

The lane is disabled by default. When enabled through `direct_overlay_supplement.generate_from_source_overlay`, it scans a Step 4.5 sentence overlay and derives target phrases only from runtime KC registry/profile/policy fields.

It does not contain course-specific labels, KC-specific production branches, model-specific assumptions, or pack/scoring admission weakening.

## Inputs

- selected KC context rows
- optional Step 5p profile guidance
- Step 4.5 sentence overlay rows
- existing Step 5x direct overlay supplement configuration

## Output

The generator emits ordinary supplement rows which then pass through the existing `direct_overlay_supplement` candidate-bank path, followed by unchanged scored-candidate and pack-composition gates.

## Guardrails

- Disabled by default.
- Phrase derivation is runtime-data driven.
- Broad phrases are filtered dynamically across the active KC slice.
- Reference-like, metadata-like, unsafe, prompt-like, and weak rows are rejected before candidate emission.
- Success remains lane-aware: only `drafting_core_evidence` counts as automatic drafting support.
