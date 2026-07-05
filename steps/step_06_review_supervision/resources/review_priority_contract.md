# Review Priority Contract

## Purpose

This document defines the first stable contract for KC review priority in the supervision layer.

It is grounded in the pilot authority:
- `R:\Thesis Project\KC_L v2\kc_review_supervision_pilot_spec.md`

It is also grounded in the current repo reality:
- Step 6 reviewable machine outputs already exist as `kc_library.jsonl`
- newer Step 6.4.2 and main-quest outputs also emit per-KC traces, `definition_short_contract_audit.jsonl`, and `tier2_recovery_queue.jsonl`

This contract does not change approval authority.
It only standardizes how the machine computes review priority and recommendation before human review.

## Stable Output Surface

The supervision helper at `src/kc_l/kc/supervision.py` emits:

- review-priority buckets:
  - `high_support`
  - `moderate_support`
  - `needs_review`
  - `low_support`
- system recommendation labels:
  - `approve_ready`
  - `review_needed`
  - `reject_recommended`

Expert-facing labels are:
- `High support`
- `Moderate support`
- `Needs review`
- `Low support`

These buckets are queue-ordering aids.
They are not final approval states.

## Input Features

### Required now

These signals are required for a fully trusted current-generation priority decision because they already exist, or can be derived cleanly, from current Step 6 machine outputs:

| Feature | Meaning | Current repo source |
| --- | --- | --- |
| `semantic_tier` | current semantic usability tier | `enrichment_traces/*.json.semantic_tier` or `tier2_recovery_queue.jsonl.semantic_tier` |
| `definition_status` | whether definition support is coherent, fragmentary, or unsupported | `enrichment_traces/*.json.definition_status` or `tier2_recovery_queue.jsonl.definition_status` |
| `accepted_quote_count` | count of accepted or verified quote evidence supporting the current draft | `tier2_recovery_queue.jsonl.accepted_quote_count` or adapter-derived from evidence spans |
| `evidence_span_count` | number of evidence spans included in the review packet | packet `evidence_spans` |
| `definition_short_contract_ok` | whether short-definition contract checks stayed clean | `definition_short_contract_audit.jsonl.definition_short_contract_ok` or trace `definition_short_audit` |
| `support_contract_downgraded` | whether strict support logic downgraded the candidate | `tier2_recovery_queue.jsonl.support_contract_downgraded` or trace `support_contract.support_contract_downgraded` |
| `contamination_category` | whether the current draft is clean or hard-contaminated | `tier2_recovery_queue.jsonl.contamination_category` or trace contamination summary |
| `sibling_ambiguity` | whether close-sibling ambiguity remains unresolved | `tier2_recovery_queue.jsonl.sibling_ambiguity` or trace contamination summary |

### Future-capable

These inputs are part of the stable contract now, but the repo should treat them as optional until the adapter can emit them reliably:

| Feature | Intended meaning |
| --- | --- |
| `operational_support_present` | procedural or application support beyond a bare definition |
| `proposal_route_agreement` | agreement or conflict across proposal routes or candidate-generation paths |
| `overlap_risk` | overlap or near-duplicate risk relative to nearby KCs or frozen library entries |
| `underspecified_wording_risk` | wording is too vague to approve safely without closer review |
| `overbroadness_risk` | draft scope looks broader than the intended KC leaf |
| `novelty_against_frozen_library` | whether the draft is clearly novel or suspiciously near-duplicate |

## Missing-Feature Handling

Missing data is handled conservatively.

- Missing `required now` features are recorded in `missing_feature_keys`.
- Missing `required now` features are never imputed positively.
- If a candidate would otherwise land in `high_support` or `moderate_support`, missing `required now` features cap it at `needs_review`.
- Missing `future-capable` features are allowed and recorded, but they do not by themselves block packet emission.

This keeps the interface stable without pretending unavailable signals already exist.

## Current Scoring Policy

The executable policy is in `src/kc_l/kc/supervision.py`.
The current v1 rule is intentionally simple:

1. Add positive support for strong semantic tier, coherent definition support, and multiple evidence spans or accepted quotes.
2. Subtract support for unsupported definition status, zero evidence spans, or zero accepted quotes.
3. Apply negative pressure for sibling ambiguity and future overlap or wording risks when present.
4. Treat these as hard blockers that force `low_support`:
   - `definition_short_contract_ok = false`
   - `support_contract_downgraded = true`
   - `contamination_category = hard_contamination`

Current bucket thresholds are:

- `high_support`: score `>= 6` and no hard blocker
- `moderate_support`: score `>= 4` and no hard blocker
- `needs_review`: score `>= 1` after conservative caps
- `low_support`: score `<= 0` or any hard blocker

## Recommendation Policy

Recommendation is derived from the same feature contract but remains separate from approval:

- `approve_ready`
  - only when the bucket is `high_support`
  - and no hard blocker is present
  - and no `required now` feature is missing
- `review_needed`
  - default middle state
  - used for `moderate_support`
  - used for `needs_review`
  - used whenever missing `required now` features prevent a confident machine recommendation
- `reject_recommended`
  - used for `low_support`
  - or when a hard blocker is present

## Separation From Human Approval

This contract does not authorize ingestion into the frozen usable library.

- review priority orders the queue
- system recommendation suggests a likely action
- only the human reviewer may produce final states:
  - `approved`
  - `edited_approved`
  - `rejected`

The machine never writes a final frozen library entry directly.

## Why This Contract Fits Current Repo Outputs

It is intentionally aligned to current machine outputs rather than hypothetical UI fields:

- Step 5.3 `review_queue.jsonl` remains an upstream evidence-risk shortlist, not the final expert packet
- Step 6 `kc_library.jsonl` supplies the machine draft text and evidence spans
- Step 6.4.2 and main-quest traces supply the stronger support, downgrade, and contamination signals needed for stable priority computation

That makes the contract minimal, current, and usable without redesigning the existing KC pipeline.
