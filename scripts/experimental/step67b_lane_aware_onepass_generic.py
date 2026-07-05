#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any


def utc_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d_%H%M%S")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


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


def item_id(item: dict[str, Any], fallback: str) -> str:
    for key in ("evidence_id", "id", "overlay_candidate_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def item_quote(item: dict[str, Any]) -> str:
    for key in ("quote_text", "quote", "text"):
        value = clean_text(item.get(key))
        if value:
            return value
    return ""


def item_context(item: dict[str, Any]) -> str:
    for key in ("context_text", "model_text", "source_block_text", "text", "quote_text", "quote"):
        value = clean_text(item.get(key))
        if value:
            return value
    return ""


def compact_items(
    items: list[dict[str, Any]],
    *,
    prefix: str,
    limit: int,
    max_quote_chars: int,
    max_context_chars: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for i, item in enumerate(items[:limit], start=1):
        eid = item_id(item, f"{prefix}{i}")
        flags = item.get("flags")
        if not isinstance(flags, list):
            flags = []

        out.append({
            "id": eid,
            "reason": clean_text(item.get("reason")),
            "flags": [str(x) for x in flags[:10]],
            "target_binding_strength": clean_text(item.get("target_binding_strength")),
            "decisive_surface": clean_text(item.get("decisive_surface")),
            "quote": item_quote(item)[:max_quote_chars],
            "context": item_context(item)[:max_context_chars],
        })

    return out


def build_prompt(packet: dict[str, Any], args: argparse.Namespace) -> str:
    kc_id = clean_text(packet.get("kc_id"))
    name = clean_text(packet.get("canonical_name"))
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
        "definition_lane": compact_items(
            definition_lane,
            prefix="D",
            limit=args.max_definition_items,
            max_quote_chars=args.max_quote_chars,
            max_context_chars=args.max_context_chars,
        ),
        "scope_lane": compact_items(
            scope_lane,
            prefix="S",
            limit=args.max_scope_items,
            max_quote_chars=args.max_quote_chars,
            max_context_chars=args.max_context_chars,
        ),
        "context_lane": compact_items(
            context_lane,
            prefix="C",
            limit=args.max_context_items,
            max_quote_chars=args.max_quote_chars,
            max_context_chars=args.max_context_chars,
        ),
        "sibling_or_negative_contrast_lane": compact_items(
            sibling_lane,
            prefix="X",
            limit=args.max_sibling_items,
            max_quote_chars=args.max_quote_chars,
            max_context_chars=args.max_context_chars,
        ),
        "quarantine_summary": {
            "count": len(quarantine_lane),
            "instruction": "Do not use quarantined evidence for any positive claim.",
        },
    }

    return f"""
You are drafting one Knowledge Component entry from evidence lanes.

Hard rules:
1. Return only valid JSON. No markdown. No commentary.
2. Use only the supplied evidence lanes. Do not use outside knowledge.
3. Do not use label text as evidence. The KC name only identifies the target.
4. Quarantine evidence must never support a positive claim.
5. Sibling or negative contrast evidence may only prevent overreach. Do not cite it as positive support.
6. If a field is not supported, set status to "abstained", text to "", supporting_evidence_ids to [], supporting_lanes to [], and give a short abstention_reason.
7. Keep grounded text concise, faithful, and semantically complete.
8. Every grounded field must cite evidence IDs from non-quarantine lanes.
9. Do not cite evidence IDs that are not present in the packet.
10. Do not fabricate formulas, conditions, examples, or textbook facts.

Drafting style policy:
- Do not merely copy textbook wording unless the evidence sentence is already the cleanest safe wording.
- Prefer a concise, lightly paraphrased KC draft that preserves the meaning of the cited evidence.
- The draft must be semantically complete enough to stand as a KC library entry.
- Do not add outside facts, examples, formulas, conditions, or terminology not supported by cited evidence.
- If the evidence is too thin for a complete field, abstain rather than padding.

Definition drafting policy:
- Use "direct_definition" only when definition_lane directly supports the definition.
- Use "contextual_synthesis" when at least two non-quarantine evidence items jointly converge enough to define the KC without inventing.
- A contextual_synthesis definition must cite at least two supporting_evidence_ids.
- A contextual_synthesis definition must include support from scope_lane or context_lane.
- Use "single_strong_context" when exactly one non-quarantine scope_lane or context_lane item is self-contained, target-bound, and strong enough to support a useful definition, even though it was not placed in definition_lane.
- single_strong_context is weaker than direct_definition or contextual_synthesis, so use it only when the wording is clearly supported by that one item.
- If the single item is vague, fragmentary, merely topical, or only mentions the KC without explaining it, abstain.
- contextual_synthesis may use scope_lane and context_lane together when they are target-bound and mutually consistent.
- Do not use sibling or quarantine evidence as positive support.

Scope drafting policy:
- Use "direct_scope" when one scope_lane item directly supports use, boundary, role, condition, consequence, or application.
- Use "single_strong_context" when exactly one context_lane item directly supports a use, boundary, role, condition, consequence, or application.
- Use "contextual_synthesis" only when multiple non-quarantine items jointly support the scope.
- A contextual_synthesis scope should cite at least two supporting_evidence_ids when possible.
- If exactly one scope_lane item directly supports the scope, prefer "direct_scope" over "contextual_synthesis".
- Scope may cite definition_lane, scope_lane, and context_lane.

Return exactly this JSON object shape:
{{
  "kc_id": "{kc_id}",
  "canonical_name": "{name}",
  "definition": {{
    "status": "grounded" or "abstained",
    "grounding_mode": "direct_definition" or "contextual_synthesis" or "single_strong_context" or "abstained",
    "text": "",
    "supporting_evidence_ids": [],
    "supporting_lanes": [],
    "abstention_reason": ""
  }},
  "scope": {{
    "status": "grounded" or "abstained",
    "grounding_mode": "direct_scope" or "contextual_synthesis" or "single_strong_context" or "abstained",
    "text": "",
    "supporting_evidence_ids": [],
    "supporting_lanes": [],
    "abstention_reason": ""
  }}
}}

Evidence packet:
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()


def call_chat(
    *,
    base_url: str,
    model: str,
    prompt: str,
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

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw)


def extract_visible_and_thinking(response: dict[str, Any]) -> tuple[str, int, bool]:
    message = response.get("message")
    if not isinstance(message, dict):
        return "", 0, False

    visible = message.get("content")
    if not isinstance(visible, str):
        visible = ""

    thinking = message.get("thinking")
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

    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None

    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None



def lane_items_for_ids(packet: dict[str, Any], lane_name: str) -> list[dict[str, Any]]:
    value = packet.get(lane_name)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def collect_lane_id_sets_for_packet(packet: dict[str, Any]) -> dict[str, set[str]]:
    lane_names = [
        "definition_lane",
        "scope_lane",
        "context_lane",
        "quarantine_lane",
        "sibling_lane",
        "sibling_contrast_lane",
    ]
    ids: dict[str, set[str]] = {lane: set() for lane in lane_names}

    for lane_name in lane_names:
        for i, item in enumerate(lane_items_for_ids(packet, lane_name), start=1):
            ids[lane_name].add(item_id(item, f"{lane_name}:{i}"))

    return ids


def field_support_ids(field: dict[str, Any]) -> list[str]:
    ids = field.get("supporting_evidence_ids")
    if not isinstance(ids, list):
        return []
    return [str(item) for item in ids if str(item).strip()]


def actual_supporting_lanes(ids: list[str], lane_id_sets: dict[str, set[str]]) -> list[str]:
    out: list[str] = []
    ordered_lanes = ["definition_lane", "scope_lane", "context_lane", "sibling_contrast_lane", "sibling_lane", "quarantine_lane"]
    for lane in ordered_lanes:
        lane_ids = lane_id_sets.get(lane, set())
        if any(eid in lane_ids for eid in ids):
            out.append(lane)
    return out


def normalize_grounding_modes(parsed: dict[str, Any], lane_id_sets: dict[str, set[str]]) -> list[str]:
    """Normalize structurally inconsistent grounding modes without changing field text or evidence IDs.

    This is deliberately conservative:
    - It only rewrites mode labels when support IDs make the original mode structurally impossible.
    - It does not invent new support IDs.
    - It does not turn abstained fields into grounded fields.
    """

    notes: list[str] = []

    definition_ids = lane_id_sets.get("definition_lane", set())
    scope_ids = lane_id_sets.get("scope_lane", set())
    context_ids = lane_id_sets.get("context_lane", set())

    def normalize_field(field_name: str) -> None:
        field = parsed.get(field_name)
        if not isinstance(field, dict):
            return

        if str(field.get("status") or "") != "grounded":
            return

        mode = str(field.get("grounding_mode") or "")
        ids = field_support_ids(field)
        actual_lanes = actual_supporting_lanes(ids, lane_id_sets)

        # Keep supporting_lanes consistent with the cited IDs. This does not alter evidence support.
        if actual_lanes:
            field["supporting_lanes"] = actual_lanes

        if field_name == "definition":
            if mode == "contextual_synthesis" and len(ids) == 1:
                eid = ids[0]
                if eid in scope_ids or eid in context_ids:
                    field["grounding_mode"] = "single_strong_context"
                    notes.append("definition: contextual_synthesis with one scope/context id normalized to single_strong_context")
            elif mode == "direct_definition":
                if not any(eid in definition_ids for eid in ids) and len(ids) == 1:
                    eid = ids[0]
                    if eid in scope_ids or eid in context_ids:
                        field["grounding_mode"] = "single_strong_context"
                        notes.append("definition: direct_definition without definition_lane support normalized to single_strong_context")

        if field_name == "scope":
            if mode == "contextual_synthesis" and len(ids) == 1:
                eid = ids[0]
                if eid in scope_ids or eid in context_ids:
                    field["grounding_mode"] = "single_strong_context"
                    notes.append("scope: contextual_synthesis with one scope/context id normalized to single_strong_context")
            elif mode == "direct_scope":
                if not any(eid in scope_ids for eid in ids) and len(ids) == 1:
                    eid = ids[0]
                    if eid in context_ids:
                        field["grounding_mode"] = "single_strong_context"
                        notes.append("scope: direct_scope with one context id normalized to single_strong_context")
                    elif eid in definition_ids:
                        field["grounding_mode"] = "single_strong_context"
                        notes.append("scope: direct_scope with one definition id normalized to single_strong_context")

    normalize_field("definition")
    normalize_field("scope")

    return notes


def require_arg(value: str | None, name: str) -> str:
    if value and str(value).strip():
        return str(value).strip()
    raise SystemExit(f"Missing required {name}. Pass {name} explicitly.")



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lanes", required=True)
    parser.add_argument("--out-root", default="data/processed/step67_sidecar_lane_drafts_generic")
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--reasoning-mode", choices=["think", "nothink"], default="nothink")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=900)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-definition-items", type=int, default=4)
    parser.add_argument("--max-scope-items", type=int, default=4)
    parser.add_argument("--max-context-items", type=int, default=4)
    parser.add_argument("--max-sibling-items", type=int, default=2)
    parser.add_argument("--max-quote-chars", type=int, default=700)
    parser.add_argument("--max-context-chars", type=int, default=1200)
    args = parser.parse_args()

    model = require_arg(args.model, "--model")
    base_url = require_arg(args.base_url, "--base-url")

    lanes_path = Path(args.lanes)
    packets = load_jsonl(lanes_path)
    if args.limit is not None:
        packets = packets[: max(0, args.limit)]

    run_id = utc_run_id()
    out_dir = Path(args.out_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / "onepass_drafts.jsonl"
    summary_path = out_dir / "summary.json"

    rows: list[dict[str, Any]] = []
    ok_count = 0
    fail_count = 0
    think = args.reasoning_mode == "think"

    print(f"STEP67B_GENERIC_ONEPASS_RUN_ID = {run_id}")
    print(f"STEP67B_GENERIC_ONEPASS_DIR = {out_dir.as_posix()}")
    print(f"STEP67B_GENERIC_ONEPASS_JSONL = {out_path.as_posix()}")
    print(f"packet_count = {len(packets)}")
    print(f"reasoning_mode = {args.reasoning_mode}")
    print(f"num_predict = {args.num_predict}")

    for index, packet in enumerate(packets, start=1):
        kc_id = clean_text(packet.get("kc_id"))
        name = clean_text(packet.get("canonical_name"))
        prompt = build_prompt(packet, args)

        print(f"[{index}/{len(packets)}] CALL {kc_id} {name}", flush=True)
        started = time.time()

        row: dict[str, Any] = {
            "kc_id": kc_id,
            "canonical_name": name,
            "ok": False,
            "error": "",
            "prompt_policy": "lane_aware_generic_v1_controlled_contextual_synthesis",
            "final_source": f"lane_aware_generic_{args.reasoning_mode}",
            "reasoning_mode": args.reasoning_mode,
            "visible_content": "",
            "visible_content_len": 0,
            "thinking_present": False,
            "thinking_char_count": 0,
            "parsed": None,
            "response_summary": {},
            "postprocess_notes": [],
        }

        try:
            response = call_chat(
                base_url=base_url,
                model=model,
                prompt=prompt,
                think=think,
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

            parsed_kc = clean_text(parsed.get("kc_id"))
            if parsed_kc != kc_id:
                raise RuntimeError(f"kc_id mismatch parsed={parsed_kc!r} expected={kc_id!r}")

            lane_id_sets = collect_lane_id_sets_for_packet(packet)
            postprocess_notes = normalize_grounding_modes(parsed, lane_id_sets)
            row["parsed"] = parsed
            row["postprocess_notes"] = postprocess_notes

            row["ok"] = True
            ok_count += 1
            print(
                f"[{index}/{len(packets)}] OK {kc_id} elapsed={time.time()-started:.2f}s "
                f"visible_chars={len(visible)} thinking_chars={thinking_chars}",
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

        rows.append(row)
        write_jsonl(out_path, rows)

    summary = {
        "stage": "step67b_lane_aware_onepass_generic",
        "run_id": run_id,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "lanes_path": lanes_path.as_posix(),
        "out_dir": out_dir.as_posix(),
        "onepass_drafts_path": out_path.as_posix(),
        "packet_count": len(packets),
        "model": model,
        "base_url": base_url,
        "reasoning_mode": args.reasoning_mode,
        "num_ctx": args.num_ctx,
        "num_predict": args.num_predict,
        "temperature": args.temperature,
        "call_policy": "exactly_one_model_call_per_kc_no_verifier_no_retry",
        "prompt_policy": "lane_aware_generic_v1_controlled_contextual_synthesis",
        "active_pointer_policy": "do_not_update_current_alias_or_active_pointer",
        "raw_thinking_storage_policy": "do_not_store_raw_thinking_only_presence_and_length",
        "ok_count": ok_count,
        "fail_count": fail_count,
    }

    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"ok_count = {ok_count}")
    print(f"fail_count = {fail_count}")
    print("STEP67B_GENERIC_ONEPASS_DONE")

    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
