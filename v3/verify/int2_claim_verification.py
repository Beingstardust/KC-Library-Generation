"""INT-2: post-generation claim-vs-evidence entailment verification. Flag-only.

Checks whether the evidence a draft CITES for each claim actually entails that claim, using an
offline NLI model. This is a separate pass over already-generated drafts, not part of retrieval or
generation:

  - does NOT modify the evidence packet
  - does NOT alter retrieval ranking
  - does NOT rewrite drafts
  - does NOT delete claims
  - does NOT change grounded/partial/abstained status
  - writes a SEPARATE sidecar file; the original drafts file is never opened for writing

Promoted per 35_INT2_PROMOTION.md with an explicit reliability caveat that must travel with the
output: the UNVERIFIABLE classification is measurably less reliable specifically for formula-to-
prose translations and close single-sentence paraphrases (see 34_INT2_ERROR_ANALYSIS.md) - a
consumer of this file's `classification` field must not treat every UNVERIFIABLE flag as equally
suspicious.

Decision policy (documented, not implicit): for a claim citing N evidence items, score each
(evidence_item, claim) pair independently and take each item's argmax NLI label. If ANY item's
argmax is CONTRADICTION, classify CONTRADICTED. Else if ANY item's argmax is ENTAILMENT, classify
SUPPORTED. Else (all NEUTRAL) classify UNVERIFIABLE. Tested against framing A (concatenated
evidence) on the calibration set with identical results (evaluate_int2_framing_a.py) - this
simpler per-item framing is used since it performs the same and is cheaper to compute
incrementally.
"""
import argparse
import hashlib
import json
import os
import sys

VERIFIER_NAME = "roberta-large-mnli"
VERIFIER_VERSION = "sha256:f4dbab1bceb16f9800f7b9a9c96b187d5400511b66982e4e845de920f69b89b5"  # model.safetensors hash
THRESHOLD_VERSION = "int2_v1_argmax_contradiction_precedence"

LABEL_MAP = {"ENTAILMENT": "supported", "NEUTRAL": "unverifiable", "CONTRADICTION": "contradicted"}
PRECEDENCE = {"contradicted": 2, "supported": 1, "unverifiable": 0}


def verification_input_hash(claim, evidence_texts):
    h = hashlib.sha256()
    h.update(claim.encode("utf-8"))
    for t in evidence_texts:
        h.update(b"\x00")
        h.update(t.encode("utf-8"))
    return "sha256:" + h.hexdigest()


def load_verifier(model_path):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(model_path, local_files_only=True)
    model.eval()
    torch.set_num_threads(os.cpu_count() or 4)
    id2label = model.config.id2label

    def score(premise, hypothesis):
        enc = tok(premise, hypothesis, truncation=True, max_length=512, return_tensors="pt")
        with torch.no_grad():
            out = model(**enc)
        probs = torch.softmax(out.logits[0], dim=-1).tolist()
        return {id2label[i]: p for i, p in enumerate(probs)}

    return score


def verify_claim(score_fn, claim, evidence_texts):
    item_scores = [score_fn(ev, claim) for ev in evidence_texts]
    mapped = []
    for s in item_scores:
        argmax = max(s, key=s.get)
        mapped.append(LABEL_MAP[argmax])
    classification = max(mapped, key=lambda m: PRECEDENCE[m]) if mapped else "unverifiable"
    support_score = max((s["ENTAILMENT"] for s in item_scores), default=0.0)
    contradiction_score = max((s["CONTRADICTION"] for s in item_scores), default=0.0)
    return {
        "classification": classification,
        "support_score": round(support_score, 4),
        "contradiction_score": round(contradiction_score, 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drafts-jsonl", required=True)
    ap.add_argument("--packets-jsonl", required=True)
    ap.add_argument("--model-path", default="/path/to/scratch/kc_l/models/verifiers/roberta-large-mnli")
    ap.add_argument("--out-jsonl", required=True,
                    help="Sidecar output. The drafts file itself is never modified.")
    a = ap.parse_args()

    packets = {}
    for line in open(a.packets_jsonl, encoding="utf-8"):
        if not line.strip():
            continue
        p = json.loads(line)
        packets[p.get("knowledge_unit_id")] = {
            e.get("evidence_id"): e.get("text")
            for e in (p.get("evidence_for_synthesis") or []) if e.get("evidence_id")
        }

    print("loading verifier from %s (local files only, no network)..." % a.model_path, flush=True)
    score_fn = load_verifier(a.model_path)
    print("verifier ready: %s" % VERIFIER_NAME, flush=True)

    n_units = 0
    n_claims = 0
    n_supported = n_unverifiable = n_contradicted = 0
    out_f = open(a.out_jsonl, "w", encoding="utf-8")
    for line in open(a.drafts_jsonl, encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        draft = row.get("draft")
        if not isinstance(draft, dict):
            continue
        uid = draft.get("knowledge_unit_id") or row.get("knowledge_unit_id")
        ev_lookup = packets.get(uid) or {}
        ck = draft.get("contextual_kc_draft") or draft.get("contextual_topic_draft") or {}
        if str(ck.get("status") or "").lower() == "abstained":
            continue  # nothing to verify; an abstention's evidence_map is required to be empty
        n_units += 1
        for idx, entry in enumerate(draft.get("evidence_map") or []):
            if not isinstance(entry, dict):
                continue
            claim = entry.get("claim")
            eids = entry.get("supporting_evidence_ids") or []
            evidence_texts = [ev_lookup.get(str(eid)) for eid in eids]
            evidence_texts = [t for t in evidence_texts if t]
            if not claim or not evidence_texts:
                continue
            result = verify_claim(score_fn, claim, evidence_texts)
            n_claims += 1
            if result["classification"] == "supported":
                n_supported += 1
            elif result["classification"] == "contradicted":
                n_contradicted += 1
            else:
                n_unverifiable += 1
            out_f.write(json.dumps({
                "knowledge_unit_id": uid,
                "claim_id": "%s:claim:%04d" % (uid, idx),
                "evidence_ids": eids,
                "claim": claim,
                "verification": {
                    "verifier": VERIFIER_NAME,
                    "verifier_version": VERIFIER_VERSION,
                    "support_score": result["support_score"],
                    "contradiction_score": result["contradiction_score"],
                    "classification": result["classification"],
                    "threshold_version": THRESHOLD_VERSION,
                    "verification_input_hash": verification_input_hash(claim, evidence_texts),
                },
            }, ensure_ascii=False) + "\n")
    out_f.close()

    print("=" * 74)
    print("INT-2 CLAIM VERIFICATION (flag-only, review metadata only)")
    print("  units processed        : %d" % n_units)
    print("  claims verified        : %d" % n_claims)
    print("  supported              : %d (%.1f%%)" % (n_supported, 100.0 * n_supported / max(n_claims, 1)))
    print("  unverifiable           : %d (%.1f%%)  <- review warning; see 35_INT2_PROMOTION.md "
         "reliability caveat for formula/paraphrase content" % (
             n_unverifiable, 100.0 * n_unverifiable / max(n_claims, 1)))
    print("  contradicted           : %d (%.1f%%)  <- high-priority review warning" % (
        n_contradicted, 100.0 * n_contradicted / max(n_claims, 1)))
    print("  output (sidecar only)  : %s" % a.out_jsonl)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
