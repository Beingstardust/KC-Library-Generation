# Supervision Integration Note

## Purpose

This note pins where the new supervision artifacts connect to the existing KC pipeline and what remains deliberately deferred.

## Where The New Artifacts Connect

The supervision layer belongs after machine KC draft emission and before any human-approved frozen-library ingestion.

In current repo terms, the attachment point is after Step 6 processed outputs are written:

- machine draft text and evidence:
  - `data/processed/kc_library/<run_id>/kc_library.jsonl`
- richer Step 6.4.2 or main-quest review signals:
  - `data/processed/kc_library/<run_id>/enrichment_traces/*.json`
  - `data/processed/kc_library/<run_id>/definition_short_contract_audit.jsonl`
  - `data/processed/kc_library/<run_id>/tier2_recovery_queue.jsonl`
- upstream provenance references:
  - Step 4 and Step 5 set ids already carried in the KC records and run manifests

The new schemas and helper do not replace those outputs.
They sit on top of them as the review-facing contract layer.

## Required Adapter Layer

Current KC outputs are not yet review packets.
An adapter is still needed.

The adapter should do exactly this:

1. Read one Step 6 processed output directory.
2. For each KC record in `kc_library.jsonl`, build a review packet.
3. Copy machine draft fields directly into:
   - `kc_candidate_id`
   - `title_draft`
   - `level_draft`
   - `definition_draft`
   - `evidence_spans`
4. Build `evidence_coverage_summary` from the KC record plus trace or short-definition audit.
5. Build `source_provenance` from the KC record metadata, Step 4 and Step 5 set ids, run id, and source document ids.
6. Build `risk_flags` from the KC record quality flags plus trace or tier2 recovery reasons.
7. Compute `review_priority` and `system_recommendation` with `src/kc_l/kc/supervision.py`.
8. Emit packet rows that validate against `src/kc_l/kc/schemas/review_packet.schema.json`.

That is the minimum adapter surface.

## What The Adapter Reuses Vs What It Adds

### Reused from current outputs

- draft title, draft definition, and evidence spans from `kc_library.jsonl`
- support and contamination signals from traces and tier2 recovery rows
- definition-short contract result from `definition_short_contract_audit.jsonl`
- source set ids already present in Step 6 record metadata

### Added by the adapter

- packet id
- packet state
- normalized evidence coverage summary
- normalized source provenance object
- normalized review priority object
- normalized system recommendation object

## Important Boundary: Step 5 Review Queue Is Not The Packet

Current Step 5.3 `review_queue.jsonl` is useful but insufficient.

It is an upstream shortlist that contains:
- evidence-risk reasons
- candidate counts
- top example snippets

It does not contain:
- final machine draft title or definition
- full evidence span objects with Step 6 draft grounding
- review-priority bucket contract
- audit-ready expert action surface

So the new supervision packet should not be wired directly to Step 5.3 `review_queue.jsonl`.
That file remains a feeder signal, not the expert packet contract.

## What Is Deliberately Not Implemented Yet

The following remain out of scope by design:

- no UI implementation
- no queue database or product workflow engine
- no multi-user moderation layer
- no new expert action types beyond Approve, Edit, Reject
- no automatic split or merge workflow
- no direct machine promotion into the frozen usable library
- no ACTIVE pointer changes
- no frozen baseline promotion
- no semantic recalibration or runtime work

## What The Future UI Should Consume

The future UI should consume the new artifacts, not raw pipeline internals, as its primary contract:

- review packets validated by `review_packet.schema.json`
- audit events validated by `review_audit.schema.json`
- queue ordering from `review_priority.rank_score` and `review_priority.bucket`
- expert actions constrained to Approve, Edit, Reject

That keeps the UI thin.
It can render stable packet sections and write stable audit events without redesigning the packet contract later.

## Historical Compatibility Note

The best adapter target is the current Step 6.4.2 or main-quest output shape because those runs already emit the strongest support and contamination traces.

Older Step 6.3 outputs can still be packetized in a reduced form, but missing richer signals should conservatively cap review priority at `needs_review`.

That preserves backward compatibility without pretending the older baseline already emits the full pilot supervision surface.
