# KC_L v2 repo surface contract

The repository is controlled by an open-ended stage graph. Step6.8 is the current validation endpoint, not terminal completion.

## Protected surfaces

- `data/input`: input corpus and hierarchy inputs.
- `src`, `steps`, `scripts`, `configs`, `tests`, `docs`: code and control surfaces.
- `data/processed` roots with `active_current`, `active_in_progress`, `protected_pipeline_family`, or `review_required` status.

## Quarantine policy

Only generated `data/processed` roots classified as `legacy_archive_retain_candidate` may be quarantined automatically, and only after pointer validation. Quarantine is reversible and must write a manifest plus restore script. Folder deletion is not authorized by this contract.
