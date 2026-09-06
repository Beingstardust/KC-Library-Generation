"""Write FINAL_JUDGE_DECODING_MANIFEST.json and refresh the three frozen locks.

Records the exact instrument used to produce judge predictions, so the qualification run and any
later reproduction are pinned to one configuration.

Deliberately does NOT write JUDGE_QUALIFIED = QUALIFIED. The judge stays formally unqualified
until it is compared against human labels.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent
REFEVAL = BASE.parent
FINAL = REFEVAL.parent
REFLIB = FINAL / "reference_library"

sys.path.insert(0, str(REFEVAL))
from run_reference_judge import DECODING  # noqa: E402
import reference_judge_prompts as P       # noqa: E402
import reference_judge_schema as S        # noqa: E402


def sha(p: Path) -> str | None:
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def sha_text(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def remote(cmd: str) -> str:
    try:
        r = subprocess.run(["ssh", "Cluster A", cmd], capture_output=True, text=True, timeout=90)
        return r.stdout.strip()
    except Exception as e:
        return f"UNAVAILABLE ({type(e).__name__})"


def git_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                           cwd=str(FINAL), timeout=10)
        return r.stdout.strip() or "NOT_A_GIT_REPO"
    except Exception:
        return "NOT_A_GIT_REPO"


now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

print("collecting environment from Cluster A ...")
# importlib.metadata rather than __version__: xgrammar does not expose a __version__ attribute,
# which silently produced "unknown" on the first attempt.
# importlib.metadata rather than __version__: xgrammar does not expose a __version__ attribute,
# which silently produced "unknown" on the first attempt.
_VER_CMD = (
    "source ~/projects/selene_judge/.venv/bin/activate 2>/dev/null; "
    "python -c \"import importlib.metadata as m; "
    "print(chr(10).join(p+'='+(m.version(p) if True else '') for p in "
    "['vllm','xgrammar','torch','transformers']))\" 2>/dev/null"
)
env = remote(_VER_CMD)

# GPU is read from the serve log of the run that produced the frozen predictions, not from a live
# nvidia-smi: the allocation is released after the run, so a live query on the login node reports
# nothing and would leave the manifest with a gap.
gpu_line = remote(
    "grep -m1 -iE 'H100|A100|A40' /path/to/pipeline/projects/selene_judge/logs/serve_1683232.log 2>/dev/null"
)
model_rev = remote(
    "cat ~/projects/selene_judge/models/Selene-1-Llama-3.3-70B/config.json 2>/dev/null | "
    "python3 -c \"import json,sys;d=json.load(sys.stdin);"
    "print(json.dumps({k:d.get(k) for k in ('_name_or_path','architectures','model_type',"
    "'torch_dtype','max_position_embeddings','vocab_size')}))\""
)
tok_rev = remote(
    "python3 -c \"import json;d=json.load(open('/path/to/pipeline/projects/selene_judge/models/"
    "Selene-1-Llama-3.3-70B/tokenizer_config.json'));"
    "print(json.dumps({k:d.get(k) for k in ('tokenizer_class','model_max_length','chat_template')}))\" "
    "2>/dev/null | head -c 400"
)

env_lines = dict(
    l.split("=", 1) for l in env.splitlines() if "=" in l and not l.startswith("NVIDIA")
) if env else {}
gpu = gpu_line.strip() or "unknown"

# prompt-builder hashes: the judge-facing semantics, pinned function by function
import inspect
prompt_hashes = {
    fn: sha_text(inspect.getsource(getattr(P, fn)))
    for fn in ("build_m1_prompt", "build_m2_prompt", "build_m3_coverage_prompt",
               "build_m3_holistic_prompt", "build_m4_prompt", "build_m4_holistic_prompt",
               "build_target_alignment_prompt", "build_decomposition_prompt")
}
schema_hashes = {
    "m1_faithfulness_schema(3)": sha_text(json.dumps(S.m1_faithfulness_schema(3), sort_keys=True)),
    "m2_correctness_schema(3)": sha_text(json.dumps(S.m2_correctness_schema(3), sort_keys=True)),
    "m3_claim_coverage_schema(3)": sha_text(json.dumps(S.m3_claim_coverage_schema(3), sort_keys=True)),
    "m3_holistic_schema": sha_text(json.dumps(S.m3_holistic_schema(), sort_keys=True)),
    "m4_retrieval_coverage_schema(3)": sha_text(json.dumps(S.m4_retrieval_coverage_schema(3), sort_keys=True)),
    "m4_holistic_schema": sha_text(json.dumps(S.m4_holistic_schema(), sort_keys=True)),
    "target_alignment_schema": sha_text(json.dumps(S.target_alignment_schema(), sort_keys=True)),
    "decomposition_schema": sha_text(json.dumps(S.decomposition_schema(), sort_keys=True)),
}

manifest = {
    "manifest_id": "FINAL_JUDGE_DECODING_MANIFEST",
    "frozen_utc": now,
    "purpose": "Pins the exact evaluator instrument used to produce judge predictions. Formal "
               "qualification predictions MUST use this configuration.",

    "judge_model": {
        "repo": "AtlaAI/Selene-1-Llama-3.3-70B",
        "served_name": "selene-1-llama-3.3-70b",
        "local_path_ants": "~/projects/selene_judge/models/Selene-1-Llama-3.3-70B",
        "model_config": model_rev,
        "tokenizer_config": tok_rev,
        "chat_template": "the tokenizer's own chat template as shipped with the model revision above; "
                          "not overridden anywhere in this pipeline",
    },

    "serving": {
        "vllm_version": env_lines.get("vllm", "unknown"),
        "xgrammar_version": env_lines.get("xgrammar", "unknown"),
        "torch_version": env_lines.get("torch", "unknown"),
        "transformers_version": env_lines.get("transformers", "unknown"),
        "structured_output_backend": "XGrammar via OpenAI-standard response_format json_schema "
                                      "(strict). extra_body/guided_json is silently ignored when "
                                      "POSTing raw JSON and must never be used here.",
        "gpu": gpu,
        "dtype": "bfloat16",
        "tensor_parallel_size": 4,
        "max_model_len": 40960,
        "gpu_memory_utilization": 0.90,
        "env": {"VLLM_USE_FLASHINFER_SAMPLER": "0"},
    },

    "decoding": dict(DECODING, max_tokens_default=3000, max_tokens_decomposition=4000),

    "decoding_rationale": {
        "frequency_penalty": "0.0. Briefly set to 0.2 while diagnosing structured-output stalls and "
                              "then REMOVED. vLLM applies a frequency penalty directly to generation "
                              "logits as a function of how often a token has already appeared, so a "
                              "nonzero value is not a formatting control and can alter semantic "
                              "decisions even under greedy decoding. Measured here: two penalty-free "
                              "runs produced an IDENTICAL M1 verdict distribution (20 FAIL / 14 PASS) "
                              "despite differing in holistic schema, while penalty=0.2 shifted it to "
                              "22 FAIL / 12 PASS. The decisive structural remedy was making rationale "
                              "optional; the penalty only moved preflight failures from 5 to 4.",
        "selection_basis": "The penalty-free configuration was chosen because it removes a "
                            "demonstrated generation-logit confound and because the structural issue "
                            "no longer requires the penalty - NOT because it maximises sentinel "
                            "accuracy.",
    },

    "structured_output_design": {
        "rationale_optional": True,
        "why": "A REQUIRED trailing free-text field was the decisive stall point: having committed a "
                "verdict the model must open a string it has nothing to put in, and inter-token "
                "whitespace is a legal continuation. Every string is length-bounded and its character "
                "class excludes newlines, so all remaining whitespace is semantically empty.",
        "decision_field_first": "The verdict is the FIRST field in the branched schemas. With the "
                                 "verdict last, the model selects the oneOf branch by choosing the next "
                                 "KEY, which made the MATERIAL_* branch effectively unreachable "
                                 "(measured: zero MATERIAL_OMISSION across 36 cases).",
        "grammar_enforcement_verified": "oneOf branches materialise and bind each label to its "
                                         "permitted evidence-id family; minItems==maxItems compiles to "
                                         "exact repetition; maxLength compiles to bounded repetition. "
                                         "if/then/else compiles cleanly but is SILENTLY DROPPED and is "
                                         "used nowhere. Verified by reading the emitted EBNF.",
        "schema_hashes": schema_hashes,
    },

    "prompt_hashes": prompt_hashes,
    "prompt_semantics_unchanged_since": "the reference-based rubric was frozen; only serialization "
                                         "shape and decoding changed after that point",

    "blinding": {
        "pattern_count": len(P._FORBIDDEN_PATTERNS),
        "patterns_sha256": sha_text(json.dumps(P._FORBIDDEN_PATTERNS, sort_keys=True)),
        "enforced_at": "prompt-build time via assert_blinded(); raises rather than warning",
    },

    "sentinel_suite": {
        "version": "reference_sentinel_gold.jsonl (36 cases, translated from the frozen rubric suite)",
        "sha256": sha(REFEVAL / "output" / "reference_sentinel_gold.jsonl"),
        "source_suite_sha256": sha(FINAL / "output" / "r9_final" / "rubric_sentinel_gold.jsonl"),
        "gold_pending": ["SENT_032", "SENT_033"],
    },

    "frozen_artifacts_unchanged": {
        "expert_reference": sha(REFLIB / "04_gold" / "expert_adjudicated_reference_kc_library.jsonl"),
        "reference_manifest": sha(REFLIB / "04_gold" / "expert_adjudicated_reference_manifest.json"),
        "candidate_freeze_manifest": sha(REFLIB / "00_freeze" / "CANDIDATE_FREEZE_MANIFEST.json"),
    },

    "code_hashes": {
        "run_reference_judge.py": sha(REFEVAL / "run_reference_judge.py"),
        "reference_judge_schema.py": sha(REFEVAL / "reference_judge_schema.py"),
        "reference_judge_prompts.py": sha(REFEVAL / "reference_judge_prompts.py"),
        "reference_claim_schema.py": sha(REFEVAL / "reference_claim_schema.py"),
        "reference_metrics.py": sha(REFEVAL / "reference_metrics.py"),
        "preflight_check.py": sha(REFEVAL / "preflight_check.py"),
    },

    "git_commit": git_commit(),

    "qualification_status": {
        "JUDGE_QUALIFIED": False,
        "statement": "The judge is formally UNQUALIFIED. Development sentinel performance does not "
                      "qualify it. Qualification requires comparison against blinded human labels on "
                      "the 180-row calibration sample under a qualification gate pre-registered "
                      "before human results are opened.",
    },
}

p = BASE / "FINAL_JUDGE_DECODING_MANIFEST.json"
p.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {p.name}")
print(f"  vllm={manifest['serving']['vllm_version']} xgrammar={manifest['serving']['xgrammar_version']} gpu={gpu}")
print(f"  decoding={manifest['decoding']}")
print(f"  JUDGE_QUALIFIED={manifest['qualification_status']['JUDGE_QUALIFIED']}")
