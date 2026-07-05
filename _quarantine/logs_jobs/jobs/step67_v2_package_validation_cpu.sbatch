#!/bin/bash
#SBATCH --job-name=s67v2_packval
#SBATCH --partition=short
#SBATCH --output=logs/s67v2_packval_%j.out
#SBATCH --error=logs/s67v2_packval_%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00

set -euo pipefail

cd /beegfs1/home/aryp26yc/projects/kc_l_v2_clean || exit 1

VALID_ROOT="$(ls -1td data/work/cache/diagnostics/step67_generic_policy_v2_sofja_validation_* | head -n 1)"

if [ -z "${VALID_ROOT:-}" ] || [ ! -d "$VALID_ROOT" ]; then
  echo "VALID_ROOT not found."
  exit 1
fi

if [ -f "$VALID_ROOT/06_replay_dir.log" ]; then
  REPLAY_DIR="$(grep '^REPLAY_DIR=' "$VALID_ROOT/06_replay_dir.log" | sed 's/^REPLAY_DIR=//')"
else
  REPLAY_DIR="$(ls -1td data/work/cache/diagnostics/step67_generic_lane_policy_v2_sofja_replay/2026-* | head -n 1)"
fi

if [ -z "${REPLAY_DIR:-}" ] || [ ! -d "$REPLAY_DIR" ]; then
  echo "REPLAY_DIR not found."
  exit 1
fi

CPUVAL_OUT="$(ls -1t logs/step67v2_cpuval_*.out 2>/dev/null | head -n 1 || true)"
CPUVAL_ERR="$(ls -1t logs/step67v2_cpuval_*.err 2>/dev/null | head -n 1 || true)"
DEFINSPECT_OUT="$(ls -1t logs/s67v2_definspect_*.out 2>/dev/null | head -n 1 || true)"
DEFINSPECT_ERR="$(ls -1t logs/s67v2_definspect_*.err 2>/dev/null | head -n 1 || true)"

STAGE="/beegfs2/scratch/aryp26yc/kc_l/return_staging/step67_generic_policy_v2_sofja_validation_$(date -u +%Y%m%dT%H%M%SZ)"
RETURN="/beegfs2/scratch/aryp26yc/kc_l/sync_bundles/step67_generic_policy_v2_sofja_validation_$(date -u +%Y%m%dT%H%M%SZ).tar.gz"

mkdir -p "$STAGE"/{validation_root,replay_dir,logs,jobs,patch_snapshot}

cp -a "$VALID_ROOT"/. "$STAGE/validation_root/"
cp -a "$REPLAY_DIR"/summary.json "$STAGE/replay_dir/summary.json"
cp -a "$REPLAY_DIR"/lane_audit.md "$STAGE/replay_dir/lane_audit.md"
cp -a "$REPLAY_DIR"/lane_packets.jsonl "$STAGE/replay_dir/lane_packets.jsonl"

cp -a jobs/step67_generic_policy_v2_validate_cpu.sbatch "$STAGE/jobs/" 2>/dev/null || true
cp -a jobs/step67_v2_inspect_definition_cpu.sbatch "$STAGE/jobs/" 2>/dev/null || true
cp -a jobs/step67_v2_package_validation_cpu.sbatch "$STAGE/jobs/" 2>/dev/null || true

if [ -n "$CPUVAL_OUT" ] && [ -f "$CPUVAL_OUT" ]; then cp -a "$CPUVAL_OUT" "$STAGE/logs/"; fi
if [ -n "$CPUVAL_ERR" ] && [ -f "$CPUVAL_ERR" ]; then cp -a "$CPUVAL_ERR" "$STAGE/logs/"; fi
if [ -n "$DEFINSPECT_OUT" ] && [ -f "$DEFINSPECT_OUT" ]; then cp -a "$DEFINSPECT_OUT" "$STAGE/logs/"; fi
if [ -n "$DEFINSPECT_ERR" ] && [ -f "$DEFINSPECT_ERR" ]; then cp -a "$DEFINSPECT_ERR" "$STAGE/logs/"; fi

cp -a src/kc_l/kc_drafting/evidence_lane_policy.py "$STAGE/patch_snapshot/evidence_lane_policy.py"
cp -a scripts/experimental/step67a_build_field_lane_packets_generic.py "$STAGE/patch_snapshot/step67a_build_field_lane_packets_generic.py"
cp -a tests/test_evidence_lane_policy.py "$STAGE/patch_snapshot/test_evidence_lane_policy.py"
cp -a tests/test_step67_sidecar_domain_agnosticity.py "$STAGE/patch_snapshot/test_step67_sidecar_domain_agnosticity.py"
cp -a docs/operator_notes/STEP67_GENERIC_LANE_POLICY_2026-04-28.md "$STAGE/patch_snapshot/STEP67_GENERIC_LANE_POLICY_2026-04-28.md"
cp -a CHANGELOG.md "$STAGE/patch_snapshot/CHANGELOG.md"

cat > "$STAGE/README_RETURN_BUNDLE.txt" <<EOF
Step 6.7 generic policy V2 Sofja validation return bundle.

Created UTC:
$(date -u +%Y-%m-%dT%H:%M:%SZ)

Repo:
$(pwd)

VALID_ROOT:
$VALID_ROOT

REPLAY_DIR:
$REPLAY_DIR

CPU validation stdout:
${CPUVAL_OUT:-missing}

CPU validation stderr:
${CPUVAL_ERR:-missing}

Definition inspection stdout:
${DEFINSPECT_OUT:-missing}

Definition inspection stderr:
${DEFINSPECT_ERR:-missing}

Purpose:
Return the Sofja-side compile/test/leakage/replay/definition-inspection artifacts for ChatGPT review.

No model call was run.
No Step 6.8 was run.
No active pointer was updated.
No full Step 6.7 was run.
EOF

(
  cd "$STAGE"
  find . -type f | sort | while read -r f; do
    sha256sum "$f"
  done > MANIFEST_SHA256.txt
)

tar -czf "$RETURN" -C "$STAGE" .

echo "VALID_ROOT=$VALID_ROOT"
echo "REPLAY_DIR=$REPLAY_DIR"
echo "STAGE=$STAGE"
echo "RETURN=$RETURN"
ls -lh "$RETURN"
