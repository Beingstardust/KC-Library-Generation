"""Audit source-observed retrieval surfaces without proposing model-authored aliases.

Candidates are literal corpus n-grams that retain a profile label's lexical head. Hierarchy-derived
branch terms are reporting signals only; this script cannot change a profile or packet.
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
from typing import Any, Iterable, Mapping


FUNCTION_WORDS = frozenset("""
a although an and are as at be been being by for from has have if in into is it its of on or that
the their these they this those to via was we were what when where which while with vs
""".split())
GENERIC_TRAILING = frozenset("""
algorithm algorithms approach approaches concept concepts definition definitions index indices
measure measures method methods metric metrics model models overview phase phases problem problems
procedure procedures process processes score scores stage stages technique techniques test tests
workflow workflows
""".split())


def load_jsonl(path: str | pathlib.Path) -> list[dict[str, Any]]:
    with pathlib.Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def stem(raw: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "", str(raw or "").lower())
    if token.endswith("ies") and len(token) > 6:
        return token[:-3] + "y"
    for suffix in ("es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            return token[:-len(suffix)]
    return token


def tokens(text: str, *, keep_function_words: bool = False) -> tuple[str, ...]:
    out = []
    for raw in re.findall(r"[A-Za-z0-9]+", str(text or "")):
        if not keep_function_words and raw.lower() in FUNCTION_WORDS:
            continue
        value = stem(raw)
        if value:
            out.append(value)
    return tuple(out)


def core_label(label: str) -> str:
    return re.sub(r"\([^)]*\)", "", str(label or "")).strip()


def label_head(label: str) -> str:
    seq = list(tokens(core_label(label)))
    while len(seq) > 1 and seq[-1] in GENERIC_TRAILING:
        seq.pop()
    return seq[-1] if seq else ""


def known_surfaces(profile: Mapping[str, Any]) -> list[tuple[str, ...]]:
    values = [profile.get("canonical_name") or ""]
    values.extend(
        item.get("term") if isinstance(item, Mapping) else item
        for item in profile.get("deterministic_label_variants") or []
    )
    seen = set()
    out = []
    for value in values:
        phrase = tokens(str(value or ""))
        if phrase and phrase not in seen:
            seen.add(phrase)
            out.append(phrase)
    return out


def ngrams_ending_at(seq: tuple[str, ...], index: int, max_words: int = 4
                      ) -> Iterable[tuple[str, ...]]:
    for width in range(2, max_words + 1):
        start = index - width + 1
        if start >= 0:
            yield seq[start:index + 1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--profiles", required=True)
    parser.add_argument("--packets", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--min-count", type=int, default=3)
    parser.add_argument("--top-candidates", type=int, default=8)
    args = parser.parse_args()

    profiles = load_jsonl(args.profiles)
    packets = load_jsonl(args.packets)
    packets_by_id = {row.get("kc_id") or row.get("knowledge_unit_id"): row for row in packets}

    # Terms common across many registry labels are weak branch evidence. The cutoff is derived
    # from the registry size, not a subject vocabulary.
    label_df: collections.Counter[str] = collections.Counter()
    for profile in profiles:
        label_df.update(set(tokens(" ".join(str(x) for x in profile.get("topic_path_labels") or []))))
    broad_cutoff = max(8, round(len(profiles) * 0.075))
    broad_terms = {term for term, count in label_df.items() if count >= broad_cutoff}

    phrase_owners: dict[tuple[str, ...], list[str]] = collections.defaultdict(list)
    profile_meta = {}
    heads = set()
    for profile in profiles:
        unit_id = profile.get("kc_id") or profile.get("knowledge_unit_id")
        name = str(profile.get("canonical_name") or "")
        surfaces = known_surfaces(profile)
        for phrase in surfaces:
            phrase_owners[phrase].append(str(unit_id))
        head = label_head(name)
        heads.add(head)
        own_terms = set(tokens(core_label(name)))
        branch_terms = set(tokens(" ".join(str(x) for x in profile.get("topic_path_labels") or [])))
        branch_terms -= own_terms | broad_terms | GENERIC_TRAILING
        profile_meta[str(unit_id)] = {
            "canonical_name": name,
            "head": head,
            "surfaces": surfaces,
            "branch_terms": branch_terms,
        }

    surface_counts: collections.Counter[tuple[str, ...]] = collections.Counter()
    # head -> candidate -> list of (document, context terms, source sample)
    candidates: dict[str, dict[tuple[str, ...], list[tuple[str, frozenset[str], str]]]] = (
        collections.defaultdict(lambda: collections.defaultdict(list)))
    rows = 0
    with pathlib.Path(args.corpus).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            sentence = str(row.get("sentence_text") or "")
            heading = str(row.get("patch_heading") or "")
            source_block = str(row.get("source_block_text") or "")
            sentence_tokens = tokens(sentence)
            context_terms = frozenset(tokens("%s %s" % (heading, source_block)))
            seen_phrases = set()
            for width in range(1, min(8, len(sentence_tokens)) + 1):
                for start in range(0, len(sentence_tokens) - width + 1):
                    phrase = sentence_tokens[start:start + width]
                    if phrase in phrase_owners:
                        seen_phrases.add(phrase)
            surface_counts.update(seen_phrases)
            for index, token in enumerate(sentence_tokens):
                if token not in heads:
                    continue
                for phrase in ngrams_ending_at(sentence_tokens, index):
                    bucket = candidates[token][phrase]
                    if len(bucket) < 1000:
                        bucket.append((str(row.get("doc_id") or ""), context_terms,
                                       sentence[:300]))

    reports = []
    draftable_without_core_surface = []
    for unit_id, meta in profile_meta.items():
        packet = packets_by_id.get(unit_id) or {}
        canonical_phrase = tokens(core_label(meta["canonical_name"]))
        core_count = surface_counts.get(canonical_phrase, 0)
        known_counts = {
            " ".join(phrase): surface_counts.get(phrase, 0) for phrase in meta["surfaces"]
        }
        if packet.get("packet_support_state") == "draftable" and core_count == 0:
            draftable_without_core_surface.append({
                "kc_id": unit_id,
                "canonical_name": meta["canonical_name"],
                "support_state": packet.get("packet_support_state"),
                "passage_count": len(packet.get("evidence_for_synthesis") or []),
            })

        scored = []
        known = set(meta["surfaces"])
        for phrase, occurrences in candidates.get(meta["head"], {}).items():
            if phrase in known or len(occurrences) < args.min_count:
                continue
            docs = sorted({doc for doc, _context, _sample in occurrences if doc})
            branch_hits = sum(bool(context & meta["branch_terms"])
                              for _doc, context, _sample in occurrences)
            known_surface_hits = sum(
                any(set(surface).issubset(context) for surface in known)
                for _doc, context, _sample in occurrences)
            if meta["branch_terms"] and branch_hits == 0:
                continue
            scored.append({
                "surface": " ".join(phrase),
                "count": len(occurrences),
                "branch_context_count": branch_hits,
                "branch_context_ratio": round(branch_hits / len(occurrences), 4),
                "licensed_surface_context_count": known_surface_hits,
                "licensed_surface_context_ratio": round(known_surface_hits / len(occurrences), 4),
                "documents": docs,
                "sample": occurrences[0][2],
            })
        scored.sort(key=lambda row: (-row["licensed_surface_context_count"],
                                     -row["branch_context_count"], -row["count"],
                                     -len(row["documents"]), row["surface"]))
        reports.append({
            "kc_id": unit_id,
            "canonical_name": meta["canonical_name"],
            "lexical_head": meta["head"],
            "branch_terms": sorted(meta["branch_terms"]),
            "canonical_core_count": core_count,
            "known_surface_counts": known_counts,
            "packet_support_state": packet.get("packet_support_state"),
            "thin_evidence": bool((packet.get("evidence_coverage") or {}).get("thin_evidence")),
            "source_observed_head_preserving_candidates": scored[:args.top_candidates],
        })

    result = {
        "corpus_rows": rows,
        "profile_count": len(profiles),
        "dynamic_broad_term_cutoff": broad_cutoff,
        "dynamic_broad_terms": sorted(broad_terms),
        "profiles_with_canonical_core_observed": sum(row["canonical_core_count"] > 0
                                                       for row in reports),
        "draftable_without_canonical_core_surface": draftable_without_core_surface,
        "profile_reports": reports,
    }
    pathlib.Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(args.out_json).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("corpus rows:", rows)
    print("profiles:", len(reports))
    print("canonical core observed:", result["profiles_with_canonical_core_observed"])
    print("draftable without canonical core:", len(draftable_without_core_surface))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
