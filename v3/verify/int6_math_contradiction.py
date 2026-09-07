"""INT-6: narrow formula-vs-prose internal contradiction check. Flag-only.

Canonical diagnostic (from the authorization): prose claims coefficients are "independent of
cluster sizes"; the cited formula is alpha_A = m_A / (m_A + m_B), which is a function of m_A, m_B.

DELIBERATELY NARROW: does not attempt general mathematical theorem proving, does not import
external mathematical knowledge, does not use an LLM. The connection between an English phrase
("cluster sizes") and a formula symbol (m_A) is made using ONLY text the draft's own cited
evidence already contains: source material conventionally states a formula and its symbol
definitions together ("where m_A and m_B are the number of points in clusters A and B
respectively"), and this project's math-handling work has already established that adjacency is
real and extractable (see the frozen architecture's own formula/lead-in handling). This script
extracts symbol -> definition-text mappings from the draft's OWN cited evidence and checks
overlap against the draft's OWN prose claims - nothing outside what the draft already cites.

Checks implemented (2 of the 5 candidate classes named in the authorization - the other three
would need either numeric range evaluation of a formula's possible values, which risks becoming
exactly the "general theorem proving" this must avoid, or cross-claim variable-redefinition
tracking with too high a false-positive risk to implement safely in this narrow pass):

  1. INDEPENDENCE_CONTRADICTED_BY_FORMULA_SYMBOL: prose claims independence/invariance with
     respect to some described quantity X; a formula cited elsewhere in the SAME draft contains a
     symbol whose OWN cited symbol-definition shares a content word with X.
  2. CONSTANT_CLAIM_CONTRADICTED_BY_VARYING_SYMBOL: prose claims a quantity is "constant" or
     "fixed"; the SAME claim's own cited formula visibly contains a subscripted/varying symbol
     (not a bare numeral) on its right-hand side.

Output: flag-only, additive sidecar. Never rewrites the equation, never rewrites the prose, never
infers which variant is correct - the expert decides.
"""
import argparse
import json
import re
import sys

INDEPENDENCE_RE = re.compile(
    r"\b(?:independent of|regardless of|does not depend on|do not depend on|"
    r"invariant (?:to|of|under)|irrespective of)\s+((?:the\s+)?[a-z][a-z\s\-]{2,50})",
    re.IGNORECASE)
CONSTANT_RE = re.compile(
    r"\b(?:are|is)\s+(?:a\s+)?constants?\b|\bfixed\s+(?:value|values|constant)\b", re.IGNORECASE)

# "where m_A and m_B are the number of points..." / "m_A is the number of points..."
SYMBOL_DEF_RE = re.compile(
    r"\b([a-zA-Z](?:_\{?[A-Za-z0-9]+\}?)?)\s+(?:is|are|denotes?|represents?)\s+"
    r"(?:the\s+)?([a-z][a-z0-9\s\-]{4,80})", re.IGNORECASE)
# subscripted or Greek-letter symbols appearing in formula text - varying quantities, not bare
# numerals or single unsubscripted letters that are more likely generic constants (k, c alone).
# Real drafted text uses BOTH conventions for the same corpus: underscore ("m_A") in some
# extractor output and bare concatenation ("mA") in model-generated prose - confirmed by reading
# the real qwen38 Group Average Linkage draft, which uses "mA", not "m_A". Both are matched.
VARYING_SYMBOL_RE = re.compile(
    r"\b[a-zA-Zα-ω](?:_\{?[A-Za-z0-9]+\}?|[A-Z])\b")

STOPWORDS = frozenset("""
a an the of to in for on with and or is are was were be been being this that these those it its
as at by from not no if then than which who whom whose what when where how we you they he she
number value values
""".split())


def content_words(text):
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in STOPWORDS}


def _singular_forms(word):
    """A word and its naive singular form, so 'clusters' overlaps 'cluster'. Deterministic
    suffix-stripping only - no external vocabulary, same class of normalisation this project
    already uses elsewhere (e.g. _split_terms for hyphenated compounds)."""
    forms = {word}
    if word.endswith("ies") and len(word) > 4:
        forms.add(word[:-3] + "y")
    elif word.endswith("es") and len(word) > 4:
        forms.add(word[:-2])
    elif word.endswith("s") and len(word) > 3:
        forms.add(word[:-1])
    return forms


def words_overlap(a, b):
    """Content-word overlap tolerant of simple singular/plural variance in either direction."""
    a_expanded = {f for w in a for f in _singular_forms(w)}
    b_expanded = {f for w in b for f in _singular_forms(w)}
    return a_expanded & b_expanded


def extract_symbol_definitions(evidence_texts):
    """symbol -> set of content words from its own cited definition, across all evidence text."""
    out = {}
    for text in evidence_texts:
        for m in SYMBOL_DEF_RE.finditer(text):
            symbol, definition = m.group(1), m.group(2)
            words = content_words(definition)
            if words:
                out.setdefault(symbol, set()).update(words)
    return out


