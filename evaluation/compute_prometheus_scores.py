"""Prometheus-2 (prometheus-eval/prometheus-7b-v2.0) absolute-grading groundedness judge.

Scores each unit's drafted claim against the evidence it actually saw (same resolution
method as compute_hhem_scores.py: row['source_packet']['evidence_for_synthesis'], frozen
at generation time - not the external, drift-prone evidence-pack file).

Rubric criterion: is the drafted text a FAITHFUL synthesis of the evidence - i.e. free of
specific invented details (numbers, definitions, named relationships) not supported by the
evidence, and free of conflating the evidence's actual subject with a distinct related
concept? Reasonable, uncontroversial general-domain elaboration that does not contradict the
evidence is explicitly NOT penalized (this rubric intentionally matches how own
manual Tier-2 read judged things - holistic faithfulness, not pure extractive entailment; see
the KC_EVAL_BASIC_003 calibration example below, where standard-but-not-literally-stated domain
knowledge is treated as a Score-5 exemplar, not a violation).

Calibration examples embedded in the rubric's score descriptions are real, verbatim
claim+evidence pairs pulled from own confirmed manual audits (not synthesized):
  - Score 5 (faithful): KC_CLF_DT_001 Hunt's Algorithm, KC_EVAL_BASIC_003 Precision
  - Score 1 (conflation): KC_CLU_DBS_006 Density-Reachable
  - Score 2 (invented specifics): KC_CLU_SIM_005 Cosine Similarity

Usage: python3 compute_prometheus_scores.py --run-id <run_id> --postprocessed-jsonl <path> --out <path> [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

PROMETHEUS_MODEL_DIR = "/path/to/scratch/kc_l/hf_models/prometheus_7b_v2_0"

SYSTEM_MESSAGE = (
    "You are a fair judge assistant tasked with evaluating the groundedness of a short "
    "educational text against specific evidence excerpts."
)

RUBRIC_CRITERIA = (
    "Is the response strictly and accurately grounded in the evidence? Judge ONLY the factual "
    "claims actually asserted. Two specific failure triggers determine a LOW score: "
    "(A) CONFLATION - the response's core defining fact is, per the evidence, actually a fact "
    "about a different, distinct concept, not the one being explained; "
    "(B) INVENTED SPECIFICS - the response confidently states a precise number, named "
    "sub-relationship, or defined range that has no basis anywhere in the evidence and is not "
    "universally-known domain knowledge. "
    "IMPORTANT: hedging or flagging uncertainty about a genuine evidence gap (e.g. saying a "
    "detail is 'not explicitly stated' or 'unclear from the available evidence') is GOOD "
    "calibration, not a flaw - it must NEVER by itself reduce the score. A response that "
    "honestly flags a gap can still score a 5. Only score low for trigger (A) or (B) above - "
    "confidently asserted, unsupported, or conflated claims - never for hedging alone."
)

REFERENCE_ANSWER = (
    "A maximally grounded response states only what is explicitly supported by the evidence "
    "below, phrased naturally. It may add standard, uncontroversial domain knowledge that does "
    "not contradict the evidence, and it may explicitly flag a gap instead of guessing - neither "
    "lowers the score. It must never assert a specific number, definition, or named relationship "
    "that has no basis in the evidence, and it must never describe a different (even if related) "
    "concept as if it were the one the evidence is actually about."
)

SCORE_DESCRIPTIONS = {
    1: (
        "TRIGGER: CONFLATION. The response's core defining fact is, per the evidence, actually a "
        "fact about a DIFFERENT concept than the one being explained - stated confidently, as if "
        "it correctly defines the target. Applies regardless of how fluent or natural the prose "
        "sounds. Short example: target concept is 'Density-Reachable'; evidence given is actually "
        "the definition of a different, related term ('Border point: not core, but within ε of a "
        "core point'); response confidently states 'A point is Density-Reachable if it is within "
        "epsilon of a core point' - it has silently substituted the border-point fact as if it "
        "defined density-reachability. That substitution alone is a Score 1, even though nothing "
        "else in the response is false."
    ),
    2: (
        "TRIGGER: INVENTED SPECIFICS (and no conflation). The response confidently states at "
        "least one precise number, named sub-part, or defined range that appears nowhere in the "
        "evidence and is not universal domain knowledge. Short example: evidence is only "
        "'Cosine similarity is a similarity score.'; response asserts 'a value between -1 and 1... "
        "0 indicates perpendicular, -1 indicates opposite' - specific numeric claims invented "
        "wholesale from a one-sentence evidence base."
    ),
    3: (
        "No conflation, no invented specifics, but one or two vague, unverifiable elaborations "
        "go beyond what the evidence clearly supports without being contradicted by it. Hedged/"
        "flagged uncertainty about a real gap does NOT belong in this tier by itself - if the "
        "only issue is honest hedging with otherwise accurate content, score 4 or 5 instead."
    ),
    4: (
        "No conflation, no invented specifics. The response closely tracks the evidence with "
        "only minor connective elaboration, OR it accurately conveys the evidence while also "
        "explicitly and honestly flagging a genuine gap instead of guessing - the hedging itself "
        "is not a defect and must not be scored as one."
    ),
    5: (
        "No conflation, no invented specifics. The response is a fully accurate, faithful "
        "synthesis of the evidence. Elaboration beyond the evidence is limited to standard, "
        "well-established, uncontroversial domain knowledge that does not contradict it. Example "
        "A: evidence describes Hunt's algorithm's recursive tree-growing, its simplifying "
        "assumptions, and that empty child nodes can arise and be labeled with the parent's most "
        "frequent class - the response synthesizes exactly this, faithfully. Example B: evidence "
        "is only 'Precision is also referred as the positive predicted value (PPV).' and the "
        "response correctly restates this AND adds "
        "'closely related to the false discovery rate (FDR), which is defined as 1-p' - this "
        "added fact is standard, true, well-established domain knowledge consistent with the "
        "evidence, not an invented specific, so it does not lower the score."
    ),
}


def build_prompt(evidence_text: str, claim_text: str) -> str:
    rubric_lines = [RUBRIC_CRITERIA]
    for score in range(1, 6):
        rubric_lines.append(f"Score {score}: {SCORE_DESCRIPTIONS[score]}")
    rubric_block = "\n".join(rubric_lines)

    instruction = (
        "Evaluate whether the following short educational text (a knowledge-component draft) "
        "is faithfully grounded in the evidence excerpts given below it.\n\n"
        f"###Evidence:\n{evidence_text}\n\n"
        "###Text to evaluate for groundedness in the evidence above:"
    )

    absolute_prompt = f"""###Task Description:
