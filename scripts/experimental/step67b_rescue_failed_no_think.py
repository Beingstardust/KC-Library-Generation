#!/usr/bin/env python3
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = """You draft knowledge-component records for expert review.

Return JSON only. Do not reason visibly. Do not include markdown.

Rules:
1. Use only the supplied evidence.
2. Write a concise paraphrase only when evidence directly supports the target KC.
3. Do not copy a full evidence sentence unless it is a formula, notation, or fixed technical phrase.
4. Do not infer a definition from sibling, background, example, procedure, or fragmentary evidence.
5. Scope may describe use, role, application, or boundary only when supported.
6. Abstain for unsupported fields.
7. Keep kc_specific_criteria empty.
"""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()


def extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty visible model content")

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        raise ValueError("visible JSON is not an object")
    except Exception:
        pass

    cleaned = re.sub(r"^```(?:json)?", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"```$", "", cleaned.strip())

    start = cleaned.find("{")
    if start < 0:
        raise ValueError("no JSON object start found in visible content")

    depth = 0
    in_string = False
    escape = False

    for idx in range(start, len(cleaned)):
        ch = cleaned[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start:idx + 1]
                    obj = json.loads(candidate)
                    if not isinstance(obj, dict):
                        raise ValueError("extracted JSON is not an object")
                    return obj

    raise ValueError("could not find balanced JSON object")


def response_summary(response: dict[str, Any]) -> dict[str, Any]:
    message = response.get("message") or {}
    content = str(message.get("content") or "")
    thinking = str(message.get("thinking") or "")
    return {
        "response_keys": sorted(response.keys()),
        "message_keys": sorted(message.keys()) if isinstance(message, dict) else [],
        "content_len": len(content),
        "content_prefix": content[:500],
        "thinking_present": bool(thinking),
        "thinking_char_count": len(thinking),
        "done": response.get("done"),
        "done_reason": response.get("done_reason"),
        "total_duration": response.get("total_duration"),
        "load_duration": response.get("load_duration"),
        "prompt_eval_count": response.get("prompt_eval_count"),
        "eval_count": response.get("eval_count"),
        "eval_duration": response.get("eval_duration"),
    }


def make_user_prompt(packet: dict[str, Any]) -> str:
    schema = {
        "kc_id": packet.get("kc_id"),
        "definition": {
            "status": "grounded | abstained",
            "text": "1 concise sentence, or empty string if abstained",
            "supporting_evidence_ids": ["E1"],
            "abstention_reason": "",
        },
        "scope": {
            "status": "grounded | abstained",
            "text": "1 concise sentence, or empty string if abstained",
            "supporting_evidence_ids": ["E1"],
            "abstention_reason": "",
        },
        "notes_for_reviewer": [],
        "kc_specific_criteria": [],
    }

    compact_packet = {
        "kc_id": packet.get("kc_id"),
        "canonical_name": packet.get("canonical_name"),
        "aliases": packet.get("aliases") or [],
        "topic_path_labels": packet.get("topic_path_labels") or [],
        "seed_definition_context_only_not_evidence": packet.get("seed_definition") or "",
        "support_pack_summary": packet.get("support_pack_summary") or {},
        "evidence": packet.get("evidence") or [],
    }

    return (
        "Draft one KC record from this evidence packet.\n"
        "The seed definition is context only, not evidence.\n"
        "Use evidence ids such as E1, E2 in supporting_evidence_ids.\n"
        "Return exactly one JSON object matching this schema:\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\n\nEvidence packet:\n"
        + json.dumps(compact_packet, ensure_ascii=False)
    )


