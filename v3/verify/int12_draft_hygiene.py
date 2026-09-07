"""INT-12: draft hygiene checks. Flag-only, additive sidecar, never rewrites a draft.

Five checks over the drafted TEXT, motivated by defects found by reading all 159 drafts against
source. They share one module because they share one input, one output contract and one traversal;
splitting them into five scripts would duplicate that boilerplate five times without separating
any concern.

None of them uses subject-matter vocabulary, a unit name, a document name or a corpus path. Each
states a property of the text and its own ledger, so it transfers to any corpus:

  A SOURCE_META_COMMENTARY_IN_BODY
      The unit narrates the condition of its evidence instead of describing its subject
      ("The source rendering of the formula is incomplete"). That belongs in uncertainty_notes,
      where it usually already appears. Downstream consumers read the body, not the notes.

  B BODY_SENTENCE_NOT_COVERED_BY_LEDGER
      STEP 3 of the drafting instruction fills evidence_map first and STEP 4 says to write using
      only claims that appear in it. Nothing enforces the second, and INT-2 verifies entailment
      per LEDGER ENTRY - so a body sentence that never entered the ledger is invisible to it.
      This check exists to bound that blind spot, not to second-guess the drafter's prose.

  C SELF_REFERENTIAL_OR_DUPLICATED_SENTENCE
      A sentence that defines a term by restating it, or that repeats another sentence of the
      same draft. Both are degenerate generation rather than content.

  D UNRENDERED_MARKUP_IN_BODY
      Extraction markup that reached the drafted text ("{ \\frac { 1 } { \\sqrt { 2 \\pi } }").
      The formula may be correct; the rendering is not something a reader can use, and the same
      formula is rendered readably in other units, so this is an inconsistency, not a style note.

  E STATED_ARITHMETIC_EVALUATED
      Where the body states a closed numeric arithmetic expression, its value is computed and
      reported. No bound is assumed and no subject knowledge is used: the reviewer is simply shown
      what the drafted expression evaluates to, which is how "0.3 + 2 * 5" was found being
      presented as an error estimate.
"""
import argparse
import ast
import collections
import json
import operator
import pathlib
import re
import sys

# Repo-relative, never a hardcoded absolute path to one checkout: an absolute entry at position 0
# overrides PYTHONPATH and silently imports another tree's package, which invalidated an A/B in
# this project before it was caught.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

# The meta-commentary rule and the sentence splitter live in the package, not here: the
# drafting runner needs the SAME answer when deciding whether a repaired draft may be
# accepted, and a rule copied into a second caller is how INT-13's dead repairs happened.
from kc_l.kc_drafting.draft_hygiene import (  # noqa: E402
    find_source_meta_commentary, split_sentences,
)

# --------------------------------------------------------------------------------------- shared

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]+")

STOPWORDS = frozenset("""
a an the of to in for on with and or is are was were be been being this that these those it its
as at by from not no if then when where which who whom whose what how we you they he she them
his her their our your can could may might must shall should will would do does did done have
has had having also more most other some such only own same so than too very just about into
over under between both each any all one two three first second next last other another however
therefore thus hence because while during before after above below up down out off again further
""".split())


def content_words(text):
    """Lowercased non-stopword tokens: the comparable substance of a sentence."""
    return {w.lower() for w in _WORD_RE.findall(str(text or ""))
            if w.lower() not in STOPWORDS}


# --------------------------------------------------------- B: body sentences outside the ledger

# A body sentence counts as accounted for when a MAJORITY of its content words appear somewhere in
# the ledger. The ledger as a whole is the support set, so coverage is measured against the union
# of its claims rather than against the best single claim: a body sentence routinely combines two
# claims, and scoring it against one of them flagged 404 sentences across 125 of 159 units - a
# volume no reviewer can act on, and mostly composition rather than unsupported content.
LEDGER_COVERAGE_FLOOR = 0.5
# Very short sentences carry too few content words for an overlap ratio to mean anything.
MIN_CONTENT_WORDS_FOR_COVERAGE = 4


def ledger_coverage(sentence, ledger_words):
    """The fraction of a sentence's content words that appear anywhere in the ledger."""
    words = content_words(sentence)
    if not words:
        return 1.0, set()
    missing = words - ledger_words
    return (len(words) - len(missing)) / len(words), missing


def find_uncovered_body_sentences(sentences, claims):
    ledger_words = set()
    for claim in claims:
        ledger_words |= content_words(claim)
    findings = []
    for s in sentences:
        if len(content_words(s)) < MIN_CONTENT_WORDS_FOR_COVERAGE:
            continue
        coverage, missing = ledger_coverage(s, ledger_words)
        if coverage >= LEDGER_COVERAGE_FLOOR:
            continue
        findings.append({
            "check": "BODY_SENTENCE_NOT_COVERED_BY_LEDGER", "sentence": s,
            "ledger_coverage": round(coverage, 3),
            "words_absent_from_ledger": sorted(missing)[:20],
            "why": "most of this sentence's content words appear nowhere in evidence_map, so "
                   "INT-2's per-claim entailment check never sees what it asserts"})
    return findings


