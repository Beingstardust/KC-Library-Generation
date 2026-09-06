"""Prompt construction for the reference-based judge tasks.

BLINDING IS ENFORCED HERE, not merely intended. assert_blinded() scans every assembled prompt for
model names, system names, retrieval-architecture names, machine draft-status labels, and any
indication that a machine seeded the reference. build_* functions call it before returning, so a
leak raises rather than silently reaching the judge.

Evidence is renumbered into opaque SRC_/REF_ ids at prompt-build time. The judge never sees a
native evidence id like "KC_CLF_UND_001:comprehensive:0000", which would leak both the KC id and
the retrieval lane.

No Data Mining-specific content and no per-case wording appears anywhere in this module - the
same generic instruction text is used for every KC.
"""
from __future__ import annotations

import re

SYSTEM_MESSAGE = (
    "You are a careful evaluator of educational knowledge-component descriptions. "
    "You judge only what the provided materials support. You never guess, never rely on outside "
    "knowledge beyond the provided materials, and never reward or penalize a text for its writing "
    "style, length, ordering, or vocabulary. You judge meaning, not wording. "
    "You return only the requested JSON object."
)

# Two tiers, because several system names in this project are also ordinary domain vocabulary.
#
# TIER 1 - unambiguous. These tokens have no legitimate meaning in Data Mining course text, so any
# occurrence is a leak.
_TIER1_PATTERNS = [
    r"\bqwen\b", r"\bgemma\b", r"\bdeep[\s_-]?seek\b", r"\bllama\b", r"\bselene\b",
    r"\broot[\s_-]?signals\b", r"\bmistral\b", r"\bcommand[\s_-]?r\b", r"\bgpt-?\d", r"\bclaude\b",
    r"\bdos[\s_-]?rag\b", r"\bbase[\s_-]?dense\b", r"\bcontrolled[\s_-]?comparator\b",
    r"\bablation\b", r"\bmachine[\s-]?(draft|generated|seeded)\b",
    r"KC_[A-Z]+_[A-Z]+_\d+",          # native KC ids
    r":comprehensive:\d+",            # native evidence ids
    r"\bqwen3\.?8\b", r"\bgemma4\b", r"\br9[\s_-]?(latest|final)\b",
]

# TIER 2 - context-sensitive. The bare word is legitimate domain vocabulary ("sensitivity" is a
# synonym for recall; "baseline assumption" is standard hypothesis-testing language; "originally
# proposed for regression" is ordinary English). Only the system-referring USAGE leaks identity,
# so each pattern requires an adjacent system-ish word. Verified against all 159 frozen reference
# texts and machine drafts: zero false positives, whereas the bare-word forms produced 11.
# Deliberately excludes generic academic nouns like "model", "analysis", "experiment" and
# "approach": phrases such as "a previously proposed model" and "sensitivity analysis" are ordinary
# textbook English and appear in the real corpus. Only wiring-level nouns are treated as leaks.
_SYSTEMISH = r"(system|arm|pipeline|architecture|retrieval|evidence\s+pack\w*|packet|condition|variant|configuration)"
_TIER2_PATTERNS = [
    rf"\bproposed\s+{_SYSTEMISH}\b", rf"\b{_SYSTEMISH}\s+proposed\b", r"\bthe\s+Proposed\b",
    rf"\bbaseline\s+{_SYSTEMISH}\b", rf"\b{_SYSTEMISH}\s+baseline\b",
    rf"\bsensitivity\s+{_SYSTEMISH}\b",
    rf"\bintrinsic\s+{_SYSTEMISH}\b", rf"\bextrinsic\s+{_SYSTEMISH}\b",
    rf"\b(intrinsic|extrinsic)\s+(evaluation|experiment)\b",
    r"\bdraft[\s_-]?status\b", r"\bself[\s-]?reported\s+status\b",
    r"\bstatus\s*[:=]\s*(grounded|partial|abstained)\b",
    r"\b(grounded|partial|abstained)\s+draft\b",
    # "seeded by a positive example" is genuine rule-induction vocabulary in the corpus; only
    # seeding BY A SYSTEM/DRAFT/LIBRARY is a leak.
    r"\bseeded\s+(from|by|with)\s+(a\s+|the\s+)?(machine|model|draft|library|generator|system|pipeline)\b",
    r"\bseed\s+(draft|text|library|artifact|arm)\b",
    r"\bretriev(al|er)\s+(architecture|system)\b",
]

