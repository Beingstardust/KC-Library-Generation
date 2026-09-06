"""Correct the model- and domain-agnosticism definitions across paper-facing documents.

The previous pass treated both as performance-equivalence claims and withdrew them when equivalence
failed to reproduce. Both are architectural properties. This splits each into three claims -
architecture, portability, performance - and repoints every reference.

Documentation only. No artifact, no result, no reference text is touched.
"""
from pathlib import Path
import sys

D = Path(__file__).parent
BASE = D.parent
LOG = []


def fix(rel, old, new, why, required=True):
    p = (BASE / rel)
    s = p.read_text(encoding="utf-8")
    if s.count(old) != 1:
        LOG.append((rel, f"({s.count(old)} matches)", "SKIPPED", why))
        if required:
            print(f"  SKIP ({s.count(old)}) {rel}: {old[:60]}")
        return
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    LOG.append((rel, old[:90], "CORRECTED", why))
    print(f"  CORRECTED {rel}")


# ---------------------------------------------------------------- claim ledger
fix("paper_consolidation/PAPER_CLAIM_LEDGER.md",
    """### `MODEL_AGNOSTIC` — pipeline is model-agnostic
**Status:** `WITHDRAWN` as an equivalence claim; ordering retained under `DRAFT_ORDER`
**Result:** TOST at pre-registered δ=0.05 gives Qwen≡Gemma in all three domains under Selene, but in
**1 of 3** under MiniCheck; only 5 of 9 comparisons agree across instruments.
**Prohibited:** "the pipeline is model-agnostic".
**Allowed:** "Equivalence between Qwen and Gemma was observed under the primary instrument but did
not reproduce under an independent entailment verifier; the equivalence conclusion is
evaluator-dependent and margin-dependent."
**Note:** the TOST analysis is retained, not deleted. Its interpretation carries the dependence.

### `DOMAIN_TRANSFER` — cross-domain behaviour
**Status:** `SUPPORTED_WITH_SCOPE` (partial)
**Result:** data-mining and sociology fall within δ=0.05 for in-scope drafters under the primary
instrument; **mathematics is consistently harder**.
**Allowed:** "partial cross-domain transfer, with a persistent mathematics effect".
**Prohibited:** "domain-agnostic".""",
    """> **Definitional correction (2026-09-02).** Model- and domain-agnosticism are **architectural**
> properties, not performance-equivalence claims. An earlier pass conflated them and withdrew the
> architectural claim when statistical equivalence failed to reproduce. Each is now split into three
> claims: architecture, portability, and performance. See
> `MODEL_AGNOSTICISM_CONSISTENCY_AUDIT.md` and `DOMAIN_AGNOSTICISM_IMPLEMENTATION_AUDIT.md`.

### `DRAFTER_ARCHITECTURE_AGNOSTIC` — the drafter is structurally replaceable
**Status:** `SUPPORTED`
**Basis:** implementation audit. All generation flows through one `ollama_generate(host, model, …)`
call; a grep for conditionals on model identity across `v3/pipeline/*.py` returns **nothing**; the
model arrives as a CLI argument with an environment default; the single capability accommodation
(`"think": False`) is applied unconditionally with the code comment recording that it is general
rather than model-specific. All three drafters emit the same output contract.
**Allowed:** "The drafting layer is model-agnostic by architecture: the drafter is replaceable behind
a common input/output contract, and no model-family-specific logic is required by the surrounding
KC-generation pipeline."
**Prohibited:** "any LLM will work" — only the named models were exercised.

### `DRAFTER_PORTABILITY_TESTED` — three model families ran the same contract
**Status:** `SUPPORTED_WITH_SCOPE`
**Scope:** Qwen3.8-27B, Gemma4-31B, DeepSeek-R1-32B.
**Result:** nine drafter × domain cells, 1,137 drafts, all parsed under one extraction contract with
no per-model handling.
**Allowed:** "The common drafting interface was exercised without architectural modification using
Qwen3.8-27B, Gemma4-31B, and DeepSeek-R1-32B."
**Limitation:** a model unable to honour the JSON output contract would fail; one did, historically,
until the uniform `think: False` accommodation was added.

### `DRAFTER_PERFORMANCE_EQUIVALENCE` — quality is invariant to drafter choice
**Status:** `NOT_ROBUST` / `SECONDARY` — **and not required by model-agnosticism**
**Result:** TOST at pre-registered δ=0.05 gives Qwen≡Gemma in all three domains under the primary
instrument but **1 of 3** under an independent entailment verifier; 5 of 9 comparisons agree.
**Allowed:** "Substituting the drafter can change output quality; architectural portability should
not be interpreted as performance invariance." And: "The ablation shows that model choice remains
consequential even in a model-agnostic architecture."
**Prohibited:** treating this result as evidence against the architectural claim.
**Note:** the analysis is retained and renamed **drafter performance-equivalence analysis**. Its
question is how sensitive KC draft quality is to drafter choice under fixed evidence — not whether
the pipeline is model-agnostic.

### `DOMAIN_ARCHITECTURE_AGNOSTIC` — subject matter enters through data, not code
**Status:** `SUPPORTED`
**Basis:** implementation audit plus artifact verification. A 2026-08-16 audit found ~66
data-mining-specific decisions per run; remediation D-1…D-7 completed 2026-08-17, AST-verified, with
exactly one subject-vocabulary string left in executable code (a docstring example). Verified against
the **evaluated** packets: zero semantic-misbinding drops, data-mining domain-specific drops down
from ~66 to 15, and the generic math-damage detector now firing in all three domains (1/2/7) with
mathematics highest.
**Allowed:** "The KC-generation architecture is domain-agnostic: the pipeline consumes a domain
corpus and curriculum representation as inputs, while retrieval, evidence construction, support
determination, drafting, provenance, and review operate through domain-independent contracts."
Key sentence: "Domain knowledge enters through the corpus and curriculum rather than through
domain-specific implementation logic."
**Prohibited:** "proven to work equally well in every domain".
**Residual:** `compound_sibling_ownership` fires 8× in data-mining and 0× elsewhere — a data-driven
asymmetry from curriculum shape, not hardcoding, but disclose it.

### `CROSS_DOMAIN_PORTABILITY_TESTED` — one architecture, three subjects
**Status:** `SUPPORTED_WITH_SCOPE`
**Scope:** Data Mining, Mathematics, Sociology; those corpora and curriculum structures.
**Allowed:** "The same architecture was exercised on Data Mining, Mathematics, and Sociology without
introducing domain-specific pipeline variants."
**Requires (not a contradiction):** a sufficiently informative corpus, a curriculum or hierarchy, a
convertible source representation, and a compatible drafting model.

### `CROSS_DOMAIN_PERFORMANCE_EQUIVALENCE` — quality is invariant to domain
**Status:** `NOT_SUPPORTED` / `SECONDARY` — **and not required by domain-agnosticism**
**Result:** data-mining and sociology fall within δ=0.05 for in-scope drafters under the primary
instrument; mathematics is consistently harder.
**Allowed:** "Performance varied by domain, with Mathematics more difficult under the measured
groundedness criterion." And: "The architecture transferred across all three tested domains, while
performance remained domain-sensitive."
**Prohibited:** treating the mathematics result as refuting architectural domain-agnosticism.
**Note:** renamed **cross-domain performance sensitivity analysis**.""",
    "Split both agnosticism claims into architecture / portability / performance.")

