#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def utc_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def get_lane(packet: dict[str, Any], names: list[str]) -> list[dict[str, Any]]:
    for name in names:
        value = packet.get(name)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            for sub in ("items", "selected", "rows", "evidence"):
                sv = value.get(sub)
                if isinstance(sv, list):
                    return [x for x in sv if isinstance(x, dict)]
    return []


def item_text(item: dict[str, Any]) -> str:
    for k in ("context_text", "model_text", "source_block_text", "text", "quote_text", "quote"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return re.sub(r"\s+", " ", v).strip()
    return ""


def item_quote(item: dict[str, Any]) -> str:
    for k in ("quote_text", "quote", "text"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return re.sub(r"\s+", " ", v).strip()
    return ""


def item_id(item: dict[str, Any], fallback: str) -> str:
    for k in ("evidence_id", "id", "overlay_candidate_id"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return fallback


def compact_items(items: list[dict[str, Any]], prefix: str, limit: int = 4) -> list[dict[str, Any]]:
    out = []
    for i, item in enumerate(items[:limit], start=1):
        eid = item_id(item, f"{prefix}{i}")
        quote = item_quote(item)
        text = item_text(item)
        reason = str(item.get("reason") or "")
        flags = item.get("flags")
        if not isinstance(flags, list):
            flags = []
        out.append({
            "id": eid,
            "reason": reason,
            "flags": flags[:8],
            "quote": quote[:700],
            "context": text[:1500],
        })
    return out


def build_prompt(packet: dict[str, Any]) -> str:
    kc_id = str(packet.get("kc_id") or "")
    name = str(packet.get("canonical_name") or "")
    seed = str(packet.get("seed_definition") or "")
    aliases = packet.get("aliases") if isinstance(packet.get("aliases"), list) else []
    topic_path = packet.get("topic_path_labels") if isinstance(packet.get("topic_path_labels"), list) else []

    definition_lane = get_lane(packet, ["definition_lane", "selected_definition_lane", "definition_items"])
    scope_lane = get_lane(packet, ["scope_lane", "selected_scope_lane", "scope_items"])
    context_lane = get_lane(packet, ["context_lane", "selected_context_lane", "context_items"])
    sibling_lane = get_lane(packet, ["sibling_lane", "sibling_contrast_lane", "sibling_contrast", "sibling_items"])
    quarantine_lane = get_lane(packet, ["quarantine_lane", "quarantine_items", "quarantine_or_irrelevant"])

    payload = {
        "kc_id": kc_id,
        "canonical_name": name,
        "aliases": aliases,
        "topic_path_labels": topic_path,
        "seed_definition_not_evidence": seed,
        "definition_lane": compact_items(definition_lane, "D"),
        "scope_lane": compact_items(scope_lane, "S"),
        "context_lane": compact_items(context_lane, "C"),
        "sibling_or_negative_contrast_lane": compact_items(sibling_lane, "X"),
        "quarantine_summary": {
            "count": len(quarantine_lane),
            "instruction": "Do not use quarantined evidence for definition or scope.",
        },
    }

    return f"""
You are drafting one Knowledge Component entry from evidence lanes.

Hard rules:
1. Return only valid JSON. No markdown. No commentary.
2. Use only the supplied evidence lanes.
3. The seed definition is NOT evidence. It is only a label-side hint. Do not cite it as support.
4. definition_lane can support definition.
5. scope_lane can support scope, consequence, usage, or boundary.
6. context_lane can help interpretation but must not by itself justify a grounded definition.
7. sibling_or_negative_contrast_lane is contrast evidence. Do not use it as positive support.
8. quarantine evidence must not be used.
9. If the evidence does not directly support a field, set that field status to "abstained" and leave text empty.
10. Do not invent textbook facts. Do not use outside knowledge.
11. Keep grounded text concise and faithful to evidence.
12. supporting_evidence_ids must refer only to IDs present in the relevant non-quarantine lane.

Return exactly this JSON object shape:
{{
  "kc_id": "{kc_id}",
  "canonical_name": "{name}",
  "definition": {{
    "status": "grounded" or "abstained",
    "text": "",
    "supporting_evidence_ids": [],
    "abstention_reason": ""
  }},
  "scope": {{
    "status": "grounded" or "abstained",
    "text": "",
    "supporting_evidence_ids": [],
    "abstention_reason": ""
  }}
}}

Evidence packet:
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()


def call_ollama_chat(
    base_url: str,
    model: str,
    prompt: str,
    *,
    think: bool,
    num_ctx: int,
    num_predict: int,
    temperature: float,
    timeout: float,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/api/chat"
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Return only valid JSON. Obey the evidence rules exactly.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "stream": False,
        "think": think,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)


def extract_visible_and_thinking(response: dict[str, Any]) -> tuple[str, int, bool]:
    msg = response.get("message")
    if not isinstance(msg, dict):
        return "", 0, False

    visible = msg.get("content")
    if not isinstance(visible, str):
        visible = ""

    thinking = msg.get("thinking")
    thinking_text = thinking if isinstance(thinking, str) else ""
    return visible.strip(), len(thinking_text), bool(thinking_text.strip())


def parse_json_object(text: str) -> dict[str, Any] | None:
    if not text.strip():
        return None

    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None

    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", required=True)
    ap.add_argument("--out-root", default="data/processed/step67_sidecar_lane_drafts")
    ap.add_argument("--model", default=os.environ.get("GEMMA_MODEL", "gemma4:31b"))
    ap.add_argument("--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    ap.add_argument("--think", action="store_true")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=700)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    lanes_path = Path(args.lanes)
    packets = load_jsonl(lanes_path)

    run_id = utc_run_id()
    out_dir = Path(args.out_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "onepass_drafts.jsonl"
    summary_path = out_dir / "summary.json"

    rows = []
    ok_count = 0
    fail_count = 0

    print(f"STEP67B_LANE_ONEPASS_RUN_ID = {run_id}")
    print(f"STEP67B_LANE_ONEPASS_DIR = {out_dir.as_posix()}")
    print(f"STEP67B_LANE_ONEPASS_JSONL = {out_path.as_posix()}")
    print(f"packet_count = {len(packets)}")
    print(f"think = {args.think}")
    print(f"num_predict = {args.num_predict}")

    for i, packet in enumerate(packets, start=1):
        kc_id = str(packet.get("kc_id") or "")
        name = str(packet.get("canonical_name") or "")
        prompt = build_prompt(packet)

        print(f"[{i}/{len(packets)}] CALL {kc_id} {name}", flush=True)
        started = time.time()

        row: dict[str, Any] = {
            "kc_id": kc_id,
            "canonical_name": name,
            "ok": False,
            "error": "",
            "prompt_policy": "lane_aware_v1_definition_scope_context_sibling_quarantine",
            "final_source": "lane_aware_gemma4_think_false" if not args.think else "lane_aware_gemma4_think_true",
            "visible_content": "",
            "visible_content_len": 0,
            "thinking_present": False,
            "thinking_char_count": 0,
            "parsed": None,
            "response_summary": {},
        }

        try:
            response = call_ollama_chat(
                args.base_url,
                args.model,
                prompt,
                think=args.think,
                num_ctx=args.num_ctx,
                num_predict=args.num_predict,
                temperature=args.temperature,
                timeout=args.timeout,
            )
            visible, thinking_chars, thinking_present = extract_visible_and_thinking(response)
            parsed = parse_json_object(visible)

            row["visible_content"] = visible
            row["visible_content_len"] = len(visible)
            row["thinking_present"] = thinking_present
            row["thinking_char_count"] = thinking_chars
            row["parsed"] = parsed
            row["response_summary"] = {
                "done": response.get("done"),
                "done_reason": response.get("done_reason"),
                "prompt_eval_count": response.get("prompt_eval_count"),
                "eval_count": response.get("eval_count"),
                "total_duration": response.get("total_duration"),
                "eval_duration": response.get("eval_duration"),
            }

            if not visible:
                raise RuntimeError("empty visible model content")
            if not isinstance(parsed, dict):
                raise RuntimeError("parsed output missing or not object")

            parsed_kc = str(parsed.get("kc_id") or "")
            if parsed_kc != kc_id:
                raise RuntimeError(f"kc_id mismatch parsed={parsed_kc!r} expected={kc_id!r}")

            row["ok"] = True
            ok_count += 1
            print(f"[{i}/{len(packets)}] OK {kc_id} elapsed={time.time()-started:.2f}s visible_chars={len(visible)} thinking_chars={thinking_chars}", flush=True)

        except Exception as e:
            row["error"] = str(e)
            fail_count += 1
            print(f"[{i}/{len(packets)}] FAIL {kc_id}: {e} visible_chars={row.get('visible_content_len')} thinking_chars={row.get('thinking_char_count')}", flush=True)

        rows.append(row)
        write_jsonl(out_path, rows)

    summary = {
        "stage": "step67b_lane_aware_gemma4_onepass",
        "run_id": run_id,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lanes_path": lanes_path.as_posix(),
        "out_dir": out_dir.as_posix(),
        "onepass_drafts_path": out_path.as_posix(),
        "packet_count": len(packets),
        "model": args.model,
        "base_url": args.base_url,
        "think": args.think,
        "num_ctx": args.num_ctx,
        "num_predict": args.num_predict,
        "temperature": args.temperature,
        "call_policy": "exactly_one_model_call_per_kc_no_verifier_no_retry",
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
        "raw_thinking_storage_policy": "do_not_store_raw_thinking_only_presence_and_length",
        "ok_count": ok_count,
        "fail_count": fail_count,
    }

    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"ok_count = {ok_count}")
    print(f"fail_count = {fail_count}")
    print("STEP67B_LANE_AWARE_GEMMA4_ONEPASS_DONE")

    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
