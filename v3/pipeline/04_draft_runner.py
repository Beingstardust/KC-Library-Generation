from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, NamedTuple, Tuple

from kc_l.kc_drafting.status_integrity import (
    apply_status_integrity_gate, UNJUSTIFIED_ABSTENTION_CODE)
from kc_l.kc_drafting.draft_hygiene import body_describes_its_evidence
from kc_l.retrieval_gate.evidence_pack import draft_math_rendering_damaged


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def norm(x: Any) -> str:
    return re.sub(r"\s+", " ", str(x or "")).strip()


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def write_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def read_jsonl(path: pathlib.Path) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    invalid = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    invalid += 1
            except Exception:
                invalid += 1
    return rows, invalid


def write_jsonl(path: pathlib.Path, rows: List[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def unit_id(packet: Mapping[str, Any]) -> str:
    return str(packet.get("knowledge_unit_id") or packet.get("kc_id") or packet.get("topic_id") or "")


def unit_type(packet: Mapping[str, Any]) -> str:
    return str(packet.get("knowledge_unit_type") or "")


def canonical_name(packet: Mapping[str, Any]) -> str:
    return norm(packet.get("canonical_name"))


def compact_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


# A source's own cross-references, including multi-reference lists ("Tables 4.1 and 4.2").
# Structural only: a generic document-part word followed by numbering.
_POINTER_NUMS = r"\s*\d+(?:\.\d+)*(?:\s*\([a-z]\))?(?:\s*(?:,|and)\s*\d+(?:\.\d+)*(?:\s*\([a-z]\))?)*"
_SOURCE_POINTER_SUBS = (
    (re.compile(r"\b(tables?)" + _POINTER_NUMS, re.I), ("the table", "the tables")),
    (re.compile(r"\b(figures?|fig\.)" + _POINTER_NUMS, re.I), ("the figure", "the figures")),
    (re.compile(r"\b(algorithms?)" + _POINTER_NUMS, re.I), ("the algorithm", "the algorithms")),
    (re.compile(r"\b(equations?|eqs?\.)" + _POINTER_NUMS, re.I), ("the equation", "the equations")),
    (re.compile(r"\b(sections?)" + _POINTER_NUMS, re.I), ("that section", "those sections")),
    (re.compile(r"\b(chapters?)" + _POINTER_NUMS, re.I), ("that chapter", "those chapters")),
    (re.compile(r"\b(appendix|appendices)\s*[A-Z0-9]+(?:\.\d+)*", re.I), ("the appendix", "the appendices")),
)
_BRACKET_CITATION_RE = re.compile(r"\s*\[\d{1,4}\]")
_TRAILING_EQ_NUMBER_RE = re.compile(r"\s*\(\s*\d+\.\d+\s*\)\s*$")
# An attribution phrase whose target has just been removed ("..., based on ." -> "...").
_DANGLING_ATTRIBUTION_RE = re.compile(
    r"[,;]?\s*\b(?:based on|according to|per|following|taken from|adapted from|see(?: also)?|cf\.)"
    r"\s*(?=[.,;:]|$)", re.I)


def _pointer_replacement(match, forms):
    """Keep singular/plural agreement with the word the source actually used."""
    head = match.group(1).lower()
    plural = head.endswith("s") and not head.endswith("ss") and head not in {"fig.", "eqs."}
    plural = plural or head == "appendices" or bool(re.search(r"(?:,|and)\s*\d", match.group(0)))
    return forms[1] if plural else forms[0]


def neutralize_source_pointers(text: str) -> str:
    """Strip the source document's own numbering from text shown to the model.

    Pointers become plain-language equivalents so grammar survives ("in Figure 3.7" -> "in the
    figure"), multi-reference lists collapse to one phrase, bracketed citation markers are
    removed, and an attribution phrase left pointing at nothing goes with them. The model cannot
    copy a number it never sees, which makes this a hard guarantee rather than an instruction it
    may ignore.
    """
    out = str(text or "")
    for pattern, forms in _SOURCE_POINTER_SUBS:
        out = pattern.sub(lambda m, _f=forms: _pointer_replacement(m, _f), out)
    out = _BRACKET_CITATION_RE.sub("", out)
    out = _DANGLING_ATTRIBUTION_RE.sub("", out)
    out = _TRAILING_EQ_NUMBER_RE.sub("", out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    return re.sub(r"\s{2,}", " ", out).strip()


_PROMPT_TEXT_FIELDS = ("text", "source_block_text", "patch_heading")


def prompt_safe_packet(packet: Mapping[str, Any]) -> Dict[str, Any]:
    """A copy of the packet with source pointers neutralized in evidence text.

    The stored packet is left untouched so evidence stays verbatim for provenance and for any
    downstream grounding check that compares a draft against its source text.
    """
    safe = dict(packet)
    for key in ("evidence_for_synthesis", "child_kc_summaries", "topic_evidence"):
        items = packet.get(key)
        if not isinstance(items, list):
            continue
        cleaned = []
        for item in items:
            if not isinstance(item, Mapping):
                cleaned.append(item)
                continue
            entry = dict(item)
            for field in _PROMPT_TEXT_FIELDS:
                if isinstance(entry.get(field), str):
                    entry[field] = neutralize_source_pointers(entry[field])
            cleaned.append(entry)
        safe[key] = cleaned
    return safe


def visible_packet_for_prompt(packet: Mapping[str, Any], mode: str) -> Dict[str, Any]:
    """The packet copy actually serialized into the model prompt for the given mode.

    "native_proposed" (default, unchanged production behavior) serializes everything
    prompt_safe_packet returns, including drafting_instruction when the packet carries it.
    "controlled_comparator" additionally drops drafting_instruction from this copy only - the
    stored/on-disk packet (and prompt_safe_packet's own dict(packet) copy) is never touched, so
    this never mutates a historical artifact. Exists because drafting_instruction is fully
    serialized into the prompt even though build_prompt's own instructional text never names it
    - a real generator-side confound for a Base Dense RAG / DOS-RAG / Proposed comparison, since
    only the proposed pipeline's packet builder attaches this field. See
    14_FINAL_GENERATOR_CONTRACT_FAIRNESS.md and 15_CONTROLLED_COMPARATOR_PROMPT_FIX.md.
    """
    safe = prompt_safe_packet(packet)
    if mode == "controlled_comparator":
        safe = {k: v for k, v in safe.items() if k != "drafting_instruction"}
    return safe


def build_prompt(packet: Mapping[str, Any], *, mode: str = "native_proposed") -> str:
    """mode="native_proposed" (default) is byte-identical to this function's behavior before the
    2026-08-17 controlled-comparator fairness fix - every existing caller (the wrapper script's
    getattr-dispatched call, any repair-prompt call) is unaffected. mode="controlled_comparator"
    is for the primary Base Dense RAG / DOS-RAG / Proposed experiment only; see
    visible_packet_for_prompt and 15_CONTROLLED_COMPARATOR_PROMPT_FIX.md.
    """
    if mode not in ("native_proposed", "controlled_comparator"):
        raise ValueError(f"unknown build_prompt mode: {mode!r}")
    utype = unit_type(packet)

    # v43b: the abstention-does-not-exempt-structure instruction differs by unit type - a topic
    # unit's schema has no segmentation_support field at all (only evaluation_support) and uses
    # contextual_topic_draft, not contextual_kc_draft. Built once, utype-aware, before `common`.
    if utype == "kc":
        _abstention_structure_note = (
            "An abstention on contextual_kc_draft is a decision about the descriptive TEXT only, not about segmentation_support or evaluation_support. segmentation_support "
            "(matching_cues, likely_dialogue_surface_forms, sibling_contrast_notes, do_not_confuse_with) must still be filled for EVERY unit regardless of status: derive "
            "these from canonical_name, aliases, hierarchy, sibling_kc_names, and rival_units_considered, which are always present on the packet whether or not there is "
            "enough evidence for a full draft - this is not inventing content, it is naming this unit and its real relationship to other real units in the same library. For "
            "evaluation_support, use any evidence the packet does contain even if it was insufficient for a full draft; where a specific field truly has nothing the packet "
            "supports, leave that list empty rather than inventing a claim - never fabricate a pedagogical claim the packet does not support.\n"
        )
    else:
        _abstention_structure_note = (
            "An abstention on contextual_topic_draft is a decision about the descriptive TEXT only, not about segmentation_support or evaluation_support. "
            "segmentation_support (topic_matching_cues, child_kc_boundary_cues, do_not_confuse_with_topics) must still be filled regardless of status: derive these "
            "from canonical_name, aliases, hierarchy, sibling_kc_names, and rival_units_considered, which are always present on the packet whether or not there is "
            "enough evidence for a full draft - this is not inventing content, it is naming this topic and its real relationship to other real units in the same "
            "library. For evaluation_support, use any evidence the packet does contain even if it was insufficient for a full draft; where a specific field truly has "
            "nothing the packet supports, leave that list empty rather than inventing a claim - never fabricate a pedagogical claim the packet does not support.\n"
        )

    common = (
        "You are drafting a grounded Knowledge Library unit for downstream dialogue segmentation, "
        "AI tutor evaluation, and expert review.\n\n"
        "Do not output chain-of-thought. Reason internally, then output only valid JSON.\n"
        "Use only the provided packet. Do not invent facts.\n"
        "Every substantive claim must be linked to evidence IDs or child KC IDs in evidence_map.\n"
        "Cite evidence ONLY through the evidence_map/supporting_evidence_ids fields. Never copy a raw "
        "identifier (e.g. \"cand_...\", \"KC_...:step5_4:...\", \"hier::path::...\"), a bare bracketed "
        "citation number (e.g. \"[12]\"), or a reference to the source document's own Equation/Figure/"
        "Table/Section/Chapter number into any draft text field - write self-contained prose instead.\n"
        "Do not accept fragments as complete drafts.\n"
        # controlled-comparator prompt-fairness fix. This paragraph, and every other
        # block below marked with the same date, moves task-general behavioral rules that used to
        # live only in the proposed pipeline's own drafting_instruction packet field (attached by
        # 02_build_kc_packets.py; real, validated fixes for real audited drafting failures -
        # commits 5c35a90/04a488f/7efabb7 - not leftover text from any retired pipeline) into this
        # shared prompt, so a comparator whose packet builder never attaches that field still
        # receives the same task methodology. None of these rules depend on shape_tags,
        # assertability, authority_tier, relevance, or any other proposed-only evidence-item
        # field. See 14_FINAL_GENERATOR_CONTRACT_FAIRNESS.md and
        # 15_CONTROLLED_COMPARATOR_PROMPT_FIX.md.
        "Before writing any prose: sort the supplied passages into what directly establishes THIS "
        "unit, what is useful background, what principally belongs to a sibling or rival unit named "
        "in sibling_kc_names/rival_units_considered, and what is not assertable as fact (a question, "
        "an exercise prompt, a hypothetical, or a statement posed for the reader to evaluate rather "
        "than a stated fact).\n"
        "Fill evidence_map FIRST, before writing any prose: each entry is one atomic claim you "
        "intend to make, tied to the evidence_id values that establish it. This ledger is the "
        "support set, not a citation list assembled afterwards. Write the draft using only claims "
        "already in the ledger; if a sentence has no ledger entry, add the entry with its real "
        "evidence_id or do not write the sentence.\n"
        "After drafting, re-read every substantive sentence against the supplied passages: remove "
        "or weaken anything the passages do not support, anything whose real subject is a sibling "
        "or rival unit, and anything that contradicts another statement in your own draft.\n"
        "STATUS is a claim about completeness relative to the EVIDENCE YOU WERE GIVEN, not about how much evidence existed or how confident you feel. Decide it with this test, in order:\n"
        "1. If the evidence supports nothing usable for THIS unit specifically - it is about a sibling, a different branch, or only the general category - status is abstained. This is covered above; do not also apply it here.\n"
        "2. Otherwise: does the draft state EVERY element the evidence itself supports, per the completeness checklist below (where an item's shape metadata marks it a formula, the formula must be written out; where it marks a procedure, the steps must be stated), with every claim evidence-linked? If yes, status is GROUNDED - regardless of length. A two-sentence draft built from two sentences of evidence is grounded if it omits nothing those two sentences offered. Thin evidence, faithfully and completely used, is grounded, not partial.\n"
        "3. status is PARTIAL only when you are knowingly leaving out or hedging something the evidence DOES support: a formula you could not reconstruct cleanly from a garbled rendering, procedure steps given out of order or incompletely, or a genuine ambiguity in the source you cannot resolve. When you use partial, uncertainty_notes must name EXACTLY what is missing or uncertain and why - not a general hedge. \"The evidence is thin\" is never by itself a reason for partial; thin-but-complete is grounded. If you cannot name a specific gap, the status is grounded, not partial.\n"
        "If the packet explicitly declares insufficient_synthesis_support or abstention_expected, abstain instead of inventing unsupported content.\n"
        "For an allowed abstention, keep contextual text empty, keep evidence_map empty, and explain the uncertainty in uncertainty_notes.\n"
        + _abstention_structure_note +
        # Relevance self-check. Every field named below already exists in the packet
        # (sibling_kc_names and hierarchy are populated on 159/159 KC packets in the audited run)
        # and is already serialized into this prompt; no instruction referenced them, so the model
        # had nothing telling it to cross-check evidence against them. Stated purely over packet
        # field names so it carries no domain vocabulary.
        "The evidence may be well-formed and clearly written and still be about a DIFFERENT concept "
        "than the unit you are drafting. Completeness of the evidence is not proof that it is on-target.\n"
        "Before drafting, check the evidence against fields already in this packet:\n"
        "- If the evidence defining subject is a term listed in sibling_kc_names rather than this "
        "unit own canonical_name, do not restate it under this unit. Set status to abstained and "
        "name the conflicting sibling in uncertainty_notes.\n"
        "- If the evidence belongs to a different branch than hierarchy.source_hierarchy_path "
        "indicates for this unit, set status to abstained and record the branch mismatch in "
        "uncertainty_notes.\n"
        "- If every evidence item describes only the general category this unit belongs to, and none "
        "states what distinguishes this unit from the entries in sibling_kc_names, set status to "
        "abstained rather than restating the category.\n"
        "- A word or phrase shared between the evidence and canonical_name is not sufficient grounds "
        "to treat the evidence as on-target. The evidence must define this unit itself.\n"
        # controlled-comparator prompt-fairness fix, continued: sibling/rival material is
        # not only an abstention trigger. The bullets above only tell the model when to abstain over
        # sibling confusion; nothing previously told the model how to use sibling context inside a
        # draft it does go on to write.
        "Where you are NOT abstaining, sibling_kc_names and rival_units_considered still name the "
        "units this one must be distinguished from. Their material may be used to CONTRAST and "
        "sharpen this unit's definition, and to say what this unit is not. It must not be absorbed "
        "into the definition: do not define a sibling, do not restate a sibling's procedure, and do "
        "not let a sibling's content set the scope of this draft.\n"
        # controlled-comparator prompt-fairness fix, continued: conflicting-evidence
        # handling did not exist anywhere in this shared prompt before.
        "If two passages disagree, if two formulas are incompatible, or if the same term is used in "
        "different senses, do not resolve the conflict from your own knowledge in either direction. "
        "Prefer the passage whose subject is most directly this unit; if that does not settle it, "
        "record the conflict in uncertainty_notes and report partial rather than choosing silently.\n"
        # Completeness contract. source_block_text is the containing block for an
        # evidence span, already present on 434/602 evidence items in the audited run and carrying
        # a formula the span itself lacked in 45 units - never referenced by any instruction.
        # Every clause is conditional on what the evidence supports, so this stays inert for
        # corpora that contain no formalism.
        "Write a COMPLETE account of this unit from the supplied passages.\n"
        "The supplied evidence contains passages retrieved from the course source for the target KC. "
        "Treat only the supplied evidence as the source of factual content. The supplied evidence may "
        "be complete, partially complete, noisy, or insufficient. Do not assume that the presence of "
        "retrieved evidence guarantees complete support for the KC.\n"
        "Length must be governed by how much the passages actually support, not by a target length. "
        "Do not compress a well-supported unit into a single sentence, and do not pad a thin one. Do "
        "not add background, applications, sibling concepts, or examples unless they are directly "
        "supported and materially improve the definition. A value drawn from a worked example "
        "describes that example: never restate it as a general property using \"any\", \"all\", or "
        "\"always\".\n"
        "Cover, in this order, every part the passages support:\n"
        "- what the unit IS: its defining statement, stated so it is distinguishable from its siblings\n"
        "- any formal or symbolic statement of it, reproduced, with each symbol's meaning given\n"
        "- how it works: if the passages describe an algorithm or procedure, state its steps IN ORDER\n"
        "- its conditions, parameters, limits, boundary or failure cases\n"
        "- why and when it is used, and how it relates to the surrounding process or to its alternatives\n"
        "Separate these parts with blank lines. Omit a part only when no passage supports it; never "
        "invent one.\n"
        # controlled-comparator prompt-fairness fix, continued.
        "Use ALL passages that bear on the unit, not only the first definitional-looking one. Define "
        "a symbol only where the passages define it - leave undefined symbols undefined rather than "
        "guessing what they stand for. If this unit's own name enumerates several components, "
        "address each named component or state explicitly which the passages do not support.\n"
        "If a passage's formula rendering is partial or unreadable, say the unit has a formula and "
        "that the source rendering is incomplete, and give no equation at all - never reconstruct, "
        "complete, simplify, or infer a formula, and never supply one from your own knowledge.\n"
        "An incomplete draft is acceptable; an invented one is not. Never add a sentence, a step, or "
        "an equation just to make the account look finished - stopping early where the passages stop "
        "is correct behaviour, and coverage_notes is where to record what is missing.\n"
        # controlled-comparator prompt-fairness fix (Fix A). The paragraph below used to
        # assert unconditionally that "each evidence item carries shape_tags" - literally false for
        # a comparator whose evidence items carry no such field (0/19,680 in the audited Base Dense
        # RAG packets). The underlying completeness rule now binds on CONTENT regardless of whether
        # a shortcut tag exists to find it by; the tag is named only as an optional shortcut when
        # present. Same treatment for assertability. See 14_FINAL_GENERATOR_CONTRACT_FAIRNESS.md.
        "If any passage in your evidence states a formula, an equation, or an ordered procedure for "
        "this unit, your draft is INCOMPLETE unless it carries that formula (with symbols explained) "
        "or those steps. This is a hard requirement, not a suggestion - do not submit a draft that "
        "skips a formula or procedure the evidence actually provides. Where an evidence item carries "
        "shape_tags (definition, formula, procedure, example) describing what KIND of content it "
        "holds, treat that tag as a shortcut for finding such passages, not as a precondition for "
        "the rule above - the rule applies whether or not the tag is present. The tags are "
        "information, not permission: draw on any passage that bears on the unit regardless of its "
        "tag.\n"
        "Where an evidence item carries an assertability field marked not_assertable_interrogative, "
        "treat its proposition as not established fact unless another item independently establishes "
        "it. Whether or not this field is present, be alert to evidence phrased as a question, an "
        "exercise prompt, or a hypothetical, and do not assert its content as fact.\n"
        "Reproducing a formula, an equation or a procedure's steps from the passages is REQUIRED "
        "content, not copying: write out the mathematics itself and the steps themselves. That "
        "exemption covers ONLY the mathematics and the steps. The ban on the source document's own "
        "numbering is absolute and has no exception - never write \"Equation 3.9\", \"Table 4.4\", "
        "\"Algorithm 8.15\", \"Figure 3.15\", \"Section 6.1\" or any similar pointer in any draft "
        "field, even when the passage you draw the formula or procedure from contains one. State "
        "the relation or the steps directly so the draft stands on its own.\n"
        "Source-document numbering has already been neutralized in the evidence you are given "
        "(pointers appear as \"the figure\", \"the table\", \"the equation\"). Do not reintroduce any "
        "numbering of your own, and do not refer the reader to a figure, table or equation they "
        "cannot see - state the content itself instead.\n"
        "Return exactly one JSON object. Do not omit top-level fields from the requested schema.\n"
        "Copy knowledge_unit_id, knowledge_unit_type, and canonical_name exactly from the schema.\n"
        "For KC units, always include segmentation_support and evidence_map.\n"
        "For KC units, contextual_kc_draft.text must be at least 180 characters unless status is abstained. That is a floor, not a target - a well-supported unit should be far longer.\n"
        "For KC units, kc_specific_criteria must be an empty list with expert_pending placeholder metadata.\n\n"
    )

    if utype == "kc":
        schema = {
            "knowledge_unit_id": unit_id(packet),
            "knowledge_unit_type": "kc",
            "canonical_name": canonical_name(packet),
            "contextual_kc_draft": {
                "status": "grounded|partial|abstained",
                "text": "integrated, legible, contextually useful KC draft",
                "supporting_evidence_ids": [],
                "coverage_notes": [],
                "uncertainty_notes": [],
            },
            "segmentation_support": {
                "matching_cues": [],
                "likely_dialogue_surface_forms": [],
                "sibling_contrast_notes": [],
                "do_not_confuse_with": [],
            },
            "evaluation_support": {
                "what_tutor_should_explain": [],
                "common_confusions_or_errors": [],
                "acceptable_teaching_moves": [],
                "red_flags": [],
            },
            "evidence_map": [
                {
                    "claim": "claim text",
                    "supporting_evidence_ids": [],
                    "support_strength": "strong|moderate|weak",
                    "support_role": "definition|scope|procedure|formula|example|contrast|context",
                }
            ],
            "kc_specific_criteria": [],
            "kc_specific_criteria_status": "expert_pending",
            "kc_specific_criteria_source": "deterministic_placeholder_not_model_authored",
        }

        return (
            common
            + "TASK TYPE: KC leaf unit draft.\n"
            + "Strict KC requirements:\n"
            + "- Output all top-level keys shown in the schema.\n"
            + "- Do not return only canonical_name, contextual_kc_draft, and evaluation_support.\n"
            + "- contextual_kc_draft.text should synthesize definition, role, and boundary/procedure context when evidence supports them.\n"
            + "- segmentation_support must contain matching cues and sibling/boundary notes useful for dialogue segmentation.\n"
            + "- evidence_map must contain at least one claim linked to concrete evidence IDs.\n"
            + "- kc_specific_criteria must remain exactly [] because expert criteria are authored later.\n"
            + "Output must follow this JSON shape exactly, with useful filled content:\n"
            + compact_json(schema)
            + "\n\nPACKET:\n"
            + compact_json(visible_packet_for_prompt(packet, mode))
        )

    if utype == "topic":
        schema = {
            "knowledge_unit_id": unit_id(packet),
            "knowledge_unit_type": "topic",
            "canonical_name": canonical_name(packet),
            "contextual_topic_draft": {
                "status": "grounded|partial|abstained",
                "text": "integrated topic draft using direct child KCs plus topic evidence",
                "supporting_evidence_ids": [],
                "coverage_notes": [],
                "uncertainty_notes": [],
            },
            "child_kc_summaries": [
                {
                    "child_kc_id": "id of one unit from direct_child_kcs",
                    "child_kc_name": "its canonical name",
                    "summary": "what this topic's evidence establishes about that unit",
                    "supporting_evidence_ids": [],
                }
            ],
            "segmentation_support": {
                "topic_matching_cues": [],
                "child_kc_boundary_cues": [],
                "do_not_confuse_with_topics": [],
            },
            "evaluation_support": {
                "what_tutor_should_cover_at_topic_level": [],
                "common_topic_level_confusions": [],
                "red_flags": [],
            },
            "evidence_map": [
                {
                    "claim": "claim text",
                    "supporting_topic_evidence_ids": [],
                    "supporting_child_kc_ids": [],
                    "support_strength": "strong|moderate|weak",
                    "support_role": "topic_overview|child_kc_synthesis|scope|contrast|gap",
                }
            ],
            "topic_gap_notes": [],
        }

        return (
            common
            + "TASK TYPE: terminal topic internal node draft.\n"
            + "The packet gives you the source passages that ground this topic’s child knowledge "
            + "units, each tagged with source_child_kc_id and source_child_kc_name, plus the full "
            + "roster of those units in direct_child_kcs. Draft the topic from those passages.\n"
            + "Account for EVERY unit listed in direct_child_kcs: give each one its own entry in "
            + "child_kc_summaries, using its exact child_kc_id. Where the passages do not support "
            + "a unit, still give it an entry and say so in its summary. Do not silently omit a "
            + "child unit.\n"
            + "Relate the child units to one another and state the boundary of the topic - a topic "
            + "draft is not an unstructured list of its children.\n"
            + "Put the evidence ids you used in contextual_topic_draft.supporting_evidence_ids, "
            + "and attribute each child unit's own evidence inside its child_kc_summaries entry.\n"
            + "Parent topics are not in scope.\n"
            + "Output must follow this JSON shape exactly, with useful filled content:\n"
            + compact_json(schema)
            + "\n\nPACKET:\n"
            + compact_json(visible_packet_for_prompt(packet, mode))
        )

    raise ValueError(f"unsupported knowledge_unit_type: {utype!r}")


def ollama_generate(host: str, model: str, prompt: str, num_ctx: int, timeout_s: int, num_predict: int | None = None) -> Dict[str, Any]:
    url = f"http://{host}/api/generate"
    options: Dict[str, Any] = {
        "temperature": 0,
        "num_ctx": num_ctx,
    }
    if num_predict is not None and int(num_predict) > 0:
        options["num_predict"] = int(num_predict)

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        # reasoning-capable
        # models (confirmed via `ollama show` listing "thinking" as a capability - qwen3.6:27b,
        # gemma4:12b) spend their num_predict budget on internal reasoning first when this isn't
        # explicitly disabled, leaving nothing for the actual structured answer - all 181 units
        # failed identically with an empty response (JSONDecodeError at char 0) once qwen3.6:27b
        # was swapped in here, even though this exact payload shape had worked fine for
        # gemma4:31b's own (non-thinking-by-default, evidently) generation all along. General,
        # not model-specific: any future reasoning-capable model swapped into this pipeline
        # would hit the same failure without this. Ollama accepts "think" as a no-op for models
        # without the capability, so this is safe unconditionally.
        "think": False,
        "options": options,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def parse_model_json(raw_response: str) -> Tuple[Dict[str, Any] | None, str]:
    text = raw_response.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None, ""
    except Exception as exc:
        # Conservative fallback: extract outermost JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
                return obj if isinstance(obj, dict) else None, ""
            except Exception as exc2:
                return None, f"json_parse_failed: {exc!r}; fallback_failed: {exc2!r}"
        return None, f"json_parse_failed: {exc!r}"


def normalize_draft_from_packet(packet: Mapping[str, Any], draft: Mapping[str, Any] | None) -> Tuple[Mapping[str, Any] | None, List[Dict[str, Any]]]:
    """Normalize deterministic wrapper fields that should not depend on model authorship.

    This intentionally does not fabricate semantic content such as contextual drafts,
    segmentation support, evaluation support, or evidence maps.
    """
    if not isinstance(draft, dict):
        return draft, []

    out: Dict[str, Any] = dict(draft)
    actions: List[Dict[str, Any]] = []

    expected_id = unit_id(packet)
    expected_type = unit_type(packet)
    expected_name = canonical_name(packet)

    for key, expected in [
        ("knowledge_unit_id", expected_id),
        ("knowledge_unit_type", expected_type),
        ("canonical_name", expected_name),
    ]:
        if out.get(key) != expected:
            actions.append({"action": "set_deterministic_wrapper_field", "field": key, "old": out.get(key), "new": expected})
            out[key] = expected

    if expected_type == "kc":
        deterministic_fields = {
            "kc_specific_criteria": [],
            "kc_specific_criteria_status": "expert_pending",
            "kc_specific_criteria_source": "deterministic_placeholder_not_model_authored",
        }
        for key, expected in deterministic_fields.items():
            if out.get(key) != expected:
                actions.append({"action": "set_deterministic_kc_placeholder", "field": key, "old": out.get(key), "new": expected})
                out[key] = expected
    elif expected_type == "topic":
        for key in ["kc_specific_criteria", "kc_specific_criteria_status", "kc_specific_criteria_source"]:
            if key in out:
                actions.append({"action": "remove_topic_forbidden_kc_specific_field", "field": key, "old": out.get(key)})
                out.pop(key, None)

    return out, actions


def packet_support_state(packet: Mapping[str, Any]) -> str:
    upstream = packet.get("upstream_summary") if isinstance(packet.get("upstream_summary"), Mapping) else {}
    state = str(packet.get("packet_support_state") or upstream.get("packet_support_state") or "").strip()
    if state:
        return state
    if packet_allows_abstention(packet):
        return "insufficient_support"
    source = str(upstream.get("packet_evidence_source") or "")
    if source == "step66_overlay_target_bound_fallback":
        return "weak_fallback"
    if source:
        return "draftable"
    return ""


def draft_declares_evidence_insufficient(packet: Mapping[str, Any], draft: Mapping[str, Any]) -> bool:
    utype = unit_type(packet)
    if utype == "kc":
        contextual = draft.get("contextual_kc_draft") if isinstance(draft.get("contextual_kc_draft"), Mapping) else {}
    elif utype == "topic":
        contextual = draft.get("contextual_topic_draft") if isinstance(draft.get("contextual_topic_draft"), Mapping) else {}
    else:
        return False

    if str(contextual.get("status") or "").lower() != "abstained":
        return False

    notes = contextual.get("uncertainty_notes") or []
    if not isinstance(notes, list):
        notes = [notes]

    evidence_ids = []
    for item in packet.get("evidence_for_synthesis") or []:
        if isinstance(item, Mapping) and item.get("evidence_id"):
            evidence_ids.append(str(item.get("evidence_id")))

    blob = " ".join(str(x) for x in notes if str(x)).lower()
    if not blob.strip():
        return False

    evidence_words = ("evidence", "provided", "source", "support", "context", "packet", "passage", "text")
    insufficiency_words = (
        "insufficient", "not enough", "no ", "none", "missing", "unsupported", "does not", "do not",
        "cannot", "unable", "lacks", "lack", "no definition", "no descriptive", "not support"
    )

    mentions_evidence = any(word in blob for word in evidence_words) or any(eid and eid.lower() in blob for eid in evidence_ids)
    mentions_insufficiency = any(word in blob for word in insufficiency_words)
    return mentions_evidence and mentions_insufficiency


def draft_abstention_is_validation_allowed(packet: Mapping[str, Any], draft: Mapping[str, Any]) -> bool:
    if not isinstance(draft, Mapping):
        return False

    utype = unit_type(packet)
    if utype == "kc":
        contextual = draft.get("contextual_kc_draft") if isinstance(draft.get("contextual_kc_draft"), Mapping) else {}
    elif utype == "topic":
        contextual = draft.get("contextual_topic_draft") if isinstance(draft.get("contextual_topic_draft"), Mapping) else {}
    else:
        return False

    if str(contextual.get("status") or "").lower() != "abstained":
        return False

    if packet_allows_abstention(packet):
        return True

    return packet_support_state(packet) == "weak_fallback" and draft_declares_evidence_insufficient(packet, draft)


def schema_repair_allowed_issue_codes() -> set[str]:
    return {
        "segmentation_support_missing",
        "evaluation_support_missing",
        "evidence_map_missing_or_empty",
    }


_ABSTENTION_REPAIR_STOPWORDS = {
    "about", "above", "after", "again", "against", "also", "approach", "approaches", "because",
    "between", "class", "classes", "data", "different", "during", "each", "from", "into",
    "method", "methods", "model", "models", "other", "point", "points", "problem", "sample",
    "samples", "test", "tests", "that", "their", "there", "these", "this", "unit", "using",
    "where", "which", "with",
}


def _repair_token_stem(token: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "", str(token or "").lower())
    if len(token) <= 3 or token in _ABSTENTION_REPAIR_STOPWORDS:
        return ""
    for suffix in ("ization", "ations", "ation", "ness", "ingly", "ing", "edly", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 4:
            token = token[: -len(suffix)]
            break
    return token[:8]


def _repair_token_stems(text: str) -> set[str]:
    stems: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9]+", str(text or "").lower()):
        stem = _repair_token_stem(raw)
        if stem:
            stems.add(stem)
        if raw.startswith("multi"):
            stems.add("multi")
        if "class" in raw:
            stems.add("class")
        if raw.startswith("init"):
            stems.add("init")
        if raw.startswith("represent"):
            stems.add("represen")
        if raw.startswith("random"):
            stems.add("random")
        if raw.startswith("missing"):
            stems.add("missing")
    return stems


def _substantive_evidence_text(text: str) -> bool:
    raw = norm(text)
    if len(raw) < 70:
        return False
    if not re.search(r"[.!?]", raw):
        return False
    if re.fullmatch(r"(?:\d+(?:\.\d+)*\s+)?[A-Z][A-Za-z\- ]{2,40}\s*\.?",
                    raw):
        return False
    return True


def packet_has_content_repair_signal(packet: Mapping[str, Any]) -> bool:
    """True when a non-abstain packet has enough target-specific text to safely ask for content.

    Packet policy is not always reliable by itself: fresh v3_20260812 rows labelled
    "comprehensive" include McNemar and Informative Missingness packets whose evidence is only a
    fragment or generic missing-data text. This gate demands both substantive prose somewhere in
    the packet and at least two target-name content-token hits across the evidence before asking a
    model to reverse its abstention.
    """
    evidence_texts = [
        norm(ev.get("text"))
        for ev in (packet.get("evidence_for_synthesis") or [])
        if isinstance(ev, Mapping) and norm(ev.get("text"))
    ]
    if not evidence_texts or not any(_substantive_evidence_text(text) for text in evidence_texts):
        return False

    target_stems = _repair_token_stems(canonical_name(packet))
    if not target_stems:
        return False
    evidence_stems = _repair_token_stems(" ".join(evidence_texts))
    return len(target_stems & evidence_stems) >= min(2, len(target_stems))


def invalid_abstention_needs_content_repair(packet: Mapping[str, Any], draft: Mapping[str, Any] | None) -> bool:
    """True when the model abstained despite repairable, target-specific packet evidence."""
    if unit_type(packet) != "kc" or not isinstance(draft, Mapping):
        return False
    if packet_allows_abstention(packet):
        return False
    if not packet_has_content_repair_signal(packet):
        return False
    ck = draft.get("contextual_kc_draft") if isinstance(draft.get("contextual_kc_draft"), Mapping) else {}
    return str(ck.get("status") or "").lower() == "abstained"


def damaged_math_needs_content_repair(packet: Mapping[str, Any], draft: Mapping[str, Any] | None,
                                      validation_issues: List[Dict[str, Any]]) -> bool:
    if unit_type(packet) not in {"kc", "topic"} or not isinstance(draft, Mapping):
        return False
    issue_codes = {str(x.get("code") or "") for x in validation_issues if isinstance(x, Mapping)}
    return bool(issue_codes & {"kc_contextual_draft_damaged_math",
                               "topic_contextual_draft_damaged_math"})


def should_attempt_schema_repair(packet: Mapping[str, Any], draft: Mapping[str, Any] | None, validation_issues: List[Dict[str, Any]]) -> bool:
    if unit_type(packet) != "kc":
        return False
    if not isinstance(draft, Mapping) or not validation_issues:
        return False

    issue_codes = {str(x.get("code") or "") for x in validation_issues if isinstance(x, Mapping)}
    if not issue_codes or not issue_codes.issubset(schema_repair_allowed_issue_codes()):
        return False

    ck = draft.get("contextual_kc_draft") if isinstance(draft.get("contextual_kc_draft"), Mapping) else {}
    # v43: a legitimate abstention has empty text and empty supporting_evidence_ids BY
    # DESIGN (see build_prompt's abstention contract) - that is the correct state, not a
    # defect, so the two checks below (which exist to confirm a draft has real content
    # before repairing it) do not apply here. Invalid abstentions are routed to a separate
    # content-repair path before this function is considered.
    if str(ck.get("status") or "").lower() == "abstained":
        return True
    if len(norm(ck.get("text"))) < 180:
        return False
    if not isinstance(ck.get("supporting_evidence_ids"), list) or not ck.get("supporting_evidence_ids"):
        return False

    return True


def build_required_output_schema(packet: Mapping[str, Any]) -> Dict[str, Any]:
    if unit_type(packet) == "topic":
        return {
            "knowledge_unit_id": unit_id(packet),
            "knowledge_unit_type": "topic",
            "canonical_name": canonical_name(packet),
            "contextual_topic_draft": {
                "status": "grounded|partial|abstained",
                "text": "topic-level context text",
                "supporting_evidence_ids": [],
                "coverage_notes": [],
                "uncertainty_notes": [],
            },
            "child_kc_summaries": [
                {
                    "child_kc_id": "child KC id",
                    "child_kc_name": "child KC name",
                    "summary": "brief child summary",
                    "supporting_evidence_ids": [],
                }
            ],
            "evaluation_support": {
                "what_tutor_should_explain": [],
                "common_confusions_or_errors": [],
                "acceptable_teaching_moves": [],
                "red_flags": [],
            },
            "evidence_map": [
                {
                    "claim": "claim text",
                    "supporting_evidence_ids": [],
                    "support_strength": "strong|moderate|weak",
                    "support_role": "definition|scope|procedure|formula|example|contrast|context",
                }
            ],
        }

    return {
        "knowledge_unit_id": unit_id(packet),
        "knowledge_unit_type": "kc",
        "canonical_name": canonical_name(packet),
        "contextual_kc_draft": {
            "status": "grounded|partial|abstained",
            "text": "KC draft text, or empty only when status is abstained and abstention is allowed",
            "supporting_evidence_ids": [],
            "coverage_notes": [],
            "uncertainty_notes": [],
        },
        "segmentation_support": {
            "matching_cues": [],
            "likely_dialogue_surface_forms": [],
            "sibling_contrast_notes": [],
            "do_not_confuse_with": [],
        },
        "evaluation_support": {
            "what_tutor_should_explain": [],
            "common_confusions_or_errors": [],
            "acceptable_teaching_moves": [],
            "red_flags": [],
        },
        "evidence_map": [
            {
                "claim": "claim text",
                "supporting_evidence_ids": [],
                "support_strength": "strong|moderate|weak",
                "support_role": "definition|scope|procedure|formula|example|contrast|context",
            }
        ],
        "kc_specific_criteria": [],
        "kc_specific_criteria_status": "expert_pending",
        "kc_specific_criteria_source": "deterministic_placeholder_not_model_authored",
    }


def build_parse_repair_prompt(packet: Mapping[str, Any], raw_response: str, parse_error: str) -> str:
    schema = build_required_output_schema(packet)

    clipped_raw = raw_response
    if len(clipped_raw) > 18000:
        clipped_raw = clipped_raw[:18000] + "\n...[TRUNCATED_RAW_RESPONSE_FOR_REPAIR]..."

    return (
        "You are repairing a malformed JSON response for a Knowledge Library drafting task.\n"
        "The previous response was not valid JSON. Your job is NOT to create a new draft from scratch.\n"
        "Recover the intended content from the malformed response where possible, use the packet only to fill missing required fields, and return exactly one complete valid JSON object.\n"
        "Do not include markdown, comments, explanations, or extra text outside JSON.\n"
        "Do not duplicate keys. Each object key must appear only once.\n"
        "Do not leave strings unfinished. Close every string, array, and object.\n"
        "Keep the heavy contract: include all required fields from the schema.\n"
        "If the source evidence is insufficient and packet policy allows abstention, output status='abstained' with empty text and clear uncertainty notes.\n\n"
        "PARSE_ERROR:\n"
        + str(parse_error)
        + "\n\nREQUIRED_SCHEMA:\n"
        + compact_json(schema)
        + "\n\nMALFORMED_RESPONSE:\n"
        + clipped_raw
        + "\n\nPACKET:\n"
        + compact_json(prompt_safe_packet(packet))
    )


def build_invalid_abstention_repair_prompt(packet: Mapping[str, Any], draft: Mapping[str, Any], validation_issues: List[Dict[str, Any]]) -> str:
    schema = build_required_output_schema(packet)
    return (
        "You are repairing an invalid abstention for a Knowledge Library KC unit.\n"
        "The previous answer abstained, but this packet does NOT declare abstention_expected or insufficient_synthesis_support and it contains evidence_for_synthesis.\n"
        "Your job is to write the best source-grounded KC draft the packet supports. Use only the packet. Do not invent facts.\n"
        "If evidence is thin but on-target, write a thin-but-complete draft and mark it grounded if no supported element is omitted; mark partial only when you can name a specific supported element that remains incomplete.\n"
        "Do not return status='abstained' unless the evidence is truly about a sibling or different branch despite the packet policy.\n"
        "Return exactly one valid JSON object matching this schema.\n\n"
        "VALIDATION_ISSUES:\n"
        + compact_json(validation_issues)
        + "\n\nREQUIRED_SCHEMA:\n"
        + compact_json(schema)
        + "\n\nPREVIOUS_DRAFT:\n"
        + compact_json(draft)
        + "\n\nPACKET:\n"
        + compact_json(prompt_safe_packet(packet))
    )


def build_damaged_math_repair_prompt(packet: Mapping[str, Any], draft: Mapping[str, Any], validation_issues: List[Dict[str, Any]]) -> str:
    schema = build_required_output_schema(packet)
    return (
        "You are repairing a draft that contains a damaged mathematical rendering.\n"
        "Use only the packet evidence. Do not reconstruct, complete, simplify, or infer any formula whose rendering is damaged in the previous draft or packet.\n"
        "If the packet has no intact formula for a claim, remove the broken equation and write the concept in prose only.\n"
        "Keep the draft source-grounded, concise, and complete for the evidence that remains usable.\n"
        "Return exactly one valid JSON object matching this schema.\n\n"
        "VALIDATION_ISSUES:\n"
        + compact_json(validation_issues)
        + "\n\nREQUIRED_SCHEMA:\n"
        + compact_json(schema)
        + "\n\nPREVIOUS_DRAFT:\n"
        + compact_json(draft)
        + "\n\nPACKET:\n"
        + compact_json(prompt_safe_packet(packet))
    )


def build_schema_repair_prompt(packet: Mapping[str, Any], draft: Mapping[str, Any], validation_issues: List[Dict[str, Any]]) -> str:
    schema = {
        "knowledge_unit_id": unit_id(packet),
        "knowledge_unit_type": "kc",
        "canonical_name": canonical_name(packet),
        "contextual_kc_draft": {
            "status": "grounded|partial|abstained",
            "text": "keep the existing contextual draft text unless it is malformed",
            "supporting_evidence_ids": [],
            "coverage_notes": [],
            "uncertainty_notes": [],
        },
        "segmentation_support": {
            "matching_cues": [],
            "likely_dialogue_surface_forms": [],
            "sibling_contrast_notes": [],
            "do_not_confuse_with": [],
        },
        "evaluation_support": {
            "what_tutor_should_explain": [],
            "common_confusions_or_errors": [],
            "acceptable_teaching_moves": [],
            "red_flags": [],
        },
        "evidence_map": [
            {
                "claim": "claim text",
                "supporting_evidence_ids": [],
                "support_strength": "strong|moderate|weak",
                "support_role": "definition|scope|procedure|formula|example|contrast|context",
            }
        ],
        "kc_specific_criteria": [],
        "kc_specific_criteria_status": "expert_pending",
        "kc_specific_criteria_source": "deterministic_placeholder_not_model_authored",
    }

    is_abstained = str(
        (draft.get("contextual_kc_draft") or {}).get("status") or ""
    ).lower() == "abstained" if isinstance(draft.get("contextual_kc_draft"), Mapping) else False
    # v43: wording branches on abstention status. The original single wording asserted
    # "the previous answer contains useful grounded contextual text", which is false for a
    # legitimate abstention and would confuse the model about what is being asked. An
    # abstained draft also correctly has no evidence to link, so it is told to leave
    # evidence_map empty rather than being implicitly asked to invent evidence links.
    if is_abstained:
        repair_context_line = (
            "The previous answer correctly abstained on contextual_kc_draft.text (kept it "
            "empty because the evidence did not support this unit specifically) but "
            "omitted required structure that does not depend on that evidence.\n"
        )
        fill_line = (
            "Fill only segmentation_support and evaluation_support. Derive segmentation_"
            "support from canonical_name, aliases, hierarchy, sibling_kc_names, and rival_"
            "units_considered in the PACKET below - these are always available regardless "
            "of evidence sufficiency and this is not inventing content. For evaluation_"
            "support, use only what the packet's evidence actually contains even though it "
            "was insufficient for a full draft; leave a list empty rather than inventing a "
            "claim it does not support. Leave evidence_map as an empty list - this unit "
            "correctly abstained and has no evidence links to report.\n"
        )
    else:
        repair_context_line = (
            "The previous answer contains useful grounded contextual text but omitted required structure.\n"
        )
        fill_line = (
            "Fill only missing or incomplete structural fields: segmentation_support, evaluation_support, and evidence_map.\n"
            "Every evidence_map item must link a concise claim to evidence IDs from contextual_kc_draft.supporting_evidence_ids or packet evidence_for_synthesis.\n"
        )

    return (
        "You are repairing a structured JSON draft for a Knowledge Library KC unit.\n"
        + repair_context_line
        + "Do not add unsupported claims. Use only the packet and previous draft.\n"
        "Keep contextual_kc_draft.text unchanged unless it is malformed.\n"
        + fill_line
        + "Return exactly one valid JSON object matching this schema.\n\n"
        "VALIDATION_ISSUES:\n"
        + compact_json(validation_issues)
        + "\n\nREQUIRED_SCHEMA:\n"
        + compact_json(schema)
        + "\n\nPREVIOUS_DRAFT:\n"
        + compact_json(draft)
        + "\n\nPACKET:\n"
        + compact_json(prompt_safe_packet(packet))
    )


class ContentRepair(NamedTuple):
    """One content repair: when it applies, how to ask for it, and how the attempt is labelled."""

    phase: str
    needs_repair: Any          # (packet, draft, validation_issues) -> bool
    build_prompt: Any          # (packet, draft, validation_issues) -> str


def content_repair_chain() -> Tuple[ContentRepair, ...]:
    """The ordered content repairs a drafting row loop must attempt, at most one per row.

    Exported as DATA rather than left as hand-written blocks because the loop that actually runs
    in production is the schema-contract probe, which drives this module by invoking functions it
    names one by one. A repair added here as a block and not mirrored there is dead on arrival,
    and two already were: the invalid-abstention repair and the damaged-math repair both existed,
    both had passing unit tests, and neither had ever executed - `repair_attempted` was 0 across
    every audited run. The same trap had already caught the status-integrity gate once.

    A caller that iterates this tuple cannot forget a repair, and the verification suite checks
    that the probe iterates it rather than naming repairs individually.
    """
    return (
        ContentRepair(
            "invalid_abstention_content_repair",
            lambda packet, draft, issues: invalid_abstention_needs_content_repair(packet, draft),
            build_invalid_abstention_repair_prompt),
        ContentRepair(
            "damaged_math_content_repair",
            damaged_math_needs_content_repair,
            build_damaged_math_repair_prompt),
        ContentRepair(
            "schema_repair",
            should_attempt_schema_repair,
            build_schema_repair_prompt),
    )


def repair_resolved(repair: ContentRepair, packet: Mapping[str, Any],
                    repaired: Mapping[str, Any] | None,
                    repair_parse_error: str,
                    repair_validation_issues: List[Dict[str, Any]]) -> bool:
    """Whether a repair attempt actually fixed what it was asked to fix.

    Three conditions, each removing a different way a repair can look successful without being so:

      * clean parse and validation - the structural floor;
      * the repair's OWN predicate stops firing, so a repair is not accepted merely because the
        model returned something well-formed. This is also what lets a model that abstains again
        KEEP its abstention: the attempt is discarded and the original draft stands;
      * the repaired body describes its SUBJECT rather than its EVIDENCE.

    The third was added after measuring the first run with the repair reachable. Denied its
    abstention, the model did not invent content - it wrote its refusal as the draft: "The
    provided evidence does not define 'Models of Randomness (Approach 1)'...". Four of seven
    repaired drafts were bodies of that kind. They satisfy every structural check and tell a
    downstream reader nothing, so an honest abstention is the better artifact and is what stands
    when this rejects the attempt.
    """
    if repair_parse_error or repair_validation_issues:
        return False
    if repair.needs_repair(packet, repaired, repair_validation_issues):
        return False
    contextual = repaired.get("contextual_kc_draft") if isinstance(repaired, Mapping) else None
    body = str((contextual or {}).get("text") or "") if isinstance(contextual, Mapping) else ""
    return not body_describes_its_evidence(body)


def packet_allows_abstention(packet: Mapping[str, Any]) -> bool:
    upstream = packet.get("upstream_summary") if isinstance(packet.get("upstream_summary"), Mapping) else {}
    return bool(
        packet.get("abstention_expected")
        or packet.get("insufficient_synthesis_support")
        or upstream.get("abstention_expected")
        or upstream.get("insufficient_synthesis_support")
    )


def validate_output(packet: Mapping[str, Any], draft: Mapping[str, Any] | None) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    if not isinstance(draft, dict):
        return [{"code": "missing_or_invalid_draft_json"}]

    if draft.get("knowledge_unit_id") != unit_id(packet):
        issues.append({"code": "knowledge_unit_id_mismatch", "expected": unit_id(packet), "actual": draft.get("knowledge_unit_id")})
    if draft.get("knowledge_unit_type") != unit_type(packet):
        issues.append({"code": "knowledge_unit_type_mismatch", "expected": unit_type(packet), "actual": draft.get("knowledge_unit_type")})

    utype = unit_type(packet)
    if utype == "kc":
        ck = draft.get("contextual_kc_draft")
        ck_status = str(ck.get("status") or "").lower() if isinstance(ck, dict) else ""
        # Empty text is the REQUIRED shape of an abstention (build_prompt: "keep contextual text
        # empty"), so status alone exempts it - not whether the packet granted permission. An
        # abstention the packet did not permit is a real signal, but it is the status-integrity
        # gate's signal (unjustified_abstention_on_draftable_packet), not a schema-shape defect.
        if ck_status != "abstained" and (not isinstance(ck, dict) or len(norm(ck.get("text"))) < 180):
            issues.append({"code": "kc_contextual_draft_missing_or_too_short"})
        if draft.get("kc_specific_criteria") != []:
            issues.append({"code": "kc_specific_criteria_not_empty"})
        if draft.get("kc_specific_criteria_status") != "expert_pending":
            issues.append({"code": "kc_specific_criteria_status_wrong"})
        if draft.get("kc_specific_criteria_source") != "deterministic_placeholder_not_model_authored":
            issues.append({"code": "kc_specific_criteria_source_wrong"})
        if isinstance(ck, dict) and ck_status != "abstained" and draft_math_rendering_damaged(ck.get("text")):
            issues.append({"code": "kc_contextual_draft_damaged_math"})
        for key in ["segmentation_support", "evaluation_support"]:
            if not isinstance(draft.get(key), dict):
                issues.append({"code": f"{key}_missing"})
    elif utype == "topic":
        ct = draft.get("contextual_topic_draft")
        ct_status = str(ct.get("status") or "").lower() if isinstance(ct, dict) else ""
        # Same exemption as the KC side, which the topic path never had.
        if ct_status != "abstained" and (not isinstance(ct, dict) or len(norm(ct.get("text"))) < 220):
            issues.append({"code": "topic_contextual_draft_missing_or_too_short"})
        # child_kc_summaries is the field the ENFORCED schema actually declares (see
        # run_step67_v2_schema_contract_probe.py's topic_json_schema, additionalProperties:False).
        # This used to require child_kc_coverage_summary, which that schema forbids - so it could
        # never be satisfied, and failed 22/22 topic drafts by construction.
        child_summaries = draft.get("child_kc_summaries")
        if not isinstance(child_summaries, list) or not child_summaries:
            issues.append({"code": "child_kc_summaries_missing_or_empty"})
        if "kc_specific_criteria" in draft:
            issues.append({"code": "topic_must_not_include_kc_specific_criteria"})
        # Terminal topic must cite evidence and account for its children unless it abstains.
        if isinstance(ct, dict) and ct.get("status") != "abstained":
            if not ct.get("supporting_evidence_ids"):
                issues.append({"code": "topic_draft_missing_supporting_evidence_ids"})
            # The real intent of the retired coverage-summary check: every direct child unit is
            # either summarised or explicitly named as unaccounted. Derived from the packet's own
            # direct_child_kcs, so it needs no field the schema refuses to emit.
            expected_children = [
                str(c.get("child_kc_id") or "")
                for c in (packet.get("direct_child_kcs") or [])
                if isinstance(c, Mapping) and c.get("child_kc_id")
            ]
            summarised = {
                str(s.get("child_kc_id") or "")
                for s in (child_summaries or []) if isinstance(s, Mapping)
            }
            unaccounted = [c for c in expected_children if c not in summarised]
            if unaccounted:
                issues.append({"code": "topic_draft_child_kcs_unaccounted",
                               "unaccounted_child_kc_ids": unaccounted[:20],
                               "unaccounted_count": len(unaccounted)})
            if draft_math_rendering_damaged(ct.get("text")):
                issues.append({"code": "topic_contextual_draft_damaged_math"})
    else:
        issues.append({"code": "unsupported_unit_type", "unit_type": utype})

    ev_map = draft.get("evidence_map")
    abstained_status = False
    if utype == "kc":
        ck = draft.get("contextual_kc_draft")
        abstained_status = isinstance(ck, dict) and str(ck.get("status") or "").lower() == "abstained"
    elif utype == "topic":
        ct = draft.get("contextual_topic_draft")
        abstained_status = isinstance(ct, dict) and str(ct.get("status") or "").lower() == "abstained"

    # An empty ledger is likewise the required shape of an abstention, whatever the packet
    # thought of the evidence - see the note on the contextual-text check above.
    if (not isinstance(ev_map, list) or not ev_map) and not abstained_status:
        issues.append({"code": "evidence_map_missing_or_empty"})

    # An evidence_map is a control mechanism, not proof of grounding, unless its ids resolve.
    # Work on answer attribution finds model self-citations can point at wrong or nonexistent
    # sources, so a citation that names nothing real is worse than no citation - it looks grounded.
    # Deterministic and domain-agnostic: ids are compared against the packet this draft came from.
    if isinstance(ev_map, list) and ev_map and not abstained_status:
        known_ids = set()
        for item in (packet.get("evidence_for_synthesis") or []):
            if isinstance(item, Mapping) and item.get("evidence_id"):
                known_ids.add(str(item.get("evidence_id")))
        cited, unknown = set(), set()
        for entry in ev_map:
            if not isinstance(entry, Mapping):
                continue
            for key in ("supporting_evidence_ids", "supporting_topic_evidence_ids"):
                for raw_id in (entry.get(key) or []):
                    ident = str(raw_id).strip()
                    if not ident:
                        continue
                    cited.add(ident)
                    if known_ids and ident not in known_ids:
                        unknown.add(ident)
        if known_ids and not cited:
            issues.append({"code": "evidence_map_cites_no_evidence_ids"})
        if unknown:
            issues.append({
                "code": "evidence_map_cites_unknown_evidence_id",
                "unknown_ids": sorted(unknown)[:8],
                "unknown_count": len(unknown),
            })
    return issues


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-json", required=True, type=pathlib.Path)
    ap.add_argument("--selected-packets-jsonl", required=True, type=pathlib.Path)
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--model", default=os.environ.get("KC_L_PROFILE_MODEL", "gemma4:31b"))
    ap.add_argument("--num-ctx", type=int, default=int(os.environ.get("OLLAMA_CONTEXT_LENGTH", "65536")))
    ap.add_argument("--timeout-s", type=int, default=900)
    ap.add_argument("--num-predict", type=int, default=int(os.environ.get("KC_L_STEP67_V2_NUM_PREDICT", "3072")))
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    plan = read_json(args.plan_json)
    packets, invalid = read_jsonl(args.selected_packets_jsonl)
    if invalid:
        raise SystemExit(f"selected packet JSONL has invalid rows: {invalid}")
    if not plan.get("ready_to_submit_tiny_smoke"):
        raise SystemExit(f"plan not ready: {plan.get('decision')}")

    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434").replace("http://", "").replace("https://", "")
    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    drafts_jsonl = args.out_dir / "step67_v2_tiny_smoke_drafts.jsonl"
    progress_json = args.out_dir / "STEP67_V2_TINY_SMOKE_PROGRESS.json"

    start = time.time()
    for i, packet in enumerate(packets, start=1):
        prompt = build_prompt(packet)
        call_start = time.time()
        try:
            api = ollama_generate(host, args.model, prompt, args.num_ctx, args.timeout_s, args.num_predict)
            call_elapsed = time.time() - call_start
        except Exception as exc:
            call_elapsed = time.time() - call_start
            runtime_error = f"{exc.__class__.__name__}: {exc!r}"
            validation_issues = [{"code": "model_call_failed", "error": runtime_error}]
            row = {
                "run_id": args.run_id,
                "created_utc": now_utc(),
                "knowledge_unit_id": unit_id(packet),
                "knowledge_unit_type": unit_type(packet),
                "canonical_name": canonical_name(packet),
                "packet_index": i,
                "model": args.model,
                "ollama_host": host,
                "num_ctx": args.num_ctx,
                "num_predict": args.num_predict,
                "prompt_chars": len(prompt),
                "raw_response_chars": 0,
                "call_elapsed_seconds": round(call_elapsed, 3),
                "ollama_metadata": {},
                "draft": None,
                "parse_error": runtime_error,
                "normalization_actions": [],
                "repair_attempted": False,
                "repair_parse_error": "",
                "repair_validation_issues_before": [],
                "repair_normalization_actions": [],
                "raw_response": "",
                "repair_raw_response": "",
                "validation_issues": validation_issues,
                "status_integrity_override": None,
                "runtime_error": runtime_error,
                "source_packet": packet,
            }
            rows.append(row)
            failures.append({
                "knowledge_unit_id": unit_id(packet),
                "knowledge_unit_type": unit_type(packet),
                "canonical_name": canonical_name(packet),
                "parse_error": runtime_error,
                "validation_issues": validation_issues,
            })
            write_jsonl(drafts_jsonl, rows)
            progress_json.write_text(json.dumps({
                "run_id": args.run_id,
                "created_utc": now_utc(),
                "processed_count": len(rows),
                "selected_packet_count": len(packets),
                "failure_count": len(failures),
                "last_packet_index": i,
                "last_packet_id": unit_id(packet),
                "last_runtime_error": runtime_error,
            }, indent=2, ensure_ascii=False), encoding="utf-8")
            continue

        raw = str(api.get("response") or "")
        parsed, parse_error = parse_model_json(raw)

        parse_repair_attempted = False
        parse_repair_parse_error = ""
        parse_repair_raw_response = ""
        parse_repair_validation_issues: List[Dict[str, Any]] = []

        if parse_error:
            parse_repair_attempted = True
            parse_repair_prompt = build_parse_repair_prompt(packet, raw, parse_error)
            try:
                parse_repair_api = ollama_generate(host, args.model, parse_repair_prompt, args.num_ctx, args.timeout_s, args.num_predict)
                parse_repair_raw_response = str(parse_repair_api.get("response") or "")
                parse_repaired_parsed, parse_repair_parse_error = parse_model_json(parse_repair_raw_response)
                if not parse_repair_parse_error:
                    parsed = parse_repaired_parsed
                    parse_error = ""
            except Exception as exc:
                parse_repair_parse_error = f"{exc.__class__.__name__}: {exc!r}"

        normalized, normalization_actions = normalize_draft_from_packet(packet, parsed)
        validation_issues = validate_output(packet, normalized)

        # One content repair per row, taken from the shared chain rather than three
        # copy-pasted blocks. The chain is the single place a repair is declared, so this loop
        # and the schema-contract probe cannot disagree about which repairs exist - which is
        # exactly how two of them came to be dead code.
        repair_attempted = False
        repair_parse_error = ""
        repair_raw_response = ""
        repair_validation_issues_before = list(validation_issues)
        repair_normalization_actions: List[Dict[str, Any]] = []

        for repair in content_repair_chain():
            if parse_error or repair_attempted:
                break
            if not repair.needs_repair(packet, normalized, validation_issues):
                continue
            repair_attempted = True
            repair_prompt = repair.build_prompt(packet, normalized, validation_issues)
            repair_api = ollama_generate(host, args.model, repair_prompt, args.num_ctx,
                                         args.timeout_s, args.num_predict)
            repair_raw_response = str(repair_api.get("response") or "")
            repair_parsed, repair_parse_error = parse_model_json(repair_raw_response)
            repaired, repair_normalization_actions = normalize_draft_from_packet(packet,
                                                                                repair_parsed)
            repair_validation_issues = validate_output(packet, repaired)

            if repair_resolved(repair, packet, repaired, repair_parse_error,
                               repair_validation_issues):
                normalized = repaired
                validation_issues = []
                for action in repair_normalization_actions:
                    tagged = dict(action)
                    tagged["phase"] = repair.phase
                    normalization_actions.append(tagged)
            else:
                validation_issues = repair_validation_issues or validation_issues

        # Status-integrity gate:
        # status is self-reported by the model with
        # no deterministic check behind it - confirmed corpus-wide that 20.3% of non-abstained KC
        # drafts (138/679) claimed grounded/partial with zero real admitted evidence
        # (evidence_lane == "ordered_pack_for_drafting") in their own packet. Forces status to
        # "abstained" when that holds; leaves contextual_kc_draft.text untouched (the model's
        # original text stays in this row for diagnostic purposes even though it's now correctly
        # excluded from the trustworthy-library surface via the existing abstained-handling path).
        normalized, status_integrity_override = apply_status_integrity_gate(packet, normalized)
        # The gate now reports both directions. The inverse one (an abstention on a packet that was
        # draftable, evidenced, and granted no abstention permission) changes no status - it is
        # surfaced as a validation issue so the unit reaches review instead of silently leaving a
        # hole in the library. Audited rate before this existed: 5 of 159 units.
        if (isinstance(status_integrity_override, dict)
                and status_integrity_override.get("code") == UNJUSTIFIED_ABSTENTION_CODE):
            validation_issues = list(validation_issues or [])
            validation_issues.append({
                "code": UNJUSTIFIED_ABSTENTION_CODE,
                "admitted_evidence_count": status_integrity_override.get("admitted_evidence_count"),
                "packet_support_state": status_integrity_override.get("packet_support_state"),
            })

        row = {
            "run_id": args.run_id,
            "created_utc": now_utc(),
            "knowledge_unit_id": unit_id(packet),
            "knowledge_unit_type": unit_type(packet),
            "canonical_name": canonical_name(packet),
            "packet_index": i,
            "model": args.model,
            "ollama_host": host,
            "num_ctx": args.num_ctx,
            "prompt_chars": len(prompt),
            "raw_response_chars": len(raw),
            "call_elapsed_seconds": round(call_elapsed, 3),
            "ollama_metadata": {k: v for k, v in api.items() if k != "response"},
            "draft": normalized,
            "parse_error": parse_error,
            "normalization_actions": normalization_actions,
            "parse_repair_attempted": parse_repair_attempted,
            "parse_repair_parse_error": parse_repair_parse_error,
            "parse_repair_validation_issues": parse_repair_validation_issues,
            "parse_repair_raw_response": parse_repair_raw_response if (parse_repair_parse_error or validation_issues) else "",
            "repair_attempted": repair_attempted,
            "repair_parse_error": repair_parse_error,
            "repair_validation_issues_before": repair_validation_issues_before,
            "repair_normalization_actions": repair_normalization_actions,
            "raw_response": raw if (parse_error or validation_issues) else "",
            "repair_raw_response": repair_raw_response if (repair_parse_error or validation_issues) else "",
            "validation_issues": validation_issues,
            "status_integrity_override": status_integrity_override,
            "source_packet": packet,
        }
        rows.append(row)
        if parse_error or validation_issues:
            failures.append({
                "knowledge_unit_id": unit_id(packet),
                "knowledge_unit_type": unit_type(packet),
                "canonical_name": canonical_name(packet),
                "parse_error": parse_error,
                "validation_issues": validation_issues,
            })

        write_jsonl(drafts_jsonl, rows)
        progress_json.write_text(json.dumps({
            "run_id": args.run_id,
            "created_utc": now_utc(),
            "processed_count": len(rows),
            "selected_packet_count": len(packets),
            "failure_count": len(failures),
            "last_packet_index": i,
            "last_packet_id": unit_id(packet),
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    elapsed = time.time() - start

    write_jsonl(drafts_jsonl, rows)

    summary = {
        "schema_version": "step67_v2_tiny_smoke_summary_v1",
        "created_utc": now_utc(),
        "run_id": args.run_id,
        "decision": "PASS_STEP67_V2_TINY_SMOKE_RUNTIME_READY_FOR_COMPACT_CLOSEOUT" if not failures else "FAIL_STEP67_V2_TINY_SMOKE_RUNTIME_OR_SCHEMA",
        "ready_for_compact_closeout": not failures,
        "ready_for_larger_run": False,
        "metrics": {
            "selected_packet_count": len(packets),
            "draft_row_count": len(rows),
            "failure_count": len(failures),
            "model_call_failed_count": sum(1 for r in rows for issue in (r.get("validation_issues") or []) if isinstance(issue, dict) and issue.get("code") == "model_call_failed"),
            "parse_repair_attempt_count": sum(1 for r in rows if r.get("parse_repair_attempted")),
            "parse_repair_success_count": sum(1 for r in rows if r.get("parse_repair_attempted") and not r.get("parse_error")),
            "schema_repair_attempt_count": sum(1 for r in rows if r.get("repair_attempted")),
            "schema_repair_success_count": sum(1 for r in rows if r.get("repair_attempted") and not r.get("validation_issues")),
            "unit_type_counter": {t: sum(1 for r in rows if r["knowledge_unit_type"] == t) for t in sorted(set(r["knowledge_unit_type"] for r in rows))},
            "elapsed_seconds": round(elapsed, 3),
            "model": args.model,
            "num_ctx": args.num_ctx,
            "ollama_host": host,
            "total_prompt_chars": sum(r["prompt_chars"] for r in rows),
            "total_raw_response_chars": sum(r["raw_response_chars"] for r in rows),
        },
        "source_paths": {
            "plan_json": str(args.plan_json),
            "selected_packets_jsonl": str(args.selected_packets_jsonl),
        },
        "artifacts": {
            "drafts_jsonl": str(drafts_jsonl),
        },
        "failures": failures,
        "policy": {
            "parent_topics_excluded": True,
            "kc_specific_criteria_model_authorship_forbidden": True,
            "topics_must_not_include_kc_specific_criteria": True,
            "claim_evidence_map_required": True,
        },
    }

    summary_json = args.out_dir / "STEP67_V2_TINY_SMOKE_SUMMARY.json"
    write_json(summary_json, summary)

    md = [
        "# Step6.7 v2 tiny smoke summary",
        "",
        f"- decision: `{summary['decision']}`",
        f"- ready_for_compact_closeout: `{summary['ready_for_compact_closeout']}`",
        "- ready_for_larger_run: `False`",
        f"- selected_packet_count: `{len(packets)}`",
        f"- draft_row_count: `{len(rows)}`",
        f"- failure_count: `{len(failures)}`",
        f"- model: `{args.model}`",
        f"- num_ctx: `{args.num_ctx}`",
        "",
        "## Failures",
    ]
    md += [f"- `{f['knowledge_unit_id']}`: {json.dumps(f, ensure_ascii=False)}" for f in failures] if failures else ["- none"]
    (args.out_dir / "STEP67_V2_TINY_SMOKE_SUMMARY.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("===== STEP6.7 V2 TINY SMOKE RUNTIME SUMMARY =====")
    print(json.dumps({
        "decision": summary["decision"],
        "ready_for_compact_closeout": summary["ready_for_compact_closeout"],
        "ready_for_larger_run": False,
        "selected_packet_count": len(packets),
        "draft_row_count": len(rows),
        "failure_count": len(failures),
        "metrics": summary["metrics"],
        "summary_json": str(summary_json),
        "summary_md": str(args.out_dir / "STEP67_V2_TINY_SMOKE_SUMMARY.md"),
        "drafts_jsonl": str(drafts_jsonl),
    }, indent=2, ensure_ascii=False))
    print("STEP67_V2_TINY_SMOKE_RUNTIME_SUMMARY_JSON=" + str(summary_json))
    print("STEP67_V2_TINY_SMOKE_RUNTIME_SUMMARY_MD=" + str(args.out_dir / "STEP67_V2_TINY_SMOKE_SUMMARY.md"))
    print("STEP67_V2_TINY_SMOKE_DRAFTS_JSONL=" + str(drafts_jsonl))
    print("STEP67_V2_TINY_SMOKE_RUNTIME_COMPLETE")

    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
