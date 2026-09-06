from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from kc_l.topic.minimal_draft import TOPIC_DRAFT_SCHEMA
from kc_l.utils.ollama_json import list_ollama_models, ollama_chat_json

DEFAULT_OVERLAY = Path('data/processed/hierarchy_overlay/2026-03-10_005659_hierarchy_overlay/hierarchy_overlay.jsonl')
DEFAULT_APPROVED_MANIFEST = Path('data/processed/kc_library_pilot_packaging_restarted/2026-04-01_133111/approved_reviewed_library_manifest.json')
DEFAULT_APPROVED_LIBRARY = Path('data/processed/kc_library_pilot_packaging_restarted/2026-04-01_133111/approved_reviewed_library_frozen.jsonl')
DEFAULT_ACTIVE_STEP4_POINTER = Path('data/processed/retrieval_index/_sets/ACTIVE_STEP4_SET.txt')
DEFAULT_BLOCKSTORE_ROOT = Path('data/processed/blockstore')
DEFAULT_PRIOR_TOPIC_BUNDLE = Path('data/processed/topic_library_draft_restarted/2026-04-01_143108')
DEFAULT_OUT_ROOT = Path('data/processed/topic_library_draft_restarted')

STOPWORDS = {'a','an','and','as','at','by','for','from','in','into','is','of','on','or','the','to','with'}
NOISE_MARKERS = ('myra spiliopoulou','introduction to data mining','springer','lecture notes','sources of the unit')
HEADING_BLACKLIST = {'closing','summary and outlook','progress and outlook','materials','sources of the unit','running example','questions?','thank you very much!'}
DEFINITION_CUES = (' is a ',' is the ',' refers to ',' known as ',' called ',' process that ',' family of methods',' family of algorithms',' defines ',' assumes ',' chooses the ',' means ',' threshold on ')
SCOPE_CUES = ('how to ','learn to ','used for ','used when ','deal with ','compare ','role of ','we have seen','different ways','covers ','perform ','applies ','find the best')
MODEL_OUTPUT_SCHEMA: dict[str, Any] = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['draft_definition','definition_support_ids','draft_scope_role','scope_support_ids','outline_children','outline_support_ids'],
    'properties': {
        'draft_definition': {'type': 'string'},
        'definition_support_ids': {'type': 'array', 'items': {'type': 'string'}},
        'draft_scope_role': {'type': 'string'},
        'scope_support_ids': {'type': 'array', 'items': {'type': 'string'}},
        'outline_children': {'type': 'array', 'items': {'type': 'string'}},
        'outline_support_ids': {'type': 'array', 'items': {'type': 'string'}},
    },
}
MODEL_SYSTEM_PROMPT = (
    'You draft conservative Topic Library entries from slide evidence only. '
    'Knowledge Topics are broader than Knowledge Components. Do not invent missing facts. '
    'If the evidence does not support a field, leave it empty. '
    'A definition should say what the topic is, not what a specific KC is or how to solve an exercise.'
)
MODEL_USER_INSTRUCTIONS = """Return exactly one JSON object with these keys only:
- draft_definition
- definition_support_ids
- draft_scope_role
- scope_support_ids
- outline_children
- outline_support_ids

Rules:
- Use only support ids that appear in the payload.
- If a field is unsupported, use an empty string or empty list.
- draft_definition must be one short, source-faithful sentence stating what the topic is and should normally mention the topic name or its core term.
- draft_scope_role may describe what the topic covers or why it matters in this slide corpus.
- outline_children should be copied or lightly normalized from outline candidates only.
- No markdown. No commentary. No extra keys.
"""


@dataclass(frozen=True)
class CandidateSpan:
    candidate_id: str
    doc_id: str
    page_index: int
    block_id: str
    support_kind: str
    excerpt: str
    score: float


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding='utf-8')


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write('\n')


def normalize_text(text: Any) -> str:
    text = str(text or '').replace('’', "'").replace('‘', "'").replace('–', '-')
    return re.sub(r'\s+', ' ', text.strip().lower())


def clean_text(text: Any) -> str:
    text = str(text or '').replace('’', "'").replace('‘', "'").replace('–', '-')
    text = re.sub(r'[\x00-\x1f]', ' ', text)
    return re.sub(r'\s+', ' ', text.strip())


def meaningful_tokens(text: Any) -> set[str]:
    return {token for token in re.findall(r'[a-z0-9]+', normalize_text(text)) if len(token) > 1 and token not in STOPWORDS}


