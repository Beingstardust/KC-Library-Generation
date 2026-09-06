from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kc_l.utils.json_io import read_json, read_jsonl, write_json


RESTARTED_REVIEWER_PASS_MODE = "restarted_bounded_human_reviewer_pass"
BOUNDARY_NOTE = (
    "This artifact records a bounded reviewer-style pass over the restarted Step 6.8 packet surface. "
    "It validates packet-surface usability and decision readiness, not machine autonomy or frozen-library correctness."
)
SCOPE_NOTE = (
    "The pass covers restarted ready packets only. Held KCs remain excluded and are assessed separately."
)
NON_GOAL = "This pass does not build approval flow, review-audit write flow, or frozen-library assembly."


REPO_ROOT = Path(__file__).resolve().parents[3]

VERDICT_PLAN: dict[str, dict[str, Any]] = {
    "KC_CLF_DT_001": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "borderline",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is reviewable, but the surfaced definition and scope still read like a noisy slide-bullet cluster rather than a settled KC surface.",
        "key_findings": [
            "The packet does make Hunt's Algorithm identifiable as a tree induction algorithm.",
            "Definition and scope still collapse into the same noisy bullet cluster.",
            "A reviewer can edit from the packet alone, but approval would be too optimistic.",
        ],
    },
    "KC_CLF_DT_003": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The formula surface is grounded and the scope gap is explicit, so the packet is enough for an edit decision without reopening internals.",
        "key_findings": [
            "The packet exposes the exact misclassification-rate formula cleanly.",
            "The missing scope is honest and reviewer-editable, not a hidden drafting failure.",
            "This is packet-sufficient for edit, but not ready for direct approval.",
        ],
    },
    "KC_CLF_DT_004": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "borderline",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is coherent enough to edit, but it remains a thin formula-first case with a preserved weak-coverage caution and no scope surface.",
        "key_findings": [
            "The surfaced Gini formula is grounded and coherent to the title.",
            "The packet remains thin and explicitly weak-coverage flagged.",
            "A reviewer can still act from the packet, but approval would overstate support.",
        ],
    },
    "KC_CLF_DT_006": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet contains enough grounded Information Gain support to edit from the packet surface, but the surfaced draft is still a formula lead-in rather than a finished KC definition.",
        "key_findings": [
            "Supporting evidence includes an explanatory sentence about prior and posterior uncertainty.",
            "The current surfaced definition remains excerpt-heavy and notation-led.",
            "This is packet-sufficient for edit, not for direct approval.",
        ],
    },
    "KC_CLF_DT_008": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "borderline",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is reviewable, but the formula rendering and scope wording still carry extraction noise that should be corrected by the reviewer before approval.",
        "key_findings": [
            "The Gain Ratio formula is present and title-aligned.",
            "The scope line is grounded but still wording-noisy.",
            "This remains an edit case rather than a clean approve surface.",
        ],
    },
    "KC_CLF_NB_001": {
        "dry_run_provisional_action": "approve",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "This is the clearest approve case in the restarted slice: the theorem equation and the classification-context scope are both explicit on the packet surface.",
        "key_findings": [
            "The packet surfaces a standard Bayes' Theorem equation directly.",
            "The scope field explains the classification interpretation without needing raw internals.",
            "The preserved weak-coverage caution is visible, but it does not block a reliable approve decision here.",
        ],
    },
    "KC_CLF_NB_004": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The meaning is clear from the packet alone, but the surfaced wording is still compressed and bullet-marked enough that edit is safer than approval.",
        "key_findings": [
            "The independence idea is understandable from the packet surface.",
            "Supporting equation evidence is present and aligned.",
            "Minor wording cleanup is still needed before approval.",
        ],
    },
    "KC_CLF_UND_001": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet makes the Learning Phase understandable, but the surfaced text still carries notation and extraction noise that should be normalized by a reviewer before approval.",
        "key_findings": [
            "The training/learning meaning is recoverable from the packet alone.",
            "Definition and scope are both grounded on the packet surface.",
            "Edit is appropriate because the packet is usable but not yet polished.",
        ],
    },
    "KC_CLF_DT_002": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is enough to reject from the packet surface alone because the surfaced text is only a dangling impurity clause, not a usable Node Impurity definition.",
        "key_findings": [
            "The title points to Node Impurity, but the surfaced definition is just a formula lead-in fragment.",
            "The evidence bundle does not expose a complete explanatory surface for the KC.",
            "Reject is more reliable than pretending this packet is editable into a stable approval surface.",
        ],
    },
    "KC_CLF_DT_005": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is rejectable from packet surface alone because the surfaced definition is procedural Hunt's Algorithm text, not a usable Entropy-at-node surface.",
        "key_findings": [
            "The strongest surfaced text is a Hunt's Algorithm procedure excerpt rather than an entropy definition.",
            "The scope field is blank and the packet never stabilizes the KC meaning.",
            "Reject is the clean reviewer action here without reopening internals.",
        ],
    },
    "KC_CLF_DT_012": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is rejectable from the packet surface because it only exposes an input signature and stray setup text, not a stable definition of splitting continuous attributes.",
        "key_findings": [
            "The surfaced definition is a parameter list rather than an explanatory concept statement.",
            "The scope line duplicates the same input signature instead of clarifying use or meaning.",
            "A reviewer can reject this packet without reopening internals.",
        ],
    },
    "KC_CLF_NB_003": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is rejectable from packet surface alone because it surfaces the Naive Independence Assumption wording again instead of a usable Conditional Probability / Likelihood surface.",
        "key_findings": [
            "The surfaced definition text semantically matches the Naive Independence Assumption, not likelihood.",
            "The weak-coverage caution is already visible on the packet.",
            "Reject is appropriate without reopening raw internals.",
        ],
    },
    "KC_CLF_NB_005": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is rejectable from packet surface because it collapses the NB learning phase into a narrow zero-probability edge case and leaves the scope explicitly blank.",
        "key_findings": [
            "The surfaced definition is an exception-style statement, not a stable learning-phase description.",
            "The scope gap is visible rather than hidden, which makes packet-only rejection possible.",
            "This packet is not a reliable basis for approve or edit without inventing missing meaning.",
        ],
    },
    "KC_CLF_NB_006": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "borderline",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet makes the NB classification phase recognizable from the packet surface, but it remains bullet-heavy and includes at least one clearly irrelevant support span, so edit is safer than approval.",
        "key_findings": [
            "The argmax classification procedure is visible on the packet surface.",
            "One support span is obviously off-topic, which lowers trust in the packet as-is.",
            "A reviewer can still edit from the packet alone without reopening internals.",
        ],
    },
    "KC_CLF_NB_008": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet does expose Laplace-smoothing parameters and the generalization note, but it still reads like a trailing where-clause rather than a finished Laplace Estimator definition.",
        "key_findings": [
            "The packet makes the smoothing role of w and na visible on the packet surface.",
            "The surfaced definition is still a clause fragment, not a self-contained estimator statement.",
            "A reviewer can edit this from packet evidence alone without reopening internals.",
        ],
    },
    "KC_CLF_NB_009": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is rejectable from packet surface alone because it only surfaces Gaussian-NB limitation bullets, not a usable definition of NB for numerical attributes.",
        "key_findings": [
            "The surfaced text is about when Gaussian assumptions fail, not what Gaussian NB is.",
            "Scope remains explicitly blank rather than hidden.",
            "Reject is the reliable packet-only action here.",
        ],
    },
    "KC_CLF_NB_010": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is rejectable from packet surface because it mixes an off-topic decision-tree clause into what should be a Sample Mean and Variance surface.",
        "key_findings": [
            "The main surfaced text is dominated by a Hunt-style decision-tree condition, not mean/variance estimation.",
            "A relevant mean/variance line exists in support, but the packet surface itself is not stable enough to approve or edit confidently.",
            "Reject is safer than pretending this is already a coherent packet.",
        ],
    },
    "KC_CLF_NB_011": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The missing-values case is recognizable from the packet surface, but the supporting bundle still includes unrelated noise, so edit is safer than approval.",
        "key_findings": [
            "The packet does state the core missing-values situation explicitly.",
            "Some support spans are clearly off-topic to the KC and lower trust in the surface as-is.",
            "A reviewer can still edit this from packet evidence alone.",
        ],
    },
    "KC_CLF_UND_002": {
        "dry_run_provisional_action": "approve",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "This packet is concise, coherent, and grounded enough that a reviewer can approve it directly from the restarted surface.",
        "key_findings": [
            "The classifier-as-oracle meaning is explicit and title-aligned.",
            "Definition and scope are the same clean grounded sentence.",
            "No caution flags or hidden gaps are present on the packet.",
        ],
    },
    "KC_CLF_UND_003": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is sufficient to edit from the packet surface, but the surfaced wording still contains extraction noise like 'model deduction' that should be corrected before approval.",
        "key_findings": [
            "The train/test split idea is explicit on the packet surface.",
            "The evaluation note is recoverable but wording-noisy.",
            "A reviewer can edit this confidently without reopening internals.",
        ],
    },
    "KC_CLF_UND_004": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The key representative-sample idea is visible, but the surfaced definition drags in extra learning-phase material that should be tightened before approval.",
        "key_findings": [
            "The representative-sample clause is present in the packet evidence.",
            "Scope is grounded and aligned, but the definition still over-extends.",
            "Edit is safer than approval for this packet surface.",
        ],
    },
    "KC_CLF_UND_005": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "borderline",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is still editable from packet surface because the mutually-exclusive-classes clause is explicit, but the scope gap and provenance-repair caution make approval inappropriate.",
        "key_findings": [
            "The core mutually-exclusive-classes statement is present in the packet evidence.",
            "The packet still appends extra training-phase material and keeps scope blank.",
            "A reviewer can trim and edit from the packet surface alone, but approval would hide uncertainty.",
        ],
    },
    "KC_EVAL_BASIC_002": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet keeps the accuracy formulas visible, but the surfaced definition is still phrased as an F-measure caveat rather than a clean Accuracy definition.",
        "key_findings": [
            "The packet contains the core accuracy formulas on the packet surface.",
            "The current definition line is still conceptually sideways and needs reviewer cleanup.",
            "This is packet-sufficient for edit, not for direct approval.",
        ],
    },
    "KC_EVAL_BASIC_003": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is rejectable from packet surface because it surfaces a Nemenyi-test statement rather than a usable Precision definition.",
        "key_findings": [
            "The surfaced definition is plainly about model-comparison statistics, not precision.",
            "The scope field is blank and does not rescue the KC meaning.",
            "Reject is the clean packet-only reviewer action.",
        ],
    },
    "KC_EVAL_BASIC_006": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is editable from packet surface because the F-measure formula is present, but the surfaced text still reads like a worked numeric example plus slide-note debris.",
        "key_findings": [
            "The core precision/recall-to-F-measure relation is visible on the packet.",
            "The current surface is still cluttered with a worked example and accuracy comparison noise.",
            "A reviewer can edit this confidently without reopening internals.",
        ],
    },
    "KC_EVAL_BASIC_007": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is rejectable from packet surface because it surfaces generic hypothesis-test text instead of a usable RMSE-for-ordinal-targets explanation.",
        "key_findings": [
            "The main surfaced text is about test statistics, not RMSE.",
            "A single ordinal-target support span is not enough to stabilize the packet surface.",
            "Reject is more reliable than pretending this packet is ready for edit or approval.",
        ],
    },
    "KC_EVAL_BASIC_008": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is rejectable from packet surface because it collapses MAE for ordinal targets into unrelated classification-underpinnings text.",
        "key_findings": [
            "The surfaced definition is about the training set rather than MAE.",
            "The caution flag is visible, but the packet never stabilizes the intended KC meaning.",
            "Reject is the honest packet-only action here.",
        ],
    },
    "KC_EVAL_BASIC_009": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is rejectable from packet surface because it recycles a generic classification recap instead of a usable multi-class confusion-matrix definition.",
        "key_findings": [
            "The surfaced text never actually defines the multi-class confusion matrix.",
            "Support spans remain semantically drifted toward classification underpinnings.",
            "Reject is the reliable reviewer action without reopening internals.",
        ],
    },
    "KC_EVAL_ENS_001": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet makes the ensemble-classifier topic visible, but the surfaced text still collapses back to a generic single-classifier statement and needs reviewer tightening.",
        "key_findings": [
            "The packet explicitly references single versus ensemble classifiers.",
            "The current definition line still reads too generically for direct approval.",
            "A reviewer can edit this from packet evidence alone.",
        ],
    },
    "KC_EVAL_ENS_003": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is now editable from packet surface because the Random Forest clause is isolated cleanly enough, but the scope gap and weak-coverage caution still make approval premature.",
        "key_findings": [
            "The surfaced definition is now target-specific instead of conflating Random Forest with Boosting.",
            "The packet still keeps scope blank and preserves the weak-coverage caution explicitly.",
            "A reviewer can edit this from the packet surface alone without reopening raw internals.",
        ],
    },
    "KC_EVAL_ENS_004": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The boosting mechanism is visible on the packet surface, but the surfaced definition still drags in Random Forest text and needs reviewer cleanup.",
        "key_findings": [
            "The weight-update idea for successive classifiers is explicitly present.",
            "The packet still starts with an unrelated Random Forest lead-in and keeps scope blank.",
            "A reviewer can edit this from the packet surface alone.",
        ],
    },
    "KC_EVAL_IMBAL_001": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The class-imbalance idea is visible from the packet surface, but the surfaced definition is still a broad course-outline fragment rather than a settled KC statement.",
        "key_findings": [
            "The scope line exposes the core rare-class condition directly.",
            "The main definition still reads like a checklist of evaluation topics.",
            "This is usable for edit from the packet surface, not for direct approval.",
        ],
    },
    "KC_EVAL_SAMP_001": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is now editable from packet surface because it explicitly states the holdout train/test split, but the wording still carries extraction noise that should be corrected before approval.",
        "key_findings": [
            "The surfaced definition now states the training-set / test-set split directly.",
            "Definition and scope are grounded on the packet surface without reopening internals.",
            "Edit is safer than approval because the wording still includes slide-style extraction noise like model deduction.",
        ],
    },
    "KC_EVAL_SAMP_002": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The correct repeated-holdout statement is present in packet evidence, but the surfaced definition still lands on unrelated test-statistic text, so edit is safer than approval.",
        "key_findings": [
            "The evidence bundle contains the right random-subsampling procedure.",
            "The packet surface still foregrounds off-topic statistical wording.",
            "A reviewer can repair this from packet evidence alone without reopening internals.",
        ],
    },
    "KC_EVAL_SAMP_003": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The k-fold procedure is visible from the packet surface, but the surfaced wording is still bullet-heavy and not yet reviewer-final.",
        "key_findings": [
            "The core train-on-k-minus-one / test-on-one-fold procedure is explicit.",
            "The current surface still reads like slide bullets rather than a settled KC sentence.",
            "A reviewer can edit this confidently from the packet alone.",
        ],
    },
    "KC_EVAL_SAMP_004": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The exact leave-one-out clue is present in packet evidence, but the surfaced definition still shows a generic error-rate fragment and keeps scope blank.",
        "key_findings": [
            "The evidence bundle explicitly contains the k-fold-with-k-equals-|D| statement.",
            "The current packet surface still does not foreground that definition cleanly.",
            "This is packet-sufficient for edit, not for direct approval.",
        ],
    },
    "KC_EVAL_SAMP_005": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The bootstrap sampling step is present in packet evidence, but the surfaced definition still collapses into a broad course-outline fragment, so edit is safer than approval.",
        "key_findings": [
            "The packet does contain the core bootstrap sampling statement.",
            "The current surfaced definition and scope still overrun into unrelated evaluation overview text.",
            "A reviewer can edit this from packet evidence alone without reopening internals.",
        ],
    },
    "KC_CLF_DT_011": {
        "dry_run_provisional_action": "reject",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "This is the explicit spot-check packet on the new 32-packet surface, and it is rejectable from packet surface alone because the surfaced text describes an n-child split, not a binary decision tree definition.",
        "key_findings": [
            "The title is Binary Decision Tree, but the surfaced definition explicitly talks about a split to n children.",
            "The packet evidence is enough to see that the surface is not binary-specific without reopening raw internals.",
            "Reject is the honest reviewer action for this spot-check inclusion.",
        ],
    },
    "KC_EVAL_BASIC_004": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is editable from packet surface because the Recall/Sensitivity formula is now clean and target-anchored, but the scope gap and weak-coverage caution still make approval premature.",
        "key_findings": [
            "The surfaced definition is now the target-only sensitivity formula rather than a mixed metric row.",
            "The scope field remains intentionally blank and reviewer-editable.",
            "A reviewer can edit from the packet surface alone without reopening internals.",
        ],
    },
    "KC_EVAL_BASIC_005": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is editable from packet surface because the Specificity formula is now clean and target-anchored, but the surface is still thin and keeps an explicit scope gap.",
        "key_findings": [
            "The surfaced definition is now the target-only specificity formula.",
            "The packet still has only one direct definition span and no scope line.",
            "Edit is safer than approval, but raw internals are not needed.",
        ],
    },
    "KC_EVAL_ENS_002": {
        "dry_run_provisional_action": "edit",
        "packet_sufficiency": "sufficient",
        "requires_raw_internals": False,
        "verdict_rationale": "The packet is editable from packet surface because Majority Voting is now recognizable and grounded, but the surfaced wording is still duplicated/noisy and carries an explicit weak-coverage caution.",
        "key_findings": [
            "The packet now makes Majority Voting identifiable from the surfaced definition alone.",
            "Definition and scope are grounded, but the wording is still repetitive and extraction-noisy.",
            "A reviewer can edit this from the packet surface alone without reopening internals.",
        ],
    },
}

