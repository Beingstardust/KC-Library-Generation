# Reference-Based Sentinel Run — Clean Results

> **DEVELOPMENT SENTINEL PERFORMANCE.** This is not a judge qualification pass. The 36 sentinels are development unit tests that check whether the evaluator measures the intended construct. Formal qualification happens only against human-labelled calibration data — see `../../paper_methods/LLM_JUDGE_VALIDATION_METHOD.md`.

- **Judge model:** `selene-1-llama-3.3-70b`
- **Sentinels:** 36  (SOURCE_BOUNDARY 2, REFERENCE_CONTENT 33, ABSTENTION 1)
- **Gold source:** `reference_sentinel_gold.jsonl`   **Predictions:** `selene_reference_sentinel_raw.json`
- Gold and predictions are read from separate files, so a gold revision recomputes aggregates **without rerunning inference**.

## Structural and contract validity

| Task | Calls | Structural | Contract | Truncated | Invalid | Call failed |
|---|---|---|---|---|---|---|
| M1 — evidence faithfulness | 34 | 100.0% | 100.0% | 0 | 0 | 0 |
| M2 — reference/source correctness | 33 | 100.0% | 100.0% | 0 | 0 | 0 |
| M3 — holistic core completeness | 33 | 100.0% | 100.0% | 0 | 0 | 0 |
| M4A — reference-claim retrieval recall | 34 | 100.0% | 100.0% | 0 | 0 | 0 |
| M4B — holistic evidence adequacy (EXPLORATORY) | 34 | 100.0% | 100.0% | 0 | 0 | 0 |
| TARGET — alignment | 33 | 100.0% | 100.0% | 0 | 0 | 0 |

## Semantic agreement — primary binary tasks

Agreement is computed on **resolved gold only**; `GOLD_PENDING` cases are excluded from agreement and reported separately rather than guessed.

| Task | Scope | n valid | Agreement | PASS prec | PASS rec | FAIL prec | FAIL rec | false PASS | false FAIL | NOT_JUDGEABLE | gold pending |
|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 — evidence faithfulness | primary | 34 | 82.4% | 100.0% | 66.7% | 72.7% | 100.0% | 0 | 6 | 0 | 0 |
| M2 — reference/source correctness | primary | 31 | 96.8% | 94.1% | 100.0% | 100.0% | 93.3% | 1 | 0 | 0 | 2 |
| M3 — holistic core completeness | primary | 32 | 90.6% | 100.0% | 82.4% | 83.3% | 100.0% | 0 | 3 | 0 | 0 |
| M4B — holistic evidence adequacy (EXPLORATORY) | **exploratory** | 34 | 23.5% | 100.0% | 3.7% | 21.2% | 100.0% | 0 | 26 | 0 | 0 |
| TARGET — alignment | primary | 33 | 81.8% | 100.0% | 80.0% | 33.3% | 100.0% | 0 | 6 | 0 | 0 |

## M4A — reference-claim retrieval recall (primary retrieval diagnostic)

- **n computable:** 34
- **mean recall:** 0.780   **median:** 1.000
- **range:** 0.000 – 1.000
- **at 1.0:** 21   **below 1.0:** 13

> This is a continuous coverage diagnostic. A value below 1.0 must NOT be read as 'insufficient evidence' - a concise evidence set can omit reference detail and still support an adequate draft. Not a condition of materially_sound.

## Confusion matrices

**M1 — evidence faithfulness**

| expected → actual | count |
|---|---|
| FAIL->FAIL | 16 |
| PASS->FAIL | 6 |
| PASS->PASS | 12 |

**M2 — reference/source correctness**

| expected → actual | count |
|---|---|
| FAIL->FAIL | 14 |
| FAIL->PASS | 1 |
| PASS->PASS | 16 |

**M3 — holistic core completeness**

| expected → actual | count |
|---|---|
| CORE_COMPLETE->CORE_COMPLETE | 14 |
| CORE_COMPLETE->MATERIAL_OMISSION | 3 |
| MATERIAL_OMISSION->MATERIAL_OMISSION | 15 |

