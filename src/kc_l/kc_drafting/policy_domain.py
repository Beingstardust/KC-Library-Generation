from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from kc_l.retrieval_gate.semantic import match_normalize

from kc_l.kc_drafting.contracts import as_text


DEFAULT_DOMAIN_POLICY_NAME = "none"
MODEL_EVALUATION_DOMAIN_POLICY_NAME = "model_evaluation_background_v1"


MODEL_EVALUATION_FAMILY_LABEL = "model evaluation and model comparison"
STATISTICAL_TEST_BACKGROUND_CUES = (
    " nemenyi test ",
    " mcnemar test ",
    " test statistic ",
    " test statistic",
    " random variable ",
    " random variable",
    " null hypothesis ",
    " p-value ",
    " significance level ",
    " critical difference ",
    " confidence interval ",
    " perform equally ",
    " performing differently ",
    " given is a random variable ",
    " follows the binomial distribution ",
    " observed number of failures ",
    " how to compare two classifiers ",
    " how to compare classification algorithms on different datasets ",
    " symmetric distribution ",
    " symmetric distribution",
    " decision rule implicitly assumes ",
    " mean=0 and variance=1 ",
    " mean _ { = 0 } ",
)
GENERIC_RECAP_BACKGROUND_CUES = (
    " classification algorithm takes as input ",
    " mutually exclusive classes ",
    " instances in each class different from the instances in the other classes ",
    " model that reflects what makes the instances in each class different ",
    " how to quantify the performance of a classifier ",
    " how to compute the performance value for a classifier ",
    " different ways of modeling classifier quality ",
)
TRAIN_TEST_SETUP_BACKGROUND_CUES = (
    " there are many ways to split ",
    " let dtest be the testset ",
    " error rate ",
    " on a test set of size ",
    " training set ",
    " test set ",
    " used for learning ",
    " used for model induction ",
    " used for model deduction ",
    " representative of the population ",
    " k-1 folds ",
    " fold di for testing ",
    " aggregate the error values ",
    " aggregate the performance values ",
    " over all k tests ",
    " equi-sized folds ",
)


@dataclass(frozen=True)
class DraftingDomainPolicy:
    name: str
    family_label: str = ""
    tolerated_background_drift_classes: tuple[str, ...] = ()
    statistical_test_background_cues: tuple[str, ...] = ()
    generic_recap_background_cues: tuple[str, ...] = ()
    train_test_setup_background_cues: tuple[str, ...] = ()

    def matches_row(self, row: Mapping[str, Any]) -> bool:
        if not self.family_label:
            return False
        return self.family_label in _row_labels(row)

    def classify_background_drift(
        self,
        *,
        row: Mapping[str, Any],
        text: str,
        quote_surface: str,
        source_block_text: str,
        anchor_strength: str,
        concept_mix_risk: str,
    ) -> str:
        if not self.matches_row(row):
            return "none"
        combined_norm = f" {_normalized_text(source_block_text or text or quote_surface)} "
        if _text_has_any_cue(combined_norm, self.statistical_test_background_cues):
            return "statistical_test_background"
        if _text_has_any_cue(combined_norm, self.generic_recap_background_cues):
            return "generic_recap"
        if _text_has_any_cue(combined_norm, self.train_test_setup_background_cues):
            return "train_test_setup_background"
        if concept_mix_risk != "single_concept" and anchor_strength != "strong":
            return "neighboring_concept_list"
        return "none"


_DOMAIN_POLICY_REGISTRY: dict[str, DraftingDomainPolicy] = {
    DEFAULT_DOMAIN_POLICY_NAME: DraftingDomainPolicy(name=DEFAULT_DOMAIN_POLICY_NAME),
    MODEL_EVALUATION_DOMAIN_POLICY_NAME: DraftingDomainPolicy(
        name=MODEL_EVALUATION_DOMAIN_POLICY_NAME,
        family_label=MODEL_EVALUATION_FAMILY_LABEL,
        tolerated_background_drift_classes=(
            "generic_recap",
            "train_test_setup_background",
            "generic_evaluation_background",
            "statistical_test_background",
        ),
        statistical_test_background_cues=STATISTICAL_TEST_BACKGROUND_CUES,
        generic_recap_background_cues=GENERIC_RECAP_BACKGROUND_CUES,
        train_test_setup_background_cues=TRAIN_TEST_SETUP_BACKGROUND_CUES,
    ),
}

_ACTIVE_DOMAIN_POLICY_NAME: ContextVar[str] = ContextVar(
    "kc_l_kc_drafting_domain_policy_name",
    default=DEFAULT_DOMAIN_POLICY_NAME,
)


def _normalize_ws(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _normalized_text(text: Any) -> str:
    return match_normalize(_normalize_ws(text or ""))


def _row_labels(row: Mapping[str, Any]) -> list[str]:
    labels = [_normalize_ws(item).lower() for item in row.get("ancestor_labels") or []]
    if labels:
        return [label for label in labels if label]
    return [_normalize_ws(item).lower() for item in row.get("source_hierarchy_path") or [] if _normalize_ws(item)]


def _text_has_any_cue(text_norm: str, cues: tuple[str, ...]) -> bool:
    return any(cue in text_norm for cue in cues)


def available_domain_policies() -> tuple[str, ...]:
    return tuple(sorted(_DOMAIN_POLICY_REGISTRY.keys()))


def normalize_domain_policy_name(value: Any) -> str:
    name = as_text(value) or DEFAULT_DOMAIN_POLICY_NAME
    if name not in _DOMAIN_POLICY_REGISTRY:
        raise RuntimeError(
            f"Unsupported Step 6.7 drafting domain policy {name!r}. "
            f"Available={list(available_domain_policies())}"
        )
    return name


def current_domain_policy_name() -> str:
    return normalize_domain_policy_name(_ACTIVE_DOMAIN_POLICY_NAME.get())


def resolve_domain_policy(name: Any | None = None) -> DraftingDomainPolicy:
    return _DOMAIN_POLICY_REGISTRY[normalize_domain_policy_name(name or current_domain_policy_name())]


@contextmanager
def drafting_domain_policy(name: Any | None) -> Iterator[DraftingDomainPolicy]:
    normalized_name = normalize_domain_policy_name(name)
    token = _ACTIVE_DOMAIN_POLICY_NAME.set(normalized_name)
    try:
        yield resolve_domain_policy(normalized_name)
    finally:
        _ACTIVE_DOMAIN_POLICY_NAME.reset(token)


def is_domain_family_member(row: Mapping[str, Any], *, policy_name: Any | None = None) -> bool:
    return resolve_domain_policy(policy_name).matches_row(row)


def classify_background_drift(
    *,
    row: Mapping[str, Any],
    text: str,
    quote_surface: str,
    source_block_text: str,
    anchor_strength: str,
    concept_mix_risk: str,
    policy_name: Any | None = None,
) -> str:
    return resolve_domain_policy(policy_name).classify_background_drift(
        row=row,
        text=text,
        quote_surface=quote_surface,
        source_block_text=source_block_text,
        anchor_strength=anchor_strength,
        concept_mix_risk=concept_mix_risk,
    )


def tolerated_background_drift_classes(*, policy_name: Any | None = None) -> tuple[str, ...]:
    return resolve_domain_policy(policy_name).tolerated_background_drift_classes
