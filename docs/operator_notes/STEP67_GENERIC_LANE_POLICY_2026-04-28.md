# Step 6.7 Generic Lane Policy

Date: 2026-04-28
Status: local sidecar refactor only; no authoritative rerun yet

## Purpose

This note records a bounded Step 6.7 sidecar policy refactor that keeps the active production drafting path untouched while extracting the reusable lane-policy lessons from the Sofja diagnostics.

The new sidecar surface is intentionally:

- deterministic
- quote-first
- domain-agnostic
- model-agnostic
- CLI-driven for replay

## New Sidecar Surface

- `src/kc_l/kc_drafting/evidence_lane_policy.py`
- `scripts/experimental/step67a_build_field_lane_packets_generic.py`
- `tests/test_evidence_lane_policy.py`
- `tests/test_step67_sidecar_domain_agnosticity.py`

## Generic Policy Rules

1. Definition promotion is local-quote first. A context block must not promote definition status when the quote itself is only relation, use, contrast, or fragment evidence.
2. Relation and extension language is contextual evidence, not a canonical definition.
3. Negative contrast is not positive support for the target concept.
4. Use-case and boundary language belongs in scope or context lanes, not definition.
5. Prompt-like or fragmentary text is quarantined.
6. Target binding is derived only from canonical name, aliases, topic-path labels, and small lexical variants generated from those fields.
7. The replay runner accepts source paths through CLI arguments and does not embed dated artifact paths.

## Repair Pass

The initial sidecar pass was directionally correct but still too permissive for definition promotion. The repair pass tightened the generic policy in four ways:

- definition promotion now requires strict quote-local target binding instead of broad subject-token overlap
- short one-token targets are protected unless the quote also supplies stronger corroboration
- usage, procedural, commonness, and tendency phrasing is demoted before any definition promotion is considered
- `called` and `known as` now count only when the named phrase itself is the target, not when the target appears as a subphrase inside a longer noun phrase

The repair pass also strengthened fragment handling for unfinished modifier endings and truncated passive fragments.

## Latest Local Replay

The bounded replay under `data/work/cache/diagnostics/step67_generic_lane_policy_v2_20260428/2026-04-28_191021/` stayed non-LLM and sidecar-only.

- packet_count remained `40`
- selected counts moved from `definition=15, scope=15, context=56, sibling=3, quarantine=217`
- selected counts now read `definition=1, scope=19, context=60, sibling=3, quarantine=219`

This local replay is still only a safety and auditability check. It does not establish production readiness or authorize a production-path import.

## Current Boundaries

- No edits were made under `_reference_artifacts/`.
- No edits were made in the stale historical repo.
- No active Step 6.7 orchestration or model-calling production file was modified.
- No authoritative Step 6.7 rerun was performed.

## What The Replay Proves

The replay is meant to prove only that the generic lane builder:

- runs without a model call
- accepts explicit input paths
- emits lane packets with definition, scope, context, sibling-contrast, and quarantine structure
- writes a machine-readable summary plus a human-auditable note

It does not prove parity with the historical diagnostic counts, and it does not establish production readiness.
