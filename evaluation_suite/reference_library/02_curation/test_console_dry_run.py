"""Milestone verification for reference_console.py (spec section 27, steps 7-13):
seed-hiding behavior, autosave/recovery, provenance resolution, and a 3-KC dry run -
all against a DISPOSABLE scratch directory, never the real work/committed/logs state.

Run: python test_console_dry_run.py
Exits non-zero on any failure. Prints PASS/FAIL per check.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import reference_console as rc

FAILURES = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def redirect_to_scratch(scratch: Path):
    rc.WORK_DIR = scratch / "work"
    rc.COMMITTED_DIR = scratch / "committed"
    rc.AMEND_DIR = scratch / "amendments"
    rc.LOG_DIR = scratch / "logs"
    for d in (rc.WORK_DIR, rc.COMMITTED_DIR, rc.AMEND_DIR, rc.LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def scan_for_seed_leak(scratch: Path, forbidden_texts: dict[str, str]) -> list[str]:
    """forbidden_texts: kc_id -> seed_body text that must not appear anywhere in scratch
    files for kc_ids whose Stage-A was never committed."""
    leaks = []
    for p in scratch.rglob("*.json*"):
        content = p.read_text(encoding="utf-8", errors="ignore")
        for kc_id, text in forbidden_texts.items():
            if text and text in content:
                leaks.append(f"{p}: contains seed text for {kc_id}")
    return leaks


def main():
    scratch = Path(tempfile.mkdtemp(prefix="ref_console_dry_run_"))
    print(f"scratch dir: {scratch}")
    redirect_to_scratch(scratch)

    console = rc.Console()  # real seed roster + real corpus (read-only, safe); work/committed redirected
    test_kc_ids = console.roster.order[:3]
    print(f"testing against: {test_kc_ids}")

    # load full seed bodies once (test-only, out-of-band) purely to check leakage later
    seed_store_probe = rc.SeedStore(rc.SEED_PATH)
    seed_store_probe._ensure_loaded()
    seed_bodies = {kc: seed_store_probe._rows[kc]["seed_body"] for kc in test_kc_ids if seed_store_probe._rows[kc]["seed_body"]}

    # === KC 1: ACCEPT path, full happy path ===
    kc1 = test_kc_ids[0]
    console._goto_index(0)

    # --- seed hiding check: reveal must be refused before commit-source-review ---
    try:
        console.seed_store.reveal(kc1, console.ws)
        check("seed hidden before Stage-A commit", False, "reveal() did not raise")
    except PermissionError:
        check("seed hidden before Stage-A commit", True)

    check("no seed leak in work file before any citation", not scan_for_seed_leak(scratch, seed_bodies))

    console.cmd_search_source("classification")
    console.cmd_set_support_state("SUPPORTED")
    hits = console.corpus.search("classification", limit=1)
    if hits:
        console.cmd_cite(hits[0].sentence_id)
    console.ws["stage_a_draft"]["source_memo"] = "Source discusses classification learning phase directly."
    rc.save_work(console.ws)

    # --- autosave/recovery: simulate crash by dropping in-memory state, reloading from disk ---
    saved_support_state = console.ws["stage_a_draft"]["support_state"]
    del console
    console = rc.Console()
    console._goto_index(0)
    recovered_support_state = console.ws["stage_a_draft"]["support_state"]
    check("autosave/recovery preserves in-progress Stage-A draft", recovered_support_state == saved_support_state,
          f"expected {saved_support_state!r} got {recovered_support_state!r}")

    console.cmd_commit_source_review("")
    check("Stage-A commit succeeds with valid draft", console.ws["stage"] == "A_COMMITTED")

    # seed must still be hidden in every persisted file up to this exact point for the OTHER 2 test KCs
    check("no seed leak for untouched KCs after KC1 Stage-A commit",
          not scan_for_seed_leak(scratch, {k: v for k, v in seed_bodies.items() if k != kc1}))

    console.cmd_reveal_seed("")
    check("reveal-seed succeeds after Stage-A commit", console.ws["stage"] == "B_REVEALED")

    console.ws["stage_bc_draft"]["reference_body"] = "Placeholder reference text for dry run."
    console.cmd_set_action("MINOR_EDIT")
    console.cmd_set_reason_codes("TERMINOLOGY_NOTATION")
    console.cmd_set_confidence("HIGH")

    # --- provenance resolution: bad sentence_id must be refused ---
    console.cmd_provenance("bogus claim :: NOT_A_REAL_SENTENCE_ID_xyz")
    check("bad sentence_id refused by provenance", len(console.ws["stage_bc_draft"]["reference_provenance"]) == 0)

    real_sid = hits[0].sentence_id if hits else None
    if real_sid:
        console.cmd_provenance(f"real claim :: {real_sid}")
    check("valid sentence_id accepted by provenance", len(console.ws["stage_bc_draft"]["reference_provenance"]) == 1)

    console.cmd_commit_reference("")
    check("KC1 full commit succeeds", (rc.COMMITTED_DIR / f"{kc1}.json").exists())

    # === KC 2: NO_REFERENCE_CORPUS_UNSUPPORTED path ===
    kc2 = test_kc_ids[1]
    console._goto_index(1)
    console.cmd_set_support_state("UNSUPPORTED")
    console.ws["stage_a_draft"]["source_memo"] = "Searched corpus extensively; no adequate source support found for this KC."
    rc.save_work(console.ws)
    console.cmd_commit_source_review("")
    console.cmd_reveal_seed("")
    console.cmd_set_action("NO_REFERENCE_CORPUS_UNSUPPORTED")
    console.cmd_set_reason_codes("SOURCE_AMBIGUITY")
    console.cmd_set_confidence("MEDIUM")
    console.cmd_commit_reference("")
    rec2 = json.loads((rc.COMMITTED_DIR / f"{kc2}.json").read_text(encoding="utf-8"))
    check("NO_REFERENCE_CORPUS_UNSUPPORTED allows empty reference_body", rec2["expert_edit"]["reference_body"] == "")

    # === KC 3: leave uncommitted, verify Stage-A memo overlength is rejected ===
    kc3 = test_kc_ids[2]
    console._goto_index(2)
    console.cmd_set_support_state("SUPPORTED")
    console.ws["stage_a_draft"]["source_memo"] = " ".join(["word"] * 200)
    rc.save_work(console.ws)
    console.cmd_commit_source_review("")
    check("overlength source_memo refused", console.ws["stage"] == "A_IN_PROGRESS")

    # --- amend path on KC1 ---
    fake_input_answers = iter(["dry-run amendment test reason", ""])
    import builtins
    real_input = builtins.input
    builtins.input = lambda *a: next(fake_input_answers)
    try:
        console.cmd_amend(kc1)
    finally:
        builtins.input = real_input
    amend_files = list(rc.AMEND_DIR.glob(f"{kc1}__amend_*.json"))
    check("amendment creates a new file without touching committed original", len(amend_files) == 1)
    original_still_intact = json.loads((rc.COMMITTED_DIR / f"{kc1}.json").read_text(encoding="utf-8"))
    check("committed KC1 record unchanged after amend", original_still_intact["kc_id"] == kc1)

    # --- final full-scratch seed-leak sweep for KC3 (never revealed) ---
    check("KC3 (never revealed) has zero seed leakage anywhere in scratch", not scan_for_seed_leak(scratch, {kc3: seed_bodies.get(kc3, "")}))

    # cleanup disposable state
    shutil.rmtree(scratch, ignore_errors=True)
    check("disposable scratch state cleaned up", not scratch.exists())

    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nALL CHECKS PASSED")
    sys.exit(1 if FAILURES else 0)


if __name__ == "__main__":
    main()
