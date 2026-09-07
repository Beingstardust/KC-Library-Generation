#!/bin/bash
#SBATCH --job-name=chain_watchdog
#SBATCH --partition=big
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=23:00:00
#SBATCH --output=/path/to/kc_l/v3/logs/chain_watchdog_%j.log
set -u
# Watchdog for the 2026-08-17 rebuild chain.
#
# The chain is wired with --dependency=afterok, and this cluster does NOT set kill_invalid_depend
# (scontrol show config -> DependencyParameters = (null)). So if any stage fails, its dependents do
# not fail - they sit PENDING with DependencyNeverSatisfied indefinitely. That is a silent death:
# nothing errors, nothing completes, and the run simply never finishes.
#
# This job runs independently of the chain, detects that state, cancels the stranded jobs so they
# stop occupying the queue, and writes a single plain-text status file that says exactly what
# happened and what to do next.

MIR=/path/to/kc_l
STATUS=$MIR/v3/logs/REBUILD_CHAIN_STATUS.txt
JOBS="246243 246244 246245 246246 246247 246248"

declare -A LABEL
LABEL[246243]="data-mining  packets"
LABEL[246244]="mathematics  packets"
LABEL[246245]="data-mining  KC drafting (qwen3.8)"
LABEL[246246]="mathematics  KC drafting (qwen3.8)"
LABEL[246247]="data-mining  topic drafting (qwen3.8)"
LABEL[246248]="mathematics  topic drafting (qwen3.8)"

write_status() {
  {
    echo "REBUILD CHAIN STATUS"
    echo "written by watchdog job ${SLURM_JOB_ID:-?} at $(date)"
    echo "======================================================================"
    for j in $JOBS; do
      st=$(sacct -j "$j" --format=State --noheader --parsable2 2>/dev/null | head -1 | tr -d ' ')
      rsn=$(squeue -j "$j" -h -o '%R' 2>/dev/null | head -1)
      printf '  %-8s %-36s %-24s %s\n' "$j" "${LABEL[$j]}" "${st:-UNKNOWN}" "${rsn:-}"
    done
    echo "======================================================================"
    echo "$1"
  } > "$STATUS"
}

STRANDED_FOUND=0

while true; do
  terminal=0
  stranded=""
  for j in $JOBS; do
    st=$(sacct -j "$j" --format=State --noheader --parsable2 2>/dev/null | head -1 | tr -d ' ')
    case "$st" in
      COMPLETED|FAILED|CANCELLED*|TIMEOUT|OUT_OF_MEMORY|NODE_FAIL) terminal=$((terminal+1)); continue;;
    esac
    rsn=$(squeue -j "$j" -h -o '%R' 2>/dev/null)
    case "$rsn" in
      *DependencyNeverSatisfied*) stranded="$stranded $j";;
    esac
  done

  if [ -n "$stranded" ]; then
    STRANDED_FOUND=1
    echo "$(date) STRANDED (dependency can never be satisfied):$stranded"
    for j in $stranded; do scancel "$j" 2>/dev/null; done
    write_status "RESULT: CHAIN BROKEN. An upstream stage failed, so these dependents could never
run and have been cancelled so they do not sit in the queue:$stranded

WHAT TO DO: look at the FAILED stage above, then read its log in v3/logs/.
Nothing was overwritten - each stage refuses to clobber existing output, and the
rebuild wrote to NEW run directories (v3_20260817_datamining_rebuild,
v3_20260817_mathematics_rebuild). All previous runs are intact."
    sleep 60
    continue
  fi

  if [ "$terminal" -ge 6 ]; then
    ok=1
    for j in $JOBS; do
      st=$(sacct -j "$j" --format=State --noheader --parsable2 2>/dev/null | head -1 | tr -d ' ')
      [ "$st" = "COMPLETED" ] || ok=0
    done
    if [ "$ok" = "1" ]; then
      write_status "RESULT: ALL SIX STAGES COMPLETED. Packets rebuilt and drafted with qwen3.8 for
both data-mining and mathematics. Check each drafting log's DRAFT VALIDATION block
in v3/logs/ for grounded/partial/abstained counts and HARD FAILURES."
    else
      write_status "RESULT: CHAIN FINISHED WITH FAILURES. See the per-stage states above and the
matching logs in v3/logs/. Note a drafting job reporting FAILED is not always a real
failure - check the DRAFT VALIDATION block and the row count in the drafts file first."
    fi
    echo "$(date) chain terminal; watchdog exiting"
    exit 0
  fi

  write_status "RESULT: IN PROGRESS. Watchdog is still running and will update this file."
  sleep 300
done