_FORBIDDEN = [re.compile(p, re.IGNORECASE) for p in (_TIER1_PATTERNS + _TIER2_PATTERNS)]
_FORBIDDEN_PATTERNS = _TIER1_PATTERNS + _TIER2_PATTERNS  # kept for tests/introspection


class BlindingViolation(RuntimeError):
    pass


def assert_blinded(prompt: str, *, allow: tuple = ()) -> None:
    """Raise if the prompt leaks system/model identity or machine-origin signals.

    `allow` exists for the rare case where a reference or draft legitimately contains a forbidden
    word as ordinary domain text (e.g. a KC genuinely about a 'baseline' classifier). Callers must
    pass it deliberately and it is recorded in the judge row, so a blinding exemption can never be
    granted silently.
    """
    for pat in _FORBIDDEN:
        if pat.pattern in allow:
            continue
        m = pat.search(prompt)
        if m:
            raise BlindingViolation(
                f"prompt contains blinding-violating text {m.group(0)!r} (pattern {pat.pattern!r}). "
                "Renumber ids or pass an explicit allow= exemption if this is genuine domain text."
            )


def render_evidence(items: list[dict], prefix: str) -> tuple[str, dict[str, str]]:
    """Renumber evidence into opaque ids. Returns (block_text, id_map native->opaque)."""
    lines, id_map = [], {}
    for i, it in enumerate(items):
        opaque = f"{prefix}_{i:03d}"
        id_map[it.get("native_id", str(i))] = opaque
        lines.append(f"[{opaque}] {it['text'].strip()}")
    return ("\n".join(lines) if lines else "(no items provided)"), id_map


def numbered_claims(claims: list[dict]) -> str:
    return "\n".join(f"[{i}] {c['text'].strip()}" for i, c in enumerate(claims))


_FORMULA_RULE = (
    "When a claim states a mathematical relation, compare it semantically rather than by "
    "appearance: check the direction of the relation, the signs, the coefficients and constants, "
    "which quantity is in the numerator and which in the denominator, any normalization, the "
    "indices and the ranges of any summation or product, the operators, the conditions under "
    "which it applies, and how terms are aggregated. Equivalent notation for the same relation is "
    "the same relation. A different relation is a different relation even if it uses the same "
    "symbols."
)

_SEMANTIC_RULE = (
    "Judge meaning, not wording. Different vocabulary, different sentence order, different "
    "structure, and different length are NOT differences in content. Two statements that assert "
    "the same thing are the same claim."
)


def build_m1_prompt(claims: list[dict], evidence_block: str, *, allow: tuple = ()) -> str:
    p = f"""TASK: M1 EVIDENCE FAITHFULNESS

Decide, for each numbered CLAIM, whether the EVIDENCE below supports it.

EVIDENCE
{evidence_block}

CLAIMS
{numbered_claims(claims)}

For each claim assign exactly one label:
  SUPPORTED    - the evidence states or directly entails the claim.
  UNSUPPORTED  - the evidence neither states nor contradicts the claim; it is simply not there.
  CONTRADICTED - the evidence asserts something incompatible with the claim.

{_SEMANTIC_RULE}
{_FORMULA_RULE}

Judge each claim only against the EVIDENCE above. Do not use outside knowledge. Cite the evidence
ids you relied on. Return one verdict per claim, covering every claim index exactly once."""
    assert_blinded(p, allow=allow)
    return p


