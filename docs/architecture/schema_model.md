# Core And Extension Schema Model

## Goal

Schema profiles are now split into two bounded layers:

1. locked core schema
2. editable extension schema

This keeps the architecture reproducible while still allowing the operator to adapt a run to the
actual source materials.

## Locked Core

The locked core schema lives at:

- `configs/schemas/default/core_schema.locked.json`

It captures must-have architectural fields and invariants such as:

- stable topic and KC identity fields
- provenance and evidence requirements
- explicit review and approval boundary fields
- separation between Topic Library and KC Library
- conservative graph semantics
- `kc_specific_criteria` present but still empty in this phase

Locked core fields must not be removed, renamed, or retyped by an extension profile.

## Editable Extension Schema

The editable extension templates live at:

- `configs/schemas/examples/extension_schema.template.json`
- `configs/schemas/examples/extension_schema.textbook_example.json`

Extension profiles are for bounded optional fields only. They may add helpful course-aware fields,
but they must not:

- replace locked core fields
- widen the review boundary
- collapse Topic and KC layers
- turn `kc_specific_criteria` into an active custom payload in this phase

## Freeze Point

Before a generation run starts, the chosen extension profile must be frozen into the run manifest
alongside:

- the locked core schema version
- the chosen extension profile path or snapshot
- the runtime mode
- the input bundle manifest

That freeze point is what makes reruns auditable.
