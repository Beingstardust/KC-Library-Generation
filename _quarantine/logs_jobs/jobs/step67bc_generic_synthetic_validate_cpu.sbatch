#!/bin/bash
#SBATCH --job-name=s67bc_synval
#SBATCH --partition=short
#SBATCH --output=logs/s67bc_synval_%j.out
#SBATCH --error=logs/s67bc_synval_%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

export PY=/home/aryp26yc/venvs/kc_l_v2/bin/python
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="/beegfs1/software/python/python-3.11.3/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

B="scripts/experimental/step67b_lane_aware_onepass_generic.py"
C="scripts/experimental/step67c_validate_lane_aware_drafts_generic.py"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTDIR="data/work/cache/diagnostics/step67bc_generic_synthetic_validate_${STAMP}"
mkdir -p "$OUTDIR"

echo "OUTDIR=$OUTDIR"
echo "HOST=$(hostname)"
echo "PY=$PY"
"$PY" --version

echo
echo "===== PY_COMPILE ====="
"$PY" -m py_compile "$B" "$C"

echo
echo "===== HELP CHECK ====="
"$PY" "$B" --help | tee "$OUTDIR/step67b_help.txt"
"$PY" "$C" --help | tee "$OUTDIR/step67c_help.txt"

echo
echo "===== CREATE SYNTHETIC LANES AND DRAFTS ====="
cat > "$OUTDIR/synthetic_lanes.jsonl" <<'JSONL'
{"kc_id":"KC_SYN_DIRECT_001","canonical_name":"Alpha Measure","definition_lane":[{"evidence_id":"D1","quote_text":"Alpha Measure is a measure that summarizes alignment between two records.","context_text":"Alpha Measure is a measure that summarizes alignment between two records.","reason":"synthetic direct definition"}],"scope_lane":[],"context_lane":[],"sibling_contrast_lane":[],"quarantine_lane":[]}
{"kc_id":"KC_SYN_CONTEXT_001","canonical_name":"Beta Procedure","definition_lane":[],"scope_lane":[{"evidence_id":"S1","quote_text":"Beta Procedure is used to transform raw observations into comparable records.","context_text":"Beta Procedure is used to transform raw observations into comparable records.","reason":"synthetic scope support"}],"context_lane":[{"evidence_id":"C1","quote_text":"The procedure applies the same transformation rule to each observation before comparison.","context_text":"The procedure applies the same transformation rule to each observation before comparison.","reason":"synthetic contextual support"}],"sibling_contrast_lane":[],"quarantine_lane":[]}
JSONL

cat > "$OUTDIR/synthetic_drafts.jsonl" <<'JSONL'
{"kc_id":"KC_SYN_DIRECT_001","canonical_name":"Alpha Measure","ok":true,"error":"","parsed":{"kc_id":"KC_SYN_DIRECT_001","canonical_name":"Alpha Measure","definition":{"status":"grounded","grounding_mode":"direct_definition","text":"Alpha Measure is a measure that summarizes alignment between two records.","supporting_evidence_ids":["D1"],"supporting_lanes":["definition_lane"],"abstention_reason":""},"scope":{"status":"abstained","grounding_mode":"abstained","text":"","supporting_evidence_ids":[],"supporting_lanes":[],"abstention_reason":"No scope evidence was provided."}}}
{"kc_id":"KC_SYN_CONTEXT_001","canonical_name":"Beta Procedure","ok":true,"error":"","parsed":{"kc_id":"KC_SYN_CONTEXT_001","canonical_name":"Beta Procedure","definition":{"status":"grounded","grounding_mode":"contextual_synthesis","text":"Beta Procedure is a procedure for applying a transformation rule to raw observations so they become comparable records.","supporting_evidence_ids":["S1","C1"],"supporting_lanes":["scope_lane","context_lane"],"abstention_reason":""},"scope":{"status":"grounded","grounding_mode":"direct_scope","text":"It is used to transform raw observations into comparable records.","supporting_evidence_ids":["S1"],"supporting_lanes":["scope_lane"],"abstention_reason":""}}}
JSONL

echo
echo "===== RUN GENERIC VALIDATOR ON SYNTHETIC DRAFTS ====="
"$PY" "$C" \
  --lanes "$OUTDIR/synthetic_lanes.jsonl" \
  --drafts "$OUTDIR/synthetic_drafts.jsonl" \
  --out-root "$OUTDIR/validated"

VALDIR="$(ls -1td "$OUTDIR/validated"/2026-* | head -n 1)"
echo "VALDIR=$VALDIR"

echo
echo "===== SYNTHETIC VALIDATION SUMMARY ====="
cat "$VALDIR/summary.json"

echo
echo "===== ARCHITECTURE GREP ====="
grep -nEi 'seed_definition|seed_floor|gemma4|gemma3|qwen3|KC_CLF|KC_CLU|KC_EVAL|ACTIVE|CURRENT|step6_8|review packet|data/processed/.*/2026-04' "$B" "$C" || true

echo
echo "STEP67BC_GENERIC_SYNTHETIC_VALIDATE_DONE"
