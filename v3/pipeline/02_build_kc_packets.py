"""Build Step 6.7 drafting packets directly from comprehensive retrieval.

Replaces the chain: step5x pack composition -> step6.6 drafting input overlay -> step6.7 packet
builder. Each of those stages narrows, and their combined effect was a packet holding a median of
2 sentence fragments. This produces the packet the drafting model actually needs: every passage
the corpus offers about the unit, ranked by relevance, as coherent blocks.

Emits the exact packet schema run_step67_v2_schema_contract_probe.py consumes, so the existing
drafting runner works unchanged.
"""
from __future__ import annotations
import argparse, json, sys, time, math, collections, pathlib, hashlib, re

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
# Repo-relative, not a hardcoded absolute path to one particular checkout. The previous
# absolute path meant ANY worktree or clone silently imported the original mirror's src
# instead of its own - which invalidated a vNext A/B before this was caught (both arms
# executed identical code and produced byte-identical packets).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'src'))
from kc_l.retrieval_gate.retrieval import BM25Index, CrossEncoderReranker, DenseIndex, build_query, candidate_query_texts, expand_query_tokens, tokenize  # noqa: E402
from kc_l.retrieval_gate.evidence_pack import (  # noqa: E402
    assemble_passages, build_corpus_block_index, build_block_successor_index,
    find_rival_units, drop_passages_claimed_by_rivals, drop_compound_sibling_formulas,
    drop_damaged_math_passages, drop_semantically_misbound_passages,
    build_document_long_sentences,
    build_document_all_sentences, build_stranded_numerator_texts,
    drop_stranded_numerator_passages, build_intact_formula_substitutions,
    build_intact_twin_index, build_damaged_formula_repairs, apply_damaged_formula_repairs,
    build_spliced_math_repairs, apply_spliced_math_repairs,
    coverage_summary, context_candidate_is_anchored, context_content_terms,
    heading_exactly_names_unit, normalized_label_phrase, defining_equation_patterns,
    compound_index_equation_patterns, is_defining_equation, _name_content_words,
    CONTEXT_RELEVANCE_FLOOR, CONTEXT_ADMISSION_BASES, RESCUE_ADMISSION_BASES,
    DEFAULT_BM25_POOL, DEFAULT_MAX_PASSAGES, DEFAULT_MAX_CHARS, DEFAULT_MIN_RELEVANCE)
from kc_l.retrieval_profile.deterministic import GENERIC_SUFFIX_TOKENS  # noqa: E402

PACKET_VERSION = 'step67_comprehensive_synthesis_packet_v1'
STRONG_TARGET_ADMISSION_BASES = RESCUE_ADMISSION_BASES | CONTEXT_ADMISSION_BASES

