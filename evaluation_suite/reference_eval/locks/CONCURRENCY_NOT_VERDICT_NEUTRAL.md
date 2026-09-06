# Measured: request concurrency changes judge verdicts. Production runs must be sequential.

**Date:** 2026-08-30
**Status:** binding constraint on every production judge run.
**Consequence:** `run_ablation_evaluation.py` defaults to `--concurrency 1` and warns if overridden.

---

## What was tested and why

The full ablation campaign is 1113 rows (7 arms x 159 KCs), roughly **93 GPU-hours sequentially**,
which fits no single scheduler allocation. Concurrency is the obvious remedy: vLLM serves many
requests at once and the GPU is otherwise idle waiting on one request at a time.

Concurrency was nevertheless treated as an **instrument change**, not a free optimisation. Reason:
vLLM batches whatever requests are in flight; batch composition changes matrix shapes and therefore
floating-point reduction order; under greedy decoding a sufficiently near tie can then resolve to a
different token. This project had already lost a run to a generation-time confound
(`frequency_penalty`), so the assumption was tested rather than trusted.

**Gate:** re-run the 36 human-calibration rows concurrently and diff every verdict against the
sequential predictions from the same rows, same server, same model, same decoding.

## Result: DIVERGENT

```
compared 36 rows x 4 tasks (144 verdicts)
DIFF HC-fe4c7df687de961fe9ef  M1_faithfulness_per_claim: sequential=PASS  concurrent=FAIL
VERDICT: DIVERGENT (1 difference)
```

The pipeline aborted automatically before writing a single ablation row.

## Isolating the cause: it is concurrency, not the node

The sequential baseline had been produced on **gpu02**, while the concurrent run was on **gpu03**,
so node identity was a confound in the gate itself. It was removed by re-running the single
divergent row on **gpu03**, sequentially, three times:

| condition | M1 | per-claim labels |
|---|---|---|
| gpu02 sequential (original) | PASS | 9/9 SUPPORTED |
| **gpu03 sequential, run 1** | **PASS** | 9/9 SUPPORTED |
| **gpu03 sequential, run 2** | **PASS** | 9/9 SUPPORTED |
| **gpu03 sequential, run 3** | **PASS** | 9/9 SUPPORTED |
| **gpu03 concurrent (6)** | **FAIL** | claim 3 -> UNSUPPORTED |

Same node, same server process, same model, same decoding. The only varying factor is concurrency.

## Two findings, both worth reporting

1. **Concurrency is not verdict-neutral.** One verdict in 144 flipped (~0.7%). Small, but it is a
   silent change to the instrument, and on a 1113-row campaign it would alter an unknown number of
   arm-level outcomes with no way to detect which.

2. **Sequential decoding is exactly reproducible — including across GPUs.** Three sequential runs on
   gpu03 returned byte-identical per-claim verdicts, and reproduced the earlier gpu02 sequential
   result. Combined with the 36/36 sentinel equivalence between the frozen Cluster A instrument and the
   Cluster-B CUDA-12 rebuild, this is strong positive evidence that the instrument is stable **provided
   requests are issued one at a time**.

## Operational consequence

- Production runs: `--concurrency 1`, always. The flag remains only for diagnostics and warns loudly.
- Throughput is instead recovered by **sharding across proven-equivalent instruments**
  (`--shard-index` / `--shard-count`), each running sequentially. Every output row carries an
  `instrument` tag so the provenance of each verdict is recoverable.
- Instruments are only eligible to share a campaign after passing the sentinel equivalence check.

## Why this is a result and not merely an obstacle

An LLM-as-judge pipeline that is reported as "temperature 0, seed fixed, therefore deterministic"
is **not** reproducible if it was served with request batching. Determinism holds per-request; it
does not survive arbitrary batch composition. Any reference-based judge study that ran its campaign
concurrently and reports greedy decoding as a reproducibility guarantee has an undisclosed source of
variance. This was caught here only because concurrency was gated instead of assumed.


---

# RESOLVED (2026-08-31): `VLLM_BATCH_INVARIANT=1` makes concurrency verdict-neutral

The conclusion above ("production runs must be sequential") was correct for vLLM's **default**
kernels, but incomplete. It was reached from first principles without checking whether the field had
already solved the problem. It has.

vLLM ships a batch-invariance mode that uses a fixed reduction order independent of batch size and
request order. It is present in our pinned vLLM 0.27.1 (`envs.py`: `VLLM_BATCH_INVARIANT`, plus
`model_executor/layers/batch_invariant.py`) and is enabled with:

    export VLLM_BATCH_INVARIANT=1

**Verified against the same gate that failed before:**

| configuration | verdicts differing from the frozen sequential baseline |
|---|---|
| default kernels, concurrency 6 | **1 / 144** (`HC-fe4c7df687de961fe9ef` M1: PASS -> FAIL) |
| **batch-invariant, concurrency 6** | **0 / 144 — EQUIVALENT** |

The specific row that flipped under default concurrency returns the correct verdict under
batch invariance. Evidence: `output/gate_equivalence_batch_invariant.json`.

## Cost

Batch invariance is not free. It disables custom all-reduce under tensor parallelism and uses
slower deterministic kernels:

- KV cache: 59,200 -> 54,000 tokens
- startup: longer (kernels are recompiled)
- throughput: ~63 s/row at concurrency 6, versus ~120 s/row sequential with default kernels.
  So the net gain is roughly **1.9x**, not the ~9x that unsafe concurrency appeared to offer.

That is the honest trade: about half the wall-clock, with verdicts provably unchanged.

## Standing rule (revised)

- Concurrency is permitted **only** with `VLLM_BATCH_INVARIANT=1`, and only after the equivalence
  gate passes for that configuration.
- With default kernels the original rule stands: sequential only.
- Requirements: NVIDIA compute capability >= 8.0 (A100 8.0, H100 9.0 both qualify). The feature is
  documented as beta.

## The reporting point is unchanged, and strengthened

"temperature 0 + fixed seed" still does **not** imply reproducibility for a batched judge. It implies
it only when the serving stack is batch-invariant. A study that reports greedy decoding as a
reproducibility guarantee, without stating whether batching was batch-invariant, has an undisclosed
source of variance. We can now state ours precisely.