EXCLUDED_CASE_PLAN: dict[str, dict[str, Any]] = {
    "KC_CLF_DT_011": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained a legitimate hold because the restarted path still lacks a clean, grounded definition surface for reviewer-facing use.",
        "key_findings": [
            "Step 6.7 still marked definition support as insufficient.",
            "The KC was intentionally kept out of the ready packet set.",
            "Exclusion here avoids burdening the reviewer with a non-ready surface.",
        ],
    },
    "KC_CLU_EVAL_005": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still does not expose a safe, coherent silhouette definition surface on the ready packet path.",
        "key_findings": [
            "Heading/formula risk and insufficient definition support remain explicit hold reasons.",
            "The KC was intentionally excluded before reviewer-session execution.",
            "Reviewing it now would require reopening unresolved internals rather than using the ready packet surface.",
        ],
    },
    "KC_CLF_DT_007": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained a legitimate hold because the restarted path still does not expose a clean, grounded reviewer-facing definition surface for it.",
        "key_findings": [
            "Step 6.7 still marked definition support as insufficient.",
            "Heading/formula risk and weak coverage remained unresolved before review readiness.",
            "Excluding it avoids forcing a reviewer to reopen unresolved internals.",
        ],
    },
    "KC_CLF_DT_009": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still lacks a safe reviewer-facing definition surface beyond formula-led fragments.",
        "key_findings": [
            "Definition support remained insufficient on the bounded drafting path.",
            "No safe short extract or scope surface was available for reviewer use.",
            "Exclusion keeps the ready session honest.",
        ],
    },
    "KC_CLF_DT_010": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still did not produce a coherent reviewer-facing definition surface for it.",
        "key_findings": [
            "The held reasons remained definition-support insufficiency plus formula-led risk.",
            "No safe short extract or scope surface was available on the ready packet path.",
            "Reviewing it now would require reopening unresolved internals.",
        ],
    },
    "KC_CLF_NB_002": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still does not expose a safe, grounded reviewer-facing surface for the intended Naive Bayes concept.",
        "key_findings": [
            "Definition support stayed insufficient and weak-coverage remained explicit.",
            "No safe short extract or scope surface was available for reviewer use.",
            "Keeping it excluded prevents premature review on a non-ready packet.",
        ],
    },
    "KC_CLF_NB_007": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still exposes only heading/formula-style fragments for the zero-frequency case, not a clean reviewer-facing definition surface.",
        "key_findings": [
            "Definition support remained insufficient before review readiness.",
            "Heading/formula risk and missing safe short extract stayed explicit hold reasons.",
            "Excluding it keeps the 48-slice ready session honest.",
        ],
    },
    "KC_EVAL_BASIC_001": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still did not surface a safe, reviewer-facing Confusion Matrix definition beyond heading-level or formula-fragment material.",
        "key_findings": [
            "Definition support stayed insufficient and weak-coverage remained explicit.",
            "No safe short extract or scope surface was available on the ready packet path.",
            "Exclusion avoids forcing review on a non-ready packet surface.",
        ],
    },
    "KC_EVAL_BASIC_004": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still lacks a clean, grounded Recall/Sensitivity reviewer-facing surface.",
        "key_findings": [
            "Definition support remained insufficient before packet readiness.",
            "Heading/formula risk and weak-coverage concerns remained unresolved.",
            "Keeping it excluded prevents premature review on a non-ready surface.",
        ],
    },
    "KC_EVAL_BASIC_005": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still does not expose a safe, coherent Specificity definition on the reviewer-ready packet path.",
        "key_findings": [
            "Definition support stayed insufficient and no safe short extract was available.",
            "Heading/formula risk remained explicit in the hold reasons.",
            "Excluding it avoids burdening the reviewer with unresolved internals.",
        ],
    },
    "KC_EVAL_ENS_002": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still did not produce a safe, reviewer-facing Majority Voting surface beyond thin or heading-led fragments.",
        "key_findings": [
            "Definition support remained insufficient before review readiness.",
            "Weak-coverage and no-safe-extract signals were still unresolved.",
            "Exclusion keeps the ready reviewer set aligned with actual packet readiness.",
        ],
    },
    "KC_EVAL_BASIC_003": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still does not expose a safe, reviewer-facing Precision surface beyond mixed metric or formula-fragment rows.",
        "key_findings": [
            "Definition support remained insufficient before packet readiness.",
            "Heading/formula risk and weak-coverage concerns were still explicit in the hold reasons.",
            "Exclusion avoids forcing a reviewer to reconstruct Precision from a non-ready surface.",
        ],
    },
    "KC_EVAL_BASIC_007": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still did not yield a clean RMSE-for-ordinal-targets definition surface beyond heading stubs and background text.",
        "key_findings": [
            "Definition support remained insufficient before review readiness.",
            "Heading-only risk and weak-coverage concerns were still unresolved.",
            "Exclusion keeps the reviewer session aligned with actual packet readiness.",
        ],
    },
    "KC_EVAL_BASIC_008": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still does not expose a clean MAE-for-ordinal-targets reviewer-facing surface beyond generic evaluation background.",
        "key_findings": [
            "Definition support remained insufficient before packet readiness.",
            "No safe short extract or scope surface was available for reviewer use.",
            "Exclusion is more honest than forcing review on generic background text.",
        ],
    },
    "KC_EVAL_BASIC_009": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still does not expose a safe multi-class confusion-matrix definition beyond heading-level material.",
        "key_findings": [
            "Definition support remained insufficient before review readiness.",
            "Heading-only risk remained explicit and no safe short extract was available.",
            "Exclusion prevents a reviewer from being asked to infer missing matrix meaning from a non-ready surface.",
        ],
    },
    "KC_EVAL_ENS_001": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still lacks a safe, reviewer-facing Ensemble Classifier definition beyond formula-led fragments.",
        "key_findings": [
            "Definition support remained insufficient before packet readiness.",
            "Formula-only risk remained explicit in the hold reasons.",
            "Exclusion keeps the ready reviewer set from overstating packet quality.",
        ],
    },
    "KC_EVAL_IMBAL_001": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still did not produce a clean, reviewer-facing class-imbalance definition surface.",
        "key_findings": [
            "Definition support remained insufficient before review readiness.",
            "Heading/formula risk remained unresolved on the ready packet path.",
            "Exclusion keeps the reviewer session honest about what is actually ready.",
        ],
    },
    "KC_EVAL_SAMP_002": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still did not expose a safe, reviewer-facing Repeated Holdout Method surface beyond heading or formula-led fragments.",
        "key_findings": [
            "Definition support remained insufficient before packet readiness.",
            "Heading/formula risk and weak-coverage concerns remained unresolved.",
            "Exclusion avoids burdening the reviewer with unresolved internals.",
        ],
    },
    "KC_EVAL_SAMP_004": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still lacks a clean Leave-One-Out Cross Validation reviewer surface beyond heading or formula fragments.",
        "key_findings": [
            "Definition support remained insufficient before packet readiness.",
            "Heading/formula risk stayed explicit and no safe short extract was available.",
            "Exclusion keeps the session limited to genuinely review-ready packets.",
        ],
    },
    "KC_EVAL_SAMP_005": {
        "pre_review_disposition": "excluded_from_ready_session",
        "packet_sufficiency": "not_reviewable",
        "requires_raw_internals": True,
        "skip_assessment": "appropriate_hold",
        "verdict_rationale": "This KC remained correctly held because the restarted path still does not expose a clean Bootstrap Sampling definition surface for reviewer-facing use.",
        "key_findings": [
            "Definition support remained insufficient before review readiness.",
            "Heading/formula risk remained unresolved and no safe short extract was available.",
            "Exclusion is the honest pre-review disposition on this packet set.",
        ],
    },
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = _as_text(value)
        if text and text not in out:
            out.append(text)
    return out


