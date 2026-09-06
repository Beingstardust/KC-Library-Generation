from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_run_stage_list_json():
    result = _run("scripts/local/run_stage.py", "--json", "list")
    payload = json.loads(result.stdout)
    assert any(row["key"] == "draft_generation" for row in payload)


def test_operator_repo_check_script_passes():
    result = _run("scripts/maintenance/check_operator_repo.py")
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_intake_preflight_blocks_without_real_inputs():
    result = _run("scripts/local/run_stage.py", "--json", "intake")
    payload = json.loads(result.stdout)
    assert payload["support_ready"] is True
    assert payload["ready_for_first_run"] is False
    assert "No course materials have been added to data/input/course_materials yet." in payload["blocking_conditions"]
    assert "No hierarchy input has been added to data/input/hierarchy yet." in payload["blocking_conditions"]


def test_review_and_freeze_preflight_block_without_generated_outputs():
    review_payload = json.loads(_run("scripts/local/run_stage.py", "--json", "review-preflight").stdout)
    freeze_payload = json.loads(_run("scripts/local/run_stage.py", "--json", "freeze-preflight").stdout)
    assert review_payload["support_ready"] is True
    assert review_payload["ready_for_first_run"] is False
    assert review_payload["blocking_conditions"] == ["No fresh review packet bundle exists yet in this clean repo."]
    assert freeze_payload["support_ready"] is True
    assert freeze_payload["ready_for_first_run"] is False
    assert freeze_payload["blocking_conditions"] == ["No approved frozen library exists yet in this clean repo."]
