from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from kc_l.kc.validators import validate_kc_record  # noqa: E402


SUPPORTED_DEFINITION_STATUSES = {"coherent_supported", "fragmentary_supported"}
STEP65_CLOSEOUT_FILENAME = "STEP6_5_NEXT_SCALE_VALIDATION_CLOSEOUT_REPORT.txt"
REQUIRED_EXAMPLE_IDS = [
    "KC_CLF_DT_004",
    "KC_CLF_DT_006",
    "KC_CLF_NB_001",
    "KC_CLF_NB_004",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def format_rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return float(numerator) / float(denominator)


def format_delta(current: float, baseline: float) -> str:
    delta = current - baseline
    return f"{delta:+.4f}"


def parse_baseline_run_id(config_snapshot: dict[str, Any]) -> str:
    inputs = dict(config_snapshot.get("inputs") or {})
    summary_path = str(inputs.get("baseline_step6_4_2_summary_json") or "")
    name = Path(summary_path).parent.name
    suffix = "_step6_4_2"
    return name[: -len(suffix)] if name.endswith(suffix) else name


def resolve_paths(run_id: str) -> dict[str, Path]:
    run_dir = REPO_ROOT / "data" / "runs" / f"{run_id}_step6_4_2"
    processed_dir = REPO_ROOT / "data" / "processed" / "kc_library" / run_id
    return {
        "run_dir": run_dir,
        "processed_dir": processed_dir,
        "summary": run_dir / "summary.json",
        "invocation": run_dir / "invocation.json",
        "config_snapshot": run_dir / "config_snapshot.yaml",
        "tool_versions": run_dir / "tool_versions.json",
        "generic_closeout": run_dir / "STEP6_4_2_CLOSEOUT_REPORT.txt",
        "kc_library": processed_dir / "kc_library.jsonl",
        "definition_short_audit": processed_dir / "definition_short_contract_audit.jsonl",
        "tier2_queue": processed_dir / "tier2_recovery_queue.jsonl",
        "traces_dir": processed_dir / "enrichment_traces",
        "report": run_dir / STEP65_CLOSEOUT_FILENAME,
        "schema": REPO_ROOT / "schema.json",
    }


def collect_top_failure_reasons(queue_rows: Iterable[dict[str, Any]]) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in queue_rows:
        for reason in row.get("reasons") or []:
            counter[str(reason)] += 1
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))