def ollama_chat(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float,
    num_ctx: int,
    num_predict: int,
    temperature: float,
) -> tuple[dict[str, Any], float]:
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": float(temperature),
            "top_p": 1.0,
            "repeat_penalty": 1.0,
            "num_ctx": int(num_ctx),
            "num_predict": int(num_predict),
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed = time.time() - start
            return json.loads(raw), elapsed
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        elapsed = time.time() - start
        raise RuntimeError(f"HTTPError {exc.code}: {body[:1000]} elapsed={elapsed:.2f}s") from exc
    except Exception as exc:
        elapsed = time.time() - start
        raise RuntimeError(f"{type(exc).__name__}: {exc} elapsed={elapsed:.2f}s") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets", required=True)
    parser.add_argument("--previous-drafts", required=True)
    parser.add_argument("--out-root", default="data/processed/step67_sidecar_rescued_drafts")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=600)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()

    packets_path = Path(args.packets)
    previous_path = Path(args.previous_drafts)

    packets = read_jsonl(packets_path)
    previous_rows = read_jsonl(previous_path)

    packet_by_kc = {str(p.get("kc_id") or ""): p for p in packets}
    if len(previous_rows) != len(packets):
        print(f"WARNING: previous rows {len(previous_rows)} != packet rows {len(packets)}", flush=True)

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(args.out_root) / run_id
    out_path = out_dir / "onepass_drafts.jsonl"
    manifest_path = out_dir / "manifest.json"

    manifest = {
        "stage": "step67b_rescue_failed_no_think",
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "packets_path": packets_path.as_posix(),
        "previous_drafts_path": previous_path.as_posix(),
        "out_dir": out_dir.as_posix(),
        "onepass_drafts_path": out_path.as_posix(),
        "model": args.model,
        "base_url": args.base_url,
        "rescue_policy": "reuse_previous_ok_rows_and_retry_failed_rows_with_think_false",
        "think": False,
        "num_ctx": args.num_ctx,
        "num_predict": args.num_predict,
        "timeout": args.timeout,
        "temperature": args.temperature,
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("STEP67B_RESCUE_RUN_ID =", run_id, flush=True)
    print("STEP67B_RESCUE_DIR =", out_dir.as_posix(), flush=True)
    print("STEP67B_RESCUE_JSONL =", out_path.as_posix(), flush=True)
    print("previous_row_count =", len(previous_rows), flush=True)
    print("packet_count =", len(packets), flush=True)
    print("num_predict =", args.num_predict, flush=True)
    print("think = false", flush=True)

    reused_ok_count = 0
    rescue_ok_count = 0
    rescue_fail_count = 0
    previous_fail_count = 0

    for index, prev in enumerate(previous_rows, start=1):
        kc_id = str(prev.get("kc_id") or "")
        packet = packet_by_kc.get(kc_id)

        if not packet:
            row = dict(prev)
            row["ok"] = False
            row["error"] = f"missing packet for kc_id={kc_id}"
            row["rescue_stage"] = "packet_missing"
            append_jsonl(out_path, row)
            rescue_fail_count += 1
            print(f"[{index}/{len(previous_rows)}] FAIL {kc_id}: missing packet", flush=True)
            continue

        if prev.get("ok") is True:
            row = dict(prev)
            row["rescue_stage"] = "reused_primary_think_true_success"
            row["final_source"] = "primary_think_true"
            append_jsonl(out_path, row)
            reused_ok_count += 1
            print(f"[{index}/{len(previous_rows)}] REUSE {kc_id}", flush=True)
            continue

        previous_fail_count += 1
        print(f"[{index}/{len(previous_rows)}] RESCUE_CALL {kc_id} {packet.get('canonical_name')}", flush=True)

        row = {
            "draft_contract_version": "step67b_rescue_failed_no_think",
            "kc_id": kc_id,
            "canonical_name": packet.get("canonical_name"),
            "source_packets_path": packets_path.as_posix(),
            "previous_drafts_path": previous_path.as_posix(),
            "model": args.model,
            "think_requested": False,
            "num_predict": args.num_predict,
            "ok": False,
            "parsed": None,
            "raw_visible_content": "",
            "visible_content_len": 0,
            "thinking_present": False,
            "thinking_char_count": 0,
            "elapsed_seconds": None,
            "response_summary": {},
            "error": "",
            "rescue_stage": "rescue_no_think_attempted",
            "final_source": "rescue_think_false",
            "previous_error": prev.get("error") or "",
            "previous_thinking_char_count": prev.get("thinking_char_count"),
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }

        try:
            response, elapsed = ollama_chat(
                base_url=args.base_url,
                model=args.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": make_user_prompt(packet)},
                ],
                timeout=args.timeout,
                num_ctx=args.num_ctx,
                num_predict=args.num_predict,
                temperature=args.temperature,
            )

            message = response.get("message") or {}
            visible = str(message.get("content") or "")
            thinking = str(message.get("thinking") or "")

            row["raw_visible_content"] = visible
            row["visible_content_len"] = len(visible)
            row["thinking_present"] = bool(thinking)
            row["thinking_char_count"] = len(thinking)
            row["elapsed_seconds"] = round(elapsed, 4)
            row["response_summary"] = response_summary(response)

            parsed = extract_json_object(visible)
            row["parsed"] = parsed
            row["ok"] = True

            rescue_ok_count += 1
            print(
                f"[{index}/{len(previous_rows)}] RESCUE_OK {kc_id} elapsed={elapsed:.2f}s "
                f"visible_chars={len(visible)} thinking_chars={len(thinking)}",
                flush=True,
            )
        except Exception as exc:
            row["error"] = str(exc)
            rescue_fail_count += 1
            print(
                f"[{index}/{len(previous_rows)}] RESCUE_FAIL {kc_id}: {exc} "
                f"visible_chars={row.get('visible_content_len')} thinking_chars={row.get('thinking_char_count')}",
                flush=True,
            )

        append_jsonl(out_path, row)

    summary = {
        **manifest,
        "reused_ok_count": reused_ok_count,
        "previous_fail_count": previous_fail_count,
        "rescue_ok_count": rescue_ok_count,
        "rescue_fail_count": rescue_fail_count,
        "merged_ok_count": reused_ok_count + rescue_ok_count,
        "merged_fail_count": rescue_fail_count,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("reused_ok_count =", reused_ok_count, flush=True)
    print("previous_fail_count =", previous_fail_count, flush=True)
    print("rescue_ok_count =", rescue_ok_count, flush=True)
    print("rescue_fail_count =", rescue_fail_count, flush=True)
    print("merged_ok_count =", reused_ok_count + rescue_ok_count, flush=True)
    print("merged_fail_count =", rescue_fail_count, flush=True)
    print("STEP67B_RESCUE_NO_THINK_DONE", flush=True)

    return 0 if rescue_fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
