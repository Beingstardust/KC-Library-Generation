# Current Step6.8 Review Packet Contract

Current Step6.8 consumes the Step6.7 postprocessed review source and emits one pending human-review packet per knowledge unit.

## Accepted input

- BEST Step6.7 postprocessed review source pointer:
  `data/processed/step67_v2_postprocessed_review_source/_sets/BEST_STEP67_V2_POSTPROCESSED_REVIEW_SOURCE.txt`

## Accepted output contract

- 165 review packets
- 144 KC packets
- 21 topic packets
- 19 segmentable-gap packets
- no `reject` action in normal draft review
- `needs_expert_rewrite` replaces rejection of the machine draft
- reviewer decision remains pending
- no expert approval inferred
- no draft regeneration
- no evidence invention
- `kc_specific_criteria` remains expert-pending
- all KCs survive the review lane

## Minimal reviewer sufficiency

Each review packet must preserve:

- unit identity
- machine draft
- review_preflight neediness hints
- source evidence enough to approve or edit responsibly
- pending reviewer decision
- survival and non-approval invariants

Topic packets may use topic-specific upstream evidence fields, but Step6.8 must expose a common reviewable evidence surface through `source_row.source_packet.evidence_for_synthesis`.

## Legacy note

The older `steps/step_06_8_kc_review_packet_emission` path emits restarted KC-only packets from older draft bundle assumptions. It is retained for provenance and historical compatibility, but it is not the current accepted Step6.8 path for the 165 KC-topic postprocessed-source flow.
