# Seed-blind reference reconstruction — Reviewer D (round 2)

**Your input file:** `reviewer_d_worksheet.jsonl` — 30 knowledge components.
**Your output file:** `independent_references/reviewer_d.jsonl` — you create this.
**Before you hand it back:** run `python validate_reviewer_d_submission.py`.

Round 1 of this audit is unusable. Nothing about that is your fault as a reader of these
instructions, but you need to know the two ways it failed so they do not happen again:

1. **The worksheet was handed over pre-filled.** It arrived carrying `reference_text`,
   `support_state` and `source_passages` already populated, which defeats the entire purpose. The
   worksheet you have now is genuinely blank — verified programmatically before it was issued.
2. **Every entry was far too short.** The spec asked for 100–250 words. The 30 submitted entries had
   a median of 22 words and a maximum of 45. A 22-word gloss cannot carry a definition, a mechanism
   and a distinguishing contrast, so the comparison that followed was between a one-line note and a
   full paragraph, which tells us nothing about bias in either direction.

Read §5 carefully. It is the part that failed.

---

## 1. What this audit is for

We built a reference library of KC descriptions. Those descriptions were written by an expert, but
they were **seeded from machine-generated drafts** — the expert edited a draft rather than starting
from a blank page. That creates a risk: the expert may have unconsciously accepted the machine's
framing of what matters.

You are the control. You write descriptions for the same concepts **from the course corpus alone**,
having never seen the machine drafts or the existing library. A third party then compares yours
against the existing ones on content, not wording.

**A null result is a real result.** If your descriptions turn out to say the same things as the
existing ones, that is a publishable finding that sizes the risk as small. You are not trying to
find fault, and you are not trying to agree. Write what the corpus supports.

---

## 2. What you must not see

If you encounter any of the following, **stop and tell the administrator**. The audit can survive an
honestly-reported contamination; it cannot survive a hidden one.

- Any KC draft produced by any system (Qwen, Gemma, DeepSeek, or any pipeline variant)
- The existing reference library, in any form, including quotations from it
- The `04_gold/` directory or anything derived from it
- Any evaluation result, score or ranking from this project
- The other reviewer's action codes, memos or reason codes
- `reviewer_d_stratum_key_DO_NOT_SHOW_REVIEWER.json`

**You may see:** the KC name, its position in the course hierarchy, and the course corpus.

You worked on this audit before. The 30 KCs you have now are a **fresh sample** — deliberately drawn
from units you did not write about last time, so your prior work does not compromise this round. If
you recognise one anyway, say so and it will be swapped out.

---

## 3. What you are given

For each KC, only three fields:

```
knowledge_unit_id   KC_CLF_NB_004
canonical_name      Naive Independence Assumption
hierarchy           Data Mining > Classification > Naive Bayes > Naive Independence Assumption
```

Plus full, searchable access to the four course documents.

You are **not** given a pre-selected passage set. Finding the relevant material is part of the task —
a pre-selected set would inherit the retrieval behaviour of the very system under test.

---

## 4. Procedure, per KC

**Step 1 — Search the corpus.** Find the passages that define or explain the concept. Record the
document, a locator (page or section), and a short quotation for each. If the corpus explains it in
three places, record all three. Aim for completeness.

**Step 2 — Commit a support state, before writing anything.**

| state | meaning |
|---|---|
| `SUPPORTED` | The corpus contains enough to write a correct, self-contained description. |
| `PARTIALLY_SUPPORTED` | The corpus touches the concept but is missing something definitional. |
| `UNSUPPORTED` | The corpus does not support describing this concept. |

If `UNSUPPORTED`: **stop for that KC.** Leave `reference_text` empty, fill `unsupported_reason`, and
move on. Do not write a description from your own knowledge — that is precisely the failure being
tested for. Some KCs in your sample are expected to be unsupported; finding them is a result.

**Step 3 — Write the description.** See §5.

**Step 4 — Record provenance.** For each substantive statement, note which recorded passage supports
it, via the `supports` field on the passage.

**Do not revise a KC after moving on.** If you later realise an earlier entry was wrong, add a note
rather than editing it. The audit needs your first independent judgement.

---

## 5. The description — this is where round 1 failed

**100–250 words. Prose. No bullet lists.** The validator rejects anything outside that range, and a
rejected submission has to be redone.

Your description must:

- State what the concept **is**, in a way a student could use
- Include whatever the corpus treats as **definitional** — the mechanism, the formula, the
  distinguishing contrast with a neighbouring concept
- Contain **nothing** unsupported by a passage you recorded in Step 1
- Not cite the corpus inline — provenance is recorded separately in `source_passages`

### Worked example

The example below uses an **invented concept from an unrelated field**, deliberately, so it cannot
prime you on any of your 30 KCs. Copy the *shape*, not the subject.

**Too short — this is round 1's failure mode (24 words):**

> A bedding plane is the surface separating two layers of sedimentary rock, marking a pause or change
> in deposition conditions.