DRAFTING_INSTRUCTION = {
    'goal': ('Write a complete account of this knowledge unit from the supplied source passages: '
             'what it is, how it works, why and when it is used, and its conditions and limits.'),
    # Evidence-first generation. The drafter selects before it writes, rather than reasoning over
    # the whole pack and hoping the result stays inside the target unit. Added after an audit found
    # the worst failure was over-consumption, not scarcity: a unit that absorbed most of a
    # neighbouring branch while every individual paragraph remained source-supported.
    'procedure': [
        'STEP 1 - TRIAGE. Before writing anything, sort the supplied passages: which directly '
        'define or establish THIS unit; which are useful background; which principally belong to '
        'one of the units named in sibling_kc_names or rival_units_considered; and which are not '
        'assertable as fact (exercise prompts, questions, hypotheticals, statements presented for '
        'the reader to evaluate).',
        'STEP 2 - SUFFICIENCY. Decide whether the passages supplied IN THIS REQUEST are sufficient, '
        'partially sufficient, or insufficient to define this unit. Judge only what you were given. '
        'Do not conclude that the course corpus lacks the concept: you cannot observe the corpus, '
        'only this packet.',
        'STEP 3 - SUPPORT LEDGER. Fill evidence_map FIRST, before writing any prose. Each entry '
        'is one atomic claim you intend to make, tied to the evidence_id values that establish '
        'it. This ledger is the support set: it is not a citation list added afterwards.',
        'STEP 4 - DRAFT. Write the definition using only claims that appear in evidence_map. If a '
        'sentence is not backed by a ledger entry, either add the entry with its real evidence_id or do not write the sentence.',
        'STEP 5 - VERIFY. Re-read each substantive sentence against the supplied passages. Remove '
        'or weaken anything the passages do not support, anything whose subject is really a sibling '
        'unit, and any statement that contradicts another statement in your own draft. Preserve '
        'formulas, conditions, quantifiers and notation exactly.',
    ],
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
        'If the passages supply a defining formula, procedure, or set of steps for this unit, the '
        'draft must carry it. A prose description of a unit whose evidence contains its defining '
        'mechanism is incomplete, however fluent it reads.',
        'If this unit\'s own name enumerates several components, address each named component or '
        'state explicitly which the passages do not support.',
        'Do not invent anything the passages do not support.',
        'Every substantive claim must be linked to evidence_id values in evidence_map, and every '
        'evidence_id you cite must be one that appears in the supplied evidence. Do not invent an '
        'identifier, and do not cite an item you did not actually use.',
        'If the passages genuinely do not cover the unit, abstain rather than padding.',
        'An incomplete draft is acceptable; an invented one is not. Never add a sentence, a step or '
        'an equation to make the account look finished. Stopping early where the passages stop is '
        'the correct behaviour, and coverage_notes is where to record what is missing.',
    ],
    # Negative boundary, derived entirely from the hierarchy the run was given.
    'boundary': ('sibling_kc_names and rival_units_considered name the units this one must be '
                 'distinguished from. Their material may be used to CONTRAST and sharpen this '
                 'unit\'s definition, and to say what this unit is not. It must not be absorbed '
                 'into the definition: do not define a sibling, do not restate a sibling\'s '
                 'procedure, and do not let a sibling\'s content set the scope of this draft.'),
    'assertability': ('Every evidence item carries an assertability field. An item marked '
                      'not_assertable_interrogative poses a question or states an exercise: it '
                      'indicates what the source DISCUSSES, but its proposition is NOT established '
                      'fact. Do not assert such a proposition unless another item marked assertable '
                      'independently establishes it. Evidence is supplied in order of definitional '
                      'authority, so earlier items are the more direct sources for this unit.'),
    'conflicts': ('If two passages disagree, if two formulas are incompatible, or if the same term '
                  'is used in different senses, do not resolve the conflict from your own knowledge '
                  'in either direction. Prefer the passage whose subject is most directly this '
                  'unit; if that does not settle it, record the conflict in uncertainty_notes and '
                  'report partial rather than choosing silently.'),
    'precision_over_breadth': ('Do not maximise breadth. A shorter definition containing only '
                               'directly supported target-unit content is better than a broad one '
                               'padded with related material. Do not add background, applications, '
                               'sibling concepts, or examples unless they are directly supported '
                               'and materially improve the definition. A value taken from a worked '
                               'example describes that example: never restate it as a general '
                               'property using "any", "all", or "always".'),
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


CONTEXT_MAX_CHARS = 1800


def retrieval_query_forms(profile):
    """Use explicit registry disambiguation when a numbered label has no source semantics."""
    overrides = [str(term).strip()
                 for term in (profile.get('retrieval_disambiguation_terms') or [])
                 if str(term).strip()]
    return overrides or candidate_query_texts(profile)


def supplement_defining_equation_rows(pool, pool_indices, equation_rows, patterns, limit=100):
    """Add exact unit-LHS equations that lexical/dense retrieval did not surface."""
    added = 0
    for row_index, text in equation_rows:
        if row_index in pool_indices or not is_defining_equation(text, patterns):
            continue
        pool.append((row_index, 0.0))
        pool_indices.add(row_index)
        added += 1
        if added >= limit:
            break
    return added


