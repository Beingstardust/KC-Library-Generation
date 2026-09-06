"""Claim representation for the reference-based evaluation.

Two frozen decompositions per KC per arm, never more:
  * ONE candidate material-claim decomposition, reused for M1 (faithfulness) and M2 (correctness)
  * ONE reference substantive-claim decomposition, reused for M3 (coverage) and M4 (retrieval)

Reusing one decomposition across the relations that share a claim set is a direct carry-over from
the Selene v3 development finding: independently re-deriving claims per criterion produced
criterion-specific claim sets that could not be compared to each other.

The decomposer is NOT ground truth. validate_claim_decomposition.py implements the bounded human
validation required before any decomposition is trusted (spec section 11).

This module defines no Data Mining-specific rules. Claim types are descriptive labels, not a
requirements ledger - there is deliberately no second KES here.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

CLAIM_TYPES = ("definition", "formula", "condition", "procedure", "relationship", "taxonomy", "factual", "other")

CLAIM_ORIGINS = ("candidate_draft", "reference")

# Claim types whose meaning is destroyed by over-splitting; the decomposition validator checks
# these more strictly and the prompts carry explicit preservation instructions.
STRUCTURE_SENSITIVE_TYPES = ("formula", "procedure")


class ClaimSchemaError(ValueError):
    pass


def stable_claim_id(subject_id: str, index: int) -> str:
    """Deterministic and human-readable. Stability is a tested property (tests/test_claims.py):
    the same subject and index always produce the same id regardless of process or platform."""
    return f"{subject_id}:claim:{index:03d}"


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Claim:
    claim_id: str
    text: str
    claim_type: str
    parent_span: str  # the verbatim slice of source text this claim was derived from
    subject_id: str
    origin: str

    def validate(self) -> None:
        if self.claim_type not in CLAIM_TYPES:
            raise ClaimSchemaError(f"claim_type {self.claim_type!r} not in {CLAIM_TYPES}")
        if self.origin not in CLAIM_ORIGINS:
            raise ClaimSchemaError(f"origin {self.origin!r} not in {CLAIM_ORIGINS}")
        if not self.text.strip():
            raise ClaimSchemaError(f"{self.claim_id}: empty claim text")
        if not self.parent_span.strip():
            raise ClaimSchemaError(f"{self.claim_id}: empty parent_span - every claim must retain the source text it came from")


@dataclass
class ClaimDecomposition:
    subject_id: str          # "<kc_id>" for a reference, "<kc_id>::<arm_id>" for a candidate draft
    kc_id: str
    origin: str
    source_text: str         # the exact text that was decomposed
    claims: list = field(default_factory=list)
    decomposer_model: str = ""
    decomposed_utc: str = ""
    source_text_sha256: str = ""

    def validate(self) -> None:
        if self.origin not in CLAIM_ORIGINS:
            raise ClaimSchemaError(f"origin {self.origin!r} not in {CLAIM_ORIGINS}")
        ids = [c.claim_id if isinstance(c, Claim) else c["claim_id"] for c in self.claims]
        if len(ids) != len(set(ids)):
            dupes = [i for i in ids if ids.count(i) > 1]
            raise ClaimSchemaError(f"{self.subject_id}: duplicate claim_id {sorted(set(dupes))}")
        for c in self.claims:
            (c if isinstance(c, Claim) else Claim(**c)).validate()
        if self.source_text_sha256 and self.source_text_sha256 != content_sha256(self.source_text):
            raise ClaimSchemaError(f"{self.subject_id}: source_text_sha256 does not match source_text - the decomposed text changed after decomposition")

    def freeze(self) -> dict:
        """Deterministic serialization: keys sorted, claims in claim_id order. Two runs producing
        the same claims must produce byte-identical output (tested)."""
        self.validate()
        claims = sorted(
            (asdict(c) if isinstance(c, Claim) else dict(c) for c in self.claims),
            key=lambda d: d["claim_id"],
        )
        payload = {
            "subject_id": self.subject_id,
            "kc_id": self.kc_id,
            "origin": self.origin,
            "source_text_sha256": self.source_text_sha256 or content_sha256(self.source_text),
            "n_claims": len(claims),
            "claims": claims,
            "decomposer_model": self.decomposer_model,
            "decomposed_utc": self.decomposed_utc,
        }
        payload["decomposition_sha256"] = hashlib.sha256(
            json.dumps({k: v for k, v in payload.items() if k != "decomposed_utc"},
                       sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        return payload


# ---------------------------------------------------------------------------
# Structural integrity checks used by both the automated tests and the bounded
# human decomposition validation. These are generic text-structure checks - they
# encode nothing about Data Mining.
# ---------------------------------------------------------------------------

_MATH_TOKEN = re.compile(r"[=<>≤≥±∑∏√/^]|\\frac|\\sum|\\prod|\\sqrt")


def looks_like_formula(text: str) -> bool:
    return bool(_MATH_TOKEN.search(text))


def formula_integrity_problems(decomp: ClaimDecomposition) -> list[str]:
    """Flags formula content in the source that no single claim preserves intact.

    A formula is 'preserved' if some claim contains a mathematical relation (an operator) rather
    than merely mentioning the formula's name. Splitting 'P(y|x) = P(x|y)P(y)/P(x)' into
    'there is a formula for the posterior' + 'it involves the prior' destroys the relation, and
    that is what this catches."""
    problems = []
    src_has_math = looks_like_formula(decomp.source_text)
    if not src_has_math:
        return problems
    claims = [c if isinstance(c, Claim) else Claim(**c) for c in decomp.claims]
    if not any(looks_like_formula(c.text) for c in claims):
        problems.append(
            f"{decomp.subject_id}: source text contains mathematical relation tokens but no single "
            "claim preserves one - possible meaning-destroying split"
        )
    for c in claims:
        if c.claim_type == "formula" and not looks_like_formula(c.text):
            problems.append(f"{c.claim_id}: typed 'formula' but contains no mathematical relation")
    return problems


def coverage_problems(decomp: ClaimDecomposition, min_ratio: float = 0.25) -> list[str]:
    """Very loose guard against wholesale omission: the union of claim parent_spans should account
    for a non-trivial share of the source text. Deliberately permissive - the real omission check
    is the human validation in validate_claim_decomposition.py; this only catches gross failure."""
    problems = []
    if not decomp.source_text.strip():
        return problems
    claims = [c if isinstance(c, Claim) else Claim(**c) for c in decomp.claims]
    if not claims:
        problems.append(f"{decomp.subject_id}: non-empty source text decomposed into zero claims")
        return problems
    covered = sum(len(c.parent_span) for c in claims)
    ratio = covered / max(1, len(decomp.source_text))
    if ratio < min_ratio:
        problems.append(
            f"{decomp.subject_id}: claim parent_spans cover only {ratio:.1%} of the source text "
            f"(<{min_ratio:.0%}) - possible material omission"
        )
    return problems


def invented_content_problems(decomp: ClaimDecomposition) -> list[str]:
    """Every parent_span must literally occur in the decomposed source text. A parent_span that
    is not a substring means the decomposer invented or paraphrased provenance."""
    problems = []
    src = decomp.source_text
    for c in (c if isinstance(c, Claim) else Claim(**c) for c in decomp.claims):
        if c.parent_span not in src:
            problems.append(f"{c.claim_id}: parent_span is not a literal substring of the source text")
    return problems


def all_structural_problems(decomp: ClaimDecomposition) -> list[str]:
    return (invented_content_problems(decomp)
            + formula_integrity_problems(decomp)
            + coverage_problems(decomp))