That is a dictionary gloss. It states what the thing is and stops. It omits how the feature forms,
what distinguishes it from the neighbouring concept a student would confuse it with, and the
diagnostic criterion the source actually emphasises. If the existing reference happens to include
those, the comparison will record "seeded reference has more content" — which says nothing about
bias, only that you wrote less.

**Adequate — 150 words:**

> A bedding plane is the surface that separates two adjacent layers of sedimentary rock, and it marks
> an interruption or a change in the conditions under which sediment was being deposited. It forms
> when deposition pauses, when the supplied sediment changes in grain size or composition, or when a
> depositional episode ends and a new one begins, so the plane records a boundary in time as well as
> in material. Bedding planes are typically parallel to the original horizontal surface on which the
> sediment settled, which is what allows them to be used to reconstruct the original orientation of
> a rock body that has since been tilted or folded. They are distinguished from joints, which are
> fractures that cut across layers rather than separating them, and which carry no depositional
> meaning. A bedding plane is often a plane of mechanical weakness, so rock tends to split along it
> preferentially.

Note what the longer version adds: formation mechanism, the diagnostic property, an explicit
contrast with the concept it is confused with, and a consequence. **Every one of those would have to
be traceable to a recorded passage.** If the corpus does not support the contrast, leave it out and
say so in `notes` — a shorter entry justified by a thin corpus is fine, but then the support state is
probably `PARTIALLY_SUPPORTED`, not `SUPPORTED`.

If you genuinely cannot reach 100 words because the corpus is thin, that is a signal about the
corpus. Mark it `PARTIALLY_SUPPORTED`, write what is supported, and explain the shortfall in `notes`.
The validator will let a `PARTIALLY_SUPPORTED` entry run short **only if** `notes` explains why.

---

## 6. Output format

Create `independent_references/reviewer_d.jsonl`. **One JSON object per line** (this is JSONL, not a
JSON array). **Do not edit `reviewer_d_worksheet.jsonl`** — it is your input and must stay untouched.

```json
{"knowledge_unit_id": "KC_CLF_NB_004", "reviewer": "D", "support_state": "SUPPORTED", "source_passages": [{"document": "DOC_introduction_to_data_mining", "locator": "§4.3, p.147", "quote": "…", "supports": ["definition", "contrast with X"]}], "reference_text": "…100-250 words…", "unsupported_reason": null, "time_minutes": 14, "notes": ""}
```

Field notes:

- `support_state` — exactly one of `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`
- `unsupported_reason` — required if and only if `support_state` is `UNSUPPORTED`
- `time_minutes` — record honestly. It is reported as a cost figure, never as a quality signal.
- `notes` — optional, except where §5 requires it

---

## 7. Before you hand it back

```
cd 05_seed_bias_audit
python validate_reviewer_d_submission.py
```

It checks all 30 units are present with no extras, word counts are in range, support states are
valid, provenance is recorded, unsupported entries are correctly shaped, and — as a contamination
check — that your text does not overlap suspiciously with the existing library. It prints a per-unit
report and exits non-zero if anything fails. **Fix everything it flags before submitting.**

The overlap check is not an accusation. It exists so that if the material ever did leak, we would
detect it ourselves rather than have a reviewer find it later.

---

## 8. How your work will be used

A third party compares your description against the existing one for the same KC, on substantive
content only:

| label | meaning |
|---|---|
| `SUBSTANTIVELY_EQUIVALENT` | Same content, different words |
| `BOTH_VALID_DIFFERENT_FORMULATION` | Both defensible, different framing or emphasis |
| `SEEDED_REFERENCE_MISSING_CONTENT` | Yours contains definitional content the existing one lacks |
| `SEEDED_REFERENCE_EXTRA_UNSUPPORTED_CONTENT` | The existing one asserts something the corpus does not support |
| `MATERIAL_SEMANTIC_DIFFERENCE` | You disagree on what the concept is |

**No BLEU, ROUGE, edit distance or any lexical-overlap measure is used for scoring.** Wording
differences are expected and carry no information.

---

## 9. Administrator checklist

- [ ] Reviewer D has not seen `04_gold/`, any system draft, or any evaluation result
- [ ] Reviewer D received `reviewer_d_worksheet.jsonl` **only** — not the stratum key
- [ ] Worksheet confirmed blank before issue (the builder prints a blank-check; it passed)
- [ ] Sample confirmed disjoint from the units this reviewer wrote in round 1 (30 excluded)
- [ ] Corpus snapshot hash recorded: `62c4d26543ee5ac2b81fbb2d7ad772b031d18616d93334122c979d99e867bc33`
- [ ] On return: `validate_reviewer_d_submission.py` passes
- [ ] Comparison run by a third party or by the judge model, with human review of any
      `MATERIAL_SEMANTIC_DIFFERENCE`
- [ ] Round-1 artifacts retained unmodified; round 2 written to new filenames

Expect 12–20 minutes per KC — roughly 6–9 hours total, splittable across sessions.
