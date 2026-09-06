# Seed-blind reference reconstruction — reviewer instructions

**This is control 6 of `ANTI_ANCHORING_PROTOCOL.md`.** Until it is completed, the thesis may not
claim seed bias was empirically ruled out, and completeness metrics stay secondary.

You are **Reviewer C**. Your job is to write reference descriptions for a sample of knowledge
components **using only the course corpus**, with no exposure to any machine-generated draft and no
exposure to the existing reference library. Your descriptions are then compared against the existing
ones by a third party, to measure whether the existing library's content was shaped by the machine
draft it was seeded from.

---

## 1. What you must not see

This is the entire point of the exercise, so it is worth being blunt: **if you see any of the
following, the audit is void** and cannot be redone with you as the reviewer.

- Any KC draft produced by any system (Qwen, Gemma, DeepSeek, or any pipeline variant).
- The existing expert reference library, in any form, including quotes from it.
- Reviewer A's `pre_seed_source_memo`, action codes, or reason codes.
- Any evaluation result, score, or ranking from this project.
- The `04_gold/` directory or anything derived from it.

You may see: the KC name, its position in the course hierarchy, and the **course corpus**.

If you accidentally encounter any of the forbidden material, stop and report it. A partially
contaminated audit reported honestly is worth more than a clean-looking one that is not.

---

## 2. What you will be given

For each assigned KC:

- **`knowledge_unit_id`** — e.g. `KC_CLF_UND_001`
- **`canonical_name`** — e.g. "Learning Phase"
- **`hierarchy`** — e.g. `Data Mining > Classification > Classification Underpinnings > Learning Phase`
- **Full corpus access** — the four source documents, searchable. You are *not* given a pre-selected
  passage set, because a pre-selected set would inherit the retrieval behaviour of the system under
  test. Finding the relevant material is part of your task.

---

## 3. The sample

**30 KCs**, stratified so the audit can distinguish the two competing explanations. Reviewer A's
action codes are used *only* to build the strata — you are never told which stratum a KC is in, and
the codes are not shown to you.

| stratum | n | why it is included |
|---|---|---|
| Reviewer A accepted the seed unchanged | 18 | Where seed influence would be largest if it exists |
| Reviewer A edited or replaced the seed | 9 | Where the existing reference already moved away from the seed |
| Corpus-unsupported | 3 | Tests whether you also conclude the corpus cannot support the KC |

Proportions mirror the full library (117 accept / 35 changed / 7 unsupported). Assignment order is
randomised so the strata are not inferable from position.

---

## 4. Procedure, per KC

**Step 1 — search the corpus.** Find the passages that define or explain this concept. Record the
document, page/section, and a short quotation for each. Aim for completeness over brevity: if the
corpus explains the concept in three places, record all three.

**Step 2 — decide the support state.** Before writing anything, commit one of:

- `SUPPORTED` — the corpus contains enough to write a correct, self-contained description.
- `PARTIALLY_SUPPORTED` — the corpus touches the concept but is missing something definitional.
- `UNSUPPORTED` — the corpus does not support describing this concept.

If `UNSUPPORTED`, stop here for this KC and record why. Do not write a description from your own
knowledge — that is precisely the failure mode being tested for.

**Step 3 — write the reference description.** 100–250 words, prose, no bullet lists. It must:

- State what the concept **is**, in a way a student could use.
- Include anything the corpus treats as **definitional** — a mechanism, a formula, a distinguishing
  contrast with a neighbouring concept.
- Contain **nothing** that is not supported by a passage you recorded in step 1.
- Not cite the corpus inline; provenance is recorded separately.

**Step 4 — record provenance.** For every substantive statement, note which recorded passage supports
it.

**Do not revise a KC after moving on.** If you realise later that an earlier one was wrong, record
that as a separate note rather than editing the original. The audit needs your first independent
judgement, not a polished final answer.

---

## 5. Output format

One JSON object per KC, one per line, in `05_seed_bias_audit/independent_references/reviewer_c.jsonl`:

```json
{
  "knowledge_unit_id": "KC_CLF_UND_001",
  "reviewer": "C",
  "support_state": "SUPPORTED",
  "source_passages": [
    {"document": "DOC_introduction_to_data_mining", "locator": "§4.3, p.147",
     "quote": "…", "supports": ["definition", "contrast with querying phase"]}
  ],
  "reference_text": "…100-250 words…",
  "unsupported_reason": null,
  "time_minutes": 14,
  "notes": "optional"
}
```

Record `time_minutes` honestly — it is reported as a cost figure, never as a quality signal.

---

## 6. How your work will be used

A third party compares your description against the existing one for the same KC on **substantive
content only**, using these labels — the same ones the protocol pre-specified:

| label | meaning |
|---|---|
| `SUBSTANTIVELY_EQUIVALENT` | Same content, different words |
| `BOTH_VALID_DIFFERENT_FORMULATION` | Both defensible, different framing or emphasis |
| `SEEDED_REFERENCE_MISSING_CONTENT` | Yours contains definitional content the existing one lacks |
| `SEEDED_REFERENCE_EXTRA_UNSUPPORTED_CONTENT` | The existing one asserts something the corpus does not support |
| `MATERIAL_SEMANTIC_DIFFERENCE` | They disagree on what the concept is |

**No BLEU, ROUGE, edit distance, or any lexical-overlap measure is used.** Wording differences are
expected and carry no information — you are not trying to reproduce anyone's phrasing.

### What the outcomes would mean

- **Mostly equivalent, no stratum effect** → the post-editing procedure did not materially shape the
  reference content. Completeness metrics can be restored to primary, with the audit cited.
- **Systematic `SEEDED_REFERENCE_MISSING_CONTENT`, concentrated in the accept stratum** → the seed
  narrowed what counted as essential. Completeness stays secondary and the bias is now *sized* rather
  than merely acknowledged.
- **Systematic `EXTRA_UNSUPPORTED_CONTENT`** → the seed introduced material the corpus does not carry.
  More serious, and it would require re-examining the affected references.

A **null result is a publishable outcome here**, not a failed experiment. The audit exists to size a
threat, and finding it small is a real finding.

---

## 7. Notes for whoever administers this

- Reviewer C must not be the person who built the pipeline, wrote the reference library, or has seen
  its evaluation results. If no such person is available, that fact should be recorded and the audit
  not run — a compromised audit is worse than a disclosed gap, because it looks like validation.
- Expect roughly 12–20 minutes per KC; 30 KCs is about 6–9 hours, splittable across sessions.
- The comparison in §6 should be done by a third person, or by the judge model with the labels above,
  with human review of any `MATERIAL_SEMANTIC_DIFFERENCE`.
- Record the corpus snapshot hash the reviewer worked from, so the audit is reproducible against the
  same corpus state.
