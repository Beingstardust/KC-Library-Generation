"""Control 6 comparison: seed-blind reference (Reviewer C) vs the seeded expert reference.

Blinded and order-randomised. The judge is shown two descriptions labelled A and B with no
indication of which is which, so it cannot favour the longer, more polished, or machine-seeded one
by recognising it. The A/B mapping is recorded for analysis.

IMPORTANT SCOPE LIMIT, applied honestly rather than papered over: Reviewer C's descriptions average
~24 words against the seeded reference's ~150, and cite ~1 passage each. The MISSING_CONTENT
direction is therefore uninterpretable - a 24-word definition will always look less complete than a
150-word one, for reasons of effort rather than bias. What the comparison CAN test is whether the
seeded reference distorts the concept or asserts content the corpus does not support, which are the
two failure modes that would actually invalidate it.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

BASE = Path(__file__).parent
REF_EVAL = BASE.parent.parent / "reference_eval"
sys.path.insert(0, str(REF_EVAL))

import reference_judge_prompts as P   # noqa: E402
from run_reference_judge import call_and_validate  # noqa: E402

DEFAULT_LIB = BASE.parent / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"
SEED = 20260901

LABELS = [
    "SUBSTANTIVELY_EQUIVALENT",
    "BOTH_VALID_DIFFERENT_FORMULATION",
    "B_MISSING_CONTENT_PRESENT_IN_A",
    "B_ASSERTS_CONTENT_A_DOES_NOT_SUPPORT",
    "MATERIAL_SEMANTIC_DIFFERENCE",
]


def schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["task", "relationship"],
        "properties": {
            "task": {"type": "string", "enum": ["REFERENCE_COMPARISON"]},
            "relationship": {"type": "string", "enum": LABELS},
            "rationale": {"type": "string", "maxLength": 400, "pattern": r"^[^\r\n]*$"},
        },
    }


def build_prompt(canonical: str, hierarchy: str, a: str, b: str, passages: list[str]) -> str:
    psg = "\n".join(f"- {p.strip()}" for p in passages) or "(none recorded)"
    p = f"""You are comparing two independently written descriptions of the same course concept.

CONCEPT: {canonical}
LOCATION IN SYLLABUS: {hierarchy}

SOURCE PASSAGES recorded from the course material for this concept:
{psg}

DESCRIPTION A:
{a.strip}

DESCRIPTION B:
{b.strip}

TASK
Judge the RELATIONSHIP between them on substantive content only. Differences in length, wording,
polish or level of detail are NOT differences in content - one description may be far shorter than
the other and still say the same thing.

  SUBSTANTIVELY_EQUIVALENT             - same content about what the concept is
  BOTH_VALID_DIFFERENT_FORMULATION     - both defensible, different framing or emphasis
  B_MISSING_CONTENT_PRESENT_IN_A       - A states defining content about the concept that B omits
  B_ASSERTS_CONTENT_A_DOES_NOT_SUPPORT - B asserts something about the concept that neither A nor
                                         the source passages support
  MATERIAL_SEMANTIC_DIFFERENCE         - they disagree about what the concept IS

Do not use lexical overlap. Judge meaning.

Return JSON with "task": "REFERENCE_COMPARISON" and a "relationship"."""
    P.assert_blinded(p)
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--reviewer", type=Path, default=BASE / "reviewer_c_worksheet.jsonl")
    ap.add_argument("--out", type=Path, default=BASE / "comparison" / "seed_audit_comparison.jsonl")
    ap.add_argument("--lib", type=Path, default=DEFAULT_LIB)
    args = ap.parse_args()
    LIB = args.lib

    raw = args.reviewer.read_text(encoding="utf-8").strip()
    rc = json.loads(raw) if raw.startswith("[") else [
        json.loads(l) for l in raw.splitlines() if l.strip()]
    lib = {json.loads(l)["knowledge_unit_id"]: json.loads(l)
           for l in open(LIB, encoding="utf-8") if l.strip()}

    rng = random.Random(SEED)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.out.exists():
        for l in open(args.out, encoding="utf-8"):
            if l.strip():
                done.add(json.loads(l)["unit_id"])

    n = 0
    with open(args.out, "a", encoding="utf-8") as fh:
        for r in rc:
            kc = r["knowledge_unit_id"]
            if kc in done:
                continue
            seeded = (lib.get(kc, {}).get("reference_text") or "").strip()
            blind = (r.get("reference_text") or "").strip()
            if not seeded or not blind:
                fh.write(json.dumps({"unit_id": kc, "status": "SKIP_EMPTY"}) + "\n")
                continue
            # randomise which description is presented as A
            blind_is_a = rng.random() < 0.5
            a, b = (blind, seeded) if blind_is_a else (seeded, blind)
            psg = [p if isinstance(p, str) else (p.get("quote") or "")
                   for p in (r.get("source_passages") or [])]
            h = lib[kc].get("hierarchy")
            path = h.get("topic_path", []) if isinstance(h, dict) else (h if isinstance(h, list) else [])
            out = call_and_validate(
                args.base_url, args.model, f"{kc}:SEEDAUDIT",
                build_prompt(lib[kc].get("canonical_name", ""), " > ".join(map(str, path)),
                             a, b, psg),
                schema(), lambda x: x.get("relationship") in LABELS, max_tokens=600)
            rec = {"unit_id": kc, "status": out["status"],
                   "blind_is_A": blind_is_a,
                   "seeded_words": len(seeded.split()), "blind_words": len(blind.split())}
            if out.get("contract_valid"):
                raw_rel = out["response"]["relationship"]
                rec["relationship_raw"] = raw_rel
                # re-express relative to the SEEDED reference regardless of A/B assignment
                # raw label is about B. blind_is_a True => B is the SEEDED reference.
                if raw_rel == "B_MISSING_CONTENT_PRESENT_IN_A":
                    rec["relationship"] = ("SEEDED_MISSING_CONTENT" if blind_is_a
                                           else "BLIND_MISSING_CONTENT")
                elif raw_rel == "B_ASSERTS_CONTENT_A_DOES_NOT_SUPPORT":
                    rec["relationship"] = ("SEEDED_EXTRA_UNSUPPORTED" if blind_is_a
                                           else "BLIND_EXTRA_UNSUPPORTED")
                else:
                    rec["relationship"] = raw_rel
                rec["rationale"] = out["response"].get("rationale", "")
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            print(f"[{n}] {kc} {rec.get('relationship')}", flush=True)
    print(f"\nseed audit comparison complete: {n} records -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
