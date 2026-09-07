from __future__ import annotations

import importlib.util
import os
import pathlib
import re
from typing import Any, Dict, List, Mapping, Tuple


FINAL_SCHEMA_RUNNER = pathlib.Path(os.environ["KC_L_FINAL_SCHEMA_RUNNER"])
SOURCE_SCHEMA_RUNNER = pathlib.Path(os.environ["KC_L_SOURCE_SCHEMA_RUNNER"])

if FINAL_SCHEMA_RUNNER.resolve() == SOURCE_SCHEMA_RUNNER.resolve():
    raise RuntimeError("FINAL_SCHEMA_RUNNER equals SOURCE_SCHEMA_RUNNER; refusing recursive import")

spec = importlib.util.spec_from_file_location("final_schema_runner", FINAL_SCHEMA_RUNNER)
final = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(final)

source = final.source
old_load_base_runner = source.load_base_runner

base = None
old_normalize = None
old_validate = None


def load_base_runner_policy(path):
    global base, old_normalize, old_validate
    loaded_base = old_load_base_runner(path)
    missing = [
        name for name in ["normalize_draft_from_packet", "validate_output"]
        if not hasattr(loaded_base, name)
    ]
    if missing:
        raise RuntimeError(f"Loaded base runner missing required policy hook(s): {missing}")
    base = loaded_base
    old_normalize = loaded_base.normalize_draft_from_packet
    old_validate = loaded_base.validate_output
    loaded_base.normalize_draft_from_packet = normalize_draft_from_packet_policy
    loaded_base.validate_output = validate_output_policy
    return loaded_base


source.load_base_runner = load_base_runner_policy


def _unit_type(packet: Mapping[str, Any]) -> str:
    try:
        return str(base.unit_type(packet))
    except Exception:
        return str(packet.get("knowledge_unit_type") or "")


def _canonical_name(packet: Mapping[str, Any]) -> str:
    return str(packet.get("canonical_name") or packet.get("name") or packet.get("title") or "")


def _draft_status(draft: Mapping[str, Any]) -> str:
    # confirmed a second, separate crash site beyond the normalize_draft_from_
    # packet_policy None-guard added earlier tonight - validate_output_policy (via
    # _is_valid_segmentable_abstention/_is_valid_partial_insufficient_support) also calls this
    # with a None draft for the same malformed-response packet, crashing here instead of there.
    # This is the single shared root: every caller checks _draft_status first, so guarding it
    # here directly (rather than patching each caller again) covers all present and future
    # call sites in one place.
    if not isinstance(draft, dict):
        return ""
    ck = draft.get("contextual_kc_draft")
    if isinstance(ck, dict):
        return str(ck.get("status") or "")
    return ""


