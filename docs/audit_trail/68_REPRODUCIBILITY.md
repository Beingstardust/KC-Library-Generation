# 68. Reproducibility of the packet build, and a noise floor I had been quoting wrongly

Every A/B in this audit was read against a "content noise floor of 4 units". That number was
wrong, and it was wrong in the direction that made my own results look weaker, which is the only
reason it survived unexamined for as long as it did.

## Where the wrong number came from

The analysers compare arm A against **the previous final build**, on the reasoning that arm A and
that build share packet-building code, so anything separating them is run-to-run variation. They
do share code. They do not share a node or a day.

```
INT-11 A/B    both arms, one job, gpu07 (A30)
INT-15 A/B    both arms, one job, gpu08 (A30)
INT-16 A/B    both arms, one job, gpu07 (A30)
INT-20 A/B    both arms, one job
r5 builds     gpu01 (A100)
```

So "arm A vs previous final build" is a cross-node, cross-day comparison, and it was being quoted
as within-run noise.

## What the real numbers are

**Same code, same inputs, same node.** Three builds on gpu01:

```
admitted evidence text : IDENTICAL in all 159 units
units differing at all : 2 / 159
what differs           : one float inside support_profile_summary's relevance
membership, admission_basis, row counts, support states : unchanged
```

The files are **not** byte-identical - the md5s differ, and I claimed byte-identity once before
checking, which was an overstatement of my own evidence. What is identical is every decision the
build makes. A float moves in the last bits for three passages; nothing that float feeds into
changes.

**Same code, same inputs, different hardware.** A100 (gpu01) against A30 (gpu07):

```
units identical            : 154
units differing in ORDER   : 4
units differing in CONTENT : 1   (one non-formula row)
support-state differences  : 0
```

## What follows

**Every A/B in this audit built both arms in one job on one node.** So each was measured under
conditions where membership is deterministic, and the correct floor for all of them is **zero**:

- INT-15: 7 units changed against 0, not against 4.
- INT-16: 4 units changed against 0, not "at the noise floor" as doc 60 says.
- INT-20: 5 units changed against 0.

The correction is recorded in the INT-20 commit as well as here, because it runs in my favour and
a correction that benefits the person making it should be stated more loudly, not less.

## The near-miss that this came out of

Chasing this started because Precision and Rand Index appeared to lose their defining formulas.
The first explanation I formed - hardware - was wrong, and the test I ran to check it was wrong
too: the job asked for partition `gpu`, which contains both A100s and A30s, and SLURM handed it
another A100. It reported a difference of zero and would have "confirmed" determinism while
testing nothing. Constraining `--gres=gpu:a30:1` is what made it a real comparison.

The actual cause was INT-20's dead rescue, and Precision's formula sitting at relevance 0.560
against a 0.55 floor. See doc 67.

## Provenance hazard worth recording separately

Two hierarchy overlay files exist at the **same timestamped path** in two project directories:

```
kc_l_v2_clean/data/processed/hierarchy_overlay/20260727T022835Z_9e856df6/.../hierarchy_overlay.jsonl
kc_l_v2_mirror_20260810/data/processed/hierarchy_overlay/20260727T022835Z_9e856df6/.../hierarchy_overlay.jsonl
```

They differ in exactly one node: KC_CLF_DT_007 is "Intrinsic Information" in one and "Split
Information" in the other. Production (`v3/jobs/01_packets.sbatch`) uses the mirror.

Building the taxonomy split from the clean copy silently renamed that unit, which changed its
retrieval query, which cost it all 13 of its evidence rows and dropped it from `draftable` to
`insufficient_support`. It looked exactly like a regression in INT-15/16 and it was a wrong file
path. Caught only by asking why one unit lost 13 rows instead of accepting the total.

A timestamped path that is not content-addressed is not provenance. Anything reading these
overlays should record which project directory it came from.

## Recommendation for the paper

State the build hardware alongside the artifact, and state that membership is reproducible on
fixed hardware and differs in one unit across GPU generations. Do not quote a packet-level noise
floor above zero for any comparison whose arms were built in the same job.
