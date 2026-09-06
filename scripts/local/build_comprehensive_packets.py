"""Build Step 6.7 drafting packets directly from comprehensive retrieval.

Replaces the chain: step5x pack composition -> step6.6 drafting input overlay -> step6.7 packet
builder. Each of those stages narrows, and their combined effect was a packet holding a median of
2 sentence fragments. This produces the packet the drafting model actually needs: every passage
the corpus offers about the unit, ranked by relevance, as coherent blocks.

Emits the exact packet schema run_step67_v2_schema_contract_probe.py consumes, so the existing
drafting runner works unchanged.
"""
from __future__ import annotations
import argparse, json, sys, io, time, math, collections, pathlib, hashlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '/path/to/projects/kc_l_v2_mirror_20260810/src')
from kc_l.retrieval_gate.retrieval import BM25Index, CrossEncoderReranker, DenseIndex, build_query, candidate_query_texts, expand_query_tokens, tokenize  # noqa: E402
from kc_l.retrieval_gate.evidence_pack import (  # noqa: E402
    assemble_passages, build_corpus_block_index, build_block_successor_index,
    find_rival_units, drop_passages_claimed_by_rivals, build_document_long_sentences,
    build_document_all_sentences,
    coverage_summary, is_structural_junk,
    DEFAULT_BM25_POOL, DEFAULT_MAX_PASSAGES, DEFAULT_MAX_CHARS, DEFAULT_MIN_RELEVANCE)

PACKET_VERSION = 'step67_comprehensive_synthesis_packet_v1'

DRAFTING_INSTRUCTION = {
    'goal': ('Write a complete account of this knowledge unit from the supplied source passages: '
             'what it is, how it works, why and when it is used, and its conditions and limits.'),
    'must_use': [
        'Use ALL passages that bear on the unit, not only the first definitional-looking one.',
        'Where the passages give an algorithm or procedure, state its steps in order.',
        'Where the passages give a formula or symbolic relation, reproduce it EXACTLY as written. '
        'Never reconstruct, complete, simplify or infer a formula, and never supply one from your own '
        'knowledge. If the rendering in the passages is partial or unreadable, say the unit has a '
        'formula and that the source rendering is incomplete, and give no equation at all.',
        'Define a symbol only where the passages define it. Leave undefined symbols undefined rather '
        'than guessing what they stand for.',
        'Where the passages give conditions, limits, parameters or failure cases, state them.',
        'Where the passages explain why or when the unit is used, include that.',
        'Prefer completeness over brevity: length should be governed by how much the passages '
        'actually support, not by a target length.',
        'Do not invent anything the passages do not support.',
        'Every substantive claim must be linked to evidence_id values in evidence_map.',
        'If the passages genuinely do not cover the unit, abstain rather than padding.',
        'An incomplete draft is acceptable; an invented one is not. Never add a sentence, a step or '
        'an equation to make the account look finished. Stopping early where the passages stop is '
        'the correct behaviour, and coverage_notes is where to record what is missing.',
    ],
    'passage_shapes': ('Each passage carries shape tags (definition, formula, procedure, example). '
                       'They tell you what KIND of content a passage holds. They are information, '
                       'not permission: use any passage that bears on the unit.'),
}


def load_jsonl(path, limit=None):
    out = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
                if limit and len(out) >= limit:
                    break
    return out


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x)) if x >= 0 else math.exp(x) / (1.0 + math.exp(x))