An instruction (might include an Input inside it), a response to evaluate, a reference answer that gets a score of 5, and a score rubric representing a evaluation criteria are given.
1. Write a detailed feedback that assess the quality of the response strictly based on the given score rubric, not evaluating in general.
2. After writing a feedback, write a score that is an integer between 1 and 5. You should refer to the score rubric.
3. The output format should look as follows: \"Feedback: (write a feedback for criteria) [RESULT] (an integer number between 1 and 5)\"
4. Please do not generate any other opening, closing, and explanations.

###The instruction to evaluate:
{instruction}

###Response to evaluate:
{claim_text}

###Reference Answer (Score 5):
{REFERENCE_ANSWER}

###Score Rubrics:
[{rubric_block}]

###Feedback: """

    return f"[INST] {SYSTEM_MESSAGE}\n\n{absolute_prompt} [/INST]"


def parse_feedback_and_score(generated_text: str) -> tuple[str, int | None]:
    if "[RESULT]" not in generated_text:
        return generated_text.strip(), None
    feedback, _, tail = generated_text.partition("[RESULT]")
    feedback = feedback.replace("Feedback:", "", 1).strip()
    match = re.search(r"-?\d+", tail)
    score = int(match.group()) if match else None
    if score is not None and not (1 <= score <= 5):
        score = None
    return feedback, score


def draft_key_for_unit_type(unit_type: str) -> str:
    return "contextual_topic_draft" if unit_type == "topic" else "contextual_kc_draft"