def build_m2_prompt(claims: list[dict], reference_block: str, source_block: str) -> str:
    p = f"""TASK: M2 REFERENCE AND SOURCE CORRECTNESS

Decide, for each numbered CLAIM, whether it is correct for this knowledge component according to
the REFERENCE DESCRIPTION and the SOURCE AUTHORITY passages.

REFERENCE DESCRIPTION
{reference_block}

SOURCE AUTHORITY
{source_block}

CLAIMS
{numbered_claims(claims)}

For each claim assign exactly one label:
  CORRECT
      The reference description states or entails this claim. Cite the REF_ id(s).
  CONTRADICTED
      The reference description asserts something incompatible with this claim. Cite the REF_ id(s).
  REFERENCE_SILENT_BUT_SOURCE_SUPPORTED
      The reference description does not address this claim, but the SOURCE AUTHORITY passages do
      support it. Cite the SRC_ id(s) that support it.
  NOT_SUPPORTED_BY_AUTHORITY
      Neither the reference description nor the source authority supports the claim. Cite nothing.

CRITICAL RULE
A claim must NOT be marked incorrect merely because its wording, its level of detail, or its
optional additional information does not appear in the reference description. The reference is one
adequate description of this knowledge component, not an exhaustive list of everything true about
it. If a claim adds correct material that the reference simply does not mention, and the source
authority supports it, the correct label is REFERENCE_SILENT_BUT_SOURCE_SUPPORTED - not
CONTRADICTED and not NOT_SUPPORTED_BY_AUTHORITY.

Use CONTRADICTED only for genuine incompatibility of content.

{_SEMANTIC_RULE}
{_FORMULA_RULE}

Return one verdict per claim, covering every claim index exactly once."""
    assert_blinded(p)
    return p


def build_m3_coverage_prompt(reference_claims: list[dict], candidate_text: str) -> str:
    p = f"""TASK: M3 REFERENCE CLAIM COVERAGE

Decide, for each numbered REFERENCE CLAIM, whether the DESCRIPTION UNDER REVIEW conveys it.

DESCRIPTION UNDER REVIEW
{candidate_text.strip()}

REFERENCE CLAIMS
{numbered_claims(reference_claims)}

For each reference claim assign exactly one label:
  PRESENT           - the description conveys this content, in any wording.
  PARTIALLY_PRESENT - the description conveys part of this content but omits a substantive part.
  ABSENT            - the description does not convey this content.

{_SEMANTIC_RULE}
{_FORMULA_RULE}

This is a descriptive coverage measurement, not a pass/fail judgment. Do not consider whether the
omission matters - only whether the content is there. Return one verdict per claim, covering every
claim index exactly once."""
    assert_blinded(p)
    return p


def build_m3_holistic_prompt(canonical_name: str, hierarchy_path: str, reference_block: str, candidate_text: str) -> str:
    p = f"""TASK: M3 CORE COMPLETENESS

KNOWLEDGE COMPONENT: {canonical_name}
LOCATION IN CURRICULUM: {hierarchy_path}

REFERENCE DESCRIPTION
{reference_block}

DESCRIPTION UNDER REVIEW
{candidate_text.strip()}

Decide whether the DESCRIPTION UNDER REVIEW contains enough of the defining content represented in
the REFERENCE DESCRIPTION to adequately identify and explain this knowledge component.

Assign exactly one label:
  CORE_COMPLETE     - a reader would come away with an adequate, correct understanding of what
                      this knowledge component is. Leave missing_defining_components empty.
  MATERIAL_OMISSION - a defining component is absent, leaving the knowledge component materially
                      underdefined. List each missing defining component.
  NOT_JUDGEABLE     - the description under review is empty or too fragmentary to assess.

DO NOT report a material omission for any of the following:
  - missing examples or illustrations
  - missing optional applications or extensions
  - missing additional detail beyond what defines the component
  - different organization, ordering, wording, or length
  - being more concise than the reference

Completeness does NOT require reproducing everything in the reference description. The reference
may contain valid enrichment beyond the minimum needed for an adequate description. Ask only
whether a DEFINING component is missing.

{_SEMANTIC_RULE}
{_FORMULA_RULE}"""
    assert_blinded(p)
    return p


def build_m4_prompt(reference_claims: list[dict], evidence_block: str) -> str:
    p = f"""TASK: M4 RETRIEVAL REFERENCE COVERAGE

Decide, for each numbered REFERENCE CLAIM, whether the EVIDENCE below contains the information
needed to support it.

EVIDENCE
{evidence_block}

REFERENCE CLAIMS
{numbered_claims(reference_claims)}

For each reference claim assign exactly one label:
  SUPPORTED_BY_RETRIEVAL     - the evidence contains this information.
  NOT_SUPPORTED_BY_RETRIEVAL - the evidence does not contain this information.

You are assessing what the evidence CONTAINS, not whether anyone used it, and not whether the
evidence is well written. {_SEMANTIC_RULE}
{_FORMULA_RULE}

Return one verdict per claim, covering every claim index exactly once."""
    assert_blinded(p)
    return p


