"""
Adapted from kcgen-kt's KC_gen.py::get_KCs_few_shot (per-source-unit few-shot KC
generation, Duan et al. ACL Findings 2026 comparator, step 1 of 3).

Domain adaptations from the real repo (see README.md for the full, explicit list):
- "Problem" -> "Source Passage": a course-material passage stands in for a
  programming problem statement; the passage itself is the grounding input,
  standing in for representative student code submissions.
- Each KC entry gains a "definition" field (3-5 sentence standalone prose),
  extending the original name + one-sentence-reasoning schema to match this
  project's own Step 6.6/6.7 output depth (brief Section 2, adaptation 2).
- Few-shot exemplars are two hand-authored Data Mining examples
  (prompts/step1_generation_prompt.md), not CodeWorkout's real expert-rubric
  exemplars -- documented as a stated limitation, not silent substitution.
- Model call path: this project's local gemma4:31b via ollama_chat_json()
  (src/kc_l/utils/ollama_json.py) -- NOT the real repo's
  openai.chat.completions.create. This is a required adaptation from the brief,
  confirmed used below (see the ollama_chat_json import and call site).

No domain-specific hardcoding: the exemplars live in an external prompt file, not
inline in this script; model name, base URL, and all generation parameters are
CLI arguments.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_SRC = Path(__file__).resolve().parents[0] / "src"  # overridden below once deployed

# Populated by --repo-src at runtime (see main()) so this script works both in this
# local dry-run staging area and once deployed under kc_l_v2_clean/ablation_studies/.


KC_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string"},
            "name": {"type": "string"},
            "definition": {"type": "string"},
        },
        "required": ["reasoning", "name", "definition"],
    },
}


def load_prompt_parts(prompt_md_path: Path) -> tuple[str, str]:
    """Split the prompt markdown file into (system_message, exemplar_user_prefix).

    File contract (see prompts/step1_generation_prompt.md): a '## SYSTEM MESSAGE'
    section followed by a '## FEW-SHOT EXEMPLARS (verbatim, prepended to every
    generation call)' section. Both are plain text/markdown, extracted verbatim.
    """
    text = prompt_md_path.read_text(encoding="utf-8")
    sys_marker = "## SYSTEM MESSAGE"
    exam_marker = "## FEW-SHOT EXEMPLARS"
    if sys_marker not in text or exam_marker not in text:
        raise ValueError(f"{prompt_md_path} missing required '{sys_marker}' / '{exam_marker}' sections")
    system_part = text.split(sys_marker, 1)[1].split(exam_marker, 1)[0].strip()
    exemplar_part = text.split(exam_marker, 1)[1].strip()
    return system_part, exemplar_part


def build_user_prompt(exemplar_prefix: str, unit_text: str) -> str:
    target_block = (
        "Now analyze the following passage.\n"
        "# Source Passage:\n" + unit_text + "\n\n"
        "Follow the instructions in the system message. First, carefully examine the passage and "
        "identify the important concepts and techniques. Then, explicitly reason about what "
        "underlying knowledge components are required based on this passage. Finally, take the "
        "examples as reference and summarize your analysis clearly into generalizable, concise "
        "knowledge components with standalone definitions."
    )
    return exemplar_prefix + "\n\n" + target_block


def generate_for_unit(
    *,
    ollama_chat_json,
    base_url: str,
    model: str,
    system_message: str,
    exemplar_prefix: str,
    unit: dict,
    num_ctx: int,
    timeout_s: float,
) -> dict:
    user_prompt = build_user_prompt(exemplar_prefix, unit["text"])
    messages = [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_prompt},
    ]
    try:
        parsed, outer, raw = ollama_chat_json(
            base_url=base_url,
            model=model,
            messages=messages,
            format_schema=KC_RESPONSE_SCHEMA,
            temperature=0.0,
            top_p=1.0,
            num_ctx=num_ctx,
            repeat_penalty=1.1,
            think=None,
            timeout_s=timeout_s,
        )
        candidates = []
        for _kc_key, kc_val in parsed.items():
            if not isinstance(kc_val, dict):
                continue
            name = str(kc_val.get("name", "")).strip()
            definition = str(kc_val.get("definition", "")).strip()
            reasoning = str(kc_val.get("reasoning", "")).strip()
            if not name or not definition:
                continue
            candidates.append({"candidate_name": name, "definition": definition, "reasoning": reasoning})
        return {
            "source_unit_id": unit["unit_id"],
            "doc_id": unit["doc_id"],
            "page_start": unit["page_start"],
            "page_end": unit["page_end"],
            "status": "ok",
            "model": model,
            "candidates": candidates,
        }
    except Exception as exc:  # noqa: BLE001 - never silently drop a unit
        return {
            "source_unit_id": unit["unit_id"],
            "doc_id": unit["doc_id"],
            "page_start": unit["page_start"],
            "page_end": unit["page_end"],
            "status": "generation_failed",
            "model": model,
            "candidates": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-src", required=True, help="path to kc_l_v2_clean/src, for importing ollama_chat_json")
    ap.add_argument("--source-units", required=True, help="source_units.jsonl (from generate_source_units.py)")
    ap.add_argument("--prompt-md", required=True, help="prompts/step1_generation_prompt.md")
    ap.add_argument("--out", required=True, help="output JSONL: one row per source unit")
    ap.add_argument("--base-url", required=True, help="e.g. http://127.0.0.1:25xxx (from OLLAMA_HOST)")
    ap.add_argument("--model", default="gemma4:31b")
    ap.add_argument("--num-ctx", type=int, default=65536)
    ap.add_argument("--timeout-s", type=float, default=180.0)
    ap.add_argument("--shard-index", type=int, default=0, help="0-based array-job shard index")
    ap.add_argument("--shard-count", type=int, default=1, help="total number of array-job shards")
    ap.add_argument("--limit", type=int, default=None, help="process only the first N units in this shard (smoke test)")
    args = ap.parse_args()

    sys.path.insert(0, args.repo_src)
    from kc_l.utils.ollama_json import ollama_chat_json  # noqa: E402  -- confirmed used, not openai.*

    system_message, exemplar_prefix = load_prompt_parts(Path(args.prompt_md))

    units = []
    with open(args.source_units, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                units.append(json.loads(line))

    shard_units = [u for i, u in enumerate(units) if i % args.shard_count == args.shard_index]
    if args.limit is not None:
        shard_units = shard_units[: args.limit]

    print(f"SHARD {args.shard_index}/{args.shard_count}: {len(shard_units)} units to process")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok_count = 0
    fail_count = 0
    total_candidates = 0
    with out_path.open("w", encoding="utf-8") as out_f:
        for i, unit in enumerate(shard_units, start=1):
            t0 = time.time()
            result = generate_for_unit(
                ollama_chat_json=ollama_chat_json,
                base_url=args.base_url,
                model=args.model,
                system_message=system_message,
                exemplar_prefix=exemplar_prefix,
                unit=unit,
                num_ctx=args.num_ctx,
                timeout_s=args.timeout_s,
            )
            elapsed = time.time() - t0
            result["call_elapsed_seconds"] = round(elapsed, 3)
            out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_f.flush()
            if result["status"] == "ok":
                ok_count += 1
                total_candidates += len(result["candidates"])
            else:
                fail_count += 1
            print(
                f"[{i}/{len(shard_units)}] {unit['unit_id']} status={result['status']} "
                f"candidates={len(result.get('candidates', []))} elapsed={elapsed:.1f}s"
            )

    print(f"SHARD_DONE ok={ok_count} failed={fail_count} total_candidates={total_candidates}")
    print(f"OUT_PATH={out_path}")


if __name__ == "__main__":
    main()