def build_example_rows(
    example_ids: list[str],
    records_by_kc: dict[str, dict[str, Any]],
    trace_by_kc: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kc_id in example_ids:
        record = records_by_kc.get(kc_id)
        trace = trace_by_kc.get(kc_id)
        if record is None or trace is None:
            rows.append(
                {
                    "kc_id": kc_id,
                    "missing": True,
                }
            )
            continue
        short_audit = dict(trace.get("definition_short_audit") or {})
        contamination_summary = dict(trace.get("contamination_summary") or {})
        validation_errors = validate_kc_record(record)
        rows.append(
            {
                "kc_id": kc_id,
                "missing": False,
                "canonical_name": str(record.get("canonical_name") or ""),
                "accepted_quote_count": len(list(trace.get("selected_candidate_ids") or [])),
                "definition_full_status": str(trace.get("definition_status") or ""),
                "definition_short_source_type": str(short_audit.get("definition_short_source_type") or "unsupported_or_empty"),
                "definition_short_contract_ok": bool(short_audit.get("definition_short_contract_ok")),
                "tier1": int(trace.get("base_tier") or 0) >= 1,
                "definition_status_supported": str(trace.get("definition_status") or "") in SUPPORTED_DEFINITION_STATUSES,
                "usable_curriculum": bool(trace.get("usable_curriculum")),
                "contamination": str(contamination_summary.get("category") or "clean") != "clean",
                "schema_valid": not validation_errors,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the Step 6.5 next-scale validation closeout report.")
    parser.add_argument("--run-id", required=True, help="Step 6.4.2 run id without suffix.")
    args = parser.parse_args()

    paths = resolve_paths(args.run_id)
    summary = load_json(paths["summary"])
    invocation = load_json(paths["invocation"])
    config_snapshot = load_json(paths["config_snapshot"])
    tool_versions = load_json(paths["tool_versions"])
    stats = dict(summary.get("stats") or {})
    total_kcs = int(stats.get("total_kcs", 0))

    baseline_run_id = parse_baseline_run_id(config_snapshot)
    baseline_paths = resolve_paths(baseline_run_id)
    baseline_summary = load_json(baseline_paths["summary"])
    baseline_stats = dict(baseline_summary.get("stats") or {})

    records = load_jsonl(paths["kc_library"])
    records_by_kc = {str(row["kc_id"]): row for row in records}
    queue_rows = load_jsonl(paths["tier2_queue"])
    top_failure_reasons = collect_top_failure_reasons(queue_rows)

    trace_by_kc: dict[str, dict[str, Any]] = {}
    for kc_id in REQUIRED_EXAMPLE_IDS:
        trace_path = paths["traces_dir"] / f"{kc_id}.json"
        if trace_path.exists():
            trace_by_kc[kc_id] = load_json(trace_path)

    example_rows = build_example_rows(REQUIRED_EXAMPLE_IDS, records_by_kc, trace_by_kc)

    tier1_target = 48
    contamination_count = int(stats.get("contamination_count", 0))
    quote_mismatch_count = int(stats.get("quote_mismatch_count", 0))
    schema_error_count = int(stats.get("schema_error_count", 0))
    definition_short_contract_fail_count = int(stats.get("definition_short_contract_fail_count", 0))

    usable_rate = format_rate(int(stats.get("usable_curriculum_count", 0)), total_kcs)
    supported_rate = format_rate(int(stats.get("definition_status_supported_count", 0)), total_kcs)
    false_rejection_rate = float(stats.get("false_rejection_failure_rate", 0.0))
    baseline_usable_rate = format_rate(
        int(baseline_stats.get("usable_curriculum_count", 0)),
        int(baseline_stats.get("total_kcs", 0)),
    )
    baseline_supported_rate = format_rate(
        int(baseline_stats.get("definition_status_supported_count", 0)),
        int(baseline_stats.get("total_kcs", 0)),
    )
    baseline_false_rejection_rate = float(baseline_stats.get("false_rejection_failure_rate", 0.0))
    thinking_used_frac = float(stats.get("thinking_used_frac", 0.0))
    baseline_thinking_used_frac = float(baseline_stats.get("thinking_used_frac", 0.0))

    acceptance_checks = [
        ("total_kcs", total_kcs == tier1_target, f"{total_kcs} vs required {tier1_target}"),
        ("tier1_count", int(stats.get("tier1_count", 0)) == tier1_target, f"{int(stats.get('tier1_count', 0))} vs required {tier1_target}"),
        ("contamination_count", contamination_count == 0, str(contamination_count)),
        ("quote_mismatch_count", quote_mismatch_count == 0, str(quote_mismatch_count)),
        ("schema_error_count", schema_error_count == 0, str(schema_error_count)),
        (
            "definition_short_contract_fail_count",
            definition_short_contract_fail_count == 0,
            str(definition_short_contract_fail_count),
        ),
        (
            "false_rejection_failure_rate_no_worse_than_32kc",
            false_rejection_rate <= baseline_false_rejection_rate + 1e-12,
            f"{false_rejection_rate:.4f} vs baseline {baseline_false_rejection_rate:.4f}",
        ),
        (
            "usable_curriculum_rate_no_collapse_vs_32kc",
            usable_rate + 1e-12 >= baseline_usable_rate,
            f"{usable_rate:.4f} vs baseline {baseline_usable_rate:.4f}",
        ),
        (
            "definition_status_supported_rate_no_collapse_vs_32kc",
            supported_rate + 1e-12 >= baseline_supported_rate,
            f"{supported_rate:.4f} vs baseline {baseline_supported_rate:.4f}",
        ),
    ]
    hard_targets_met = all(item[1] for item in acceptance_checks)

    advisory_reasons: list[str] = []
    if thinking_used_frac > baseline_thinking_used_frac + 0.02:
        advisory_reasons.append(
            f"ThinkingUsedFracWorsened:{thinking_used_frac:.4f}>{baseline_thinking_used_frac:.4f}+0.02"
        )
    for example in example_rows:
        if example.get("missing"):
            advisory_reasons.append(f"MissingExampleTrace:{example['kc_id']}")
            continue
        if not bool(example["tier1"]):
            advisory_reasons.append(f"ExampleTier1Drop:{example['kc_id']}")
        if bool(example["contamination"]):
            advisory_reasons.append(f"ExampleContamination:{example['kc_id']}")
        if not bool(example["schema_valid"]):
            advisory_reasons.append(f"ExampleSchemaInvalid:{example['kc_id']}")
        if not bool(example["usable_curriculum"]):
            advisory_reasons.append(f"ExampleNotUsable:{example['kc_id']}")

    recommendation_status = "READY_FOR_FULL_128" if hard_targets_met and not advisory_reasons else "NOT_READY_FOR_FULL_128"
    recommendation_reasons = [
        f"{name}:{detail}"
        for name, passed, detail in acceptance_checks
        if not passed
    ] + advisory_reasons

    lines: list[str] = []
    lines.append("STEP 6.5 NEXT-SCALE VALIDATION CLOSEOUT REPORT")
    lines.append("")
    lines.append("1) Executive summary")
    lines.append("- Mode: dry_run")
    lines.append(f"- Run id: {args.run_id}")
    lines.append(f"- Compared against accepted 32-KC validation run: {baseline_run_id}")
    lines.append(f"- Acceptance: {'PASS' if hard_targets_met else 'FAIL'}")
    lines.append(f"- Recommendation: {recommendation_status}")
    lines.append(f"- total_kcs: {total_kcs}")
    lines.append(f"- tier1_count: {int(stats.get('tier1_count', 0))}")
    lines.append(f"- usable_curriculum_count: {int(stats.get('usable_curriculum_count', 0))}")
    lines.append(f"- usable_curriculum_rate: {usable_rate:.4f}")
    lines.append(f"- definition_status_supported_count: {int(stats.get('definition_status_supported_count', 0))}")
    lines.append(f"- definition_status_supported_rate: {supported_rate:.4f}")
    lines.append(f"- false_rejection_failure_rate: {false_rejection_rate:.4f}")
    lines.append(f"- thinking_used_frac: {thinking_used_frac:.4f}")
    lines.append("")
    lines.append("2) Run metadata")
    lines.append(f"- Config: {invocation.get('config')}")
    lines.append(f"- limit_kcs: {invocation.get('limit_kcs')}")
    lines.append(f"- Baseline summary: data/runs/{baseline_run_id}_step6_4_2/summary.json")
    lines.append(f"- Baseline closeout: data/runs/{baseline_run_id}_step6_4_2/STEP6_4_9_CONTRACT_DECOUPLE_CLOSEOUT_REPORT.txt")
    lines.append(f"- Generation preferred model: {((config_snapshot.get('models') or {}).get('generation') or {}).get('preferred_model', '')}")
    lines.append(f"- Gate model: {((config_snapshot.get('models') or {}).get('gate_llm') or {}).get('model', '')}")
    lines.append(f"- Reranker preferred model: {((config_snapshot.get('models') or {}).get('reranker') or {}).get('preferred', '')}")
    lines.append(f"- Reranker device: {((stats.get('bootstrap') or {}).get('device') or '')}")
    lines.append(f"- Ollama version: {tool_versions.get('ollama_cli', '')}")
    lines.append("")
    lines.append("3) Acceptance table")
    for name, passed, detail in acceptance_checks:
        lines.append(f"- {name}: {'PASS' if passed else 'FAIL'} | {detail}")
    lines.append(f"- usable_curriculum_count_delta_vs_32kc: {int(stats.get('usable_curriculum_count', 0)) - int(baseline_stats.get('usable_curriculum_count', 0)):+d}")
    lines.append(f"- usable_curriculum_rate_delta_vs_32kc: {format_delta(usable_rate, baseline_usable_rate)}")
    lines.append(
        f"- definition_status_supported_count_delta_vs_32kc: {int(stats.get('definition_status_supported_count', 0)) - int(baseline_stats.get('definition_status_supported_count', 0)):+d}"
    )
    lines.append(f"- definition_status_supported_rate_delta_vs_32kc: {format_delta(supported_rate, baseline_supported_rate)}")
    lines.append(
        f"- false_rejection_failures_delta_vs_32kc: {int(stats.get('false_rejection_failures', 0)) - int(baseline_stats.get('false_rejection_failures', 0)):+d}"
    )
    lines.append(f"- false_rejection_failure_rate_delta_vs_32kc: {format_delta(false_rejection_rate, baseline_false_rejection_rate)}")
    lines.append(f"- thinking_used_frac_delta_vs_32kc: {format_delta(thinking_used_frac, baseline_thinking_used_frac)}")
    lines.append("")
    lines.append("4) Top failure reasons")
    if top_failure_reasons:
        for reason, count in top_failure_reasons[:10]:
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("5) Contamination adjudication breakdown")
    lines.append(f"- contamination_count: {contamination_count}")
    lines.append(f"- hard_contamination_count: {int(stats.get('hard_contamination_count', 0))}")
    lines.append(f"- sibling_ambiguity_count: {int(stats.get('sibling_ambiguity_count', 0))}")
    lines.append(f"- sibling_ambiguity_resolved_count: {int(stats.get('sibling_ambiguity_resolved_count', 0))}")
    lines.append(f"- sibling_ambiguity_failed_count: {int(stats.get('sibling_ambiguity_failed_count', 0))}")
    competitor_breakdown = dict(stats.get("contamination_competitor_kc_ids") or {})
    if competitor_breakdown:
        lines.append("- competitor_kc_ids_involved:")
        for kc_id, count in sorted(competitor_breakdown.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {kc_id}: {count}")
    else:
        lines.append("- competitor_kc_ids_involved: none")
    lines.append("")
    lines.append("6) Definition_short final-record audit")
    lines.append(f"- definition_short_nonempty_count: {int(stats.get('definition_short_nonempty_count', 0))}")
    lines.append(f"- definition_short_contract_ok_count: {int(stats.get('definition_short_contract_ok_count', 0))}")
    lines.append(f"- definition_short_contract_fail_count: {definition_short_contract_fail_count}")
    short_source_breakdown = dict(stats.get("definition_short_source_breakdown") or {})
    lines.append(
        f"- definition_short_source_breakdown.derived_from_definition_full: {int(short_source_breakdown.get('derived_from_definition_full', 0))}"
    )
    lines.append(
        f"- definition_short_source_breakdown.direct_quote_short: {int(short_source_breakdown.get('direct_quote_short', 0))}"
    )
    lines.append(
        f"- definition_short_source_breakdown.unsupported_or_empty: {int(short_source_breakdown.get('unsupported_or_empty', 0))}"
    )
    lines.append(f"- definition_short_post_preserve_rewrite_count: {int(stats.get('definition_short_post_preserve_rewrite_count', 0))}")
    lines.append(f"- definition_short_post_preserve_drop_count: {int(stats.get('definition_short_post_preserve_drop_count', 0))}")
    lines.append("")
    lines.append("7) Contract-decoupling audit")
    lines.append(f"- tier1_post_short_cleanup_regression_count: {int(stats.get('tier1_post_short_cleanup_regression_count', 0))}")
    lines.append(f"- tier1_post_short_cleanup_restored_count: {int(stats.get('tier1_post_short_cleanup_restored_count', 0))}")
    lines.append(
        f"- definition_status_post_short_cleanup_regression_count: {int(stats.get('definition_status_post_short_cleanup_regression_count', 0))}"
    )
    lines.append(
        f"- definition_status_post_short_cleanup_restored_count: {int(stats.get('definition_status_post_short_cleanup_restored_count', 0))}"
    )
    source_breakdown_selected_quotes = dict(stats.get("source_breakdown_selected_quotes") or {})
    lines.append(
        f"- source_breakdown_selected_quotes.step5_3_primary: {int(source_breakdown_selected_quotes.get('step5_3_primary', 0))}"
    )
    lines.append(
        f"- source_breakdown_selected_quotes.step6_3_anchor: {int(source_breakdown_selected_quotes.get('step6_3_anchor', 0))}"
    )
    lines.append(
        f"- source_breakdown_selected_quotes.step4_neighbor: {int(source_breakdown_selected_quotes.get('step4_neighbor', 0))}"
    )
    role_breakdown = dict(stats.get("role_source_breakdown") or {})
    selected_roles = dict(role_breakdown.get("selected_quotes") or {})
    kc_roles = dict(role_breakdown.get("kcs") or {})
    lines.append(f"- role_source_breakdown.selected_quotes.heuristic: {int(selected_roles.get('heuristic', 0))}")
    lines.append(f"- role_source_breakdown.selected_quotes.model: {int(selected_roles.get('model', 0))}")
    lines.append(f"- role_source_breakdown.kcs.heuristic: {int(kc_roles.get('heuristic', 0))}")
    lines.append(f"- role_source_breakdown.kcs.model: {int(kc_roles.get('model', 0))}")
    lines.append("")
    lines.append("8) Detailed KC examples")
    for row in example_rows:
        if row.get("missing"):
            lines.append(f"- {row['kc_id']}: missing trace or record")
            continue
        lines.append(
            f"- {row['kc_id']} | {row['canonical_name']} "
            f"| accepted_quote_count={row['accepted_quote_count']} "
            f"| definition_full_status={row['definition_full_status']} "
            f"| definition_short_source_type={row['definition_short_source_type']} "
            f"| definition_short_contract_ok={yes_no(bool(row['definition_short_contract_ok']))} "
            f"| Tier1={yes_no(bool(row['tier1']))} "
            f"| definition_status_supported={yes_no(bool(row['definition_status_supported']))} "
            f"| usable_curriculum={yes_no(bool(row['usable_curriculum']))} "
            f"| contamination={yes_no(bool(row['contamination']))} "
            f"| schema_valid={yes_no(bool(row['schema_valid']))}"
        )
    lines.append("")
    lines.append("9) Recommendation")
    lines.append(f"- {recommendation_status}")
    if recommendation_reasons:
        for reason in recommendation_reasons:
            lines.append(f"- Reason: {reason}")
    else:
        lines.append("- Reason: All hard targets were met and no additional advisory blockers were found.")
    lines.append("")

    report_text = "\n".join(lines)
    write_text(paths["report"], report_text)
    print(report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