**M4B — holistic evidence adequacy (EXPLORATORY)**

| expected → actual | count |
|---|---|
| EVIDENCE_ADEQUATE->EVIDENCE_ADEQUATE | 1 |
| EVIDENCE_ADEQUATE->MATERIAL_EVIDENCE_GAP | 26 |
| MATERIAL_EVIDENCE_GAP->MATERIAL_EVIDENCE_GAP | 7 |

**TARGET — alignment**

| expected → actual | count |
|---|---|
| TARGET_ALIGNED->TARGET_ALIGNED | 24 |
| TARGET_ALIGNED->WRONG_TARGET | 6 |
| WRONG_TARGET->WRONG_TARGET | 3 |

## Mismatches

**M1 — evidence faithfulness** (6)

- `SENT_003` expected **PASS**, got **FAIL**
- `SENT_007` expected **PASS**, got **FAIL**
- `SENT_012` expected **PASS**, got **FAIL**
- `SENT_014` expected **PASS**, got **FAIL**
- `SENT_017` expected **PASS**, got **FAIL**
- `SENT_018` expected **PASS**, got **FAIL**

**M2 — reference/source correctness** (1)

- `SENT_029` expected **FAIL**, got **PASS**

**M3 — holistic core completeness** (3)

- `SENT_011` expected **CORE_COMPLETE**, got **MATERIAL_OMISSION**
- `SENT_029` expected **CORE_COMPLETE**, got **MATERIAL_OMISSION**
- `SENT_035` expected **CORE_COMPLETE**, got **MATERIAL_OMISSION**

**M4B — holistic evidence adequacy (EXPLORATORY)** (26)

- `SENT_004` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_005` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_006` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_007` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_008` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_009` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_011` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_014` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_015` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_016` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_017` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_018` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_019` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_020` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_021` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_022` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_023` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_024` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_025` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_026` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_027` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_028` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_030` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_031` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_032` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**
- `SENT_036` expected **EVIDENCE_ADEQUATE**, got **MATERIAL_EVIDENCE_GAP**

**TARGET — alignment** (6)

- `SENT_019` expected **TARGET_ALIGNED**, got **WRONG_TARGET**
- `SENT_020` expected **TARGET_ALIGNED**, got **WRONG_TARGET**
- `SENT_021` expected **TARGET_ALIGNED**, got **WRONG_TARGET**
- `SENT_023` expected **TARGET_ALIGNED**, got **WRONG_TARGET**
- `SENT_024` expected **TARGET_ALIGNED**, got **WRONG_TARGET**
- `SENT_025` expected **TARGET_ALIGNED**, got **WRONG_TARGET**

## Gold-pending cases

2 sentinel(s) carry a disputed criterion awaiting project-owner adjudication: `SENT_032`, `SENT_033`.

They remain in the 36-case suite and their other criteria score normally; only the disputed criterion is held as `GOLD_PENDING` and excluded from agreement. Full case packages: `pending_sentinel_adjudication.json`.

No aggregate in this report was computed from a guessed label.

## Claim decomposition

- candidate claims: **206**   reference claims: **258**
- structural problems: candidate 2, reference 0
- Structural checks only (parent_span must be a literal substring; formula relations must survive splitting; gross under-coverage flagged). Bounded **human** validation of the decomposition is still required before final results are opened.

## Metric scope

| Task | primary_use | qualification_gate | derived_metric_dependency |
|---|---|---|---|
| M1 — evidence faithfulness | True | True | True |
| M2 — reference/source correctness | True | True | True |
| M3 — holistic core completeness | True | True | True |
| M4A — reference-claim retrieval recall | True | True | False |
| M4B — holistic evidence adequacy (EXPLORATORY) | False | False | False |
| TARGET — alignment | True | True | True |

`materially_sound` excludes **both** M4 outputs. It measures the final KC draft; retrieval coverage explains that outcome rather than defining it.

---

**Next step is human calibration, not system evaluation.** No intrinsic or extrinsic comparison has been run and no candidate ranking has been inspected.