def supplement_dense_formula_rows(pool, pool_indices, dense_index, query, formula_row_indices,
                                  limit=40):
    """Add formula-shaped rows the dense index ranks highly for this unit, whatever their LHS.

    supplement_defining_equation_rows() rescues equations whose LEFT-HAND SIDE names the unit. Real
    notation rarely does: Bayes' theorem's LHS is P(Y|X), the Laplace estimator's is P(Xi=c|y), an
    external-index entropy's is e_i. Measured on the real corpus, the defining formula for Bayes,
    Laplace, external entropy and the two-model variance comparison was present, undamaged, and a
    usable payload in every case, yet never reached the pool.

    Shape is used here ONLY to decide where to look. Every row added still faces the same
    cross-encoder relevance floor, math-integrity check, ownership adjudication and budget as any
    other candidate, so this widens recall without weakening admission.
    """
    if not dense_index or not getattr(dense_index, 'available', False) or not formula_row_indices:
        return 0
    added = 0
    for row_index, _score in dense_index.top_k(query, limit * 4):
        if added >= limit:
            break
        if row_index in pool_indices or row_index not in formula_row_indices:
            continue
        pool.append((row_index, 0.0))
        pool_indices.add(row_index)
        added += 1
    return added


def score_context_records(reranker, query, records, unit_labels, base_scores=None):
    """Score text consistently with licensed source context at every relevance checkpoint."""
    if not records:
        return []
    if base_scores is None:
        base_scores = [sigmoid(x) for x in reranker.score(
            query, [str(record.get('text') or '') for record in records])]
    best = [(float(score), 'standalone') for score in base_scores]
    probes, owners, modes = [], [], []
    for idx, record in enumerate(records):
        if best[idx][0] >= DEFAULT_MIN_RELEVANCE:
            continue
        text = str(record.get('text') or '').strip()
        context = str(record.get('context') or text).strip()
        heading = str(record.get('heading') or '').strip()
        if not context_candidate_is_anchored(text, context, heading, unit_labels):
            continue
        bounded_context = context[:CONTEXT_MAX_CHARS]
        if bounded_context and bounded_context != text:
            probes.extend((bounded_context, '%s\nContext: %s' % (text, bounded_context)))
            owners.extend((idx, idx))
            modes.extend(('source_block', 'sentence_plus_source_block'))
        if heading and heading_exactly_names_unit(heading, unit_labels):
            probes.append('%s: %s' % (heading, text))
            owners.append(idx)
            modes.append('exact_unit_heading')
    if probes:
        probe_scores = [sigmoid(x) for x in reranker.score(query, probes)]
        for idx, mode, score in zip(owners, modes, probe_scores):
            if float(score) > best[idx][0]:
                best[idx] = (float(score), mode)
    return best


def passage_has_strong_target_anchor(passage, unit_labels):
    """Require a real target binding before calling a packet draftable."""
    if passage.get('admission_basis') in STRONG_TARGET_ADMISSION_BASES:
        return True
    text = str(passage.get('text') or '').strip()
    heading = str(passage.get('patch_heading') or '')
    normalized_text = normalized_label_phrase('%s %s' % (heading, text))
    text_terms = context_content_terms('%s %s' % (heading, text))
    for label in unit_labels or []:
        core = re.sub(r'\([^)]*\)', '', str(label or '')).strip()
        phrase = normalized_label_phrase(core)
        if phrase and re.search(r'(?:^|\s)' + re.escape(phrase) + r'(?:\s|$)', normalized_text):
            return True
        label_terms = context_content_terms(core)
        if label_terms and label_terms.issubset(text_terms):
            return True
    return False