def unique_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        normalized = normalize_text(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(item)
    return out


def slugify(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', normalize_text(text)).strip('-') or 'topic'


def topic_id(path: list[str]) -> str:
    return 'topic::' + '/'.join(slugify(part) for part in path)


def block_order_key(block: dict[str, Any]) -> tuple[int, int, str]:
    block_id = str(block.get('block_id', ''))
    suffix_match = re.search(r':(-?\d+)$', block_id)
    suffix = int(suffix_match.group(1)) if suffix_match else 10**9
    return int(block.get('page_index', 0)), suffix, block_id


def is_noise_line(text: str) -> bool:
    normalized = normalize_text(text)
    return bool(
        not normalized
        or normalized in HEADING_BLACKLIST
        or any(marker in normalized for marker in NOISE_MARKERS)
        or re.fullmatch(r'\d+(?:/\d+)?', normalized)
        or normalized in {'√','▶','·','···'}
    )


def is_footer_like(block: dict[str, Any]) -> bool:
    text = normalize_text(block.get('text_raw', ''))
    return bool(not text or 'myra spiliopoulou' in text or re.search(r'\b\d+/\d+\b', text) or '···' in text)


def split_block_lines(block: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, raw_line in enumerate(str(block.get('text_raw', '')).splitlines()):
        line = clean_text(raw_line)
        if is_noise_line(line):
            continue
        out.append({'line_id': f"{block['block_id']}#l{idx}", 'doc_id': str(block.get('doc_id', '')), 'page_index': int(block.get('page_index', 0)), 'block_id': str(block.get('block_id', '')), 'text': line})
    return out


def looks_heading_like(text: str) -> bool:
    cleaned = clean_text(text)
    normalized = normalize_text(cleaned)
    token_count = len(cleaned.split())
    return bool(cleaned and normalized not in HEADING_BLACKLIST and len(cleaned) <= 100 and 0 < token_count <= 10 and not any(cue in f' {normalized} ' for cue in DEFINITION_CUES) and not (re.search(r'[.!?]$', cleaned) and token_count > 4))


def looks_summary_like(text: str) -> bool:
    normalized = normalize_text(text)
    return bool(normalized.startswith('how to ') or normalized.startswith('we have seen') or normalized.startswith('in these two units') or any(cue in normalized for cue in SCOPE_CUES))


def looks_definition_like(text: str) -> bool:
    normalized = normalize_text(text)
    return bool(any(cue in f' {normalized} ' for cue in DEFINITION_CUES) or ' naive assumption' in normalized or ' significance level' in normalized or ' p-value ' in f' {normalized} ' or ' tree of clusters' in normalized or ' overlapping neighbourhoods' in normalized or ' optimal subset of features' in normalized)


def definition_is_strong(text: str, topic_title: str, outline_children: list[str]) -> bool:
    normalized = normalize_text(text)
    if not normalized or len(clean_text(text).split()) < 5:
        return False
    if normalized == normalize_text(topic_title):
        return False
    if normalized in {normalize_text(item) for item in outline_children}:
        return False
    if not re.search(r'\b(is|are|uses|used|based|method|process|algorithm|test|function|criterion|family|compares|groups|selects)\b', normalized):
        return False
    title_tokens = meaningful_tokens(topic_title)
    if title_tokens and not (title_tokens & meaningful_tokens(text)):
        return False
    return True


def topic_variants(label: str) -> list[str]:
    cleaned = clean_text(label)
    variants = [cleaned]
    if '(' in cleaned and ')' in cleaned:
        variants.extend(clean_text(item) for item in re.findall(r'\(([^)]+)\)', cleaned))
        stripped = clean_text(re.sub(r'\([^)]*\)', '', cleaned))
        if stripped:
            variants.append(stripped)
    if ':' in cleaned:
        variants.extend(clean_text(part) for part in cleaned.split(':'))
    variants.append(cleaned.replace('&', 'and'))
    return unique_preserve([variant for variant in variants if variant])


def match_score(text: str, variants: list[str]) -> float:
    normalized = normalize_text(text)
    text_tokens = meaningful_tokens(normalized)
    best = 0.0
    for variant in variants:
        variant_normalized = normalize_text(variant)
        variant_tokens = meaningful_tokens(variant_normalized)
        if not variant_tokens:
            continue
        score = 10.0 if variant_normalized and variant_normalized in normalized else 0.0
        overlap = len(variant_tokens & text_tokens)
        if overlap == len(variant_tokens):
            score += 7.0
        elif overlap >= max(2, len(variant_tokens) - 1):
            score += 4.0
        elif overlap > 0:
            score += float(overlap)
        best = max(best, score)
    return best


def prepare_page_catalog(blocks_by_doc: dict[str, list[dict[str, Any]]]) -> dict[str, dict[int, dict[str, Any]]]:
    catalog: dict[str, dict[int, dict[str, Any]]] = {}
    for doc_id, blocks in blocks_by_doc.items():
        pages: dict[int, dict[str, Any]] = defaultdict(lambda: {'lines': []})
        for block in sorted(blocks, key=block_order_key):
            if is_footer_like(block):
                continue
            pages[int(block.get('page_index', 0))]['lines'].extend(split_block_lines(block))
        catalog[doc_id] = dict(sorted(pages.items()))
    return catalog


def candidate_from_lines(prefix: str, doc_id: str, page_index: int, block_id: str, support_kind: str, score: float, lines: list[dict[str, Any]]) -> CandidateSpan | None:
    excerpt = clean_text(' '.join(line['text'] for line in lines if line['text']))
    if not excerpt or len(excerpt) < 3:
        return None
    candidate_id = f'{prefix}:{doc_id}:{page_index}:{abs(hash((block_id, excerpt, support_kind))) % 10**8}'
    return CandidateSpan(candidate_id=candidate_id, doc_id=doc_id, page_index=page_index, block_id=block_id, support_kind=support_kind, excerpt=excerpt, score=round(score, 6))


def dedupe_candidates(candidates: list[CandidateSpan], limit: int) -> list[CandidateSpan]:
    seen: set[tuple[str, int, str]] = set()
    out: list[CandidateSpan] = []
    for candidate in sorted(candidates, key=lambda item: (-item.score, item.page_index, item.candidate_id)):
        key = (candidate.doc_id, candidate.page_index, normalize_text(candidate.excerpt))
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= limit:
            break
    return out


def collect_scope_summary_candidates(doc_id: str, pages: dict[int, dict[str, Any]], branch_variants: list[str]) -> list[CandidateSpan]:
    out: list[CandidateSpan] = []
    for page_index, page in pages.items():
        page_lines = list(page.get('lines') or [])
        if not page_lines:
            continue
        joined = normalize_text(' '.join(line['text'] for line in page_lines[:10]))
        if not ('we have seen' in joined or 'how to ' in joined or 'summary' in joined or 'progress and outlook' in joined or 'summary and outlook' in joined):
            continue
        for line in page_lines:
            line_score = match_score(line['text'], branch_variants)
            if line_score <= 0 and not looks_summary_like(line['text']):
                continue
            if not looks_summary_like(line['text']) and len(line['text'].split()) > 14:
                continue
            candidate = candidate_from_lines('scope', doc_id, page_index, line['block_id'], 'scope_candidate', max(5.0, line_score + 3.0), [line])
            if candidate:
                out.append(candidate)
    return out

def collect_topic_candidates(topic: dict[str, Any], child_topics_by_parent: dict[str, list[dict[str, Any]]], sibling_topics_by_parent: dict[str, list[dict[str, Any]]], page_catalog: dict[str, dict[int, dict[str, Any]]], doc_titles: dict[str, str]) -> dict[str, Any]:
    path = [str(item) for item in topic.get('source_hierarchy_path') or []]
    topic_label = str(topic.get('label') or '')
    topic_level = int(topic.get('depth_overlay') or 0)
    target_variants = topic_variants(topic_label)
    branch_variants = unique_preserve(path[1:] if len(path) > 1 else path)
    child_labels = [str(row.get('label') or '') for row in child_topics_by_parent.get(topic['hier_node_id'], []) if row.get('label')]
    sibling_labels = [str(row.get('label') or '') for row in sibling_topics_by_parent.get(topic.get('parent_hier_node_id') or '', []) if str(row.get('label') or '') != topic_label]
    sibling_variants = unique_preserve([item for label in sibling_labels for item in topic_variants(label)])

    doc_scores = {doc_id: doc_relevance_score(topic, doc_titles.get(doc_id, doc_id), target_variants) for doc_id in page_catalog}
    repeated_heading_counts: dict[str, int] = defaultdict(int)
    for doc_id, pages in page_catalog.items():
        seen_in_doc: set[str] = set()
        for page in pages.values():
            for line in list(page.get('lines') or [])[:8]:
                if not looks_heading_like(line['text']):
                    continue
                normalized = normalize_text(line['text'])
                if normalized and normalized not in seen_in_doc:
                    seen_in_doc.add(normalized)
                    repeated_heading_counts[f"{doc_id}::{normalized}"] += 1
    page_matches: list[dict[str, Any]] = []
    for doc_id, pages in page_catalog.items():
        for page_index, page in pages.items():
            best_line = None
            best_score = 0.0
            for line in list(page.get('lines') or [])[:8]:
                if not looks_heading_like(line['text']):
                    continue
                if repeated_heading_counts.get(f"{doc_id}::{normalize_text(line['text'])}", 0) > 3:
                    continue
                target_score = match_score(line['text'], target_variants)
                sibling_score = match_score(line['text'], sibling_variants) if sibling_variants else 0.0
                if target_score >= 6.0 and target_score >= sibling_score and target_score > best_score:
                    best_line = line
                    best_score = target_score
            if best_line:
                page_matches.append({'doc_id': doc_id, 'page_index': page_index, 'heading_line': best_line, 'heading_score': best_score})

    relevant_doc_ids: list[str] = []
    for doc_id, score in doc_scores.items():
        if topic_level == 1:
            relevant_doc_ids.append(doc_id)
        elif topic_level == 2 and score >= 4.0:
            relevant_doc_ids.append(doc_id)
        elif topic_level >= 3 and score >= 5.0:
            relevant_doc_ids.append(doc_id)
    relevant_doc_ids.extend(match['doc_id'] for match in page_matches if match['heading_score'] >= 6.0)
    relevant_doc_ids = unique_preserve(relevant_doc_ids)

    definition_candidates: list[CandidateSpan] = []
    scope_candidates: list[CandidateSpan] = []
    outline_candidates: list[CandidateSpan] = []
    unit_header_candidates: list[CandidateSpan] = []

    for doc_id in relevant_doc_ids:
        pages = page_catalog[doc_id]
        if 0 in pages:
            first_page_lines = list(pages[0].get('lines') or [])
            header_lines = [line for line in first_page_lines if match_score(line['text'], branch_variants or target_variants) > 0]
            if header_lines:
                candidate = candidate_from_lines('unit', doc_id, 0, header_lines[0]['block_id'], 'unit_header', 4.0 + match_score(' '.join(line['text'] for line in header_lines), branch_variants or target_variants), header_lines[:2])
                if candidate:
                    unit_header_candidates.append(candidate)
                    scope_candidates.append(candidate)
        scope_candidates.extend(collect_scope_summary_candidates(doc_id, pages, branch_variants or target_variants))

    for match in page_matches:
        doc_id = match['doc_id']
        page_index = int(match['page_index'])
        page_lines = list(page_catalog[doc_id][page_index].get('lines') or [])
        heading_line = dict(match['heading_line'])
        heading_score = float(match['heading_score'])
        context_lines: list[dict[str, Any]] = []
        passed_heading = False
        for line in page_lines:
            if line['line_id'] == heading_line['line_id']:
                passed_heading = True
                continue
            if not passed_heading:
                continue
            if looks_heading_like(line['text']) and context_lines:
                break
            context_lines.append(line)
            if len(context_lines) >= 5:
                break

        heading_candidate = candidate_from_lines('outline', doc_id, page_index, heading_line['block_id'], 'outline_candidate', heading_score + 1.0, [heading_line])
        if heading_candidate:
            outline_candidates.append(heading_candidate)
            scope_candidates.append(CandidateSpan(candidate_id=heading_candidate.candidate_id.replace('outline', 'scope', 1), doc_id=heading_candidate.doc_id, page_index=heading_candidate.page_index, block_id=heading_candidate.block_id, support_kind='scope_candidate', excerpt=heading_candidate.excerpt, score=heading_candidate.score))

        combined_candidate = candidate_from_lines('context', doc_id, page_index, heading_line['block_id'], 'page_context', heading_score + (2.0 if context_lines else 0.0), [heading_line, *context_lines])
        if combined_candidate:
            if looks_definition_like(combined_candidate.excerpt):
                definition_candidates.append(CandidateSpan(candidate_id=combined_candidate.candidate_id.replace('context', 'definition', 1), doc_id=combined_candidate.doc_id, page_index=combined_candidate.page_index, block_id=combined_candidate.block_id, support_kind='definition_candidate', excerpt=combined_candidate.excerpt, score=combined_candidate.score + 1.0))
            scope_candidates.append(CandidateSpan(candidate_id=combined_candidate.candidate_id.replace('context', 'scope', 1), doc_id=combined_candidate.doc_id, page_index=combined_candidate.page_index, block_id=combined_candidate.block_id, support_kind='scope_candidate', excerpt=combined_candidate.excerpt, score=combined_candidate.score))

        for line in context_lines:
            line_score = match_score(line['text'], target_variants) or 3.0
            if looks_definition_like(line['text']):
                candidate = candidate_from_lines('definition', doc_id, page_index, line['block_id'], 'definition_candidate', heading_score + line_score + 2.0, [line])
                if candidate:
                    definition_candidates.append(candidate)
            if looks_summary_like(line['text']) or len(line['text'].split()) >= 6:
                candidate = candidate_from_lines('scope', doc_id, page_index, line['block_id'], 'scope_candidate', heading_score + line_score + 1.0, [line])
                if candidate:
                    scope_candidates.append(candidate)

    if topic_level <= 2 and child_labels:
        for doc_id in relevant_doc_ids[:2]:
            if 0 not in page_catalog[doc_id]:
                continue
            header_lines = [line for line in page_catalog[doc_id][0].get('lines') or [] if 'block' in normalize_text(line['text']) or 'unit' in normalize_text(line['text'])]
            if header_lines:
                candidate = candidate_from_lines('scope', doc_id, 0, header_lines[0]['block_id'], 'scope_candidate', 5.0, header_lines[:2])
                if candidate:
                    scope_candidates.append(candidate)

    return {
        'child_labels': child_labels,
        'relevant_doc_ids': relevant_doc_ids,
        'definition_candidates': dedupe_candidates(definition_candidates, 8),
        'scope_candidates': dedupe_candidates(scope_candidates, 10),
        'outline_candidates': dedupe_candidates(outline_candidates, 10),
        'unit_header_candidates': dedupe_candidates(unit_header_candidates, 4),
    }


def doc_relevance_score(topic: dict[str, Any], doc_title: str, target_variants: list[str]) -> float:
    score = 0.0
    title_normalized = normalize_text(doc_title)
    title_tokens = meaningful_tokens(doc_title)
    path = [str(item) for item in topic.get('source_hierarchy_path') or []]
    branch_labels = path[1:] if len(path) > 1 else path
    for label in branch_labels:
        label_normalized = normalize_text(label)
        label_tokens = meaningful_tokens(label)
        if label_normalized and label_normalized in title_normalized:
            score += 6.0
        score += float(len(label_tokens & title_tokens))
    score += match_score(doc_title, target_variants)
    return score


def choose_model_name() -> str:
    installed = list_ollama_models()
    for name in ('qwen3.5:9b', 'qwen3:latest'):
        if name in installed:
            return name
    raise RuntimeError(f'No supported local generation model found. Installed={installed}')


def normalize_model_result(raw: dict[str, Any]) -> dict[str, Any]:
    draft_definition = clean_text(raw.get('draft_definition') or raw.get('topic_definition') or '')
    draft_scope_role = raw.get('draft_scope_role') or raw.get('topic_scope') or ''
    if isinstance(draft_scope_role, list):
        draft_scope_role = '; '.join(clean_text(item) for item in draft_scope_role if clean_text(item))
    draft_scope_role = clean_text(draft_scope_role)
    outline_children = raw.get('outline_children') or raw.get('topic_outline') or []
    if not isinstance(outline_children, list):
        outline_children = []
    outline_children = [clean_text(item) for item in outline_children if clean_text(item)]
    return {
        'draft_definition': draft_definition,
        'definition_support_ids': [str(item) for item in (raw.get('definition_support_ids') or []) if str(item).strip()],
        'draft_scope_role': draft_scope_role,
        'scope_support_ids': [str(item) for item in (raw.get('scope_support_ids') or []) if str(item).strip()],
        'outline_children': outline_children,
        'outline_support_ids': [str(item) for item in (raw.get('outline_support_ids') or []) if str(item).strip()],
    }


def call_topic_model(model_name: str, topic: dict[str, Any], child_labels: list[str], relevant_units: list[dict[str, str]], definition_candidates: list[CandidateSpan], scope_candidates: list[CandidateSpan], outline_candidates: list[CandidateSpan]) -> dict[str, Any]:
    payload = {
        'topic_title': str(topic.get('label') or ''),
        'topic_path': [str(item) for item in topic.get('source_hierarchy_path') or []],
        'child_topics': child_labels,
        'relevant_units': relevant_units,
        'candidate_definition_spans': [{'id': c.candidate_id, 'doc_id': c.doc_id, 'page_index': c.page_index, 'text': c.excerpt} for c in definition_candidates],
        'candidate_scope_spans': [{'id': c.candidate_id, 'doc_id': c.doc_id, 'page_index': c.page_index, 'text': c.excerpt} for c in scope_candidates],
        'candidate_outline_spans': [{'id': c.candidate_id, 'doc_id': c.doc_id, 'page_index': c.page_index, 'text': c.excerpt} for c in outline_candidates],
    }
    messages = [
        {'role': 'system', 'content': MODEL_SYSTEM_PROMPT},
        {'role': 'user', 'content': MODEL_USER_INSTRUCTIONS + '\nPayload:\n' + json.dumps(payload, ensure_ascii=False)},
    ]
    parsed, _outer, _raw = ollama_chat_json(base_url='http://127.0.0.1:11434', model=model_name, messages=messages, format_schema=MODEL_OUTPUT_SCHEMA, temperature=0.0, top_p=1.0, num_ctx=8192, repeat_penalty=1.0, think=False, timeout_s=180.0)
    return normalize_model_result(parsed)


def clip_definition(text: str) -> str:
    text = clean_text(text)
    return text if len(text) <= 240 else text[:237].rstrip() + '...'


def deterministic_scope_fallback(child_labels: list[str], source_units: list[dict[str, str]]) -> str:
    if child_labels:
        return 'This topic organizes the slide corpus around: ' + '; '.join(child_labels[:6]) + '.'
    if source_units:
        return 'Grounded source units: ' + '; '.join(unit['unit_title'] for unit in source_units[:4]) + '.'
    return ''


def build_source_units(source_refs: list[dict[str, Any]], doc_titles: dict[str, str]) -> list[dict[str, str]]:
    ordered_doc_ids = unique_preserve([ref['doc_id'] for ref in source_refs])
    return [{'doc_id': doc_id, 'unit_title': doc_titles.get(doc_id, doc_id)} for doc_id in ordered_doc_ids]


def branch_label_mismatch(topic: dict[str, Any], source_units: list[dict[str, str]]) -> bool:
    path = [str(item) for item in topic.get('source_hierarchy_path') or []]
    if len(path) < 3 or not source_units:
        return False
    branch_tokens = meaningful_tokens(path[1])
    source_tokens = meaningful_tokens(' '.join(unit['unit_title'] for unit in source_units))
    return bool(branch_tokens and source_tokens and branch_tokens.isdisjoint(source_tokens))


def outline_children_from_support(model_children: list[str], child_labels: list[str], outline_candidates: list[CandidateSpan]) -> tuple[list[str], str]:
    if child_labels:
        return child_labels, 'outline_from_hierarchy'
    if model_children:
        return unique_preserve(model_children)[:6], 'outline_from_slide_candidates'
    return unique_preserve([candidate.excerpt for candidate in outline_candidates])[:6], 'outline_from_slide_candidates'

def latest_run_dir(doc_root: Path) -> Path:
    candidates = sorted(path for path in doc_root.iterdir() if path.is_dir())
    if not candidates:
        raise FileNotFoundError(f'No blockstore runs found under {doc_root}')
    return candidates[-1]


def extract_doc_title(blocks: list[dict[str, Any]], doc_id: str) -> str:
    texts: list[str] = []
    for block in blocks:
        if int(block.get('page_index', 0)) != 0:
            continue
        text = clean_text(block.get('text_raw', ''))
        if not text or 'myra spiliopoulou' in normalize_text(text) or re.search(r'\b\d+/\d+\b', text):
            continue
        texts.append(text)
    if not texts:
        return doc_id
    preferred = [text for text in texts if 'block' in normalize_text(text) or 'unit' in normalize_text(text)]
    return ' | '.join(preferred[:2]) if preferred else texts[0]


def load_active_doc_ids(pointer_path: Path) -> tuple[list[str], Path]:
    manifest_name = pointer_path.read_text(encoding='utf-8').strip()
    manifest_path = pointer_path.parent / manifest_name
    manifest = read_json(manifest_path)
    doc_ids = sorted((manifest.get('docs') or {}).keys())
    preferred = 'DM2_2_Clustering_withSilhouetteSlide_removed'
    obsolete = 'DM2_2_Clustering_Silhouette'
    if preferred in doc_ids and obsolete in doc_ids:
        doc_ids = [doc_id for doc_id in doc_ids if doc_id != obsolete]
    return doc_ids, manifest_path


def load_blocks(doc_ids: list[str], blockstore_root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], list[str]]:
    blocks_by_doc: dict[str, list[dict[str, Any]]] = {}
    doc_titles: dict[str, str] = {}
    exact_paths: list[str] = []
    for doc_id in doc_ids:
        run_dir = latest_run_dir(blockstore_root / doc_id)
        blocks_path = run_dir / 'blocks.jsonl'
        rows = [row for row in read_jsonl(blocks_path) if row.get('layer') == 'pymupdf']
        blocks_by_doc[doc_id] = rows
        doc_titles[doc_id] = extract_doc_title(rows, doc_id)
        exact_paths.append(str(blocks_path).replace('\\', '/'))
    return blocks_by_doc, doc_titles, exact_paths


def build_source_refs(lookup: dict[str, CandidateSpan], definition_support_ids: list[str], scope_support_ids: list[str], outline_support_ids: list[str], unit_header_candidates: list[CandidateSpan]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for support_id in [*definition_support_ids, *scope_support_ids, *outline_support_ids]:
        candidate = lookup.get(support_id)
        if not candidate:
            continue
        refs.append({'doc_id': candidate.doc_id, 'page_index': candidate.page_index, 'block_id': candidate.block_id, 'support_kind': candidate.support_kind, 'excerpt': candidate.excerpt})
    if not refs:
        for candidate in unit_header_candidates[:2]:
            refs.append({'doc_id': candidate.doc_id, 'page_index': candidate.page_index, 'block_id': candidate.block_id, 'support_kind': candidate.support_kind, 'excerpt': candidate.excerpt})
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str, str]] = set()
    for ref in refs:
        key = (ref['doc_id'], ref['page_index'], ref['block_id'], normalize_text(ref['excerpt']))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped[:10]


def build_topic_quality_comparison(prior_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]], runtime: dict[str, Any]) -> str:
    prior_by_id = {row['topic_id']: row for row in prior_rows}
    new_by_id = {row['topic_id']: row for row in new_rows}
    changed_lines: list[str] = []
    improved = 0
    weakened = 0
    for topic_id_value, new_row in new_by_id.items():
        prior_row = prior_by_id.get(topic_id_value)
        if not prior_row:
            continue
        prior_def = bool(prior_row.get('draft_definition'))
        new_def = bool(new_row.get('draft_definition'))
        prior_scope = bool(prior_row.get('draft_scope_role'))
        new_scope = bool(new_row.get('draft_scope_role'))
        if new_def and not prior_def:
            improved += 1
            changed_lines.append(f"- `{new_row['topic_title']}` gained a grounded definition.")
        elif prior_def and not new_def:
            weakened += 1
            changed_lines.append(f"- `{new_row['topic_title']}` lost a prior definition because the redraft did not keep it grounded enough.")
        elif new_scope and not prior_scope:
            changed_lines.append(f"- `{new_row['topic_title']}` gained a scope/role draft.")
    if not changed_lines:
        changed_lines = ['- No material topic-level text changes were detected.']
    return """# Topic Quality Comparison

## Runtime
- Model-backed drafting ran: `true`
- Backend: `{backend}`
- Model: `{model}`

## Count comparison
- Prior topic count: `{prior_count}`
- New topic count: `{new_count}`
- Prior grounded definitions: `{prior_defs}`
- New grounded definitions: `{new_defs}`
- Prior scope-only count: `{prior_scope_only}`
- New scope-only count: `{new_scope_only}`
- Prior title-only weak count: `{prior_weak}`
- New title-only weak count: `{new_weak}`

## Notable changes
{changes}

## Caution
This pass improves drafting quality only where the slide evidence supports it. Topics that still lack grounded definitions remain honest blanks rather than forced prose.
""".format(
        backend=runtime['backend'],
        model=runtime['model_name'],
        prior_count=len(prior_rows),
        new_count=len(new_rows),
        prior_defs=sum(1 for row in prior_rows if row.get('draft_definition')),
        new_defs=sum(1 for row in new_rows if row.get('draft_definition')),
        prior_scope_only=sum(1 for row in prior_rows if (not row.get('draft_definition') and row.get('draft_scope_role'))),
        new_scope_only=sum(1 for row in new_rows if (not row.get('draft_definition') and row.get('draft_scope_role'))),
        prior_weak=sum(1 for row in prior_rows if 'title_only_support' in (row.get('draft_flags') or [])),
        new_weak=sum(1 for row in new_rows if 'title_only_support' in (row.get('draft_flags') or [])),
        changes='\n'.join(changed_lines[:12]),
    )


