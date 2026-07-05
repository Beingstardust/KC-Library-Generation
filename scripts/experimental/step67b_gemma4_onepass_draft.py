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

Use only the supplied evidence. Think privately, but the visible response must be JSON only.

Rules:
1. Write a concise paraphrase when evidence directly supports the target KC.
2. Do not copy a full evidence sentence unless it is a formula, notation, or fixed technical phrase.
3. Do not infer a definition from sibling, background, example, procedure, or fragmentary evidence.
4. Scope may describe use, role, application, or boundary only when supported.
5. Abstain for unsupported fields.
6. Do not mention the prompt, the user, or your reasoning.
7. Return exactly the requested JSON object.

Few-shot pattern:
- Direct evidence: "A target variable is the value a model predicts." Good definition: "A target variable is the outcome that a model is intended to predict."
- Sibling evidence: "Concept B is not Concept A." Good definition for Concept A: abstain unless the evidence explicitly defines Concept A.
- Procedure evidence: "The method ranks candidates and keeps those above a threshold." Good scope: "The method is used to retain candidates whose score exceeds a threshold."
"""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
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

    cleaned = text
    cleaned = re.sub(r"^```(?:json)?", "", cleaned.strip(), flags=re.IGNORECASE)
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


def make_user_prompt(packet: dict[str, Any]) -> str:
    compact_packet = {
        "kc_id": packet.get("kc_id"),
        "canonical_name": packet.get("canonical_name"),
        "aliases": packet.get("aliases") or [],
        "topic_path_labels": packet.get("topic_path_labels") or [],
        "seed_definition_context_only_not_evidence": packet.get("seed_definition") or "",
        "support_pack_summary": packet.get("support_pack_summary") or {},
        "evidence": packet.get("evidence") or [],
    }

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

    return (
        "Draft one KC record from this evidence packet.\n"
        "The seed definition is context only, not evidence.\n"
        "Use local evidence ids such as E1, E2 in supporting_evidence_ids.\n"
        "The visible answer must be JSON only and must fit this exact schema:\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\n\nEvidence packet:\n"
        + json.dumps(compact_packet, ensure_ascii=False)
    )


def ollama_chat(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float,
    think: bool,
    num_ctx: int,
    num_predict: int,
    temperature: float,
) -> tuple[dict[str, Any], float]:
    url = base_url.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": bool(think),
        "format": "json",
        "options": {
            "temperature": float(temperature),
            "top_p": 1.0,
            "repeat_penalty": 1.0,
            "num_ctx": int(num_ctx),
            "num_predict": int(num_predict),
        },
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
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
        "thinking_prefix_suppressed": thinking[:0],
        "done": response.get("done"),
        "done_reason": response.get("done_reason"),
        "total_duration": response.get("total_duration"),
        "load_duration": response.get("load_duration"),
        "prompt_eval_count": response.get("prompt_eval_count"),
        "eval_count": response.get("eval_count"),
        "eval_duration": response.get("eval_duration"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets", required=True)
    parser.add_argument("--out-root", default="data/processed/step67_sidecar_onepass_drafts")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=900)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--think", choices=["true", "false"], default="true")
    args = parser.parse_args()

    packets_path = Path(args.packets)
    packets = read_jsonl(packets_path)

    if not packets:
        raise SystemExit(f"FAIL: no packets found at {packets_path}")

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path(args.out_root) / run_id
    out_path = out_dir / "onepass_drafts.jsonl"
    manifest_path = out_dir / "manifest.json"

    manifest = {
        "stage": "step67b_gemma4_onepass_draft_diag_v2",
        "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "packets_path": packets_path.as_posix(),
        "out_dir": out_dir.as_posix(),
        "onepass_drafts_path": out_path.as_posix(),
        "packet_count": len(packets),
        "model": args.model,
        "base_url": args.base_url,
        "think": args.think == "true",
        "num_ctx": args.num_ctx,
        "num_predict": args.num_predict,
        "timeout": args.timeout,
        "temperature": args.temperature,
        "call_policy": "exactly_one_model_call_per_kc_no_verifier_no_retry",
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
        "raw_thinking_storage_policy": "do_not_store_raw_thinking_only_presence_and_length",
        "diagnostic_policy": "preserve_visible_content_and_response_shape_even_when_json_parse_fails",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("STEP67B_ONEPASS_RUN_ID =", run_id, flush=True)
    print("STEP67B_ONEPASS_DIR =", out_dir.as_posix(), flush=True)
    print("STEP67B_ONEPASS_JSONL =", out_path.as_posix(), flush=True)
    print("packet_count =", len(packets), flush=True)
    print("num_predict =", args.num_predict, flush=True)
    print("think =", args.think, flush=True)

    ok_count = 0
    fail_count = 0

    for index, packet in enumerate(packets, start=1):
        kc_id = str(packet.get("kc_id") or "")
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": make_user_prompt(packet)},
        ]

        row = {
            "draft_contract_version": "step67b_onepass_draft_diag_v2",
            "kc_id": kc_id,
            "canonical_name": packet.get("canonical_name"),
            "source_packets_path": packets_path.as_posix(),
            "model": args.model,
            "think_requested": args.think == "true",
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
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }

        print(f"[{index}/{len(packets)}] CALL {kc_id} {packet.get('canonical_name')}", flush=True)

        try:
            response, elapsed = ollama_chat(
                base_url=args.base_url,
                model=args.model,
                messages=messages,
                timeout=args.timeout,
                think=args.think == "true",
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
            row["ok"] = True
            row["parsed"] = parsed

            ok_count += 1
            print(
                f"[{index}/{len(packets)}] OK {kc_id} elapsed={elapsed:.2f}s "
                f"visible_chars={len(visible)} thinking_chars={len(thinking)}",
                flush=True,
            )
        except Exception as exc:
            row["error"] = str(exc)
            fail_count += 1
            print(
                f"[{index}/{len(packets)}] FAIL {kc_id}: {exc} "
                f"visible_chars={row.get('visible_content_len')} "
                f"thinking_chars={row.get('thinking_char_count')}",
                flush=True,
            )

        append_jsonl(out_path, row)

    final_summary = {
        **manifest,
        "ok_count": ok_count,
        "fail_count": fail_count,
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }

    (out_dir / "summary.json").write_text(json.dumps(final_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("ok_count =", ok_count, flush=True)
    print("fail_count =", fail_count, flush=True)
    print("STEP67B_GEMMA4_ONEPASS_DONE", flush=True)

    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