# Target identity is stricter than retrieval relevance. A near-neighbour statement can repeat a
# target's modifiers while assigning them to a different head noun: "gadgets in a gadget set are
# reliably calibrated" is not evidence that "Reliably Calibrated Widgets" exists. These are only
# grammatical/function words and registry-generic trailing descriptors; no corpus vocabulary is
# encoded here.
_IDENTITY_FUNCTION_WORDS = frozenset("""
a although an and are as at be been being by for from has have if in into is it its notice of on or
that the their these they this those to via was we were what when where which while with vs
""".split())
_IDENTITY_DEFINITIONAL_SUBJECT_PATTERNS = (
    re.compile(
        r"^\s*(?:In [^,]{3,40},\s*)?(?:(?:A|An|The|These|This|Those|Some)\s+)?"
        r"(?P<subject>[A-Za-z][A-Za-z0-9 \-()'/]{2,80}?)\s+"
        r"(?:is|are)\s+(?:defined\s+as|called|known\s+as|referred\s+to\s+as|"
        r"classified\s+as|used\s+to|a\b|an\b|the\b)", re.I),
    re.compile(
        r"^\s*(?:In [^,]{3,40},\s*)?(?:(?:A|An|The|These|This|Those|Some)\s+)?"
        r"(?P<subject>[A-Za-z][A-Za-z0-9 \-()'/]{2,80}?)\s+"
        r"(?:is|are)\s+[^.!?]{1,80}\b(?:if|when)\b", re.I),
    re.compile(
        r"^\s*(?:In [^,]{3,40},\s*)?(?:(?:A|An|The|These|This|Those|Some)\s+)?"
        r"(?P<subject>[A-Za-z][A-Za-z0-9 \-()'/]{2,80}?)\s+"
        r"(?:refers\s+to|means|denotes|measures|consists\s+of)\b", re.I),
)
_IDENTITY_COPULAR_SUBJECT_RE = re.compile(
    r"^\s*(?:In [^,]{3,40},\s*)?(?:(?:A|An|The|These|This|Those|Some)\s+)?"
    r"(?P<subject>[A-Za-z][A-Za-z0-9 \-()'/]{1,100}?)\s+"
    r"(?:is|are)\s+(?P<predicate>[^.!?]{1,180})", re.I)


