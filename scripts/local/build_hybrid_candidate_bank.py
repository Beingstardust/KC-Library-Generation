"""Build an augmented candidate bank: existing lexical candidates UNION hybrid-retrieved ones."""
from __future__ import annotations
import argparse, json, sys, io, time, collections, pathlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '/path/to/projects/kc_l_v2_mirror_20260810/src')
from kc_l.retrieval_gate.retrieval import (  # noqa: E402
    BM25Index, CrossEncoderReranker, retrieve_for_unit, synthesize_bank_row,
    DEFAULT_BM25_TOPK, DEFAULT_RERANK_TOPN, DEFAULT_RERANKER)


def load_jsonl(path):
    out = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus-jsonl', required=True)
    ap.add_argument('--profile-jsonl', required=True)
    ap.add_argument('--base-bank-jsonl', required=True)
    ap.add_argument('--out-jsonl', required=True)
    ap.add_argument('--bm25-topk', type=int, default=DEFAULT_BM25_TOPK)
    ap.add_argument('--rerank-topn', type=int, default=DEFAULT_RERANK_TOPN)
    ap.add_argument('--min-rerank-prob', type=float, default=0.5)
    ap.add_argument('--reranker', default=DEFAULT_RERANKER)
    ap.add_argument('--stats-json', default=None)
    a = ap.parse_args()

    t0 = time.time()
    corpus = load_jsonl(a.corpus_jsonl)
    print('corpus sentences: %d (%.1fs)' % (len(corpus), time.time() - t0), flush=True)

    t0 = time.time()
    index = BM25Index([r.get('sentence_text') or '' for r in corpus])
    print('bm25 index built (%.1fs)' % (time.time() - t0), flush=True)

    reranker = CrossEncoderReranker(a.reranker)
    print('reranker available=%s device=%s%s' % (
        reranker.available, getattr(reranker, 'device', '-'),
        '' if reranker.available else ' err=' + getattr(reranker, 'load_error', '?')), flush=True)
    if not reranker.available:
        print('ABORT: refusing to build a bank on BM25 alone - precision would be unguarded.')
        return 3

    base = load_jsonl(a.base_bank_jsonl)
    template_for = {}
    existing_sids = collections.defaultdict(set)
    for row in base:
        unit = row.get('kc_id') or row.get('knowledge_unit_id')
        template_for.setdefault(unit, row)
        existing_sids[unit].add(row.get('sentence_id'))
    print('base bank: %d rows / %d units' % (len(base), len(template_for)), flush=True)

    profiles = load_jsonl(a.profile_jsonl)
    added, skipped_dup, no_template = 0, 0, 0
    per_unit = collections.Counter()
    out_rows = list(base)

    t0 = time.time()
    for n, prof in enumerate(profiles, 1):
        unit = prof.get('kc_id') or prof.get('knowledge_unit_id')
        template = template_for.get(unit)
        if template is None:
            no_template += 1
            continue
        hits = retrieve_for_unit(prof, index, corpus, reranker,
                                 bm25_topk=a.bm25_topk, rerank_topn=a.rerank_topn,
                                 min_rerank_prob=a.min_rerank_prob)
        for hit in hits:
            sid = hit['sentence'].get('sentence_id')
            if sid in existing_sids[unit]:
                skipped_dup += 1
                continue
            out_rows.append(synthesize_bank_row(
                template, hit['sentence'], bm25_score=hit['bm25_score'],
                rerank_score=hit['rerank_score'], rerank_prob=hit['rerank_prob'], rank=hit['rank']))
            existing_sids[unit].add(sid)
            added += 1
            per_unit[unit] += 1
        if n % 20 == 0:
            print('  %d/%d units, +%d rows (%.0fs)' % (n, len(profiles), added, time.time() - t0), flush=True)

    pathlib.Path(a.out_jsonl).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out_jsonl, 'w', encoding='utf-8') as fh:
        for r in out_rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')

    stats = {
        'base_rows': len(base), 'hybrid_rows_added': added, 'total_rows': len(out_rows),
        'units_with_hybrid': len(per_unit), 'skipped_duplicates': skipped_dup,
        'units_without_template': no_template,
        'mean_hybrid_per_unit': round(added / max(len(per_unit), 1), 2),
        'bm25_topk': a.bm25_topk, 'rerank_topn': a.rerank_topn,
        'min_rerank_prob': a.min_rerank_prob, 'reranker': a.reranker,
    }
    print('\n=== DONE ===')
    for k, v in stats.items():
        print('  %-26s %s' % (k, v))
    if a.stats_json:
        pathlib.Path(a.stats_json).write_text(json.dumps(stats, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
