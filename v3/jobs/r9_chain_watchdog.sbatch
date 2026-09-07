#!/bin/bash
#SBATCH --job-name=r9_chain_watchdog
#SBATCH --partition=big
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=23:00:00
#SBATCH --output=/path/to/shared%j.log
set -u

MIR=${MIR:-/path/to/shared}
STATUS=${STATUS:-$MIR/v3/logs/R9_CHAIN_STATUS_${SLURM_JOB_ID:-unknown}.txt}
JOBS=${JOBS:?FATAL: submit with JOBS='jobid jobid ...'}
LABELS=${LABELS:-}
SLEEP_SECONDS=${SLEEP_SECONDS:-300}

mkdir -p "$(dirname "$STATUS")"

label_for_index() {
  local idx=$1
  if [ -z "$LABELS" ]; then
    echo "job_$idx"
    return
  fi
  echo "$LABELS" | tr '|' '\n' | sed -n "$((idx + 1))p"
}

write_status() {
  local msg=$1
  {
    echo "R9 CHAIN STATUS"
    echo "written by watchdog job ${SLURM_JOB_ID:-?} at $(date)"
    echo "======================================================================"
    local idx=0
    for j in $JOBS; do
      st=$(sacct -j "$j" --format=State --noheader --parsable2 2>/dev/null | head -1 | tr -d ' ')
      rsn=$(squeue -j "$j" -h -o '%R' 2>/dev/null | head -1)
      printf '  %-10s %-42s %-24s %s\n' "$j" "$(label_for_index "$idx")" "${st:-UNKNOWN}" "${rsn:-}"
      idx=$((idx + 1))
    done
    echo "======================================================================"
    echo "$msg"
  } > "$STATUS"
}

while true; do
  terminal=0
  stranded=""
  for j in $JOBS; do
    st=$(sacct -j "$j" --format=State --noheader --parsable2 2>/dev/null | head -1 | tr -d ' ')
    case "$st" in
      COMPLETED|FAILED|CANCELLED*|TIMEOUT|OUT_OF_MEMORY|NODE_FAIL)
        terminal=$((terminal + 1))
        continue
        ;;
    esac
    rsn=$(squeue -j "$j" -h -o '%R' 2>/dev/null)
    case "$rsn" in
      *DependencyNeverSatisfied*) stranded="$stranded $j" ;;
    esac
  done

  if [ -n "$stranded" ]; then
    for j in $stranded; do scancel "$j" 2>/dev/null; done
    write_status "RESULT: CHAIN BROKEN. These dependency-stranded jobs were cancelled:$stranded"
    sleep 60
    continue
  fi

  count=0
  for _j in $JOBS; do count=$((count + 1)); done
  if [ "$terminal" -ge "$count" ]; then
    ok=1
    for j in $JOBS; do
      st=$(sacct -j "$j" --format=State --noheader --parsable2 2>/dev/null | head -1 | tr -d ' ')
      [ "$st" = "COMPLETED" ] || ok=0
    done
    if [ "$ok" = "1" ]; then
      write_status "RESULT: ALL JOBS COMPLETED."
    else
      write_status "RESULT: CHAIN FINISHED WITH FAILURES. Inspect the per-job logs above."
    fi
    exit 0
  fi

  write_status "RESULT: IN PROGRESS. Watchdog is still polling."
  sleep "$SLEEP_SECONDS"
done
