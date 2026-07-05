# Step 6 KC Record Schema

This iteration uses `schema.json` at repo root as the authoritative KC record contract.

## Why this schema exists

Step 6 turns broad Step 5 evidence candidates into a frozen KC library that is:

- stable by `kc_id`
- grounded to evidence spans with frozen upstream provenance
- incomplete when the source is incomplete
- shaped for a future end-user UI, including Streamlit

The schema intentionally keeps a stable record shape while allowing empty values for fields that cannot yet be supported from the source. Empty values do not mean "known empty"; they mean "not grounded enough yet". Only Tier 1 blockers push the KC into recovery.

## Design rules

- Registry identity is authoritative:
  `kc_id`, `kc_path`, `canonical_name`, `aliases`, and `seed_definition` come from the KC registry.
- Extracted content must be grounded:
  `definition_short`, `definition_full`, scope fields, and type-specific fields are filled only from evidence.
- Quotes are strict:
  every evidence quote must be a literal substring of the source block text.
- Recovery is first-class:
  unsupported Tier 1 requirements push a KC into `recovery_state` and `recovery_reasons`; richer Tier 2 gaps stay visible as `quality_flags`.
- UI stability matters:
  Step 6 keeps a predictable top-level record shape so a Streamlit app can render fixed sections and then show recovery gaps instead of hiding them.

## Field groups

### Registry shell

- `kc_id`
- `kc_path`
- `canonical_name`
- `aliases`
- `seed_definition`

These fields anchor identity and navigation in the future UI. `kc_path` is stored as an array because that matches the registry and makes breadcrumb rendering easy.

### Grounded core content

- `kc_type`
- `definition_short`
- `definition_full`
- `scope_includes`
- `scope_excludes`
- `evidence_minimal`
- `field_evidence_map`

These fields support downstream retrieval and instruction. `field_evidence_map` is especially important for UI work because it lets a future app show "this sentence came from these blocks" without reparsing logs.

### Type-specific fields

The schema keeps type-specific fields for later UI panels and editing:

- `procedure`: `inputs_outputs`, `procedure_steps`, `parameters`, `termination_condition`
- `metric`: `formal_definition`, `interpretation`, `when_to_use`, `when_not_to_use`
- `theorem_or_claim`: `claim_statement`, `assumptions`
- `misconception_cluster`: `misconception_statement`, `canonical_correction`, `diagnostic_cues`, `remediation_suggestions`

These fields are preserved even when they are empty. That keeps the record shape stable and avoids UI branching around missing keys.

### Deferred authoring fields

- `kc_specific_criteria`

This is intentionally kept as an empty string in Step 6. It is reserved for later user authoring in the UI layer and should not be hallucinated from source content.

### Audit and recovery

- `source_set_ids`
- `record_meta`
- `quality_flags`
- `recovery_state`
- `recovery_reasons`

These fields support traceability, filtering, and QA views in later tools.

## Usability vs existence

JSON Schema guarantees record shape. The Step 6 Python validator guarantees usability.

A record can exist and still differ in downstream readiness:

- Tier 0: the schema-valid record exists with the registry identity shell.
- Tier 1: retrieval-usable. It needs at least 2 `evidence_minimal` spans, at least 2 verified quotes, at least one of `definition_short` or `definition_full`, and at least one verified evidence span with a retrieval-supporting role such as `definition`, `equation`, `procedure`, or `other`.
- Tier 2: instruction-usable. It needs Tier 1 plus richer boundary/detail fields such as `scope_includes`, `scope_excludes`, and type-specific completeness when the KC is not a plain concept.

Why `scope_excludes` is not a Tier 1 requirement:

- The Step 6 corpus support for `scope_excludes` was 0 of 128 in the frozen run dated 2026-03-06.
- Keeping `scope_excludes` in the schema preserves the stable record shape for later UI and editing work.
- Making `scope_excludes` optional for Tier 1 allows retrieval-grounded KCs to be usable without fabricating unsupported out-of-scope boundaries.

## Streamlit implications

This schema is intentionally suitable for a future Streamlit UI:

- breadcrumb and tree navigation from `kc_path`
- summary/detail cards from `definition_short` and `definition_full`
- expandable evidence inspectors from `field_evidence_map`
- warning badges from `quality_flags`
- recovery queues from `recovery_state` and `recovery_reasons`
- type-specific tabs that can stay visible even when fields are empty

That means the UI can remain stable while the extraction pipeline improves in later iterations.