def _identity_lexical_stem(raw):
    token = re.sub(r"[^a-z0-9]+", "", str(raw or "").lower())
    if token.endswith("ies") and len(token) > 6:
        return token[:-3] + "y"
    for suffix in ("es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            return token[:-len(suffix)]
    return token


def _identity_lexical_terms(raw):
    return {_identity_lexical_stem(token)
            for token in re.findall(r"[A-Za-z0-9]+", str(raw or ""))
            if (token.lower() not in _IDENTITY_FUNCTION_WORDS
                and _identity_lexical_stem(token))}


def _identity_label_shape(label):
    core = re.sub(r"\([^)]*\)", "", str(label or ""))
    sequence = [token.lower() for token in re.findall(r"[A-Za-z0-9]+", core)
                if token.lower() not in _IDENTITY_FUNCTION_WORDS]
    while len(sequence) > 1 and sequence[-1] in GENERIC_SUFFIX_TOKENS:
        sequence.pop()
    sequence = [_identity_lexical_stem(token) for token in sequence
                if _identity_lexical_stem(token)]
    if len(sequence) < 3:
        return "", set()
    return sequence[-1], set(sequence[:-1])


def _compatible_definitional_subject(text, unit_labels):
    target_terms = set()
    for label in unit_labels or []:
        target_terms |= context_content_terms(
            re.sub(r"\([^)]*\)", "", str(label or "")))
    if not target_terms:
        return ""
    for sentence in re.split(r"(?<=[.!?])\s+", str(text or "")):
        for pattern in _IDENTITY_DEFINITIONAL_SUBJECT_PATTERNS:
            match = pattern.match(sentence)
            if not match:
                continue
            subject = match.group("subject").strip()
            if context_content_terms(subject) & target_terms:
                return subject
    return ""


def passage_has_positive_target_identity(passage, unit_labels):
    """Positive source identity independent of a retrieval/relevance admission basis."""
    text = str(passage.get("text") or "").strip()
    heading = str(passage.get("patch_heading") or "").strip()
    normalized = normalized_label_phrase("%s %s" % (heading, text))
    for label in unit_labels or []:
        core = re.sub(r"\([^)]*\)", "", str(label or "")).strip()
        phrase = normalized_label_phrase(core)
        if phrase and re.search(r"(?:^|\s)" + re.escape(phrase) + r"(?:\s|$)", normalized):
            return True
    if passage.get("admission_basis") == "name_anchored_defining_equation":
        return True
    return bool(_compatible_definitional_subject(text, unit_labels))


def modifier_foreign_head_decoys(text, canonical_name):
    """Statements matching a target's modifiers while repeatedly naming another head.

    The foreign head must occur in both subject and predicate. This excludes incidental subjects
    such as "the results" and unresolved pronouns, which a broader subject-mismatch experiment
    falsely treated as competing concepts.
    """
    head, modifiers = _identity_label_shape(canonical_name)
    if not head or len(modifiers) < 2:
        return []
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+", str(text or "")):
        match = _IDENTITY_COPULAR_SUBJECT_RE.match(sentence)
        if not match:
            continue
        subject = match.group("subject").strip()
        predicate = match.group("predicate").strip()
        subject_terms = _identity_lexical_terms(subject)
        predicate_terms = _identity_lexical_terms(predicate)
        repeated_foreign = (subject_terms - modifiers - {head}) & predicate_terms
        if (subject_terms and head not in subject_terms and head not in predicate_terms
                and modifiers.issubset(predicate_terms) and repeated_foreign):
            out.append({"subject": subject, "predicate": predicate})
    return out


def packet_has_foreign_head_decoy_without_identity(passages, unit_labels):
    """A packet-level veto: explicit near-neighbour identity and no positive target identity."""
    assertable = [passage for passage in passages or []
                  if passage_assertability(passage) == ASSERTABLE]
    if any(passage_has_positive_target_identity(passage, unit_labels)
           for passage in assertable):
        return False
    canonical_name = str(next(iter(unit_labels or []), ""))
    return any(modifier_foreign_head_decoys(passage.get("text") or "", canonical_name)
               for passage in assertable)


def assess_support_state(passages, unit_labels):
    """Report evidence availability without claiming that retrieval proved completeness."""
    if not passages:
        return 'insufficient_support', 'no_passage_cleared_relevance_threshold'
    if packet_has_foreign_head_decoy_without_identity(passages, unit_labels):
        return ('insufficient_support',
                'modifier_matched_foreign_head_without_positive_target_identity')
    for passage in passages:
        text = str(passage.get('text') or '').strip()
        shapes = set(passage.get('shapes') or [])
        # INT-1: a passage whose own text is interrogative states what the source ASKS, not what
        # it asserts, and must not be able to establish a KC as draftable by itself - even when it
        # is long, formula-bearing, and target-anchored. This does not remove the passage from
        # `passages`; it stays available as ordinary contextual evidence (evidence_item() already
        # tags it `not_assertable_interrogative` downstream). This only prevents it from
        # single-handedly satisfying the support gate. passage_assertability() is a pure function
        # of passage text, safe to call here even though it is normally computed later in
        # evidence_item() - no ordering dependency.
        assertable = passage_assertability(passage) == ASSERTABLE
        formula_substance = (assertable and 'formula' in shapes and len(text) >= 8
                             and any(x in text for x in '=<>≤≥'))
        prose_substance = (assertable and len(text) >= 60 and shapes != {'heading'}
                           and any(mark in text for mark in '.;:!?'))
        anchored = passage_has_strong_target_anchor(passage, unit_labels)
        if anchored and (formula_substance or prose_substance):
            return ('draftable',
                    'target_anchored_substantive_passages_available_no_completeness_claim')
    return 'weak_fallback', 'only_fragmentary_heading_or_unanchored_passages_available'


INTERROGATIVE_ASSERTABILITY = 'not_assertable_interrogative'
ASSERTABLE = 'assertable'

# Authority tiers for evidence ordering. Lower sorts earlier. Derived entirely from the shape tags
# the sentence overlay already computes, so this carries no subject matter and works on any corpus.
_AUTHORITY_TIER = {'definition': 0, 'formula': 1, 'procedure': 2, 'example': 3}
_DEFAULT_TIER = 4
_NON_ASSERTABLE_TIER = 5


def passage_assertability(passage):
    """Whether this passage's proposition may be stated as fact.

    A question tells you what the source discusses, not what it establishes. Detected from terminal
    punctuation only - a property of the text, not of any subject. Motivated by an observed failure
    where a True/False exercise prompt became a stated fact in a draft.
    """
    text = str(passage.get('text') or '').strip()
    return INTERROGATIVE_ASSERTABILITY if text.endswith('?') else ASSERTABLE


def authority_tier(passage):
    """Definitional-authority rank: definitions and formulas lead, questions sink to the end."""
    if passage_assertability(passage) != ASSERTABLE:
        return _NON_ASSERTABLE_TIER
    shapes = set(passage.get('shapes') or [])
    tiers = [_AUTHORITY_TIER[s] for s in shapes if s in _AUTHORITY_TIER]
    return min(tiers) if tiers else _DEFAULT_TIER


def order_by_definitional_authority(passages):
    """Stable re-sort by authority tier, preserving the existing order inside each tier.

    Long-context work finds material in the middle of a long context is attended to less reliably,
    so a defining passage should not sit behind loosely relevant prose. Python's sort is stable, so
    relevance-then-document-order within a tier - which is what keeps a procedure's steps in
    sequence - survives untouched.
    """
    return sorted(passages or [], key=authority_tier)


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
        # A question indicates what the source discusses, not what it establishes. Surfaced as a
        # field so the drafter reads it rather than re-inferring it from the text every time.
        'assertability': passage_assertability(passage),
        'authority_tier': authority_tier(passage),
        'support_profile_summary': {
            'admission_basis': passage.get('admission_basis') or 'cross_encoder_relevance',
            'relevance': passage.get('relevance'),
            'bm25_score': passage.get('bm25_score'),
            'shape_tags': list(passage.get('shapes') or []),
            'duplicate_variants_collapsed': passage.get('duplicate_variants', 1),
            # Provenance for cross-layer formula recovery: without this, a passage whose text was
            # substituted from an intact rendering is indistinguishable from an ordinary one, and
            # the substitution becomes unauditable downstream even though it is already working.
            'recovered_from_severed_numerator': bool(
                passage.get('recovered_from_severed_numerator')),
            # What the extractors actually said, not only which rendering won. A reviewer
            # auditing a formula-heavy unit needs to see that a conflicting rendering existed.
            'extractor_agreement_count': passage.get('extractor_agreement_count'),
            'extractor_conflict': passage.get('extractor_conflict'),
            # INT-11 provenance. A repaired rendering reads like an ordinary one, so where it came
            # from has to travel with it: which document and layer supplied the intact text, and
            # whether it was found on the row's own page or somewhere less corroborated.
            'formula_repaired_from_doc_id': passage.get('formula_repaired_from_doc_id'),
            'formula_repaired_from_layer': passage.get('formula_repaired_from_layer'),
            'formula_repair_locality': passage.get('formula_repair_locality'),
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
    # INT-11. A rendering the damage checks reject is not necessarily a rendering the corpus
    # lacks: the same equation is often carried intact by a math-aware extraction layer
    # elsewhere. Repair before ANY index is built, so retrieval, block assembly, the lead-in
    # payload rescue and the drop passes all read one consistent text - a repair applied later
    # would be invisible to whichever of those paths ran first. Provenance is written onto every
    # repaired row; nothing here invents mathematics.
    # INT-22. Marginal equations spliced through the middle of a word - "that werem A m B
    # merged", "For the weightedalphaA=..." - put one formula inside the sentence that names a
    # DIFFERENT one, so a drafter binds the wrong coefficients to the right term. Repaired first,
    # before the formula repair below, so that pass reads prose that has not been interleaved.
    # The equations are not lost: they exist elsewhere as their own display rows, where they are
    # attached to nothing and cannot mislead.
    _splice_repairs = build_spliced_math_repairs(corpus)
    corpus, _n_splice = apply_spliced_math_repairs(corpus, _splice_repairs)
    print('spliced-math rows repaired from a clean twin: %d distinct renderings, %d rows'
          % (len(_splice_repairs), _n_splice), flush=True)

    _twin_index = build_intact_twin_index(corpus)
    _formula_repairs = build_damaged_formula_repairs(corpus, _twin_index)
    corpus, _n_repaired = apply_damaged_formula_repairs(corpus, _formula_repairs)
    print('damaged formulas repaired from an intact twin: %d distinct renderings, %d rows'
          % (len(_formula_repairs), _n_repaired), flush=True)
    index = BM25Index([r.get('sentence_text') or '' for r in corpus])
    blocks = build_corpus_block_index(corpus)
    successors = build_block_successor_index(corpus)
    long_sentences = build_document_long_sentences(corpus)
    all_sentences = build_document_all_sentences(corpus)
    # A display fraction's numerator, severed from its denominator by the extractor,
    # parses as a complete equation but states something FALSE. The damage checks cannot
    # see it - the row is well formed - so it is identified from its neighbour here and
    # dropped rather than repaired: guessing where the bar belonged would fabricate
    # mathematics, while dropping leaves the drafter to report the formula missing.
    stranded_numerators = build_stranded_numerator_texts(corpus)
    # Where a math-aware extraction layer carries the SAME equation intact on the same
    # page, use that rendering instead of dropping the severed one. Nothing is invented:
    # the correct text is already in the corpus, and the match requires both the same
    # left-hand side and the severed numerator to appear inside the replacement.
    extractor_agreement = {}
    intact_substitutions = build_intact_formula_substitutions(
        corpus, stranded_numerators, agreement_out=extractor_agreement)
    print('stranded numerators: %d (intact cross-layer replacements: %d)'
          % (len(stranded_numerators), len(intact_substitutions)), flush=True)
    heading_rows = collections.defaultdict(list)
    equation_rows = []
    formula_row_indices = set()
    for idx, row in enumerate(corpus):
        heading = str(row.get('patch_heading') or '').strip()
        if heading:
            heading_rows[heading].append(idx)
        equation_text = str(row.get('sentence_text') or '').strip()
        if row.get('is_formula_like') or '=' in equation_text:
            equation_rows.append((idx, equation_text))
        if row.get('is_formula_like'):
            formula_row_indices.add(idx)
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
    # Curriculum-derived branch context for compound-sibling ownership: each unit's own
    # ancestry words. compound_sibling_formula_owner subtracts the base unit's branch from
    # the compound sibling's, so only genuinely discriminating ancestry can move a passage.
    # Replaces a hardcoded subject word list that could never fire outside one curriculum.
    unit_branch_terms = {}
    _ambiguous_branch_names = set()
    for p in profiles:
        labels = list(p.get('topic_path_labels') or [])
        parent = str(p.get('parent_topic_label') or '')
        if parent:
            labels.append(parent)
        terms = set()
        for label in labels:
            terms |= _name_content_words(str(label))
        key = str(p.get('canonical_name') or '')
        if key in unit_branch_terms and unit_branch_terms[key] != terms:
            # The same name denotes two different branches, so it has no well-defined branch.
            # Giving it neither (rather than whichever was built last) keeps compound ownership
            # falling back to the compound's own qualifier words - the conservative direction.
            _ambiguous_branch_names.add(key)
            unit_branch_terms[key] = set()
        elif key not in _ambiguous_branch_names:
            unit_branch_terms[key] = terms
    if _ambiguous_branch_names:
        print('ambiguous canonical names (branch context withheld): %s'
              % sorted(_ambiguous_branch_names), flush=True)
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
        unit_equation_patterns = (defining_equation_patterns(unit_label_list)
                                  + compound_index_equation_patterns(unit_label_list))

        # Let the corpus decide which query formulation this unit is best expressed by, instead
        # of a hand-written rule about when ancestor context or acronym expansion helps (neither
        # answer is right in general - measured both ways on real units this session). Each
        # candidate form gets the SAME full retrieval it would actually receive, and the winner's
        # work is what we keep, so nothing is decided on a sample the decision does not apply to.
        q_forms = retrieval_query_forms(prof)
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
            # Exact unit-bearing headings can restore short numbered steps whose sentence text
            # omits the algorithm name. Word-overlap headings are deliberately insufficient: the
            # overlay has confirmed wrong headings, including null-distribution text attached to
            # distance properties. The same exact-label predicate licenses scoring below.
            heading_added = 0
            for heading, row_indices in heading_rows.items():
                if not heading_exactly_names_unit(heading, [form]):
                    continue
                for i in row_indices:
                    if i not in f_idx:
                        f_pool.append((i, 0.0))
                        f_idx.add(i)
                        heading_added += 1
                        if heading_added >= 100:
                            break
                if heading_added >= 100:
                    break
            # BM25 can exclude a short defining equation when a source-specific query contains
            # several prose terms. Exact unit-LHS matching is deterministic and narrow; rows
            # added here still pass the normal reranker, math, ownership, and final gates.
            supplement_defining_equation_rows(
                f_pool, f_idx, equation_rows, unit_equation_patterns, limit=100)
            # The above only rescues equations whose LHS names the unit. Most defining formulas are
            # written in notation instead, so this makes formula-shaped rows visible to the same
            # relevance gate regardless of what their left-hand side is called.
            supplement_dense_formula_rows(
                f_pool, f_idx, dense, form, formula_row_indices, limit=40)
            context_labels = unit_label_list + [form]
            f_hits = [{'sentence': corpus[i], 'bm25_score': s} for i, s in f_pool]
            if f_hits:
                f_scores = rr.score(form, [str(h['sentence'].get('sentence_text') or '') for h in f_hits])
                standalone = [sigmoid(sc) for sc in f_scores]
                context_records = [{
                    'text': str(h['sentence'].get('sentence_text') or ''),
                    'context': str(h['sentence'].get('source_block_text')
                                   or h['sentence'].get('sentence_text') or ''),
                    'heading': str(h['sentence'].get('patch_heading') or ''),
                } for h in f_hits]
                context_results = score_context_records(
                    rr, form, context_records, context_labels, standalone)
                for h, base, (sc, mode) in zip(f_hits, standalone, context_results):
                    h['rerank_prob_standalone'] = base
                    h['rerank_prob'] = sc
                    if mode != 'standalone' and sc >= CONTEXT_RELEVANCE_FLOOR:
                        h['context_score_mode'] = mode
                f_hits.sort(key=lambda h: -h['rerank_prob'])
            f_passages = assemble_passages(
                f_hits, blocks, max_passages=a.max_passages, max_chars=a.max_chars,
                min_relevance=a.min_relevance,
                verify_scorer=(lambda texts, _q=form: [sigmoid(s) for s in rr.score(_q, texts)]),
                context_scorer=(lambda records, _q=form, _labels=context_labels: [
                    score for score, _mode in score_context_records(rr, _q, records, _labels)]),
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
        qtext, passages = chosen['form'], chosen['passages']

        # A passage can be about the right words and the wrong unit. Where another unit of this
        # same library claims it decisively, it is that unit's evidence, not this one's - the
        # failure behind eight of the eighteen wrongly-"grounded" drafts in the reviewed run.
        rivals = find_rival_units(name, all_unit_names)
        # Candidate-level math checks run before block assembly. Assembly can concatenate two
        # individually admissible fragments into a damaged formula, so enforce the same contract
        # again on the exact text that will reach drafting.
        passages, math_drops = drop_damaged_math_passages(passages)
        passages, _stranded_drops = drop_stranded_numerator_passages(
            passages, stranded_numerators, intact_substitutions, extractor_agreement)
        math_drops.extend(_stranded_drops)
        passages, compound_drops = drop_compound_sibling_formulas(
            passages, name, rivals, all_unit_names, unit_branch_terms)
        passages, semantic_drops = drop_semantically_misbound_passages(
            passages, name, rivals)
        passages, rival_drops = drop_passages_claimed_by_rivals(
            passages, name, rivals,
            (lambda q, texts: [sigmoid(s) for s in rr.score(q, texts)]))
        rival_drops = math_drops + compound_drops + semantic_drops + rival_drops
        q_scores = {x['form']: x['max_rel'] for x in attempts}
        q_counts = {x['form']: x['n'] for x in attempts}
        q_shapes = {x['form']: x['core_shapes'] for x in attempts}
        # Definitions and formulas lead; interrogative material sinks to the end. Stable, so the
        # relevance-then-document-order arrangement inside each tier is preserved.
        passages = order_by_definitional_authority(passages)
        cov = coverage_summary(passages)
        support_state, support_reason = assess_support_state(passages, unit_label_list + [qtext])
        no_support = support_state == 'insufficient_support'
        weak_support = support_state == 'weak_fallback'
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
                'registry_disambiguation_applied': bool(
                    prof.get('retrieval_disambiguation_terms')),
            },
            'drafting_instruction': DRAFTING_INSTRUCTION,
            'insufficient_synthesis_support': no_support,
            'abstention_expected': no_support,
            'insufficient_support_reasons': ([support_reason]
                                             if no_support or weak_support else []),
            'packet_support_state': support_state,
            'support_state_reason': support_reason,
            'weak_fallback_abstention_allowed': weak_support,
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
