from __future__ import annotations

from typing import Mapping, Sequence

# NOTE on templating style: the rendered bash body is full of literal shell ${VAR} syntax and
# SLURM %j/%x output-path tokens. Both collide with Python's str.format() ("{...}") and
# %-style formatting ("%x"/"%j" look like format specifiers). To avoid escaping either, each
# script is built as a list of lines - f-strings are used only on lines that actually inject a
# Python value and contain no literal ${...}/%j/%x on that same line; every other line is a
# plain string.

CORRECT_LD_LIBRARY_PATH = "/path/to/software/python/python-3.11.3/lib:/path/to/software/rh8/usr/lib64"

# Confirmed by direct inspection (SSH + real sourcing test) that ~/kc_l_v2_env.sh does NOT
# provide these two - both required for MinerU to use its real local model cache
# (/path/to/scratch/kc_l/mineru_models/PDF-Extract-Kit-1.0, confirmed to actually
# contain the real unimernet_hf_small_2503 model) instead of trying to reach the (unreachable)
# HuggingFace Hub. Values match the confirmed-good manual reference launcher
# (run_step2_pair_validate.slurm) exactly.
MINERU_TOOLS_CONFIG_JSON = "/path/to/scratch/kc_l/config/mineru_local.json"
MINERU_MODEL_SOURCE = "local"


def _env_parity_lines(*, restore_strict: bool) -> list[str]:
    """Source ~/kc_l_v2_env.sh (HF_HOME/XDG_CACHE_HOME/TRANSFORMERS_CACHE/TORCH_HOME/
    OLLAMA_*/DOCLING_BIN/MINERU_BIN/PATH/its own Ollama-CUDA LD_LIBRARY_PATH entries) plus the
    2 vars confirmed missing from it - the systemic env-parity gap between the orchestrator's
    rendered jobs and the confirmed-good manually-authored launcher scripts.

    Two things confirmed the hard way (by actually sourcing it via SSH), not assumed:
    1. `module load python/python-3.11.3` (the script's first line) fails with "command not
       found" when sourced from a non-login shell - which is exactly what a SLURM batch script
       is. Under `set -e`, this SILENTLY ABORTS THE WHOLE JOB right at the source line, before
       any real work runs - confirmed directly: a test script with `set -euo pipefail; source
       ~/kc_l_v2_env.sh; echo REACHED` never printed REACHED. `set +e` brackets the source call
       so this known, harmless quirk (the LD_LIBRARY_PATH module load would have set is already
       covered by CORRECT_LD_LIBRARY_PATH above) cannot abort the job, while a genuinely broken
       source (nothing after it executing) is still caught by the HF_HOME canary check below -
       fail loudly, don't let this become a second silent-failure mode.
    2. The hardcoded CORRECT_LD_LIBRARY_PATH line MUST run before this, not after: this
       function's own `export LD_LIBRARY_PATH="...:${LD_LIBRARY_PATH:-}"` line preserves
       whatever was already set by appending it at the end - sourcing first and setting
       CORRECT_LD_LIBRARY_PATH after would instead need the reverse ":$LD_LIBRARY_PATH" pattern
       and still work, but calling this AFTER the existing hardcoded export (already rendered
       by both functions before this helper is called) means both paths end up present with no
       template changes needed at the call site beyond inserting this block.

    restore_strict: whether to leave `set -e` active after the source call, matching whatever
    mode the CALLING template uses for the rest of its own script - render_cpu_job() runs under
    `set -euo pipefail` throughout (restore_strict=True: temporarily suspend it only for this
    known-noisy source call, then turn it back on exactly as before). render_ollama_job() runs
    under `set +e` throughout by design (its own docstring: explicit $? checks like READY_RC/
    MODEL_VISIBLE_RC/RUNNER_RC instead of shell error-exit semantics) - restore_strict=False
    leaves it in that same +e mode rather than silently switching the rest of that script to
    strict mode, which would break its own designed error handling.
    """
    return [
        'KC_L_V2_ENV="$HOME/kc_l_v2_env.sh"',
        'if [ ! -f "$KC_L_V2_ENV" ]; then',
        '  echo "FATAL: kc_l_v2_env.sh not found at $KC_L_V2_ENV"',
        "  exit 1",
        "fi",
        "set +e",
        'source "$KC_L_V2_ENV"',
        "set -e" if restore_strict else "set +e",
        'if [ -z "${HF_HOME:-}" ]; then',
        '  echo "FATAL: kc_l_v2_env.sh did not set HF_HOME - environment sourcing may have failed"',
        "  exit 1",
        "fi",
        f'export MINERU_TOOLS_CONFIG_JSON={_shell_quote(MINERU_TOOLS_CONFIG_JSON)}',
        f'export MINERU_MODEL_SOURCE={_shell_quote(MINERU_MODEL_SOURCE)}',
    ]