def evidence_item(passage, idx, unit):
    return {
        'evidence_id': '%s:comprehensive:%04d' % (unit, idx),
        'text': passage['text'],
        'source_block_text': passage['text'],
        'doc_id': passage.get('doc_id'),
        'page_index': passage.get('page_index'),
        'patch_heading': passage.get('patch_heading') or '',
        'sentence_id': passage.get('seed_sentence_id'),
        'evidence_lane': 'comprehensive_relevance_ranked',
        'role': ','.join(passage.get('shapes') or []) or 'context',
        'roles': list(passage.get('shapes') or []),
        'shape_tags': list(passage.get('shapes') or []),
        'relevance': passage.get('relevance'),
        'score_for_packet': passage.get('relevance'),
        'sentence_count': passage.get('sentence_count'),
        'routing_recommendation': 'comprehensive_relevance_admitted',
        'review_risk_flags': [],
        'selected_text_mode': 'source_block_passage',
        'support_profile_summary': {
            'admission_basis': passage.get('admission_basis') or 'cross_encoder_relevance',
            'relevance': passage.get('relevance'),
            'bm25_score': passage.get('bm25_score'),
            'shape_tags': list(passage.get('shapes') or []),
            'duplicate_variants_collapsed': passage.get('duplicate_variants', 1),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus-jsonl', required=True)
    ap.add_argument('--profile-jsonl', required=True)
    ap.add_argument('--out-jsonl', required=True)
    ap.add_argument('--stats-json', default=None)
    ap.add_argument('--bm25-pool', type=int, default=DEFAULT_BM25_POOL)
    ap.add_argument('--max-passages', type=int, default=DEFAULT_MAX_PASSAGES)
    ap.add_argument('--max-chars', type=int, default=DEFAULT_MAX_CHARS)
    ap.add_argument('--min-relevance', type=float, default=DEFAULT_MIN_RELEVANCE)
    ap.add_argument('--limit-units', type=int, default=None)
    a = ap.parse_args()

    t0 = time.time()
    corpus = load_jsonl(a.corpus_jsonl)
    index = BM25Index([r.get('sentence_text') or '' for r in corpus])
    blocks = build_corpus_block_index(corpus)
    successors = build_block_successor_index(corpus)
    long_sentences = build_document_long_sentences(corpus)
    all_sentences = build_document_all_sentences(corpus)
    rr = CrossEncoderReranker()
    print('corpus=%d blocks=%d reranker=%s device=%s (%.0fs)' % (
        len(corpus), len(blocks), rr.available, getattr(rr, 'device', '-'), time.time() - t0), flush=True)
    if not rr.available:
        print('ABORT: reranker unavailable; relevance is the only quality gate here.')
        return 3

    t_dense = time.time()
    # Cache key includes the corpus file's own identity, so a different or changed corpus
    # rebuilds rather than silently reusing another corpus's vectors.
    _st = pathlib.Path(a.corpus_jsonl).stat()
    _key = hashlib.sha1(('%s|%d|%d|%d' % (a.corpus_jsonl, _st.st_size, int(_st.st_mtime),
                                          len(corpus))).encode('utf-8')).hexdigest()[:16]
    _cache = str(pathlib.Path(a.out_jsonl).parent.parent / '_dense_cache' / ('emb_%s.npz' % _key))
    dense = DenseIndex([r.get('sentence_text') or '' for r in corpus], cache_path=_cache)
    print('dense_index=%s device=%s cache=%s (%.0fs)' % (
        dense.available, getattr(dense, 'device', '-'),
        getattr(dense, 'cache_status', '-'), time.time() - t_dense), flush=True)

    profiles = load_jsonl(a.profile_jsonl)
    all_unit_names = [str(p.get('canonical_name') or '') for p in profiles]
    if a.limit_units:
        profiles = profiles[:a.limit_units]

    # sibling names by parent topic, from the registry labels themselves
    by_parent = collections.defaultdict(list)
    for p in profiles:
        by_parent[str(p.get('parent_topic_label') or '')].append(str(p.get('canonical_name') or ''))

    packets, agg = [], []
    t0 = time.time()
    for n, prof in enumerate(profiles, 1):
        unit = prof.get('kc_id') or prof.get('knowledge_unit_id')
        name = str(prof.get('canonical_name') or '')
        _, qtokens = build_query(prof)
        base_expanded = expand_query_tokens(index, qtokens)
        # the unit's own labels, used only to recognise its defining equation
        unit_label_list = [name] + [
            (d.get('term') if isinstance(d, dict) else d)
            for d in (prof.get('deterministic_label_variants') or [])]
        unit_label_list = [str(x) for x in unit_label_list if x]

        # Let the corpus decide which query formulation this unit is best expressed by, instead
        # of a hand-written rule about when ancestor context or acronym expansion helps (neither
        # answer is right in general - measured both ways on real units this session). Each
        # candidate form gets the SAME full retrieval it would actually receive, and the winner's
        # work is what we keep, so nothing is decided on a sample the decision does not apply to.
        q_forms = candidate_query_texts(prof)
        attempts = []
        for form in q_forms:
            form_tokens = list(base_expanded)
            # the form's own tokens also widen recall - an expanded acronym is exactly the
            # surface form the corpus is likely to actually use
            for tok in tokenize(form):
                if tok not in form_tokens:
                    form_tokens.append(tok)
            f_pool = index.top_k(form_tokens, a.bm25_pool)
            f_idx = {i for i, _ in f_pool}
            if dense.available:
                for i, _ in dense.top_k(form, 50):
                    if i not in f_idx:
                        f_pool.append((i, 0.0))
                        f_idx.add(i)
            f_hits = [{'sentence': corpus[i], 'bm25_score': s} for i, s in f_pool]
            if f_hits:
                f_scores = rr.score(form, [str(h['sentence'].get('sentence_text') or '') for h in f_hits])
                for h, sc in zip(f_hits, f_scores):
                    h['rerank_prob'] = sigmoid(sc)
                f_hits.sort(key=lambda h: -h['rerank_prob'])
            f_passages = assemble_passages(
                f_hits, blocks, max_passages=a.max_passages, max_chars=a.max_chars,
                min_relevance=a.min_relevance,
                verify_scorer=(lambda texts, _q=form: [sigmoid(s) for s in rr.score(_q, texts)]),
                member_verifier=(lambda texts, _q=form: [sigmoid(s) for s in rr.score(_q, texts)]),
                block_successors=successors,
                doc_long_sentences=long_sentences,
                doc_all_sentences=all_sentences,
                unit_labels=unit_label_list)
            f_rels = [float(p.get('relevance') or 0.0) for p in f_passages]
            f_max = max(f_rels, default=0.0)
            f_mean = (sum(f_rels) / len(f_rels)) if f_rels else 0.0
            f_cov = coverage_summary(f_passages)
            f_core = sum(1 for k in ('has_definition', 'has_formula', 'has_procedure')
                         if f_cov.get(k))
            attempts.append({'form': form, 'hits': f_hits, 'passages': f_passages,
                             'n': len(f_passages), 'max_rel': f_max, 'mean_rel': f_mean,
                             'core_shapes': f_core})

        # Rank by how much of the unit's substance the form actually delivers (definition /
        # formula / procedure), then by the precision of what it admits, and only then by
        # volume. Ranking on volume first rewarded the form that admitted the most text
        # regardless of whether that text was about the unit at all.
        chosen = max(attempts, key=lambda x: (x['core_shapes'], round(x['mean_rel'], 3), x['n']))
        qtext, hits, passages = chosen['form'], chosen['hits'], chosen['passages']

        # A passage can be about the right words and the wrong unit. Where another unit of this
        # same library claims it decisively, it is that unit's evidence, not this one's - the
        # failure behind eight of the eighteen wrongly-"grounded" drafts in the reviewed run.
        rivals = find_rival_units(name, all_unit_names)
        passages, rival_drops = drop_passages_claimed_by_rivals(
            passages, name, rivals,
            (lambda q, texts: [sigmoid(s) for s in rr.score(q, texts)]))
        q_scores = {x['form']: x['max_rel'] for x in attempts}
        q_counts = {x['form']: x['n'] for x in attempts}
        q_shapes = {x['form']: x['core_shapes'] for x in attempts}
        cov = coverage_summary(passages)
        parent = str(prof.get('parent_topic_label') or '')
        siblings = sorted({s for s in by_parent.get(parent, []) if s and s != name})
        packets.append({
            'knowledge_unit_id': unit,
            'kc_id': unit,
            'knowledge_unit_type': prof.get('knowledge_unit_type') or 'kc',
            'canonical_name': name,
            'packet_version': PACKET_VERSION,
            'aliases': [d.get('term') if isinstance(d, dict) else d
                        for d in (prof.get('deterministic_label_variants') or [])],
            'hierarchy': {
                'topic_path': list(prof.get('topic_path_labels') or []),
                'source_hierarchy_path': list(prof.get('topic_path_labels') or []) + ([name] if name else []),
                'parent_topic_label': parent,
                'leaf_label': name,
            },
            'sibling_kc_names': siblings,
            'rival_units_considered': rivals,
            'evidence_dropped_to_rival_units': rival_drops,
            'evidence_for_synthesis': [evidence_item(p, i, unit) for i, p in enumerate(passages)],
            'evidence_coverage': cov,
            'query_formulation': {
                'selected': qtext,
                'candidates': q_forms,
                'max_relevance_by_form': {k: round(v, 4) for k, v in (q_scores or {}).items()},
                'passage_count_by_form': q_counts,
                'core_shape_count_by_form': q_shapes,
                'basis': 'full_retrieval_per_form_core_shapes_then_mean_relevance_then_count',
            },
            'drafting_instruction': DRAFTING_INSTRUCTION,
            'insufficient_synthesis_support': not passages,
            'abstention_expected': not passages,
            'insufficient_support_reasons': ([] if passages else ['no_passage_cleared_relevance_threshold']),
            'packet_support_state': 'comprehensive' if passages else 'insufficient_support',
            'support_state_reason': 'relevance_ranked_comprehensive_assembly',
            'weak_fallback_abstention_allowed': not passages,
        })
        agg.append(cov)
        if n % 20 == 0:
            print('  %d/%d units (%.0fs)' % (n, len(profiles), time.time() - t0), flush=True)

    pathlib.Path(a.out_jsonl).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out_jsonl, 'w', encoding='utf-8') as fh:
        for p in packets:
            fh.write(json.dumps(p, ensure_ascii=False) + '\n')

    n = max(len(agg), 1)
    stats = {
        'units': len(packets),
        'units_with_evidence': sum(1 for c in agg if c['passage_count'] > 0),
        'units_empty': sum(1 for c in agg if c['passage_count'] == 0),
        'mean_passages': round(sum(c['passage_count'] for c in agg) / n, 2),
        'mean_chars': round(sum(c['total_chars'] for c in agg) / n, 1),
        'mean_sentences': round(sum(c['sentence_count'] for c in agg) / n, 1),
        'units_with_definition': sum(1 for c in agg if c['has_definition']),
        'units_with_formula': sum(1 for c in agg if c['has_formula']),
        'units_with_procedure': sum(1 for c in agg if c['has_procedure']),
        'units_with_example': sum(1 for c in agg if c['has_example']),
    }
    print('\n=== DONE ===')
    for k, v in stats.items():
        print('  %-26s %s' % (k, v))
    if a.stats_json:
        pathlib.Path(a.stats_json).write_text(json.dumps(stats, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
