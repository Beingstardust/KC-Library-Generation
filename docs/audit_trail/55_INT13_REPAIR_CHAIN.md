# 55. INT-13: two content repairs existed and had never once executed

Not a wrong rule. An unreached one.

## How it was found

Asked whether the pipeline was at its ceiling, the honest check was whether anything already built
was failing to run. `repair_attempted` is recorded on every drafted row, and it was **0 across
every audited drafting job**. Meanwhile 8 units abstained on packets the validator calls
draftable, which is exactly the condition `invalid_abstention_needs_content_repair()` exists to
detect.

Evaluating that gate against the final run: it returns True for **7 of 159 units** - Learning
Phase, Target Attribute, Bushy Decision Tree, Multi-class Confusion Matrix, Classification
Threshold, Models of Randomness 1 and 2. So the repair was applicable, and never applied.

## Why

The production drafting loop is `run_step67_v2_schema_contract_probe.py`, not
`04_draft_runner.py`'s own `main()`. The probe drives the runner by invoking functions it names
one at a time:

```
base_mod.build_prompt                 base_mod.parse_model_json
base_mod.normalize_draft_from_packet  base_mod.validate_output
base_mod.apply_status_integrity_gate  base_mod.build_parse_repair_prompt
base_mod.should_attempt_schema_repair base_mod.build_schema_repair_prompt
```

`invalid_abstention` appeared **zero** times, and so did `damaged_math`. Both repairs were written
as blocks inside the runner's own loop, which nothing executes.

This had already happened once. The status-integrity gate was found dead the same way on
2026-08-17, and that fix's own comment documents the trap - including the identical evidence
("0 of 159 real audited drafts carried a status_integrity_override"). The lesson had been written
down and the next two instances still went unnoticed, because the evidence for them lived in a
run-metadata field nobody was reading.

## The fix repairs the class, not the two instances

Repairs are declared ONCE as data:

```python
content_repair_chain() -> (invalid_abstention_content_repair,
                           damaged_math_content_repair,
                           schema_repair)
```

Both loops iterate it. A repair added to the chain is reached by the production loop without
anyone remembering to mirror it. Fixing only the two instances would have left the third, fourth
and fifth to be discovered the same way.

Two things were unified while consolidating:

- **`repair_resolved()`** replaces three slightly different acceptance rules with one that
  requires the repair's OWN predicate to stop firing, not merely a clean parse and validation.
  That is what stops a repair being accepted because the model returned something well-formed.
  It also means **a model that abstains again keeps its abstention** - the attempt is discarded
  and the original draft stands. Nothing here manufactures confidence on the model's behalf,
  which is the failure the status-integrity gate exists to prevent.
- **`repair_phase`** is now written onto every row. "Never applicable" and "never reached"
  previously looked identical in the output, and that ambiguity is what hid this.

## Verification

18 unit tests, 12 regression guards. Four guards protect the class rather than the instances:
the probe must iterate the chain (INT13-3), name no individual predicate (INT13-4), hardcode no
phase literal (INT13-5), and use the shared acceptance rule (INT13-6). Suite 393 -> 405 checks,
0 failed.

Sabotage: 8 cases, all caught by their target guard, tree restored byte for byte.

### The guard that was defeatable

INT13-3 originally asserted that the string `content_repair_chain()` appears in the probe's
source. Deleting the actual call left it passing, because the explanatory comment directly above
the loop contains that same string - the check was satisfied by the comment describing what had
just been removed. It now uses `live_calls()`, which resolves reachability from the AST.

That helper exists in this suite because an earlier sabotage round defeated five source-text
checks the same way. This was the sixth. The pattern is consistent enough to state plainly: **a
guard written against source text is a guard against spelling, not against behaviour.**

## Two operational mistakes made while shipping this

- A **sabotaged probe was copied to the drafting cluster**, because the re-sync read the primary
  compute cluster's working tree while an audit was mid-run. Caught by diffing the deployed file against git.
  Deployments now come from `git show HEAD:<path>`, which a running audit cannot touch.
- **`scp` from a Windows workstation committed CRLF**, and the harness's text-mode restore
  silently normalised it back to LF - so the repository looked modified after an audit that had
  restored everything correctly. `git diff --ignore-all-space` confirmed zero content change.
  The harness now restores in binary mode and verifies the bytes, and the line endings were
  normalised in `fcffb00`.

## Answer to the question that prompted this

The pipeline was NOT at its ceiling. What looked like a ceiling was partly a reachability failure
in code that had already been written, tested, and believed to be running.
