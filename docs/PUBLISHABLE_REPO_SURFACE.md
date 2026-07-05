# Publishable repo surface

This repository should be pushed as code, configuration, documentation, small manifests, and reproducible orchestration logic. Generated artifacts should be either pointer-governed live surfaces, quarantined historical surfaces, or external scratch artifacts.

## Live Git-facing surface

- `src/`
- `steps/`
- `scripts/`
- `tests/`
- `configs/`
- `docs/`
- `data/input/` only if small/licensed and intended for release
- pointer manifests and small registry files

## Non-live generated surfaces

- `_quarantine/`
- `_archive/`
- large `data/processed/` outputs unless explicitly pointer-governed
- historical logs, jobs, run outputs, cache folders, and backup bundles

## Rule

Do not delete thesis provenance. Quarantine first, close out, then decide retention separately.