def formula_symbols(text):
    return set(VARYING_SYMBOL_RE.findall(text))


def check_independence(prose_claims, formula_claims, symbol_defs, formula_evidence_texts=None):
    """Checks two shapes: an independence claim in SEPARATE prose text vs. a cited formula's
    symbols, AND a formula-role claim whose OWN text states both the formula and the independence
    claim together in one sentence - confirmed the dominant real shape by inspecting real drafts
    (e.g. "...coefficients aA=mA/(mA+mB)... which are constants independent of cluster size" is
    ONE formula-role claim, not a separate prose claim citing a formula claim).

    Two signals are tried, strict first: (1) a cleanly-parsed "symbol IS/ARE definition" sentence
    (highest confidence, names the exact symbol) and (2) if that fails, whether the claimed-
    independent-of term appears anywhere in the SAME formula claim's own cited evidence text.
    Signal (2) exists because real corpus extraction is frequently too garbled for a clean
    grammatical parse to succeed (confirmed on the real Group Average Linkage evidence itself: a
    scrambled table extraction reading "...that werem A m B merged..." has no parseable "X is Y"
    sentence, yet plainly states the formula's coefficients are about the clusters' sizes) - still
    fully deterministic and still confined to text the draft itself already cites, no external
    knowledge, just a weaker/broader match than signal (1)."""
    formula_evidence_texts = formula_evidence_texts or {}
    warnings = []
    # self-contained: the formula claim's own text carries both the equation and the assertion
    for fc in formula_claims:
        for m in INDEPENDENCE_RE.finditer(fc["text"]):
            claimed_independent_of = content_words(m.group(1))
            if not claimed_independent_of:
                continue
            fired = False
            for sym in formula_symbols(fc["text"]):
                def_words = symbol_defs.get(sym)
                overlap = words_overlap(def_words, claimed_independent_of) if def_words else set()
                if overlap:
                    fired = True
                    warnings.append({
                        "warning_type": "INDEPENDENCE_CONTRADICTED_BY_FORMULA_SYMBOL",
                        "confidence": "high",
                        "involved_claim_ids": [fc["claim_id"]],
                        "involved_formula": fc["text"][:200],
                        "explanation": (
                            "This claim's own text states both a formula and an independence "
                            "assertion about it. The formula contains symbol '%s', whose own "
                            "cited definition ('%s') shares the term '%s' with what the claim "
                            "says the result is independent of ('%s')."
                            % (sym, ", ".join(sorted(def_words))[:80],
                              sorted(overlap)[0],
                              m.group(1).strip())),
                        "prose_text": fc["text"][:200],
                    })
            if fired:
                continue
            # signal 2: broader fallback over the same claim's own cited evidence text
            ev_words = set()
            for ev in formula_evidence_texts.get(fc["claim_id"]) or []:
                ev_words |= content_words(ev)
            overlap = words_overlap(ev_words, claimed_independent_of)
            if overlap:
                warnings.append({
                    "warning_type": "INDEPENDENCE_CONTRADICTED_BY_FORMULA_SYMBOL",
                    "confidence": "low",
                    "involved_claim_ids": [fc["claim_id"]],
                    "involved_formula": fc["text"][:200],
                    "explanation": (
                        "This claim's own text states both a formula and an independence "
                        "assertion, but the SAME claim's own cited evidence text mentions '%s' - "
                        "the term the claim says the result is independent of. (Weaker signal: "
                        "no clean per-symbol definition could be parsed from the cited evidence, "
                        "which is itself a known real extraction-quality issue on this corpus - "
                        "the overlap is against the evidence's full text, not a specific symbol.)"
                        % sorted(overlap)[0]),
                    "prose_text": fc["text"][:200],
                })
    for pc in prose_claims:
        for m in INDEPENDENCE_RE.finditer(pc["text"]):
            claimed_independent_of = content_words(m.group(1))
            if not claimed_independent_of:
                continue
            for fc in formula_claims:
                syms = formula_symbols(fc["text"])
                for sym in syms:
                    def_words = symbol_defs.get(sym)
                    overlap = words_overlap(def_words, claimed_independent_of) if def_words else set()
                    if overlap:
                        warnings.append({
                            "warning_type": "INDEPENDENCE_CONTRADICTED_BY_FORMULA_SYMBOL",
                            "involved_claim_ids": [pc["claim_id"], fc["claim_id"]],
                            "involved_formula": fc["text"][:200],
                            "explanation": (
                                "Prose claims independence from '%s', but the cited formula "
                                "contains symbol '%s', whose own cited definition ('%s') shares "
                                "the term '%s' - the formula's own evidence defines this symbol "
                                "in terms of the quantity the prose claims independence from."
                                % (m.group(1).strip(), sym,
                                  ", ".join(sorted(def_words))[:80],
                                  sorted(overlap)[0])),
                            "prose_text": pc["text"][:200],
                        })
    return warnings