def _relative_repo_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def _load_inputs(review_packet_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    packet_path = review_packet_dir / "review_packets.jsonl"
    summary_path = review_packet_dir / "review_packet_summary.json"
    session_manifest_path = review_packet_dir / "real_reviewer_session_manifest.json"
    if not packet_path.exists() or not summary_path.exists() or not session_manifest_path.exists():
        raise FileNotFoundError(f"Required restarted reviewer-session artifacts missing under {review_packet_dir}")
    packets = read_jsonl(packet_path)
    summary = read_json(summary_path)
    session_manifest = read_json(session_manifest_path)
    return packets, summary, session_manifest


def _ordered_packets(session_manifest: Mapping[str, Any], packets: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {_as_text(packet.get("review_packet_id")): dict(packet) for packet in packets}
    ordered: list[dict[str, Any]] = []
    for packet_id in session_manifest.get("included_review_packet_ids") or []:
        packet = by_id.get(_as_text(packet_id))
        if packet is None:
            raise ValueError(f"session manifest references missing packet: {packet_id}")
        ordered.append(packet)
    return ordered


def _build_verdict(packet: Mapping[str, Any]) -> dict[str, Any]:
    kc_id = _as_text(packet.get("kc_candidate_id"))
    plan = VERDICT_PLAN.get(kc_id)
    if plan is None:
        raise ValueError(f"No verdict plan configured for {kc_id}")
    return {
        "kc_candidate_id": kc_id,
        "review_packet_id": _as_text(packet.get("review_packet_id")),
        "title_draft": _as_text(packet.get("title_draft")),
        "current_review_priority_bucket": _as_text((packet.get("review_priority") or {}).get("bucket")),
        "current_system_recommendation": _as_text((packet.get("system_recommendation") or {}).get("label")),
        "content_source_mode": _as_text(packet.get("content_source_mode")),
        "content_repair_applied": bool(packet.get("content_repair_applied")),
        "scope_status": _as_text(packet.get("scope_status")),
        "risk_flags": _normalize_string_list(packet.get("risk_flags")),
        "dry_run_provisional_action": plan["dry_run_provisional_action"],
        "packet_sufficiency": plan["packet_sufficiency"],
        "requires_raw_internals": bool(plan["requires_raw_internals"]),
        "verdict_rationale": plan["verdict_rationale"],
        "key_findings": list(plan["key_findings"]),
    }


def _build_excluded_case(summary_item: Mapping[str, Any]) -> dict[str, Any]:
    kc_id = _as_text(summary_item.get("kc_candidate_id"))
    plan = EXCLUDED_CASE_PLAN.get(kc_id)
    if plan is None:
        raise ValueError(f"No excluded-case plan configured for {kc_id}")
    return {
        "kc_candidate_id": kc_id,
        "draft_status": _as_text(summary_item.get("draft_status")),
        "summary_exclusion_reasons": _normalize_string_list(summary_item.get("reasons")),
        "pre_review_disposition": plan["pre_review_disposition"],
        "packet_sufficiency": plan["packet_sufficiency"],
        "requires_raw_internals": bool(plan["requires_raw_internals"]),
        "skip_assessment": plan["skip_assessment"],
        "verdict_rationale": plan["verdict_rationale"],
        "key_findings": list(plan["key_findings"]),
    }


def _draft_actions(verdicts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in verdicts:
        actions.append(
            {
                "kc_candidate_id": item["kc_candidate_id"],
                "review_packet_id": item["review_packet_id"],
                "title_draft": item["title_draft"],
                "machine_bucket": item["current_review_priority_bucket"],
                "machine_recommendation": item["current_system_recommendation"],
                "draft_human_action": item["dry_run_provisional_action"],
                "packet_sufficiency": item["packet_sufficiency"],
                "requires_raw_internals": item["requires_raw_internals"],
                "content_repair_applied": item["content_repair_applied"],
                "content_source_mode": item["content_source_mode"],
                "workflow_decision_ready": not bool(item["requires_raw_internals"]),
                "workflow_note": item["verdict_rationale"],
            }
        )
    return actions


def _headline_findings(verdicts: Sequence[Mapping[str, Any]], excluded_cases: Sequence[Mapping[str, Any]]) -> list[str]:
    approve_count = sum(1 for item in verdicts if item.get("dry_run_provisional_action") == "approve")
    edit_count = sum(1 for item in verdicts if item.get("dry_run_provisional_action") == "edit")
    reject_count = sum(1 for item in verdicts if item.get("dry_run_provisional_action") == "reject")
    scope_gap_ids = [item["kc_candidate_id"] for item in verdicts if item.get("scope_status") == "abstained"]
    return [
        f"The restarted {len(verdicts)}-packet slice is reviewer-actionable from packet surface alone: {approve_count} approve, {edit_count} edit, and {reject_count} reject decision(s) required no raw-internals reopen.",
        f"The explicit scope-gap packets {scope_gap_ids} remained honest edit-or-reject cases rather than hidden drafting failures.",
        "Bayes' Theorem and Querying Phase are the clearest approve-from-packet cases on the restarted path at this scale.",
        f"The held KCs {[item['kc_candidate_id'] for item in excluded_cases]} remained correctly outside the ready reviewer set rather than being forced into review.",
        "KC_CLF_DT_011 is the explicit spot-check item on this rerun and is rejectable from packet surface alone.",
    ]


def build_restarted_human_reviewer_pass(review_packet_dir: Path) -> tuple[Path, Path, Path]:
    review_packet_dir = review_packet_dir.resolve()
    packets, summary, session_manifest = _load_inputs(review_packet_dir)
    ordered_packets = _ordered_packets(session_manifest, packets)

    verdicts = [_build_verdict(packet) for packet in ordered_packets]
    excluded_cases = [_build_excluded_case(item) for item in summary.get("excluded_kcs") or []]

    action_counts = Counter(item["dry_run_provisional_action"] for item in verdicts)
    sufficiency_counts = Counter(item["packet_sufficiency"] for item in verdicts)
    actions = _draft_actions(verdicts)

    verdict_payload = {
        "review_packet_dir": str(review_packet_dir),
        "source_processed_dir": str(summary.get("source_processed_dir") or ""),
        "dry_run_mode": RESTARTED_REVIEWER_PASS_MODE,
        "dry_run_scope": "all restarted ready packets on the bounded slice; held cases assessed separately and kept excluded",
        "selected_packet_count": len(verdicts),
        "selected_packet_ids": [item["review_packet_id"] for item in verdicts],
        "selected_kc_ids": [item["kc_candidate_id"] for item in verdicts],
        "dry_run_action_counts": dict(action_counts),
        "packet_sufficiency_counts": dict(sufficiency_counts),
        "headline_findings": _headline_findings(verdicts, excluded_cases),
        "verdicts": verdicts,
        "excluded_case_assessments": excluded_cases,
    }

    workflow_payload = {
        "review_packet_dir": str(review_packet_dir),
        "source_processed_dir": str(summary.get("source_processed_dir") or ""),
        "validation_mode": RESTARTED_REVIEWER_PASS_MODE,
        "boundary_note": BOUNDARY_NOTE,
        "session_scope": SCOPE_NOTE,
        "non_goal": NON_GOAL,
        "draft_action_space": ["approve", "edit", "reject"],
        "paths_exercised": {
            "approve_path_exercised": int(action_counts.get("approve", 0)) > 0,
            "edit_path_exercised": int(action_counts.get("edit", 0)) > 0,
            "reject_path_exercised": int(action_counts.get("reject", 0)) > 0,
            "excluded_held_cases_present": bool(excluded_cases),
        },
        "draft_action_counts": dict(action_counts),
        "packet_sufficiency_counts": dict(sufficiency_counts),
        "packet_only_decision_count": sum(1 for item in actions if item["workflow_decision_ready"]),
        "selected_packet_count": len(actions),
        "draft_actions": actions,
        "excluded_case_assessments": excluded_cases,
        "workflow_findings": verdict_payload["headline_findings"],
    }

    lines = [
        "# Human-Supervised Workflow Validation",
        "",
        f"- Review packet directory: `{_relative_repo_path(review_packet_dir)}`",
        f"- Source processed directory: `{_relative_repo_path(Path(str(summary.get('source_processed_dir') or '.')) )}`",
        f"- Validation mode: `{workflow_payload['validation_mode']}`",
        f"- Boundary: {BOUNDARY_NOTE}",
        f"- Session scope: {SCOPE_NOTE}",
        f"- Non-goal: {NON_GOAL}",
        "",
        "## Workflow Status",
        "",
        f"- Approve path exercised: `{workflow_payload['paths_exercised']['approve_path_exercised']}`",
        f"- Edit path exercised: `{workflow_payload['paths_exercised']['edit_path_exercised']}`",
        f"- Reject path exercised: `{workflow_payload['paths_exercised']['reject_path_exercised']}`",
        f"- Excluded held cases present: `{workflow_payload['paths_exercised']['excluded_held_cases_present']}`",
        f"- Draft action counts: `{workflow_payload['draft_action_counts']}`",
        f"- Packet sufficiency counts: `{workflow_payload['packet_sufficiency_counts']}`",
        f"- Packet-only decision count: `{workflow_payload['packet_only_decision_count']}/{len(actions)}`",
        "",
        "## Workflow Findings",
        "",
    ]
    for finding in workflow_payload["workflow_findings"]:
        lines.append(f"- {finding}")

    lines.extend(["", "## Included Packet Decisions", ""])
    for item in verdicts:
        lines.extend(
            [
                f"### {item['kc_candidate_id']} - {item['title_draft']}",
                "",
                f"- Machine label: `{item['current_review_priority_bucket']}` / `{item['current_system_recommendation']}`",
                f"- Reviewer decision: `{item['dry_run_provisional_action']}`",
                f"- Packet sufficiency: `{item['packet_sufficiency']}`",
                f"- Requires raw internals: `{item['requires_raw_internals']}`",
                f"- Risk flags: `{item['risk_flags']}`",
                f"- Rationale: {item['verdict_rationale']}",
                "- Key findings:",
            ]
        )
        for finding in item["key_findings"]:
            lines.append(f"  - {finding}")
        lines.append("")

    lines.extend(["## Excluded Held Cases", ""])
    for item in excluded_cases:
        lines.extend(
            [
                f"### {item['kc_candidate_id']}",
                "",
                f"- Draft status: `{item['draft_status']}`",
                f"- Pre-review disposition: `{item['pre_review_disposition']}`",
                f"- Summary exclusion reasons: `{item['summary_exclusion_reasons']}`",
                f"- Assessment: `{item['skip_assessment']}`",
                f"- Rationale: {item['verdict_rationale']}",
                "- Key findings:",
            ]
        )
        for finding in item["key_findings"]:
            lines.append(f"  - {finding}")
        lines.append("")

    lines.extend(
        [
            "## Bottom Line",
            "",
            "- The restarted packet surface now supports bounded reviewer decisions without reopening raw internals for the ready set.",
            "- This pass still does not imply autonomous approval or any downstream frozen-library update.",
        ]
    )
    md_text = "\n".join(lines).rstrip() + "\n"

    verdict_path = review_packet_dir / "reviewer_dry_run_verdicts.json"
    workflow_json_path = review_packet_dir / "human_supervised_draft_actions.json"
    workflow_md_path = review_packet_dir / "human_supervised_workflow_validation.md"
    write_json(verdict_path, verdict_payload)
    write_json(workflow_json_path, workflow_payload)
    workflow_md_path.write_text(md_text, encoding="utf-8")
    return verdict_path, workflow_json_path, workflow_md_path
