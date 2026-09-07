"""Two-stage expert curation console for the 159-KC reference library.

STAGE A (source-first review) happens with the Qwen seed strictly hidden. STAGE B/C
(seed reveal + expert edit) only unlocks after Stage A is committed for that KC.

Hard safety rule enforced in code, not just by convention: SeedStore.reveal is the
ONLY code path in this file that ever reads seed_body/seed_status out of qwen_seed.jsonl,
and it refuses unless the work-state for that kc_id already has stage_a committed. No
other command handler holds a reference to seed content before that gate passes.

Autosave writes the in-progress work record to 02_curation/work/<kc_id>.json after every
mutating command, so a crash cannot lose the expert's current edit. Autosave is NOT commit:
Stage-A stays fully editable via save-draft until commit-source-review is run; after that,
the committed Stage-A snapshot is never edited again in place (see 'amend').
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from corpus_search import CorpusIndex
import reference_schema as schema

BASE = Path(__file__).parent
SEED_PATH = BASE.parent / "01_seed" / "qwen_seed.jsonl"
WORK_DIR = BASE / "work"
COMMITTED_DIR = BASE / "committed"
AMEND_DIR = BASE / "amendments"
LOG_DIR = BASE / "logs"
for d in (WORK_DIR, COMMITTED_DIR, AMEND_DIR, LOG_DIR):
    d.mkdir(parents=True, exist_ok=True)


def log(event: str, **fields) -> None:
    rec = {"ts": schema.utcnow_iso(), "event": event, **fields}
    with open(LOG_DIR / "console.log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


class KCRoster:
    """Identity-only fields (kc_id, canonical_name, hierarchy_path). Never holds seed_body."""

    def __init__(self, path: Path):
        self.entries: dict[str, dict] = {}
        self.order: list[str] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                kc_id = row["kc_id"]
                self.entries[kc_id] = {
                    "kc_id": kc_id,
                    "canonical_name": row["canonical_name"],
                    "hierarchy_path": row["hierarchy_path"],
                }
                self.order.append(kc_id)
        self.order.sort()


class SeedStore:
    """Gated access to seed_body/seed_status. reveal() is the only method that returns them,
    and it refuses unless work-state proves Stage-A is already committed for that kc_id."""

    def __init__(self, path: Path):
        self._path = path
        self._rows: dict[str, dict] | None = None  # lazily loaded, holds full rows incl. body

    def _ensure_loaded(self) -> None:
        if self._rows is None:
            rows = {}
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    rows[row["kc_id"]] = row
            self._rows = rows

    def reveal(self, kc_id: str, work_state: dict) -> dict:
        if work_state.get("stage") not in ("A_COMMITTED", "B_REVEALED", "COMMITTED"):
            raise PermissionError(
                f"REFUSED: Stage-A source review is not yet committed for {kc_id}. "
                "Run commit-source-review before reveal-seed."
            )
        self._ensure_loaded()
        return self._rows[kc_id]


def new_work_state(kc_id: str) -> dict:
    return {
        "kc_id": kc_id,
        "stage": "A_IN_PROGRESS",
        "stage_a_draft": {"support_state": None, "source_refs": [], "source_memo": "", "search_log": []},
        "stage_a_committed": None,
        "stage_bc_draft": {"action": None, "reason_codes": [], "reference_body": "", "reference_provenance": [], "confidence": None, "review_seconds": None},
        "review_started_at": time.time(),
        "seed_revealed_at": None,
        "last_saved_at": None,
    }


def load_work(kc_id: str) -> dict:
    p = WORK_DIR / f"{kc_id}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    committed_p = COMMITTED_DIR / f"{kc_id}.json"
    if committed_p.exists():
        rec = json.loads(committed_p.read_text(encoding="utf-8"))
        ws = new_work_state(kc_id)
        ws["stage"] = "COMMITTED"
        ws["stage_a_committed"] = rec["source_first_review"]
        ws["stage_bc_committed"] = rec["expert_edit"]
        return ws
    return new_work_state(kc_id)


def save_work(ws: dict) -> None:
    ws["last_saved_at"] = schema.utcnow_iso()
    p = WORK_DIR / f"{ws['kc_id']}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ws, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)  # atomic on both POSIX and Windows - protects against a crash mid-write


def open_in_editor(initial_text: str) -> str:
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write(initial_text)
        path = tf.name
    try:
        subprocess.run([editor, path], check=False)
        return Path(path).read_text(encoding="utf-8")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class Console:
    def __init__(self):
        self.roster = KCRoster(SEED_PATH)
        self.seed_store = SeedStore(SEED_PATH)
        self.corpus = CorpusIndex(str(BASE.parent / "corpus_support" / "sentence_corpus.jsonl"))
        self.cursor = 0
        self.ws = load_work(self.roster.order[self.cursor])
        log("session_start", n_kc=len(self.roster.order))

    # -- navigation --
    def _goto_index(self, idx: int) -> None:
        idx = max(0, min(len(self.roster.order) - 1, idx))
        self.cursor = idx
        self.ws = load_work(self.roster.order[self.cursor])
        self._print_kc_header()

    def cmd_next(self, _arg):
        self._goto_index(self.cursor + 1)

    def cmd_previous(self, _arg):
        self._goto_index(self.cursor - 1)

    def cmd_goto(self, arg):
        kc_id = arg.strip()
        if kc_id not in self.roster.entries:
            print(f"unknown kc_id: {kc_id}")
            return
        self._goto_index(self.roster.order.index(kc_id))

    def _print_kc_header(self):
        e = self.roster.entries[self.ws["kc_id"]]
        idx = self.cursor + 1
        n = len(self.roster.order)
        seed_state = {"A_IN_PROGRESS": "SEED HIDDEN", "A_COMMITTED": "SOURCE REVIEW COMMITTED (seed not yet revealed)",
                      "B_REVEALED": "SEED REVEALED", "COMMITTED": "COMMITTED"}[self.ws["stage"]]
        print(f"\n[{idx}/{n}] {e['kc_id']} - {e['canonical_name']}")
        print(f"  hierarchy: {' > '.join(e['hierarchy_path'])}")
        print(f"  status: {seed_state}")

    # -- source search/navigation --
    def cmd_search_source(self, arg):
        parts = arg.split()
        regex = False
        if parts and parts[0] == "--regex":
            regex = True
            parts = parts[1:]
        query = " ".join(parts)
        try:
            hits = self.corpus.search(query, regex=regex, limit=25)
        except ValueError as e:
            print(f"error: {e}")
            return
        self.ws["stage_a_draft"]["search_log"].append({"query": query, "regex": regex, "n_hits": len(hits), "ts": schema.utcnow_iso()})
        save_work(self.ws)
        if not hits:
            print("no matches")
            return
        for s in hits:
            print(f"  {s.sentence_id}  (p.{s.page_index})  {s.sentence_text[:120]}")

    def cmd_open_source(self, arg):
        sid = arg.strip()
        s = self.corpus.get(sid)
        if s is None:
            print(f"no such sentence_id: {sid}")
            return
        print(f"[{s.sentence_id}] doc={s.doc_id} page={s.page_index} block={s.block_id}")
        print(f"  sentence: {s.sentence_text}")
        print(f"  block text: {s.source_block_text[:500]}")
        flags = [n for n, v in (("formula", s.is_formula_like), ("definition", s.is_definition_like),
                                 ("procedure", s.is_procedure_like), ("example", s.is_example_like)) if v]
        if flags:
            print(f"  content type: {', '.join(flags)}")

    def cmd_show_source_context(self, arg):
        sid = arg.strip()
        ctx = self.corpus.context(sid, before=3, after=3)
        if not ctx:
            print(f"no such sentence_id: {sid}")
            return
        for s in ctx:
            marker = ">>" if s.sentence_id == sid else "  "
            print(f"{marker} [{s.sentence_id}] {s.sentence_text}")

    # -- stage A --
    def cmd_set_support_state(self, arg):
        state = arg.strip().upper()
        if state not in schema.SUPPORT_STATES:
            print(f"must be one of {schema.SUPPORT_STATES}")
            return
        self.ws["stage_a_draft"]["support_state"] = state
        save_work(self.ws)
        print(f"support_state set to {state}")

    def cmd_cite(self, arg):
        sid = arg.strip()
        if not self.corpus.resolve(sid):
            print(f"REFUSED: {sid} does not resolve in the corpus - not added")
            return
        refs = self.ws["stage_a_draft"]["source_refs"]
        if not any(r["sentence_id"] == sid for r in refs):
            s = self.corpus.get(sid)
            refs.append({"sentence_id": sid, "doc_id": s.doc_id, "excerpt": s.sentence_text[:200]})
            save_work(self.ws)
        print(f"cited: {sid}  ({len(refs)} total)")

    def cmd_uncite(self, arg):
        sid = arg.strip()
        refs = self.ws["stage_a_draft"]["source_refs"]
        self.ws["stage_a_draft"]["source_refs"] = [r for r in refs if r["sentence_id"] != sid]
        save_work(self.ws)
        print(f"removed {sid}")

    def cmd_memo(self, _arg):
        current = self.ws["stage_a_draft"]["source_memo"]
        text = open_in_editor(current or "# Write your 1-4 sentence pre-seed source memo below this line.\n")
        text = "\n".join(l for l in text.splitlines() if not l.startswith("#")).strip()
        self.ws["stage_a_draft"]["source_memo"] = text
        save_work(self.ws)
        print(f"memo saved ({len(text.split())} words)")

    def cmd_save_draft(self, _arg):
        save_work(self.ws)
        print("draft autosaved")

    def cmd_commit_source_review(self, _arg):
        if self.ws["stage"] != "A_IN_PROGRESS":
            print(f"REFUSED: stage is {self.ws['stage']}, not A_IN_PROGRESS")
            return
        d = self.ws["stage_a_draft"]
        stage_a = schema.StageASourceFirstReview(
            support_state=d["support_state"], source_refs=d["source_refs"],
            source_memo=d["source_memo"], search_log=d["search_log"],
        )
        try:
            committed = stage_a.to_committed_dict()
        except schema.SchemaError as e:
            print(f"REFUSED: {e}")
            return
        self.ws["stage_a_committed"] = committed
        self.ws["stage"] = "A_COMMITTED"
        save_work(self.ws)
        log("stage_a_committed", kc_id=self.ws["kc_id"], support_state=committed["support_state"], sha256=committed["sha256"])
        print(f"Stage-A committed and LOCKED for {self.ws['kc_id']}. It cannot be edited from here on - use 'amend' if a correction is genuinely required later.")

    # -- stage B/C --
    def cmd_reveal_seed(self, _arg):
        try:
            seed = self.seed_store.reveal(self.ws["kc_id"], self.ws)
        except PermissionError as e:
            print(str(e))
            return
        if self.ws["stage"] == "A_COMMITTED":
            self.ws["stage"] = "B_REVEALED"
            self.ws["seed_revealed_at"] = schema.utcnow_iso()
            save_work(self.ws)
            log("seed_revealed", kc_id=self.ws["kc_id"])
        print(f"\n--- SEED (status: {seed['seed_status']}) ---")
        print(seed["seed_body"] or "(empty - no draft text)")
        print("--- end seed ---")
        print(
            "\nWrite the reference from the course corpus, not from the Qwen wording. The Qwen draft "
            "is only an editing scaffold. Preserve its text only where you independently judge that "
            "text to be the clearest source-faithful representation. You are free to delete, add, "
            "reorganize, or rewrite it."
        )

    def cmd_edit_reference(self, _arg):
        if self.ws["stage"] not in ("B_REVEALED",):
            print(f"REFUSED: reveal-seed first (current stage: {self.ws['stage']})")
            return
        current = self.ws["stage_bc_draft"]["reference_body"]
        text = open_in_editor(current)
        self.ws["stage_bc_draft"]["reference_body"] = text
        save_work(self.ws)
        print(f"reference_body saved ({len(text.split())} words)")

    def cmd_set_action(self, arg):
        action = arg.strip().upper()
        if action not in schema.EXPERT_ACTIONS:
            print(f"must be one of {schema.EXPERT_ACTIONS}")
            return
        self.ws["stage_bc_draft"]["action"] = action
        save_work(self.ws)

    def cmd_set_reason_codes(self, arg):
        codes = [c.strip().upper() for c in arg.split(",") if c.strip()]
        bad = [c for c in codes if c not in schema.REASON_CODES]
        if bad:
            print(f"unknown reason codes: {bad}")
            return
        self.ws["stage_bc_draft"]["reason_codes"] = codes
        save_work(self.ws)

    def cmd_set_confidence(self, arg):
        c = arg.strip().upper()
        if c not in schema.CONFIDENCE_LEVELS:
            print(f"must be one of {schema.CONFIDENCE_LEVELS}")
            return
        self.ws["stage_bc_draft"]["confidence"] = c
        save_work(self.ws)

    def cmd_provenance(self, arg):
        """provenance <claim text> :: <sentence_id>[,<sentence_id>...]"""
        if "::" not in arg:
            print("usage: provenance <claim text> :: <sentence_id>[,<sentence_id>...]")
            return
        claim, refs_str = arg.split("::", 1)
        claim = claim.strip()
        sids = [s.strip() for s in refs_str.split(",") if s.strip()]
        bad = [s for s in sids if not self.corpus.resolve(s)]
        if bad:
            print(f"REFUSED: these do not resolve in the corpus: {bad}")
            return
        self.ws["stage_bc_draft"]["reference_provenance"].append({"claim": claim, "source_refs": sids})
        save_work(self.ws)
        print(f"provenance entry added ({len(self.ws['stage_bc_draft']['reference_provenance'])} total)")

    def cmd_commit_reference(self, _arg):
        if self.ws["stage"] != "B_REVEALED":
            print(f"REFUSED: stage is {self.ws['stage']}, expected B_REVEALED")
            return
        d = self.ws["stage_bc_draft"]
        elapsed = time.time() - self.ws["review_started_at"]
        edit = schema.ExpertEdit(
            action=d["action"], reason_codes=d["reason_codes"], reference_body=d["reference_body"],
            reference_provenance=d["reference_provenance"], confidence=d["confidence"], review_seconds=elapsed,
        )
        seed = self.seed_store.reveal(self.ws["kc_id"], self.ws)
        try:
            committed = edit.to_committed_dict(seed_sha256=seed["seed_sha256"])
        except schema.SchemaError as e:
            print(f"REFUSED: {e}")
            return
        record = schema.ReferenceRecord(
            kc_id=self.ws["kc_id"], canonical_name=self.roster.entries[self.ws["kc_id"]]["canonical_name"],
            hierarchy_path=self.roster.entries[self.ws["kc_id"]]["hierarchy_path"],
            source_first_review=self.ws["stage_a_committed"],
            seed={"seed_artifact_id": self.ws["kc_id"], "seed_sha256": seed["seed_sha256"]},
            expert_edit=committed, validation_status="PENDING",
        )
        out = COMMITTED_DIR / f"{self.ws['kc_id']}.json"
        if out.exists():
            print(f"REFUSED: {out} already committed. Use 'amend' for corrections.")
            return
        out.write_text(json.dumps(record.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        self.ws["stage"] = "COMMITTED"
        save_work(self.ws)
        log("reference_committed", kc_id=self.ws["kc_id"], action=committed["action"], sha256=committed["sha256"])
        print(f"COMMITTED {self.ws['kc_id']} -> {out}")

    def cmd_amend(self, arg):
        kc_id = arg.strip() or self.ws["kc_id"]
        committed_p = COMMITTED_DIR / f"{kc_id}.json"
        if not committed_p.exists():
            print(f"{kc_id} has no committed record to amend")
            return
        reason = input("amendment reason: ").strip()
        if not reason:
            print("REFUSED: amendment requires a reason")
            return
        original = json.loads(committed_p.read_text(encoding="utf-8"))
        original_sha = schema.sha256_of(original)
        print("what changed - new source_memo, or leave blank to skip:")
        new_memo = input("> ").strip()
        amendment = {
            "kc_id": kc_id, "reason": reason, "amended_at": schema.utcnow_iso(),
            "previous_committed_sha256": original_sha,
            "new_source_memo": new_memo or None,
        }
        existing = sorted(AMEND_DIR.glob(f"{kc_id}__amend_*.json"))
        n = len(existing) + 1
        amend_path = AMEND_DIR / f"{kc_id}__amend_{n:03d}.json"
        amend_path.write_text(json.dumps(amendment, indent=2, ensure_ascii=False), encoding="utf-8")
        log("amendment_recorded", kc_id=kc_id, path=str(amend_path))
        print(f"amendment recorded at {amend_path}. Original committed record at {committed_p} was NOT modified.")

    # -- status --
    def cmd_status(self, _arg):
        self._print_kc_header()
        d = self.ws["stage_a_draft"]
        print(f"  stage_a_draft: support_state={d['support_state']} n_refs={len(d['source_refs'])} memo_words={len((d['source_memo'] or '').split())}")
        if self.ws["stage_a_committed"]:
            print(f"  stage_a_committed: {self.ws['stage_a_committed']['support_state']} @ {self.ws['stage_a_committed']['committed_at']}")
        bc = self.ws.get("stage_bc_draft", {})
        if bc:
            print(f"  stage_bc_draft: action={bc.get('action')} n_provenance={len(bc.get('reference_provenance', []))}")

    def cmd_progress(self, _arg):
        n = len(self.roster.order)
        committed = list(COMMITTED_DIR.glob("*.json"))
        actions = {}
        unsupported = 0
        for p in committed:
            rec = json.loads(p.read_text(encoding="utf-8"))
            a = rec["expert_edit"]["action"]
            actions[a] = actions.get(a, 0) + 1
            if a == "NO_REFERENCE_CORPUS_UNSUPPORTED":
                unsupported += 1
        print(f"reviewed: {len(committed)}/{n}")
        for a in schema.EXPERT_ACTIONS:
            print(f"  {a}: {actions.get(a, 0)}")

    def cmd_quit(self, _arg):
        save_work(self.ws)
        log("session_end", kc_id=self.ws["kc_id"])
        print("saved. bye.")
        raise SystemExit(0)

    HELP = """