def _evidence_items(packet: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    xs = packet.get("evidence_for_synthesis") or []
    return [x for x in xs if isinstance(x, dict)]


def _support_state(packet: Mapping[str, Any]) -> str:
    up = packet.get("upstream_summary") if isinstance(packet.get("upstream_summary"), dict) else {}
    return str(packet.get("packet_support_state") or up.get("packet_support_state") or "")


def _all_strings(obj: Any, limit: int = 80) -> List[str]:
    out: List[str] = []
    if isinstance(obj, str):
        s = re.sub(r"\s+", " ", obj).strip()
        if s:
            out.append(s)
    elif isinstance(obj, dict):
        for _, value in list(obj.items())[:limit]:
            out.extend(_all_strings(value, limit=limit))
    elif isinstance(obj, list):
        for value in obj[:limit]:
            out.extend(_all_strings(value, limit=limit))
    return out[:limit]


def _abstention_notes(draft: Mapping[str, Any]) -> str:
    ck = draft.get("contextual_kc_draft")
    if not isinstance(ck, dict):
        return ""
    notes = []
    notes.extend(_all_strings(ck.get("coverage_notes") or []))
    notes.extend(_all_strings(ck.get("uncertainty_notes") or []))
    return " ".join(notes).lower()


def _looks_like_insufficient_support_abstention(packet: Mapping[str, Any], draft: Mapping[str, Any]) -> bool:
    if _unit_type(packet) != "kc":
        return False
    if _draft_status(draft) != "abstained":
        return False

    ck = draft.get("contextual_kc_draft")
    if not isinstance(ck, dict):
        return False

    if str(ck.get("text") or "").strip():
        return False

    evidence_map = draft.get("evidence_map")
    if evidence_map not in (None, []):
        return False

    support_state = _support_state(packet).lower()
    if support_state in {"insufficient_support", "weak_fallback"}:
        return True

    if len(_evidence_items(packet)) == 0:
        return True

    notes = _abstention_notes(draft)
    insufficient_markers = [
        "insufficient",
        "not enough",
        "no target-bound",
        "no directly relevant",
        "not directly relevant",
        "does not provide",
        "do not provide",
        "unrelated",
        "irrelevant",
        "cannot ground",
        "cannot be grounded",
        "lacks evidence",
        "lack evidence",
        "contains no definition",
        "contains no substantive definition",
        "no substantive definition",
        "no definition",
        "no information regarding",
        "no information about",
        "no substantive",
        "lacks a cohesive explanation",
        "lacks a complete explanation",
        "lacks procedural details",
        "lacks role",
        "lacks definition",
        "lacks substantive",
        "fragmented mentions",
        "fragmented evidence",
    ]

    return any(marker in notes for marker in insufficient_markers)


# the check above only catches FULL abstention (model outputs nothing at all).
# A model that honestly attempts a short PARTIAL draft from genuinely thin evidence (status
# "partial", non-empty text, 1 or fewer cited evidence ids) still fails validate_output's
# len(text) < 180 check (see scripts/experimental/run_step67_v2_tiny_smoke.py's validate_output)
# with no path to acceptance - confirmed via a real run (KC_CLU_EVAL_007, "Models of Randomness
# (Approach 2)": 1 real evidence_for_synthesis item, model's own text 152 chars, own
# uncertainty_notes explicitly saying evidence was "extremely limited... only a fragment").
# This mirrors the existing abstention check's structure but requires ALL of several independent
# signals to agree (packet's own real evidence count - not just the model's self-report -, the
# model citing at most one evidence id, AND the model's own uncertainty language matching the
# same trusted marker vocabulary) before treating a short partial draft as tolerable, to avoid
# quietly accepting a genuinely low-effort or wrong short draft that happens to have adequate
# evidence available. Deliberately does NOT touch kc_specific_criteria_status/_source or
# evidence_map (those already passed validation for this exact failure mode) - only marks the
# draft's own uncertainty_notes so the repair is auditable, same spirit as the abstention repair
# above but without discarding the model's real (if thin) answer.
_MIN_KC_CONTEXTUAL_DRAFT_TEXT_CHARS = 180  # must track validate_output()'s own threshold exactly
_PARTIAL_INSUFFICIENT_SUPPORT_MARKER = "policy_partial_insufficient_support_repair"


def _looks_like_insufficient_partial_support(
    packet: Mapping[str, Any], draft: Mapping[str, Any], pre_repair_issues: list,
) -> bool:
    # Only ever repair the EXACT known failure mode in isolation - if any OTHER validation
    # issue is present alongside it (a real schema mismatch, missing field, etc.), never repair,
    # so a genuinely different problem can't get silently swallowed together with this one.
    issue_codes = {str(i.get("code")) for i in (pre_repair_issues or []) if isinstance(i, Mapping)}
    if issue_codes != {"kc_contextual_draft_missing_or_too_short"}:
        return False

    if _unit_type(packet) != "kc":
        return False
    if _draft_status(draft) != "partial":
        return False

    ck = draft.get("contextual_kc_draft")
    if not isinstance(ck, dict):
        return False

    text = re.sub(r"\s+", " ", str(ck.get("text") or "")).strip()
    if not text or len(text) >= _MIN_KC_CONTEXTUAL_DRAFT_TEXT_CHARS:
        return False  # empty text is the FULL-abstention case above; long enough needs no repair

    supporting_ids = ck.get("supporting_evidence_ids") or []
    if len(supporting_ids) > 1:
        return False

    # Packet's own real evidence pool - independent of the model's self-report, harder to game.
    if len(_evidence_items(packet)) > 2:
        return False

    notes = _abstention_notes(draft)
    insufficient_markers = [
        "insufficient",
        "not enough",
        "no target-bound",
        "no directly relevant",
        "not directly relevant",
        "does not provide",
        "do not provide",
        "unrelated",
        "irrelevant",
        "cannot ground",
        "cannot be grounded",
        "lacks evidence",
        "lack evidence",
        "contains no definition",
        "contains no substantive definition",
        "no substantive definition",
        "no definition",
        "no information regarding",
        "no information about",
        "no substantive",
        "lacks a cohesive explanation",
        "lacks a complete explanation",
        "lacks a detailed definition",
        "lacks a detailed explanation",
        "lacks procedural details",
        "lacks role",
        "lacks definition",
        "lacks substantive",
        "fragmented mentions",
        "fragmented evidence",
        "extremely limited",
        "only a fragment",
        "limited evidence",
    ]
    return any(marker in notes for marker in insufficient_markers)


def _repair_partial_insufficient_support(packet: Mapping[str, Any], draft: Dict[str, Any]) -> Dict[str, Any]:
    """Unlike _repair_segmentable_abstention(), this preserves the model's real partial text/
    evidence as-is - the draft is genuine, just thin - and only appends an auditable marker
    noting the policy layer reviewed and tolerated it, rather than wiping it into an abstention.
    """
    draft = dict(draft)
    ck = dict(draft.get("contextual_kc_draft") or {})
    notes = list(ck.get("uncertainty_notes") or [])
    marker_note = (
        f"{_PARTIAL_INSUFFICIENT_SUPPORT_MARKER}: retained as a genuine partial draft - the "
        "packet's own real evidence pool and the model's own uncertainty notes both "
        "independently indicate insufficient source support; flagged for expert review rather "
        "than treated as a schema failure."
    )
    if marker_note not in notes:
        notes.append(marker_note)
    ck["uncertainty_notes"] = notes
    draft["contextual_kc_draft"] = ck
    return draft


def _is_valid_partial_insufficient_support(packet: Mapping[str, Any], draft: Mapping[str, Any]) -> bool:
    if _unit_type(packet) != "kc":
        return False
    # reached directly from validate_output_policy without going through
    # _draft_status first (unlike the other callers), so it needs its own guard against a
    # None/non-dict draft - same malformed-response case documented on _draft_status above.
    if not isinstance(draft, dict):
        return False
    ck = draft.get("contextual_kc_draft")
    if not isinstance(ck, dict):
        return False
    if str(ck.get("status") or "").lower() != "partial":
        return False
    if not str(ck.get("text") or "").strip():
        return False
    notes = ck.get("uncertainty_notes") or []
    return any(_PARTIAL_INSUFFICIENT_SUPPORT_MARKER in str(n) for n in notes)


def _normalize_cue(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().strip(" |;,.:")


def _cue_is_bad(text: str) -> bool:
    text = _normalize_cue(text)
    if not text:
        return True

    low = text.lower()

    if len(text) > 220:
        return True
    if "/" in text or "\\" in text:
        return True
    if re.search(r"\b(doc_|cand_|kc_|jsonl|manifest|sha256|mineru|step4|step5|step6)\b", low):
        return True
    if re.fullmatch(r"[a-f0-9]{8,}", low):
        return True

    bad_exact = {
        "usable",
        "weak",
        "strong",
        "metadata_only",
        "source_surface_fallback",
        "fallback_surface_match",
        "definitional_anchor",
        "context_completion_anchor",
        "formula_or_parameter_anchor",
        "target_token",
        "no_target_binding",
        "candidate_pool_membership_only",
        "formula_without_target_binding",
        "example_like",
        "fragmentary",
        "broad_topic_only",
        "sibling_contrast",
        "surface:text",
        "non",
        "set",
        "generation",
    }
    return low in bad_exact


def _title_terms(name: str) -> List[str]:
    name = _normalize_cue(name)
    terms: List[str] = []
    if name:
        terms.append(name)

    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", name)
    stop = {
        "and",
        "the",
        "for",
        "with",
        "versus",
        "subclass",
        "subcategory",
        "goodness",
        "criteria",
        "product",
        "moment",
    }
    for word in words:
        if word.lower() not in stop:
            terms.append(word)

    out: List[str] = []
    seen = set()
    for term in terms:
        key = term.lower()
        if key not in seen and not _cue_is_bad(term):
            seen.add(key)
            out.append(term)
    return out


def _flatten(obj: Any, prefix: str = "") -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.append((path, value))
            if isinstance(value, (dict, list)):
                out.extend(_flatten(value, path))
    elif isinstance(obj, list):
        for i, value in enumerate(obj[:80]):
            path = f"{prefix}[{i}]"
            out.append((path, value))
            if isinstance(value, (dict, list)):
                out.extend(_flatten(value, path))
    return out


def _curate_matching_cues(packet: Mapping[str, Any], max_cues: int = 12) -> Tuple[List[str], List[Dict[str, Any]]]:
    name = _canonical_name(packet)
    cues: List[str] = []
    provenance: List[Dict[str, Any]] = []

    def add(cue: str, source: str, field_path: str, role: str) -> None:
        cue = _normalize_cue(cue)
        if _cue_is_bad(cue):
            return
        key = cue.lower()
        if key in {x.lower() for x in cues}:
            return
        cues.append(cue)
        provenance.append(
            {
                "cue": cue,
                "source": source,
                "field_path": field_path,
                "cue_role": role,
                "grounding_role": "segmentation_only_not_instructional_grounding",
            }
        )

    for term in _title_terms(name):
        add(term, "canonical_title_or_title_variant", "canonical_name", "identity")

    allowed_fragments = [
        "query_text",
        "query_used",
        "query_variants",
        "aliases",
        "deterministic_variants",
        "active_query_terms",
        "accepted_source_cues",
        "surface_form",
        "matching_cue",
    ]

    for path, value in _flatten(packet):
        path_low = path.lower()
        if not any(fragment in path_low for fragment in allowed_fragments):
            continue
        if "quote_surface" in path_low:
            continue

        for text in _all_strings(value, limit=20):
            for part in re.split(r"[|;]", text):
                add(part, "packet_profile_or_query_field", path, "profile_or_query_cue")

    return cues[:max_cues], provenance[:max_cues]


def _surface_forms(name: str, cues: List[str]) -> List[str]:
    name = _normalize_cue(name)
    forms = [
        f"What is {name}?",
        f"Can you explain {name}?",
        f"When should I use {name}?",
    ]

    for cue in cues:
        cue = _normalize_cue(cue)
        if not cue or cue.lower() == name.lower() or len(cue) > 90:
            continue
        forms.append(f"How does {cue} relate to {name}?")
        if len(forms) >= 5:
            break

    out: List[str] = []
    seen = set()
    for form in forms:
        key = form.lower()
        if key not in seen:
            seen.add(key)
            out.append(form)
    return out


def _repair_segmentable_abstention(packet: Mapping[str, Any], draft: Dict[str, Any]) -> Dict[str, Any]:
    draft = dict(draft)
    ck = draft.get("contextual_kc_draft")
    if not isinstance(ck, dict):
        ck = {}

    seg = draft.get("segmentation_support")
    if not isinstance(seg, dict):
        seg = {}

    ev = draft.get("evaluation_support")
    if not isinstance(ev, dict):
        ev = {}

    name = _canonical_name(packet)
    cues, provenance = _curate_matching_cues(packet)

    if len(cues) < 2:
        for term in _title_terms(name):
            if term.lower() not in {c.lower() for c in cues}:
                cues.append(term)
                provenance.append(
                    {
                        "cue": term,
                        "source": "canonical_title_or_title_variant",
                        "field_path": "canonical_name",
                        "cue_role": "identity",
                        "grounding_role": "segmentation_only_not_instructional_grounding",
                    }
                )
            if len(cues) >= 2:
                break

    ck["status"] = "abstained"
    ck["text"] = ""
    ck["supporting_evidence_ids"] = []
    ck["coverage_notes"] = [
        "No target-bound source evidence was available for a grounded machine-authored KC draft."
    ]
    notes = list(ck.get("uncertainty_notes") or [])
    notes.append(
        "This row is preserved for segmentation matching using title/profile cues only; those cues are not grounding evidence."
    )
    ck["uncertainty_notes"] = notes

    seg["matching_cues"] = cues
    seg["likely_dialogue_surface_forms"] = _surface_forms(name, cues)
    seg["cue_provenance"] = provenance
    seg["grounding_status"] = "segmentation_only_not_instructional_grounding"
    seg["evidence_gap_status"] = "no_target_bound_synthesis_evidence_in_checked_step67_packets"
    seg["sibling_contrast_notes"] = list(seg.get("sibling_contrast_notes") or [])
    seg["sibling_contrast_notes"].append(
        "Use only as segmentation support. Do not treat profile/title cues as source-grounded instructional evidence."
    )
    seg["do_not_confuse_with"] = list(seg.get("do_not_confuse_with") or [])

    ev["what_tutor_should_explain"] = list(ev.get("what_tutor_should_explain") or [])
    ev["common_confusions_or_errors"] = list(ev.get("common_confusions_or_errors") or [])
    ev["acceptable_teaching_moves"] = list(ev.get("acceptable_teaching_moves") or [])
    ev["red_flags"] = list(ev.get("red_flags") or [])
    ev["red_flags"].append(
        "Do not evaluate tutor correctness from this machine draft alone; no target-bound source evidence supported an instructional KC draft."
    )
    ev["grounding_status"] = "insufficient_source_support_for_instructional_evaluation"

    draft["contextual_kc_draft"] = ck
    draft["segmentation_support"] = seg
    draft["evaluation_support"] = ev
    draft["evidence_map"] = []
    draft["kc_specific_criteria"] = []
    draft["kc_specific_criteria_status"] = "requires_expert_review"
    draft["kc_specific_criteria_source"] = "not_machine_authored"

    return draft


def _is_valid_segmentable_abstention(packet: Mapping[str, Any], draft: Mapping[str, Any]) -> bool:
    if _unit_type(packet) != "kc":
        return False
    if _draft_status(draft) != "abstained":
        return False

    ck = draft.get("contextual_kc_draft")
    seg = draft.get("segmentation_support")
    ev = draft.get("evaluation_support")

    if not isinstance(ck, dict) or not isinstance(seg, dict) or not isinstance(ev, dict):
        return False

    if str(ck.get("text") or "").strip():
        return False
    if ck.get("supporting_evidence_ids"):
        return False
    if draft.get("evidence_map") != []:
        return False
    if seg.get("grounding_status") != "segmentation_only_not_instructional_grounding":
        return False
    if len(seg.get("matching_cues") or []) < 2:
        return False
    if len(seg.get("likely_dialogue_surface_forms") or []) < 2:
        return False

    return True


def normalize_draft_from_packet_policy(packet: Mapping[str, Any], draft: Dict[str, Any]):
    normalized, actions = old_normalize(packet, draft)

    # old_normalize can return a non-dict (confirmed: None, for a packet whose
    # raw model response failed to parse into any usable draft shape) - every policy check below
    # assumes a dict and crashes on None (AttributeError: 'NoneType' object has no attribute
    # 'get'), which previously took down the entire drafting job on one bad packet instead of
    # just recording that one packet's failure. Short-circuit here so this policy wrapper is a
    # no-op for that case, matching exactly what would happen without this wrapper at all - the
    # underlying parse failure is already captured elsewhere (draft/parse_error fields on the
    # output row); this wrapper's job is repairing valid-but-imperfect drafts, not inventing
    # structure for a draft that was never produced.
    if not isinstance(normalized, dict):
        return normalized, actions

    if _looks_like_insufficient_support_abstention(packet, normalized):
        normalized = _repair_segmentable_abstention(packet, normalized)
        actions = list(actions or [])
        actions.append("policy_segmentable_abstention_repair")
        return normalized, actions

    pre_repair_issues = old_validate(packet, normalized)
    if pre_repair_issues and _looks_like_insufficient_partial_support(packet, normalized, pre_repair_issues):
        normalized = _repair_partial_insufficient_support(packet, normalized)
        actions = list(actions or [])
        actions.append(_PARTIAL_INSUFFICIENT_SUPPORT_MARKER)
        return normalized, actions

    return normalized, actions


def validate_output_policy(packet: Mapping[str, Any], draft: Mapping[str, Any]):
    issues = old_validate(packet, draft)

    if issues and _is_valid_segmentable_abstention(packet, draft):
        return []

    if issues and _is_valid_partial_insufficient_support(packet, draft):
        return []

    return issues



if __name__ == "__main__":
    raise SystemExit(source.run())
