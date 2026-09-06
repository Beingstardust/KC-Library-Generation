"""Standalone Prometheus-2 load+generate+parse smoke test.

Confirms (a) the model/tokenizer load correctly from local weights, (b) generation completes
without hanging, (c) the output matches the expected "Feedback: ... [RESULT] N" format and
parses cleanly, and (d) the parsed score direction is sane on one clear-cut known-bad example
(Density-Reachable/Border-point conflation - expected low score) before running anything
corpus-wide. Mirrors the HHEM deployment's own "verify empirically before trusting" discipline.
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compute_prometheus_scores import PROMETHEUS_MODEL_DIR, build_prompt, parse_feedback_and_score  # noqa: E402

import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

CLAIM = (
    "The Density-Reachable concept is crucial in DBSCAN clustering. A point is Density-Reachable "
    "if it is within a specified distance (epsilon) of at least one core point. This concept "
    "helps define the cluster's core and border points, contributing to the overall cluster "
    "structure."
)
EVIDENCE = "Border The point is not core, but it is within ε of at least one core point."

print(f"Loading tokenizer+model from {PROMETHEUS_MODEL_DIR} ...")
t0 = time.time()
tokenizer = AutoTokenizer.from_pretrained(PROMETHEUS_MODEL_DIR)
# No device_map="auto" - that requires the `accelerate` package, which isn't installed here
# (and isn't needed: this is a single-GPU job, gres=gpu:1, and the 14.5GB bf16 model fits
# comfortably on one A100 80GB - accelerate's device_map is for multi-GPU/CPU-offload sharding).
model = AutoModelForCausalLM.from_pretrained(PROMETHEUS_MODEL_DIR, dtype=torch.bfloat16)
model = model.to("cuda")
model.eval()
print(f"LOAD_OK in {time.time() - t0:.1f}s")

prompt = build_prompt(EVIDENCE, CLAIM)
print(f"PROMPT_CHARS={len(prompt)}")

inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
print(f"INPUT_TOKENS={inputs['input_ids'].shape[1]}")

t0 = time.time()
with torch.no_grad():
    output_ids = model.generate(
        **inputs,
        max_new_tokens=512,
        do_sample=False,
        temperature=None,
        top_p=None,
        pad_token_id=tokenizer.eos_token_id,
    )
gen_time = time.time() - t0
generated = tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
print(f"GENERATE_OK in {gen_time:.1f}s, {output_ids.shape[1] - inputs['input_ids'].shape[1]} new tokens")
print("---RAW OUTPUT---")
print(generated)
print("---END RAW OUTPUT---")

feedback, score = parse_feedback_and_score(generated)
print(f"PARSED_SCORE={score}")
print(f"PARSED_FEEDBACK={feedback[:300]}")

if score is None:
    print("SMOKE_TEST_RESULT=FAIL (could not parse a 1-5 score from output)")
elif score <= 2:
    print(f"SMOKE_TEST_RESULT=PASS (score={score}, correctly flagged the known-bad conflation example as low)")
else:
    print(f"SMOKE_TEST_RESULT=FAIL (score={score}, expected low score 1-2 for a confirmed concept-conflation example)")