def build_topic_report(manifest: dict[str, Any], overlap_examples: list[dict[str, str]], mismatch_topics: list[str], prior_bundle: Path) -> str:
    counts = manifest['counts']
    overlap_lines = [f"- `{row['topic_title']}` vs `{row['kc_title']}` (`{row['kc_id']}`)" for row in overlap_examples] or ['- No direct wording-overlap examples were surfaced automatically.']
    mismatch_lines = [f"- `{title}` remains a hierarchy/source mismatch and stays explicitly flagged." for title in mismatch_topics] or ['- No hierarchy/source mismatches were detected.']
    return """# Topic Draft Report

## Drafting runtime
- Model-backed drafting actually ran: `true`
- Backend: `{backend}`
- Model: `{model}`
- Topics attempted through the model: `{attempted}`
- Model runtime failures: `{failures}`

## Output counts
- Topic drafts produced: `{topic_count}`
- Grounded definitions: `{definitions}`
- Scope-only topics: `{scope_only}`
- Title-only weak topics: `{weak}`

## Hierarchy coverage
All overlay topic nodes were drafted from the current hierarchy scaffold.

## Key mismatches
{mismatches}

## Topic/KC separation
These topic drafts remain a separate typed layer. They do not modify or insert anything into the KC Library.

## Topic/KC overlaps
{overlaps}

## Comparison baseline
This bundle supersedes the prior topic draft pass at `{prior_bundle}` for pilot topic-draft quality, while leaving that earlier bundle untouched.

## Judgment
The new topic layer is suitable to keep as the pilot Topic Library draft only if the team accepts that slide sparsity still limits definition coverage. Richer textbook-backed reruns should improve topic definitions more than hierarchy coverage.
""".format(
        backend=manifest['runtime']['backend'],
        model=manifest['runtime']['model_name'],
        attempted=counts['llm_attempted_topics'],
        failures=counts['llm_failed_topics'],
        topic_count=counts['topic_draft_count'],
        definitions=counts['grounded_definition_count'],
        scope_only=counts['scope_only_count'],
        weak=counts['weak_title_only_count'],
        mismatches='\n'.join(mismatch_lines),
        overlaps='\n'.join(overlap_lines[:8]),
        prior_bundle=str(prior_bundle).replace('\\', '/'),
    )

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--overlay', type=Path, default=DEFAULT_OVERLAY)
    parser.add_argument('--approved_manifest', type=Path, default=DEFAULT_APPROVED_MANIFEST)
    parser.add_argument('--approved_library', type=Path, default=DEFAULT_APPROVED_LIBRARY)
    parser.add_argument('--active_step4_pointer', type=Path, default=DEFAULT_ACTIVE_STEP4_POINTER)
    parser.add_argument('--blockstore_root', type=Path, default=DEFAULT_BLOCKSTORE_ROOT)
    parser.add_argument('--prior_topic_bundle', type=Path, default=DEFAULT_PRIOR_TOPIC_BUNDLE)
    parser.add_argument('--out_root', type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()

    run_id = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    created_utc = datetime.now(timezone.utc).isoformat()
    out_dir = args.out_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    overlay_rows = read_jsonl(args.overlay)
    approved_manifest = read_json(args.approved_manifest)
    approved_rows = read_jsonl(args.approved_library)
    approved_kc_titles = {row['kc_id']: row.get('title') or row.get('final_text', {}).get('title') or row.get('canonical_name', '') for row in approved_rows}

    active_doc_ids, active_set_manifest_path = load_active_doc_ids(args.active_step4_pointer)
    blocks_by_doc, doc_titles, blockstore_paths = load_blocks(active_doc_ids, args.blockstore_root)
    page_catalog = prepare_page_catalog(blocks_by_doc)
    topic_rows = [row for row in overlay_rows if row.get('node_type') == 'topic']
    topic_rows.sort(key=lambda row: (int(row.get('depth_overlay', 0)), row.get('source_hierarchy_path', [])))
    child_topics_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    sibling_topics_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in topic_rows:
        parent = str(row.get('parent_hier_node_id') or '')
        child_topics_by_parent[parent].append(row)
        sibling_topics_by_parent[parent].append(row)

    model_name = choose_model_name()
    topic_drafts: list[dict[str, Any]] = []
    link_candidates: list[dict[str, Any]] = []
    overlap_examples: list[dict[str, str]] = []
    mismatch_topics: list[str] = []
    runtime_failures: list[dict[str, str]] = []

    llm_attempted_topics = 0
    llm_succeeded_topics = 0
    llm_failed_topics = 0
    deterministic_scope_fallback_topics = 0
    deterministic_outline_topics = 0
    model_definition_topics = 0
    model_scope_topics = 0

    for topic in topic_rows:
        path = [str(item) for item in topic['source_hierarchy_path']]
        parent_id = topic_id(path[:-1]) if len(path) > 1 else None
        bundle = collect_topic_candidates(topic, child_topics_by_parent, sibling_topics_by_parent, page_catalog, doc_titles)
        child_labels = list(bundle['child_labels'])
        definition_candidates = list(bundle['definition_candidates'])
        scope_candidates = list(bundle['scope_candidates'])
        outline_candidates = list(bundle['outline_candidates'])
        unit_header_candidates = list(bundle['unit_header_candidates'])
        relevant_units = [{'doc_id': doc_id, 'unit_title': doc_titles.get(doc_id, doc_id)} for doc_id in bundle['relevant_doc_ids']]

        llm_attempted_topics += 1
        llm_result: dict[str, Any]
        llm_error = ''
        try:
            llm_result = call_topic_model(model_name, topic, child_labels, relevant_units, definition_candidates, scope_candidates, outline_candidates)
            llm_succeeded_topics += 1
        except Exception as exc:
            llm_failed_topics += 1
            llm_error = f'{type(exc).__name__}:{exc}'
            llm_result = {'draft_definition': '', 'definition_support_ids': [], 'draft_scope_role': '', 'scope_support_ids': [], 'outline_children': [], 'outline_support_ids': []}
            runtime_failures.append({'topic_title': str(topic.get('label') or ''), 'error': llm_error})

        lookup = {candidate.candidate_id: candidate for candidate in [*definition_candidates, *scope_candidates, *outline_candidates, *unit_header_candidates]}
        allowed_ids = set(lookup)
        definition_support_ids = [item for item in llm_result['definition_support_ids'] if item in allowed_ids]
        scope_support_ids = [item for item in llm_result['scope_support_ids'] if item in allowed_ids]
        outline_support_ids = [item for item in llm_result['outline_support_ids'] if item in allowed_ids]

        draft_definition = clip_definition(llm_result['draft_definition'])
        if not definition_support_ids or len(draft_definition.split()) <= 2:
            draft_definition = ''
        draft_scope_role = clean_text(llm_result['draft_scope_role']) if scope_support_ids else ''

        source_refs = build_source_refs(lookup, definition_support_ids, scope_support_ids, outline_support_ids, unit_header_candidates)
        source_units = build_source_units(source_refs, doc_titles)
        if not draft_scope_role:
            draft_scope_role = deterministic_scope_fallback(child_labels, source_units)
            if draft_scope_role:
                deterministic_scope_fallback_topics += 1

        outline_children, outline_flag = outline_children_from_support(list(llm_result['outline_children']), child_labels, outline_candidates)
        if outline_flag == 'outline_from_hierarchy':
            deterministic_outline_topics += 1

        if draft_definition and not definition_is_strong(draft_definition, str(topic.get('label') or ''), outline_children):
            draft_definition = ''

        if draft_definition:
            model_definition_topics += 1
        if draft_scope_role and scope_support_ids:
            model_scope_topics += 1

        flags = []
        flags.append('definition_grounded' if draft_definition else 'definition_missing')
        flags.append('scope_role_grounded' if draft_scope_role else 'scope_role_missing')
        if draft_definition:
            flags.append('model_drafted_definition')
        if draft_scope_role and scope_support_ids:
            flags.append('model_drafted_scope_role')
        if not scope_support_ids and draft_scope_role:
            flags.append('scope_role_hierarchy_fallback')
        flags.append(outline_flag)
        support_kinds = unique_preserve([ref['support_kind'] for ref in source_refs])
        flags.extend(f'support_{kind}' for kind in support_kinds)
        if len(source_units) > 1:
            flags.append('cross_unit_aggregate')
        if source_refs and all(ref['support_kind'] in {'unit_header', 'outline_candidate'} for ref in source_refs) and not draft_definition:
            flags.append('title_only_support')
        if branch_label_mismatch(topic, source_units):
            flags.append('source_branch_label_mismatch')
            mismatch_topics.append(str(topic.get('label') or ''))
        if llm_error:
            flags.append('llm_runtime_failed')

        topic_id_value = topic_id(path)
        topic_drafts.append({'topic_id': topic_id_value, 'topic_title': str(topic.get('label') or ''), 'topic_level': int(topic.get('depth_overlay', 0)), 'parent_topic_id': parent_id, 'draft_definition': draft_definition, 'draft_scope_role': draft_scope_role, 'outline_children': outline_children, 'source_refs': source_refs, 'source_units': source_units, 'draft_flags': unique_preserve(flags)})

        approved_descendants = sorted({kc_id for kc_id in topic.get('descendant_kc_ids', []) if kc_id in approved_kc_titles})
        for kc_id in approved_descendants:
            kc_title = approved_kc_titles[kc_id]
            link_candidates.append({'link_type': 'topic_contains_approved_kc_candidate', 'topic_id': topic_id_value, 'topic_title': str(topic.get('label') or ''), 'kc_id': kc_id, 'kc_title': kc_title, 'basis': 'hierarchy_overlay_descendant_membership', 'approved_kc_only': True})
            if meaningful_tokens(topic.get('label') or '') & meaningful_tokens(kc_title):
                overlap_examples.append({'topic_title': str(topic.get('label') or ''), 'kc_id': kc_id, 'kc_title': kc_title})
                break

    counts = {
        'topic_draft_count': len(topic_drafts),
        'grounded_definition_count': sum(1 for row in topic_drafts if row['draft_definition']),
        'scope_only_count': sum(1 for row in topic_drafts if (not row['draft_definition'] and row['draft_scope_role'])),
        'weak_title_only_count': sum(1 for row in topic_drafts if 'title_only_support' in row['draft_flags']),
        'source_unit_count': len(doc_titles),
        'llm_attempted_topics': llm_attempted_topics,
        'llm_succeeded_topics': llm_succeeded_topics,
        'llm_failed_topics': llm_failed_topics,
        'model_definition_topics': model_definition_topics,
        'model_scope_topics': model_scope_topics,
        'deterministic_scope_fallback_topics': deterministic_scope_fallback_topics,
        'deterministic_outline_topics': deterministic_outline_topics,
    }

    runtime = {
        'backend': 'ollama',
        'base_url': 'http://127.0.0.1:11434',
        'model_name': model_name,
        'model_fields': ['draft_definition', 'draft_scope_role'],
        'deterministic_fields': ['topic_id', 'topic_title', 'topic_level', 'parent_topic_id', 'outline_children'],
        'runtime_failures': runtime_failures,
    }
    manifest = {
        'schema_version': 'topic_library.draft_manifest.v2',
        'run_id': run_id,
        'created_utc': created_utc,
        'package_status': 'quality_first_topic_redraft_emitted',
        'object_type': 'topic_library_draft_bundle',
        'approved_kc_count': approved_manifest['counts']['approved_reviewed_entries_frozen'],
        'schema_handling': {
            'schema_changed': False,
            'schema_reference_path': str((args.prior_topic_bundle / 'topic_schema_minimal.json')).replace('\\', '/'),
            'allowed_fields': ['topic_id','topic_title','topic_level','parent_topic_id','draft_definition','draft_scope_role','outline_children','source_refs','source_units','draft_flags'],
        },
        'separation_invariants': {
            'separate_topic_and_kc_layers': True,
            'kc_library_artifacts_read_only': True,
            'approved_kc_boundary_unmodified': True,
            'no_step6_7_or_6_8_rerun': True,
            'no_kc_artifact_writes': True,
        },
        'inputs': {
            'state_files': ['AGENTS.md','CHANGELOG.md','CURRENT_ACTIVE_STATE.md','Target design.md'],
            'prior_topic_bundle': str(args.prior_topic_bundle).replace('\\', '/'),
            'overlay_jsonl': str(args.overlay).replace('\\', '/'),
            'approved_kc_manifest': str(args.approved_manifest).replace('\\', '/'),
            'approved_kc_library': str(args.approved_library).replace('\\', '/'),
            'active_step4_pointer': str(args.active_step4_pointer).replace('\\', '/'),
            'active_step4_manifest': str(active_set_manifest_path).replace('\\', '/'),
            'active_doc_ids': active_doc_ids,
            'blockstore_jsonl_paths': blockstore_paths,
        },
        'counts': counts,
        'runtime': runtime,
        'coverage': {
            'topic_paths': [' > '.join(row['source_hierarchy_path']) for row in topic_rows],
            'source_doc_ids': sorted(doc_titles.keys()),
            'mismatch_topics': unique_preserve(mismatch_topics),
            'overlap_examples': overlap_examples[:8],
        },
        'outputs': {
            'topic_drafts_jsonl': str((out_dir / 'topic_drafts.jsonl')).replace('\\', '/'),
            'topic_draft_manifest_json': str((out_dir / 'topic_draft_manifest.json')).replace('\\', '/'),
            'topic_draft_report_md': str((out_dir / 'topic_draft_report.md')).replace('\\', '/'),
            'topic_quality_comparison_md': str((out_dir / 'topic_quality_comparison.md')).replace('\\', '/'),
            'topic_to_kc_link_candidates_jsonl': str((out_dir / 'topic_to_kc_link_candidates.jsonl')).replace('\\', '/'),
        },
    }

    prior_rows = read_jsonl(args.prior_topic_bundle / 'topic_drafts.jsonl')
    topic_report = build_topic_report(manifest, overlap_examples[:8], unique_preserve(mismatch_topics), args.prior_topic_bundle)
    quality_comparison = build_topic_quality_comparison(prior_rows, topic_drafts, runtime)

    write_jsonl(out_dir / 'topic_drafts.jsonl', topic_drafts)
    write_json(out_dir / 'topic_draft_manifest.json', manifest)
    (out_dir / 'topic_draft_report.md').write_text(topic_report, encoding='utf-8')
    (out_dir / 'topic_quality_comparison.md').write_text(quality_comparison, encoding='utf-8')
    write_jsonl(out_dir / 'topic_to_kc_link_candidates.jsonl', link_candidates)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())