# ---------------------------------------------------------------- superseded table
fix("paper_consolidation/PAPER_CLAIM_LEDGER.md",
    "| `MODEL_AGNOSTIC` | pipeline is model-agnostic | `WITHDRAWN` | `DRAFT_ORDER` |",
    "| `MODEL_AGNOSTIC` (as a performance claim) | \"drafters perform equivalently\" | `WITHDRAWN` | "
    "`DRAFTER_PERFORMANCE_EQUIVALENCE`. **The architectural claim was never withdrawn and is now "
    "`DRAFTER_ARCHITECTURE_AGNOSTIC`.** |",
    "Withdrawal applied to the performance reading only, not the architectural claim.")

# ---------------------------------------------------------------- non-claims
fix("paper_consolidation/PAPER_NONCLAIMS.md",
    "| The pipeline is model-agnostic. | Gemma >= Qwen > DeepSeek is stable in mathematics and data-mining across instruments; the equivalence result is evaluator-dependent. |",
    "| Drafter choice does not affect quality. | The architecture is model-agnostic — the drafter is "
    "replaceable behind a common contract — but substituting it **does** change output quality. "
    "Portability is not performance invariance. |\n"
    "| Any LLM will work as the drafter. | Three model families were exercised through the common "
    "interface: Qwen3.8-27B, Gemma4-31B, DeepSeek-R1-32B. |",
    "Previous non-claim denied the architectural property, which is supported.")

fix("paper_consolidation/PAPER_NONCLAIMS.md",
    "| The pipeline is domain-agnostic. | Partial cross-domain transfer, with a persistent mathematics effect. |",
    "| Domain choice does not affect quality. | The architecture is domain-agnostic — subject matter "
    "enters through corpus and curriculum, not pipeline semantics — but performance remains "
    "domain-sensitive, with mathematics measurably harder. |\n"
    "| The pipeline works equally well in every domain. | It transferred to all three tested domains "
    "without domain-specific variants; performance differed. |",
    "Previous non-claim denied the architectural property, which the implementation audit supports.")

if __name__ == "__main__":
    print("applying agnosticism corrections:")
    ok = sum(1 for r in LOG if r[2] == "CORRECTED")
    print(f"\n{ok}/{len(LOG)} applied")