def build_m4_holistic_prompt(canonical_name: str, hierarchy_path: str, reference_block: str, evidence_block: str) -> str:
    p = f"""TASK: M4 EVIDENCE ADEQUACY

KNOWLEDGE COMPONENT: {canonical_name}
LOCATION IN CURRICULUM: {hierarchy_path}

REFERENCE DESCRIPTION (shown only to indicate what an adequate description of this component needs)
{reference_block}

EVIDENCE AVAILABLE
{evidence_block}

Decide whether the EVIDENCE AVAILABLE contains enough material for someone to write an adequate,
correct description of this knowledge component.

Assign exactly one label:
  EVIDENCE_ADEQUATE    - the evidence contains what is needed. Leave missing_evidence_for empty.
  MATERIAL_EVIDENCE_GAP- the evidence lacks something defining, so an adequate description could
                         not be written from it alone. List what is missing.
  NOT_JUDGEABLE        - no evidence was provided or it is unintelligible.

The evidence does NOT need to contain everything in the reference description. It needs to contain
enough for an adequate description. Do not report a gap for missing examples, missing optional
detail, or evidence that is differently worded from the reference.

{_SEMANTIC_RULE}
{_FORMULA_RULE}"""
    assert_blinded(p)
    return p


def build_target_alignment_prompt(canonical_name: str, hierarchy_path: str, reference_block: str,
                                   candidate_text: str, source_block: str) -> str:
    p = f"""TASK: TARGET ALIGNMENT

INTENDED KNOWLEDGE COMPONENT: {canonical_name}
LOCATION IN CURRICULUM: {hierarchy_path}

REFERENCE DESCRIPTION OF THE INTENDED COMPONENT
{reference_block}

SOURCE AUTHORITY
{source_block}

DESCRIPTION UNDER REVIEW
{candidate_text.strip()}

First state, in your own words, what the DESCRIPTION UNDER REVIEW is centrally about, and what the
REFERENCE DESCRIPTION is centrally about. Then decide whether they describe the same knowledge
component.

Assign exactly one label:
  TARGET_ALIGNED - the description under review is centrally about the same knowledge component.
  WRONG_TARGET   - the description under review is centrally about a different concept, even if
                   what it says about that other concept is accurate and well sourced.
  NOT_JUDGEABLE  - the description under review is empty or too fragmentary to identify a subject.

A description that is entirely accurate about a NEIGHBOURING or RELATED concept is WRONG_TARGET.
Being correct about the wrong thing is still the wrong thing.

Do not decide this by counting shared words or matching terminology. A description may use
different vocabulary and still be about the same component; it may reuse the component's name and
still be centrally about something else.

Additional detail beyond the reference is not by itself wrong target."""
    assert_blinded(p)
    return p


def build_decomposition_prompt(text: str, origin_label: str, *, allow: tuple = ()) -> str:
    p = f"""TASK: CLAIM DECOMPOSITION

Break the TEXT below into its material claims - the substantive assertions it makes about the
subject.

TEXT
{text.strip()}

Rules:
  - Extract only what the text actually asserts. Do not add anything the text does not say. Do not
    infer implicit facts.
  - Do not create claims from headings, section labels, or purely stylistic phrasing.
  - Keep each mathematical relation intact as ONE claim, together with the meaning of its variables
    where losing them would make the relation uninterpretable. Never split a formula into a claim
    about its name and a separate claim about its parts.
  - Keep a procedure's steps together when splitting them would destroy the procedure's meaning.
    Separate steps are separate claims only when each stands on its own.
  - For each claim, give parent_span: the exact, verbatim, contiguous slice of the TEXT above that
    the claim came from. It must appear character-for-character in the TEXT.
  - Label each claim with the type that best fits: definition, formula, condition, procedure,
    relationship, taxonomy, factual, or other.

Return every material claim. Do not summarize and do not editorialize."""
    assert_blinded(p, allow=allow)
    return p
