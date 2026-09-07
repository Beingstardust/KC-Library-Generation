from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from kc_l.hierarchy.loader import KCLeafRaw
from kc_l.retrieval_profile.deterministic import content_tokens


@dataclass(frozen=True)
class ValidationIssue:
    level: str  # "ERROR" or "WARN"
    code: str
    message: str
    kc_id: str | None = None
    kc_path: list[str] | None = None


def validate_kc_leaves(kcs: Iterable[KCLeafRaw]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen_ids: set[str] = set()
    name_to_ids: dict[str, list[str]] = {}

    for kc in kcs:
        if not kc.kc_id:
            issues.append(
                ValidationIssue(
                    level="ERROR",
                    code="MISSING_KC_ID",
                    message="KC leaf missing kc_id.",
                    kc_path=kc.kc_path,
                )
            )
        else:
            if kc.kc_id in seen_ids:
                issues.append(
                    ValidationIssue(
                        level="ERROR",
                        code="DUPLICATE_KC_ID",
                        message=f"Duplicate kc_id: {kc.kc_id}",
                        kc_id=kc.kc_id,
                        kc_path=kc.kc_path,
                    )
                )
            seen_ids.add(kc.kc_id)

        if not kc.seed_definition:
            issues.append(
                ValidationIssue(
                    level="WARN",
                    code="MISSING_SEED_DEFINITION",
                    message="Seed definition is empty (input 'definition').",
                    kc_id=kc.kc_id or None,
                    kc_path=kc.kc_path,
                )
            )

        # Alias-sufficiency check: empty aliases has proven, across a full week of
        # retrieval-defect investigation on real corpora, to be one of the strongest predictors
        # of downstream retrieval failure at full-corpus scale - directly implicated in most of
        # the traced Mechanism-A cases (the KC's canonical name alone doesn't match the corpus's
        # own wording, and no alias was available to bridge that gap). A missing seed_definition
        # ALONE is already flagged above; a missing seed_definition on top of empty aliases is a
        # materially worse signal - there is then no fallback wording anywhere on the node for
        # retrieval to fall back on, and it is only otherwise discoverable via a multi-hour
        # drafting run plus manual audit. This is a structural completeness check only (are
        # these fields populated at all) - deliberately domain-agnostic, no judgment on content.
        if not kc.aliases and not kc.seed_definition:
            issues.append(
                ValidationIssue(
                    level="WARN",
                    code="EMPTY_ALIASES_AND_SEED_DEFINITION",
                    message=(
                        "Both aliases and seed_definition are empty - this KC has no alternate "
                        "wording anywhere on the node for retrieval to fall back on if the "
                        "canonical_name doesn't match the corpus's own phrasing. Strongly "
                        "correlated with retrieval failure at full-corpus scale; add at least "
                        "one alias or a seed_definition before submitting."
                    ),
                    kc_id=kc.kc_id or None,
                    kc_path=kc.kc_path,
                )
            )

        # Generic-canonical-name check: confirmed root cause of the KC_CLU_EVAL_004
        # "Separation" retrieval failure (see the week's grounding-audit follow-up). This is not
        # a correlation like the check above - it is a proven, mathematically deterministic zero.
        # score_snippet_for_kc's strong_target_binding requires either a multi-word exact/
        # stripped alias match or >=2 overlapping content tokens between the KC's label and a
        # candidate sentence. With empty aliases, deterministic_label_variants(canonical_name,
        # []) produces the canonical name as the ONLY queryable term; if that name tokenizes to
        # <=1 content token (e.g. "Separation", "Cohesion", "Overfitting", "Precision"), no
        # candidate sentence can ever satisfy strong binding, so every candidate gets
        # score = min(score, 0.0) regardless of content quality - confirmed directly against
        # production data (score_snippet_for_kc returned 0.0 for the true SSB-formula definition
        # sentence for "Separation" before its aliases were added, 20.75 after). Distinct from
        # EMPTY_ALIASES_AND_SEED_DEFINITION above because seed_definition does not help here at
        # all - the Seedless runtime rule keeps seed_definition out of live retrieval scoring
        # entirely, so a KC can pass that check (has a seed_definition) and still hit this one.
        # Kept at WARN, matching this validator's documented, relied-upon contract (see
        # loader.py's own comment: "validate_kc_leaves only WARNs ... never ERRORs") - even
        # though this is a proven deterministic failure rather than a correlation, introducing
        # a new ERROR code here would break that contract for any caller that treats has_errors
        # as a hard gate. Severity is conveyed through the message text instead.
        if not kc.aliases and len(content_tokens(kc.canonical_name)) <= 1:
            issues.append(
                ValidationIssue(
                    level="WARN",
                    code="GENERIC_CANONICAL_NAME_WITHOUT_ALIASES",
                    message=(
                        "canonical_name has <=1 content token and aliases are empty - this KC's "
                        "deterministic retrieval scoring can mathematically never satisfy "
                        "strong_target_binding (requires a multi-word alias match or >=2 "
                        "overlapping content tokens). Every candidate sentence will score 0 "
                        "regardless of content quality unless it happens to survive via the "
                        "exploratory fallback lane. Add at least one multi-word alias before "
                        "submitting - a bare synonym is not enough, it must add content tokens "
                        "beyond the canonical name itself."
                    ),
                    kc_id=kc.kc_id or None,
                    kc_path=kc.kc_path,
                )
            )

        name_to_ids.setdefault(kc.canonical_name, []).append(kc.kc_id)

    for name, ids in name_to_ids.items():
        if len(ids) > 1:
            issues.append(
                ValidationIssue(
                    level="WARN",
                    code="DUPLICATE_CANONICAL_NAME",
                    message=f"Canonical name appears multiple times: '{name}' with kc_ids={ids}",
                )
            )

    return issues


def has_errors(issues: list[ValidationIssue]) -> bool:
    return any(i.level == "ERROR" for i in issues)