def extract_claim_and_evidence(row: dict) -> tuple[str, str, str, str]:
    unit_id = row.get("knowledge_unit_id") or (row.get("draft") or {}).get("knowledge_unit_id")
    unit_type = row.get("knowledge_unit_type") or (row.get("draft") or {}).get("knowledge_unit_type") or "kc"
    draft = row.get("draft") or {}
    ck = draft.get(draft_key_for_unit_type(unit_type)) or {}
    claim_text = str(ck.get("text") or "")
    draft_status = ck.get("status")

    source_packet = row.get("source_packet") or {}
    evidence_items = source_packet.get("evidence_for_synthesis") or []
    evidence_texts = [str(item.get("text") or "").strip() for item in evidence_items if isinstance(item, dict)]
    evidence_texts = [t for t in evidence_texts if t]
    evidence_text = "\n".join(evidence_texts)

    return str(unit_id), claim_text, evidence_text, draft_status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--postprocessed-jsonl", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None, help="score only first N eligible units (for sanity checks)")
    ap.add_argument("--unit-ids", default=None, help="comma-separated unit_ids to restrict scoring to (for sanity checks)")
    args = ap.parse_args()

    print(f"Loading Prometheus-2 model+tokenizer from {PROMETHEUS_MODEL_DIR} ...")
    tokenizer = AutoTokenizer.from_pretrained(PROMETHEUS_MODEL_DIR)
    # No device_map="auto" - that requires the `accelerate` package, which isn't installed here
    # (and isn't needed: this is a single-GPU job, gres=gpu:1, and the 14.5GB bf16 model fits
    # comfortably on one A100 80GB - accelerate's device_map is for multi-GPU/CPU-offload sharding).
    model = AutoModelForCausalLM.from_pretrained(PROMETHEUS_MODEL_DIR, dtype=torch.bfloat16)
    model = model.to("cuda")
    model.eval()
    print("Model loaded.")

    rows = [json.loads(line) for line in open(args.postprocessed_jsonl, encoding="utf-8")]
    print(f"Loaded {len(rows)} rows for run_id={args.run_id}")

    restrict_ids = set(args.unit_ids.split(",")) if args.unit_ids else None

    items = []
    skipped = []
    for row in rows:
        unit_id, claim_text, evidence_text, draft_status = extract_claim_and_evidence(row)
        if restrict_ids is not None and unit_id not in restrict_ids:
            continue
        if not claim_text.strip() or not evidence_text.strip():
            skipped.append(unit_id)
            continue
        items.append({
            "unit_id": unit_id,
            "canonical_name": row.get("canonical_name"),
            "knowledge_unit_type": row.get("knowledge_unit_type"),
            "draft_status": draft_status,
            "claim_text": claim_text,
            "evidence_text": evidence_text,
        })

    if args.limit is not None:
        items = items[: args.limit]

    print(f"Scoring {len(items)} claim/evidence pairs ({len(skipped)} skipped - empty claim or no evidence)")

    results = []
    for i, item in enumerate(items):
        prompt = build_prompt(item["evidence_text"], item["claim_text"])
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
                temperature=None,
                top_p=None,
                pad_token_id=tokenizer.eos_token_id,
            )
        generated = tokenizer.decode(
            output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
        )
        feedback, score = parse_feedback_and_score(generated)
        results.append({
            "unit_id": item["unit_id"],
            "canonical_name": item["canonical_name"],
            "knowledge_unit_type": item["knowledge_unit_type"],
            "draft_status": item["draft_status"],
            "prometheus_score": score,
            "prometheus_feedback": feedback,
            "raw_generation": generated,
        })
        print(f"  [{i + 1}/{len(items)}] {item['unit_id']} -> score={score}")

    parsed_scores = [r["prometheus_score"] for r in results if r["prometheus_score"] is not None]
    parse_failures = [r["unit_id"] for r in results if r["prometheus_score"] is None]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_id": args.run_id,
            "total_rows": len(rows),
            "scored_count": len(results),
            "skipped_count": len(skipped),
            "skipped_unit_ids": skipped,
            "parse_failure_count": len(parse_failures),
            "parse_failure_unit_ids": parse_failures,
            "mean_prometheus_score": sum(parsed_scores) / len(parsed_scores) if parsed_scores else None,
            "results": results,
        }, f, indent=2)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