commands:
  next | previous | goto <kc_id>
  search-source <query> [--regex] | open-source <sentence_id> | show-source-context <sentence_id>
  set-support-state <SUPPORTED|PARTIALLY_SUPPORTED|UNSUPPORTED|AMBIGUOUS_OR_CONFLICTING>
  cite <sentence_id> | uncite <sentence_id> | memo (opens editor)
  commit-source-review
  reveal-seed
  edit-reference (opens editor)
  set-action <ACCEPT|MINOR_EDIT|MAJOR_EDIT|REPLACE|NO_REFERENCE_CORPUS_UNSUPPORTED>
  set-reason-codes <CODE,CODE,...> | set-confidence <HIGH|MEDIUM|LOW>
  provenance <claim text> :: <sentence_id>[,<sentence_id>...]
  commit-reference
  save-draft | status | progress | amend [<kc_id>] | quit
"""

    def cmd_help(self, _arg):
        print(self.HELP)

    def run(self):
        self._print_kc_header()
        print(self.HELP)
        dispatch = {
            "next": self.cmd_next, "previous": self.cmd_previous, "goto": self.cmd_goto,
            "search-source": self.cmd_search_source, "open-source": self.cmd_open_source,
            "show-source-context": self.cmd_show_source_context,
            "set-support-state": self.cmd_set_support_state, "cite": self.cmd_cite, "uncite": self.cmd_uncite,
            "memo": self.cmd_memo, "commit-source-review": self.cmd_commit_source_review,
            "reveal-seed": self.cmd_reveal_seed, "edit-reference": self.cmd_edit_reference,
            "set-action": self.cmd_set_action, "set-reason-codes": self.cmd_set_reason_codes,
            "set-confidence": self.cmd_set_confidence, "provenance": self.cmd_provenance,
            "commit-reference": self.cmd_commit_reference, "save-draft": self.cmd_save_draft,
            "status": self.cmd_status, "progress": self.cmd_progress, "amend": self.cmd_amend,
            "quit": self.cmd_quit, "help": self.cmd_help,
        }
        while True:
            try:
                line = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.cmd_quit("")
                return
            if not line:
                continue
            cmd, _, arg = line.partition(" ")
            handler = dispatch.get(cmd)
            if handler is None:
                print(f"unknown command: {cmd!r} (try 'help')")
                continue
            try:
                handler(arg)
            except SystemExit:
                raise
            except Exception as e:
                print(f"error: {e}")
                log("error", kc_id=self.ws.get("kc_id"), command=cmd, error=str(e))


if __name__ == "__main__":
    Console().run()