def check_constant(prose_claims, formula_claims):
    warnings = []
    # self-contained: same real-shape fix as check_independence above
    for fc in formula_claims:
        if not CONSTANT_RE.search(fc["text"]):
            continue
        syms = formula_symbols(fc["text"])
        if syms:
            warnings.append({
                "warning_type": "CONSTANT_CLAIM_CONTRADICTED_BY_VARYING_SYMBOL",
                "confidence": "low",
                "involved_claim_ids": [fc["claim_id"]],
                "involved_formula": fc["text"][:200],
                "explanation": (
                    "This claim's own text states a formula AND calls it constant/fixed, but "
                    "the formula visibly contains symbol(s) %s that are not bare numerals."
                    % sorted(syms)),
                "prose_text": fc["text"][:200],
            })
    for pc in prose_claims:
        if not CONSTANT_RE.search(pc["text"]):
            continue
        cited = {eid for eid in pc.get("evidence_ids") or []}
        for fc in formula_claims:
            if not (cited & set(fc.get("evidence_ids") or [])):
                continue  # only compare a claim against a formula it ITSELF cites
            syms = formula_symbols(fc["text"])
            if syms:
                warnings.append({
                    "warning_type": "CONSTANT_CLAIM_CONTRADICTED_BY_VARYING_SYMBOL",
                    "confidence": "low",
                    "involved_claim_ids": [pc["claim_id"], fc["claim_id"]],
                    "involved_formula": fc["text"][:200],
                    "explanation": (
                        "Prose claims a constant/fixed value, but its own cited formula visibly "
                        "contains symbol(s) %s that are not bare numerals - a formula containing "
                        "a symbol is a function of that symbol unless stated otherwise."
                        % sorted(syms)),
                    "prose_text": pc["text"][:200],
                })
    return warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drafts-jsonl", required=True)
    ap.add_argument("--packets-jsonl", required=True)
    ap.add_argument("--out-jsonl", required=True)
    a = ap.parse_args()

    packets = {}
    for line in open(a.packets_jsonl, encoding="utf-8"):
        if not line.strip():
            continue
        p = json.loads(line)
        packets[p.get("knowledge_unit_id")] = {
            e.get("evidence_id"): e.get("text")
            for e in (p.get("evidence_for_synthesis") or []) if e.get("evidence_id")
        }

    n_units = n_flags = 0
    out_f = open(a.out_jsonl, "w", encoding="utf-8")
    for line in open(a.drafts_jsonl, encoding="utf-8"):
        if not line.strip():
            continue
        row = json.loads(line)
        draft = row.get("draft")
        if not isinstance(draft, dict):
            continue
        uid = draft.get("knowledge_unit_id") or row.get("knowledge_unit_id")
        ev_lookup = packets.get(uid) or {}
        ck = draft.get("contextual_kc_draft") or draft.get("contextual_topic_draft") or {}
        if str(ck.get("status") or "").lower() == "abstained":
            continue
        n_units += 1

        prose_claims, formula_claims = [], []
        for idx, entry in enumerate(draft.get("evidence_map") or []):
            if not isinstance(entry, dict) or not entry.get("claim"):
                continue
            claim_id = "%s:claim:%04d" % (uid, idx)
            eids = entry.get("supporting_evidence_ids") or []
            rec = {"claim_id": claim_id, "text": entry["claim"], "evidence_ids": eids}
            if entry.get("support_role") == "formula":
                formula_claims.append(rec)
            else:
                prose_claims.append(rec)

        evidence_texts = [ev_lookup[eid] for fc in formula_claims for eid in fc["evidence_ids"]
                         if eid in ev_lookup]
        symbol_defs = extract_symbol_definitions(evidence_texts)
        formula_evidence_texts = {
            fc["claim_id"]: [ev_lookup[eid] for eid in fc["evidence_ids"] if eid in ev_lookup]
            for fc in formula_claims
        }

        warnings = (check_independence(prose_claims, formula_claims, symbol_defs,
                                       formula_evidence_texts)
                   + check_constant(prose_claims, formula_claims))
        for w in warnings:
            n_flags += 1
            out_f.write(json.dumps({
                "knowledge_unit_id": uid,
                "math_consistency_warning": True,
                **w,
                "source_evidence_references": list({
                    eid for fc in formula_claims for eid in fc["evidence_ids"]}),
            }, ensure_ascii=False) + "\n")
    out_f.close()

    print("=" * 74)
    print("INT-6 MATH CONSISTENCY CHECK (flag-only, review metadata only)")
    print("  units processed  : %d" % n_units)
    print("  warnings raised  : %d" % n_flags)
    print("  output (sidecar) : %s" % a.out_jsonl)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
