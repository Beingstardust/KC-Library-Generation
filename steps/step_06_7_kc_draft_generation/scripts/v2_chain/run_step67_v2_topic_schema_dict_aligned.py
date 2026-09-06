from __future__ import annotations

import importlib.util
import os
import pathlib
from typing import Any, Dict, Mapping


SOURCE_SCHEMA_RUNNER = pathlib.Path(os.environ["KC_L_SOURCE_SCHEMA_RUNNER"])

spec = importlib.util.spec_from_file_location("schema_contract_source_runner", SOURCE_SCHEMA_RUNNER)
source = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(source)


def child_coverage_item_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "child_kc_id",
            "child_kc_name",
            "coverage_status",
            "coverage_summary",
            "supporting_evidence_ids",
        ],
        "properties": {
            "child_kc_id": {"type": "string"},
            "child_kc_name": {"type": "string"},
            "coverage_status": {
                "type": "string",
                "enum": ["covered", "partially_covered", "not_covered", "insufficient_evidence"],
            },
            "coverage_summary": {"type": "string"},
            "supporting_evidence_ids": source.schema_string_array(),
        },
        "additionalProperties": False,
    }


def topic_json_schema_dict_aligned(packet: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "knowledge_unit_id",
            "knowledge_unit_type",
            "canonical_name",
            "contextual_topic_draft",
            "child_kc_summaries",
            "child_kc_coverage_summary",
            "evaluation_support",
            "evidence_map",
        ],
        "properties": {
            "knowledge_unit_id": {"type": "string"},
            "knowledge_unit_type": {"type": "string", "enum": ["topic"]},
            "canonical_name": {"type": "string"},
            "contextual_topic_draft": {
                "type": "object",
                "required": [
                    "status",
                    "text",
                    "supporting_evidence_ids",
                    "supporting_child_kc_ids",
                    "coverage_notes",
                    "uncertainty_notes",
                ],
                "properties": {
                    "status": {"type": "string", "enum": ["grounded", "partial", "abstained"]},
                    "text": {"type": "string"},
                    "supporting_evidence_ids": source.schema_string_array(),
                    "supporting_child_kc_ids": source.schema_string_array(),
                    "coverage_notes": source.schema_string_array(),
                    "uncertainty_notes": source.schema_string_array(),
                },
                "additionalProperties": False,
            },
            "child_kc_summaries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["child_kc_id", "child_kc_name", "summary", "supporting_evidence_ids"],
                    "properties": {
                        "child_kc_id": {"type": "string"},
                        "child_kc_name": {"type": "string"},
                        "summary": {"type": "string"},
                        "supporting_evidence_ids": source.schema_string_array(),
                    },
                    "additionalProperties": False,
                },
            },
            "child_kc_coverage_summary": {
                "type": "object",
                "required": [
                    "included_child_kcs",
                    "missing_or_weak_child_kcs",
                    "topic_boundary_notes",
                ],
                "properties": {
                    "included_child_kcs": {
                        "type": "array",
                        "items": child_coverage_item_schema(),
                    },
                    "missing_or_weak_child_kcs": {
                        "type": "array",
                        "items": child_coverage_item_schema(),
                    },
                    "topic_boundary_notes": source.schema_string_array(),
                },
                "additionalProperties": False,
            },
            "evaluation_support": source.schema_evaluation_support(),
            "evidence_map": source.schema_evidence_map(),
        },
        "additionalProperties": False,
    }


def output_schema_dict_aligned(packet: Mapping[str, Any]) -> Dict[str, Any]:
    if source.unit_type(packet) == "topic":
        return topic_json_schema_dict_aligned(packet)
    return source.kc_json_schema(packet)


old_make_prompt = source.make_prompt


def make_prompt_dict_aligned(base_mod: Any, packet: Mapping[str, Any], schema: Mapping[str, Any]) -> str:
    prompt = old_make_prompt(base_mod, packet, schema)

    if source.unit_type(packet) == "topic":
        prompt += (
            "\n\nTOPIC VALIDATOR CONTRACT REQUIREMENT:\n"
            "For topic rows, child_kc_coverage_summary must be an object, not an array.\n"
            "Use exactly these keys inside child_kc_coverage_summary: included_child_kcs, missing_or_weak_child_kcs, topic_boundary_notes.\n"
            "Put child KCs that are meaningfully summarized by the topic draft in included_child_kcs.\n"
            "Put child KCs with weak, missing, or only name-level support in missing_or_weak_child_kcs.\n"
            "Each child coverage item must include child_kc_id, child_kc_name, coverage_status, coverage_summary, and supporting_evidence_ids.\n"
            "contextual_topic_draft.supporting_child_kc_ids must list only child KC IDs actually supported by the topic draft.\n"
            "Do not invent child KC IDs. Use only child IDs present in the packet.\n"
            "Do not include kc_specific_criteria in topic rows.\n"
        )

    return prompt


source.topic_json_schema = topic_json_schema_dict_aligned
source.output_schema = output_schema_dict_aligned
source.make_prompt = make_prompt_dict_aligned

output_schema = output_schema_dict_aligned
topic_json_schema = topic_json_schema_dict_aligned
make_prompt = make_prompt_dict_aligned

if __name__ == "__main__":
    raise SystemExit(source.run())
