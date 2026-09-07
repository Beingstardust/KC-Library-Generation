"""For each cluster-4 (under-retrieval) unit: does the CORRECT content even reach the candidate
pool (BM25 + dense), and if so, at what rank and reranker score? Distinguishes:

    NEVER_CANDIDATE   - the correct sentence isn't found by BM25 or dense at all - a recall
                        problem, needs a different query or a different recall channel
    LOW_RANK          - found, but far down the ranking - a ranking problem, the query
                        formulation doesn't discriminate it from more prominent content
    BELOW_FLOOR       - found and reasonably ranked, but the reranker itself scores it under
                        min_relevance - an admission-floor problem
    ADMITTED          - actually clears everything; the failure must be downstream (drafting or
                        rival-stripping), not retrieval

Uses the real corpus, the real BM25/dense indices (same code path as the packet builder), and the
real reranker, run once per unit's query forms.
"""
import json
import math
import sys

sys.path.insert(0, '/path/to/kc_l/src')
from kc_l.retrieval_gate.retrieval import BM25Index, CrossEncoderReranker, DenseIndex, candidate_query_texts

MIR = '/path/to/kc_l'
DATA = MIR + '/data/v3/runs/v3_20260812'
PROD = '/path/to/shared'
CORPUS = (PROD + '/data/processed/retrieval_sentence_overlay/20260727T022835Z_9e856df6/'
          '2026-07-27_085228/sentence_corpus.jsonl')

# (canonical_name, substrings that would identify a correct/ideal candidate sentence)
TARGETS = {
    'Querying Phase': ['deduc', 'appl', 'test instance', 'predict', 'classif', 'unseen'],
    'Splitting Continuous Attributes': ['< v', 'threshold', 'split point', 'sorted values'],
    'Cost Matrix': ['cost of predicting', 'actual class', 'predicted class'],
    'RIPPER Rule Induction': ['sequential covering', 'grow', 'prune', 'foil'],
    'Cosine Similarity': ['dot product', 'magnitude', 'norm'],
    'Centroid Initialization Sensitivity': ['different initial', 'local optim', 'restart', 'initial centroid'],
    'External Index: Purity': ['purity(i)', 'purity =', 'majority class'],
    'External Index: Precision': ['precision(i,j)', 'm ij', 'mij'],
    'External Index: Recall': ['recall(i,j)', 'm ij', 'mij'],
    'NB Learning Phase': ['prior', 'class-conditional', 'estimate'],
    'Evaluation Workflow': ['training set', 'validation', 'test set'],
}

import hashlib
import pathlib

print('loading corpus...')
corpus = [json.loads(l) for l in open(CORPUS, encoding='utf-8')]
print('corpus: %d sentences' % len(corpus))
texts = [str(r.get('sentence_text') or '') for r in corpus]
index = BM25Index(texts)
rr = CrossEncoderReranker()
# same cache-key derivation as the real packet builder, so this hits the already-warm cache
# instead of re-embedding 100k sentences from scratch
_st = pathlib.Path(CORPUS).stat()
_key = hashlib.sha1(('%s|%d|%d|%d' % (CORPUS, _st.st_size, int(_st.st_mtime),
                                      len(corpus))).encode('utf-8')).hexdigest()[:16]
_cache = str(pathlib.Path(DATA) / 'packets' / '..' / '_dense_cache' / ('emb_%s.npz' % _key))
_cache = str(pathlib.Path(MIR) / 'v3' / '_dense_cache' / ('emb_%s.npz' % _key))
dense = DenseIndex(texts, cache_path=_cache)
print('reranker available:', rr.available, 'dense available:', dense.available,
      'dense cache_status:', getattr(dense, 'cache_status', '?'))


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


profiles = {}
with open(DATA + '/profiles/kc_profiles.jsonl', encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        profiles[r.get('canonical_name')] = r

for name, markers in TARGETS.items():
    prof = profiles.get(name)
    if not prof:
        print('MISSING PROFILE:', name)
        continue
    forms = candidate_query_texts(prof)
    print('=' * 100)
    print(name, '| forms:', forms)

    for form in forms:
        from kc_l.retrieval_gate.retrieval import tokenize
        tokens = tokenize(form)
        pool = index.top_k(tokens, 400)
        pool_idx = {i for i, _ in pool}
        if dense.available:
            for i, _ in dense.top_k(form, 50):
                if i not in pool_idx:
                    pool.append((i, 0.0))
                    pool_idx.add(i)

        # is a marker-matching sentence anywhere in the pool?
        found_in_pool = []
        for i, bm25score in pool:
            t = texts[i].lower()
            if any(m.lower() in t for m in markers):
                found_in_pool.append((i, bm25score))

        if not found_in_pool:
            # check whether it exists in the FULL corpus at all (sanity)
            exists_anywhere = any(any(m.lower() in texts[i].lower() for m in markers) for i in range(len(texts)))
            print('  form=%-30r  NEVER_CANDIDATE (pool=%d)  exists_in_corpus_at_all=%s' % (
                form, len(pool), exists_anywhere))
            continue

        # score the pool with the real reranker, find the marker sentence's rank
        pool_sorted = sorted(pool, key=lambda x: -x[1])
        cand_texts = [texts[i] for i, _ in pool_sorted]
        scores = rr.score(form, cand_texts)
        scored = sorted(zip(pool_sorted, scores), key=lambda x: -x[1])
        for rank, ((i, _bm), sc) in enumerate(scored):
            t = texts[i].lower()
            if any(m.lower() in t for m in markers):
                prob = sigmoid(sc)
                status = ('ADMITTED' if prob >= 0.55 else 'BELOW_FLOOR')
                print('  form=%-30r  %s  rank=%d/%d  reranker_prob=%.3f' % (
                    form, status, rank, len(scored), prob))
                print('      text: %r' % texts[i][:140])
                break