def _sbatch_header(
    *,
    job_name: str,
    partition: str,
    cpus_per_task: int,
    mem: str,
    time_limit: str,
    log_dir: str,
    gres: str | None = None,
    exclude_nodes: str | None = None,
) -> list[str]:
    lines = [
        "#!/bin/bash",
        f"#SBATCH --job-name={job_name}",
        f"#SBATCH --partition={partition}",
    ]
    if gres:
        lines.append(f"#SBATCH --gres={gres}")
    if exclude_nodes:
        lines.append(f"#SBATCH --exclude={exclude_nodes}")
    lines += [
        f"#SBATCH --cpus-per-task={cpus_per_task}",
        f"#SBATCH --mem={mem}",
        f"#SBATCH --time={time_limit}",
        f"#SBATCH --output={log_dir}/slurm-%j.out",
        f"#SBATCH --error={log_dir}/slurm-%j.err",
        "",
    ]
    return lines


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def render_cpu_job(
    *,
    job_name: str,
    run_id: str,
    repo_root: str,
    python_bin: str,
    script_path: str,
    script_args: Sequence[str],
    log_dir: str,
    partition: str = "big",
    cpus_per_task: int = 8,
    mem: str = "64G",
    time_limit: str = "04:00:00",
    gres: str | None = None,
    extra_env: Mapping[str, str] | None = None,
    pre_commands: Sequence[str] = (),
    extra_commands: Sequence[str] = (),
) -> str:
    """Render a plain CPU-or-GPU (non-Ollama) stage SLURM script.

    Always sets LD_LIBRARY_PATH explicitly to the confirmed-correct HPC path - never relies
    on it being inherited from the submitting shell.

    gres: optional SLURM GPU resource request (e.g. "gpu:a40:1"), mirroring render_ollama_job's
    existing gres parameter - _sbatch_header() already supports this optionally. When None (the
    default, used by every stage wired before this parameter existed), the rendered script is
    byte-identical to before. This is for stages that need real GPU-accelerated Python/torch
    processing without Ollama's own serve/ready-poll/model-check machinery (e.g. Docling/MinerU)
    - callers combine it with an explicit `partition` override (the default "big" partition has
    no GPUs) and typically an extra_env entry any GPU-aware subprocess needs (e.g.
    MINERU_DEVICE_MODE).

    pre_commands: optional raw bash lines run BEFORE the main script_path command, after env
    setup - e.g. `nvidia-smi || true` for GPU visibility in the log, matching the confirmed-good
    historical GPU launcher (run_step3_6_actual_corpus_gpu.slurm). When empty (the default), the
    rendered script is byte-identical to before.

    extra_commands: optional raw bash lines run AFTER the main script_path command, in the same
    SLURM job, only if it exits 0 (checked explicitly rather than relying solely on `set -e`, so
    the intermediate RUNNER_RC is always visible in the log). Used for stages whose real-world
    launcher chains a second script in the same job - e.g. a "freeze the ACTIVE pointer" step
    that must run after the main stage script and needs a value (like an internally-generated
    timestamp run_id) that is only knowable once the main script has actually written its
    output, not predictable ahead of time. When empty (the default, used by every stage wired
    before this parameter existed), the rendered script is byte-identical to before.
    """
    lines = _sbatch_header(
        job_name=job_name,
        partition=partition,
        cpus_per_task=cpus_per_task,
        mem=mem,
        time_limit=time_limit,
        log_dir=log_dir,
        gres=gres,
    )
    lines += [
        "set -euo pipefail",
        "",
        f"REPO={_shell_quote(repo_root)}",
        'cd "$REPO"',
        "",
        'export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"',
        f'export LD_LIBRARY_PATH="{CORRECT_LD_LIBRARY_PATH}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"',
        "",
    ]
    lines += _env_parity_lines(restore_strict=True)
    for key, value in (extra_env or {}).items():
        lines.append(f"export {key}={_shell_quote(value)}")
    lines += [
        "",
        f'echo "===== {job_name} (run_id={run_id}) ====="',
        "date -u",
        "hostname",
        'echo "SLURM_JOB_ID=${SLURM_JOB_ID:-}"',
        f'echo "RUN_ID={run_id}"',
        "",
    ]
    if pre_commands:
        lines += list(pre_commands)
        lines += [""]
    lines += [
        _build_command_line(python_bin, script_path, script_args),
    ]
    if extra_commands:
        lines += [
            "RUNNER_RC=$?",
            'echo "RUNNER_RC=$RUNNER_RC"',
            'if [ "$RUNNER_RC" -ne 0 ]; then exit "$RUNNER_RC"; fi',
            "",
        ]
        lines += list(extra_commands)
        lines += [
            "",
            'exit 0',
            "",
        ]
    else:
        lines += [
            "RUNNER_RC=$?",
            'echo "RUNNER_RC=$RUNNER_RC"',
            'exit "$RUNNER_RC"',
            "",
        ]
    return "\n".join(lines)