# --------------------------------------------------- C: self-referential or duplicated sentences

# The unit must be the DIRECT OBJECT of a verb that produces or defines it. Merely appearing
# twice around any copula is ordinary prose: "Accuracy is an estimate ... not the exact true
# accuracy" and "Precision is related to FDR ... precision = 1 - FDR" are both fine, and both
# were flagged when the test was "two mentions with a definitional verb somewhere between them".
# Circularity is the narrower shape "... is used to CONSTRUCT the confusion matrix".
_CIRCULAR_OBJECT_VERBS = (r"construct|build|create|produce|define|compute|calculate|form|"
                          r"generate|make|derive|obtain|determine")


def find_self_referential_sentences(sentences, unit_name):
    """A sentence that explains a term by naming that same term as what it produces or defines."""
    findings = []
    name = str(unit_name or "").strip()
    if not name:
        return findings
    circular = re.compile(
        r"\b" + re.escape(name) + r"\b.{0,200}?\b(?:" + _CIRCULAR_OBJECT_VERBS + r")s?\b\s+"
        r"(?:the\s+|a\s+|an\s+)?" + re.escape(name) + r"\b",
        re.IGNORECASE | re.DOTALL)
    for s in sentences:
        match = circular.search(s)
        if match:
            findings.append({
                "check": "SELF_REFERENTIAL_SENTENCE", "sentence": s,
                "matched": match.group(0)[:160],
                "why": "the unit is named as the object of a verb that produces or defines it, "
                       "in a sentence that already had the unit as its subject"})
    return findings


def find_duplicated_sentences(sentences):
    seen = collections.defaultdict(list)
    for s in sentences:
        words = content_words(s)
        if len(words) >= MIN_CONTENT_WORDS_FOR_COVERAGE:
            seen[frozenset(words)].append(s)
    return [{"check": "DUPLICATED_SENTENCE", "sentence": group[0],
             "occurrences": len(group), "variants": group[1:],
             "why": "two sentences of the same draft carry the same content words"}
            for group in seen.values() if len(group) > 1]


# ----------------------------------------------------------------- D: unrendered markup in body

_MARKUP_RE = re.compile(r"\\(?:frac|sqrt|mathsf|mathrm|operatorname|widehat|left|right|sum|prod)\b"
                        r"|\$\$|\\\[|\\\]")


def find_unrendered_markup(sentences):
    return [{"check": "UNRENDERED_MARKUP_IN_BODY", "sentence": s,
             "markup": sorted(set(_MARKUP_RE.findall(s))),
             "why": "extraction markup reached the drafted text; the same formula is rendered "
                    "readably in other units, so this is an inconsistency rather than a style note"}
            for s in sentences if _MARKUP_RE.search(s)]


# ------------------------------------------------------------------ E: stated arithmetic, valued

# The trailing guard rejects only a following DIGIT, so that a number is never cut in half. An
# earlier version also rejected a following ".", which made a sentence-final period block the full
# match: "0.3 + 2 * 5." backtracked to "0.3 + 2" and reported 2.3 for an expression worth 10.3.
# A check that shows a reviewer the wrong value is worse than no check, so the guard is as narrow
# as the thing it protects.
_ARITH_RE = re.compile(r"(?<![\w.])((?:\d+(?:\.\d+)?)(?:\s*[-+*/x×·]\s*(?:\d+(?:\.\d+)?)){1,8})"
                       r"(?!\d)")
_SAFE_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub,
                ast.Mult: operator.mul, ast.Div: operator.truediv}


def evaluate_arithmetic(expression):
    """The value of a closed numeric expression, or None when it is not one.

    Parsed and walked rather than eval()'d: the input is model-generated text, and an evaluator
    that accepts anything beyond arithmetic on literals is an arbitrary-code path.
    """
    normalised = expression.replace("×", "*").replace("·", "*").replace("x", "*")
    try:
        tree = ast.parse(normalised, mode="eval")
    except SyntaxError:
        return None

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = walk(node.operand)
            return None if value is None else (value if isinstance(node.op, ast.UAdd) else -value)
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
            left, right = walk(node.left), walk(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Div) and right == 0:
                return None
            return _SAFE_BINOPS[type(node.op)](left, right)
        return None

    try:
        return walk(tree)
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None


def find_stated_arithmetic(sentences):
    findings = []
    for s in sentences:
        for match in _ARITH_RE.finditer(s):
            value = evaluate_arithmetic(match.group(1))
            if value is None:
                continue
            findings.append({
                "check": "STATED_ARITHMETIC_EVALUATED", "sentence": s,
                "expression": match.group(1).strip(), "value": round(float(value), 6),
                "why": "the drafted text states this arithmetic; its value is reported so a "
                       "reviewer can see whether the result is possible for the quantity named"})
    return findings


# ------------------------------------------------------------------------------------- traversal

