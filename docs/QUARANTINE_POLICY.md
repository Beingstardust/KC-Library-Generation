# Quarantine policy

Quarantine is not deletion. It is a reversible mirror-tested move for stale generated outputs.

Automatic quarantine scope is limited to `legacy_archive_retain_candidate` generated `data/processed` roots. Review-required, protected, active-current, and active-in-progress roots must remain live.

Master quarantine requires a separate plan-only step, restore script, post-mutation validation, Step6.8 smoke, and pointer hash checks.