def render_ollama_job(
    *,
    job_name: str,
    run_id: str,
    repo_root: str,
    python_bin: str,
    script_path: str,
    script_args: Sequence[str],
    log_dir: str,
    model: str,
    num_ctx: int,
    num_predict: int,
    ollama_bin: str,
    ollama_models_dir: str,
    runtime_env_path: str | None = None,
    partition: str = "gpu80GB",
    gres: str = "gpu:1",
    cpus_per_task: int = 8,
    mem: str = "64G",
    time_limit: str = "06:00:00",
    extra_env: Mapping[str, str] | None = None,
    extra_commands: Sequence[str] = (),
    exclude_nodes: str | None = "gpu03",
    ollama_host_cli_arg: str | None = '--ollama-host "$OLLAMA_HOST"',
    require_main_command_success: bool = True,
) -> str:
    """Render a GPU/Ollama stage SLURM script.

    Modeled directly on the confirmed-good
    step67_v2_full165_kc_topic_policy_marker_fix_20260520T195051Z.slurm: start `ollama serve`
    in the background, poll /api/tags until ready, confirm the target model is visible via
    `ollama list`, then run the stage script. Always sets LD_LIBRARY_PATH explicitly.

    `ollama_host_cli_arg` is appended to the command automatically (as a raw, unquoted trailing
    arg) - do not include an equivalent flag in script_args yourself. It defaults to
    `--ollama-host "$OLLAMA_HOST"`, matching every stage wired before this parameter existed
    (their rendered scripts are byte-identical to before). OLLAMA_HOST is computed at runtime
    from a per-job dynamic port, so this must stay a raw trailing arg rather than a script_args
    entry - script_args are always single-quoted as literals, which would pass the literal
    string "$OLLAMA_HOST" instead of its expanded value. Pass a different string (e.g.
    `--base-url "http://$OLLAMA_HOST"`) for a target script whose argparse uses a different
    flag name and/or expects a full scheme-included URL instead of a bare host:port. Pass None
    to suppress the trailing arg entirely for a script that accepts neither.

    extra_commands: same contract as render_cpu_job's own extra_commands - raw bash lines run
    AFTER the main script_path command, only if it exits 0. This whole function uses `set +e`
    (unlike render_cpu_job's `set -euo pipefail`), so the RUNNER_RC guard below is added
    explicitly rather than relying on shell error-exit semantics. When empty (the default,
    used by every stage wired before this parameter existed), the rendered script is
    byte-identical to before.
    """
    lines = _sbatch_header(
        job_name=job_name,
        partition=partition,
        cpus_per_task=cpus_per_task,
        mem=mem,
        time_limit=time_limit,
        log_dir=log_dir,
        gres=gres,
        exclude_nodes=exclude_nodes,
    )
    lines += [
        "set +e",
        "",
        f"REPO={_shell_quote(repo_root)}",
        f"RUN_ID={_shell_quote(run_id)}",
        f"LOG_DIR={_shell_quote(log_dir)}",
        "",
        'export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"',
        f'export LD_LIBRARY_PATH="{CORRECT_LD_LIBRARY_PATH}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"',
        "",
    ]
    lines += _env_parity_lines(restore_strict=False)
    lines += [
        "",
        'cd "$REPO"',
        "",
    ]
    if runtime_env_path:
        lines += [
            f"RUNTIME_ENV={_shell_quote(runtime_env_path)}",
            'if [ -f "$RUNTIME_ENV" ]; then',
            "  set -a",
            '  . "$RUNTIME_ENV"',
            "  set +a",
            "fi",
            "",
        ]
    lines += [
        f"export OLLAMA_BIN={_shell_quote(ollama_bin)}",
        f"export OLLAMA_MODELS={_shell_quote(ollama_models_dir)}",
        f"export KC_L_PROFILE_MODEL={_shell_quote(model)}",
        f'export OLLAMA_CONTEXT_LENGTH="{num_ctx}"',
        f'export KC_L_STEP67_V2_NUM_PREDICT="{num_predict}"',
        'export OLLAMA_NUM_PARALLEL="1"',
        'export OLLAMA_MAX_LOADED_MODELS="1"',
    ]
    for key, value in (extra_env or {}).items():
        lines.append(f"export {key}={_shell_quote(value)}")
    lines += [
        "",
        "PORT=$((25000 + (${SLURM_JOB_ID:-0} % 10000)))",
        'export OLLAMA_HOST="127.0.0.1:$PORT"',
        "",
        f'echo "===== {job_name} (run_id={run_id}) ====="',
        "date -u",
        "hostname",
        'echo "SLURM_JOB_ID=${SLURM_JOB_ID:-}"',
        f'echo "RUN_ID={run_id}"',
        'echo "OLLAMA_HOST=$OLLAMA_HOST"',
        "",
        'mkdir -p "$LOG_DIR"',
        "",
        '"$OLLAMA_BIN" serve > "$LOG_DIR/ollama_serve.log" 2>&1 &',
        "OLLAMA_PID=$!",
        "",
        _shell_quote(python_bin) + " - <<'PYWAIT'",
    ]
    lines += [
        "from __future__ import annotations",
        "",
        "import os",
        "import time",
        "import urllib.request",
        "",
        'url = "http://" + os.environ["OLLAMA_HOST"] + "/api/tags"',
        "ready = False",
        'last_error = ""',
        "for _ in range(90):",
        "    try:",
        "        with urllib.request.urlopen(url, timeout=2) as r:",
        '            print("OLLAMA_READY=1")',
        '            print(r.read().decode("utf-8", errors="replace")[:800])',
        "            ready = True",
        "            break",
        "    except Exception as exc:",
        '        last_error = type(exc).__name__ + ": " + str(exc)',
        "        time.sleep(2)",
        "",
        "if not ready:",
        '    print("OLLAMA_READY=0")',
        '    print("LAST_ERROR=" + last_error)',
        '    raise RuntimeError("Ollama did not become ready")',
        "PYWAIT",
        "",
        "READY_RC=$?",
        'echo "READY_RC=$READY_RC"',
        "",
        'if [ "$READY_RC" -ne 0 ]; then',
        '  echo "FINAL_RC=21"',
        "  exit 21",
        "fi",
        "",
        '"$OLLAMA_BIN" list > "$LOG_DIR/ollama_list.txt" 2>&1',
        'cat "$LOG_DIR/ollama_list.txt"',
        "",
        f'grep -q {_shell_quote(model)} "$LOG_DIR/ollama_list.txt"',
        "MODEL_VISIBLE_RC=$?",
        'echo "MODEL_VISIBLE_RC=$MODEL_VISIBLE_RC"',
        "",
        'if [ "$MODEL_VISIBLE_RC" -ne 0 ]; then',
        '  echo "FINAL_RC=22"',
        "  exit 22",
        "fi",
        "",
        _build_command_line(
            python_bin,
            script_path,
            script_args,
            raw_trailing_args=(ollama_host_cli_arg,) if ollama_host_cli_arg else (),
        ),
        "RUNNER_RC=$?",
        'echo "RUNNER_RC=$RUNNER_RC"',
    ]
    if extra_commands:
        if require_main_command_success:
            lines += [
                'if [ "$RUNNER_RC" -ne 0 ]; then exit "$RUNNER_RC"; fi',
                "",
            ]
        else:
            # require_main_command_success=False (2026-08-16, job 245994 incident): the main
            # command's own exit code is informational only here, already echoed above as
            # RUNNER_RC - it does NOT gate whether extra_commands run. Used when the main
            # command's exit code conflates "genuinely failed" with an unrelated informational
            # signal (run_step67_v2_schema_contract_probe.py returns 2 whenever ANY record
            # needed schema repair, even one that repaired cleanly, not only on real failures -
            # the standalone v3/jobs/02_draft_kc_*.sbatch scripts already just echo this rc and
            # never act on it) and extra_commands already implements its own correct, stricter
            # gating via real output-artifact checks (see step_06v_kc_draft_generation's own
            # extra_commands: a [ -f ... ] check for the raw drafts file and a VALIDATE_RC check
            # from the actual validate_drafts.py run - those are what should decide success here).
            lines += [""]
        lines += list(extra_commands)
        lines += [
            "",
            'exit 0',
            "",
        ]
    else:
        lines += [
            'exit "$RUNNER_RC"',
            "",
        ]
    return "\n".join(lines)


def _build_command_line(
    python_bin: str,
    script_path: str,
    script_args: Sequence[str],
    *,
    raw_trailing_args: Sequence[str] = (),
) -> str:
    """Build the final command line. script_args are literal values and always single-quoted
    (safe against word-splitting/globbing). raw_trailing_args are inserted verbatim - use this
    only for shell variable references (e.g. '--ollama-host "$OLLAMA_HOST"") that must expand
    at runtime; single-quoting one of those would silently pass the literal string instead of
    its expanded value (caught by rendering and inspecting a real script during development).
    """
    parts = [_shell_quote(python_bin), _shell_quote(script_path)] + [_shell_quote(a) for a in script_args]
    parts += list(raw_trailing_args)
    return " ".join(parts)