def draft_body_and_claims(draft):
    contextual = (draft.get("contextual_kc_draft")
                  or draft.get("contextual_topic_draft") or {})
    body = str(contextual.get("text") or "")
    claims = [str(e.get("claim") or "") for e in (draft.get("evidence_map") or [])
              if isinstance(e, dict) and e.get("claim")]
    return body, claims


# F  DEFINITIONAL_SUBJECT_IS_NOT_THE_UNIT
#     The draft opens by defining something adjacent to the unit rather than the unit. The clearest
#     instance found by an external review of r3 is Mutually Exclusive Classes, whose draft says
#     "a rule set is defined as mutually exclusive if no two rules ... are triggered by the same
#     instance" - true, well-evidenced, and about rule sets. Faithfulness to the evidence and
#     relevance to the unit are different properties, and only the first is checked anywhere else.
#
#     The subject of the sentence is compared with the unit's own name, both reduced to prefix-
#     stemmed content words. A fixed-length prefix is used rather than suffix stripping because a
#     suffix list gets "Redundancy"/"Redundant" and "duplicates"/"Duplicate" wrong in opposite
#     directions; six characters needs no list and no linguistics. Measured over the 159 r3
#     drafts: 5 flagged, of which 4 are defensible on reading and 1 is borderline.
_DEFINITIONAL_SUBJECT_RE = re.compile(
    r"^\s*(?:In [^,]{3,40},\s*)?(?:(?:A|An|The|These|This|Those|Some)\s+)?"
    r"(?P<subject>[A-Za-z][A-Za-z0-9 \-()'/]{2,60}?)"
    r"\s+(?:is|are)\s+(?:defined\s+as|a\b|an\b|the\b|used\s+to|classified\s+as)",
    re.IGNORECASE)
_TERM_PREFIX = 6
_TERM_STOPWORDS = frozenset("""
a an and or the of for in on to with by from as at is are its it this that these those be
one two three any each such other same more most than then there here which who what when where
""".split())


def term_words(text):
    """Prefix-stemmed content words of a term.

    No hyphen handling is needed and none is done: the word pattern excludes '-' and '/', so
    "Density-Reachable" already yields two words. An earlier version substituted them for spaces
    first; sabotage showed removing that line changed nothing, which is how it was found to be
    dead. The reason "Density-reachability" once failed to match "Density-Reachable" was the
    suffix-list stemmer, not the hyphen.
    """
    return {w[:_TERM_PREFIX] for w in
            re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", str(text or "").lower())
            if w not in _TERM_STOPWORDS}


def find_unbound_definitional_subject(sentences, unit_name):
    """The unit's opening definition, when its subject shares no term with the unit's name."""
    name_words = term_words(unit_name)
    if not name_words:
        return []
    for sentence in sentences[:3]:
        match = _DEFINITIONAL_SUBJECT_RE.match(sentence)
        if not match:
            continue
        subject = match.group("subject").strip()
        subject_words = term_words(subject)
        if not subject_words or (subject_words & name_words):
            return []
        return [{
            "check": "DEFINITIONAL_SUBJECT_IS_NOT_THE_UNIT",
            "sentence": sentence,
            "defined_subject": subject,
            "unit_name": unit_name,
            "why": "the draft's definitional sentence defines this subject, which shares no term "
                   "with the unit's name; evidence can be faithfully used and still describe a "
                   "neighbouring concept rather than this one",
        }]
    return []


def hygiene_findings(unit_name, body, claims):
    sentences = split_sentences(body)
    return (find_source_meta_commentary(sentences)
            + find_uncovered_body_sentences(sentences, claims)
            + find_self_referential_sentences(sentences, unit_name)
            + find_duplicated_sentences(sentences)
            + find_unrendered_markup(sentences)
            + find_stated_arithmetic(sentences)
            + find_unbound_definitional_subject(sentences, unit_name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--drafts-jsonl", required=True)
    ap.add_argument("--out-jsonl", required=True)
    a = ap.parse_args()

    n_units, counts = 0, collections.Counter()
    with open(a.out_jsonl, "w", encoding="utf-8") as out_f:
        for line in open(a.drafts_jsonl, encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            draft = row.get("draft")
            if not isinstance(draft, dict):
                continue
            n_units += 1
            name = row.get("canonical_name") or ""
            body, claims = draft_body_and_claims(draft)
            if not body.strip():
                continue
            for finding in hygiene_findings(name, body, claims):
                counts[finding["check"]] += 1
                out_f.write(json.dumps({
                    "knowledge_unit_id": row.get("knowledge_unit_id"),
                    "canonical_name": name,
                    "draft_hygiene_finding": True,
                    **finding,
                }, ensure_ascii=False) + "\n")

    print("=" * 78)
    print("INT-12 DRAFT HYGIENE (flag-only, review metadata only)")
    print("  units processed : %d" % n_units)
    for check, n in counts.most_common():
        print("  %-40s %4d" % (check, n))
    print("  output (sidecar): %s" % a.out_jsonl)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
