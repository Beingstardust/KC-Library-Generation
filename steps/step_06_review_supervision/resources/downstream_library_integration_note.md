# Downstream Library Integration Note

## Purpose

This note defines how downstream experiments should consume the current full provisional KC library package without confusing it with the frozen reviewed library.

## Current Operational Tier

Use the full provisional machine-pass package as the operational draft tier for downstream experiments:

- `full_provisional_machine_pass_library.jsonl`
- `full_provisional_library_manifest.json`

This tier is acceptable for operational progress because it already excludes sandboxed reject or skipped cases.

This tier is not human-approved.
It remains draft material.

## Required Tier Separation

Downstream code must distinguish tiers explicitly via `library_tier`:

- `frozen_reviewed_library`
  - only human-approved tier
  - separate from the provisional package
- `provisional_machine_pass_library`
  - operational draft tier for experiments now
  - not approved or final
- `kc_review_sandbox`
  - reject, skipped, or otherwise non-operational material
  - excluded from ordinary downstream use

Do not infer tier from file name alone.
Do not treat missing tier metadata as acceptable.

## How To Consume The Provisional Tier Now

Use the downstream loader contract in `src/kc_l/kc/downstream_library.py`.

Recommended path:

1. Load `full_provisional_library_manifest.json`.
2. Resolve the provisional package through `load_full_provisional_machine_pass_library_from_manifest(...)`.
3. Consume only the returned operational records.
4. Preserve `library_tier`, `review_status`, and `source_run_id` in downstream outputs and experiment manifests.

This keeps experimental outputs auditable.

## Why Frozen Reviewed Stays Separate

The frozen reviewed library is still the only human-approved tier.

The provisional tier exists so downstream work can proceed without waiting for full-corpus human review.
That is an operational convenience, not a status promotion.

If downstream work needs reviewed-only claims, it must use a separately tier-wrapped frozen reviewed source, not the provisional package.

## Why Sandbox Must Stay Excluded

Sandbox entries contain reject, skipped, or otherwise unusable cases.
Loading them as ordinary KC records would silently reintroduce exactly the material the supervision layer separated out.

The loader contract therefore treats sandbox as non-operational and fails loudly if it is used as an operational KC source.

## What Later Review Can Change

Later human review can change tier membership:

- provisional entries may later become reviewed and move into a future frozen reviewed package
- sandbox entries may later be repaired and re-emitted through review packets

Until that happens, downstream experiments should treat the provisional tier as draft-only and report it that way.
