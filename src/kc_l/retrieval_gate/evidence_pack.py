"""Comprehensive evidence assembly: everything the corpus says about a unit.

WHY THIS REPLACES THE EXISTING PACK PATH
----------------------------------------
The shipped Step 5x pack path is built to EXCLUDE. It caps a pack at 8 items and 1800 characters,
allows at most 2 definition_kernel / 3 explanatory_gloss / 2 formula_notation / 2
example_or_procedure items, and gates every candidate through a stack that asks "is this a
definition of the unit?" - role eligibility, lexical target binding, shapeaware bucketing,
definition_subject_mismatch. Measured consequences on ablation_01_v3: zero procedure evidence and
18 formula items library-wide, mean 3.22 items per unit, and a textbook-perfect definition
sentence (a textbook definition sentence) scoring 5.55 against a 6.0 definition_kernel threshold and being dropped with every role ineligible.

That architecture is correct for producing a one-line gloss. It cannot produce a complete account
of a topic - the algorithm, the procedure, the formula, the conditions, the motivation - because
it discards exactly the material that is not shaped like a definition sentence.

WHAT THIS DOES INSTEAD
----------------------
Relevance decides inclusion; shape decides nothing.

  1. RETRIEVE broadly - BM25 over the whole corpus, query from registry labels only.
  2. RANK by cross-encoder relevance. This is the only quality gate. On the confirmed failure
     cases it scores a correct definition passage 0.906, an unrelated-topic passage
     0.003, and a sibling-term passage 0.001 - discrimination the lexical stack never achieved.
  3. EXPAND each retained sentence to its containing source block, so the draft sees coherent
     passages rather than truncated fragments. (The segmenter splits mid-formula: a definition truncated mid-expression is a real corpus sentence.)
  4. MERGE blocks, dedupe, drop only genuine non-content (navigation boilerplate, author
     affiliations, bibliography lines) using flags the corpus already carries.
  5. ORDER by relevance, then restore document order within each source region so a procedure's
     steps arrive in sequence.
  6. EMIT with a budget sized for completeness, not for a gloss.

Shape flags travel with each passage so the drafting prompt can tell a definition from a
procedure from a formula - as information, never as an admission filter.

Domain agnosticity: queries use registry labels, BM25 is corpus-statistical, the reranker is a
general relevance model, and the junk filters key off structural corpus flags. No subject-matter
vocabulary anywhere.
"""
from __future__ import annotations

import collections
import functools
import hashlib
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Completeness budget. The legacy path allowed 8 items / 1800 chars.
DEFAULT_MAX_PASSAGES = 40
DEFAULT_MAX_CHARS = 14000
# 0.5 is the decision boundary of the reranker's sigmoid: below it the model is actively saying
# "not relevant". Admitting at 0.30 therefore let through content the model had judged against.
# Measured consequence: for a unit whose name the reranker cannot place, every passage - correct
# and contaminating alike - sat at a flat ~0.500, and a 0.30 floor admitted all forty of them.
DEFAULT_MIN_RELEVANCE = 0.55
# A unit's passages must also stand up against its OWN best hit. Where the reranker has no real
# opinion the top score is itself near the boundary, and this keeps such a unit sparse instead of
# padding it with forty arbitrary passages. Insufficiency then reflects genuinely weak support
# rather than a threshold accident.
DEFAULT_RELATIVE_FLOOR = 0.85
DEFAULT_BM25_POOL = 400

SHAPE_FLAGS = ("is_definition_like", "is_formula_like", "is_procedure_like",
               "is_example_like", "is_heading_like")

# Structural non-content the corpus already identifies.
JUNK_FLAGS = ("is_nav_boilerplate", "is_author_affiliation", "is_meta")

_REFERENCE_RE = re.compile(
    r"^\s*(\[\d+\]|\d+\.\s+[A-Z][a-z]+,\s|[A-Z][a-z]+,\s+[A-Z]\.\s)"
)
_PAGE_ARTIFACT_RE = re.compile(r"^\s*(page\s+\d+|\d+\s*$|chapter\s+\d+\s*$)", re.I)
# A bracket citation ANYWHERE in the sentence, not only at the start, is a reliable signal of
# survey/bibliography prose in this corpus's citation style - e.g. "An overview of decision tree
# induction algorithms can be found in the survey articles by Buntine [129], Moret [166]..." is
# not a citation LIST (would not match the start-anchored check above) but is clearly not
# definitional content about the unit itself. Confirmed against a real case: this was the
# passage retained for a KC whose packet otherwise had no substantive definitional content.
_INLINE_CITATION_RE = re.compile(r"\[\d{1,4}\]")

# Reference-list entries carry structural bibliographic markers and no subject content. Each
# pattern must co-occur with a 4-digit year (or be an unambiguous volume(issue):pages form) so
# ordinary prose containing a number range is not swept up with it. No domain vocabulary.
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_PAGES_RE = re.compile(r"\bp(?:p|ages)?\.?\s*\d+\s*[-\u2013]\s*\d+", re.I)
_VOLPAGE_RE = re.compile(r"\b\d+\s*\(\s*\d+\s*\)\s*:\s*\d+\s*[-\u2013]\s*\d+")
# The trailing \b after "proc(?:\.|eedings)" only ever matched the "eedings" branch: a literal
# period is not a word character, so \b immediately after "proc\." requires the NEXT character to
# be a word character too, which real citations never satisfy ("In Proc. of ..." has whitespace on
# both sides of the period). The "proc\." branch is unambiguously delimited by its own period and
# does not need - or get any benefit from - a trailing \b.
_VENUE_RE = re.compile(
    r"\bin\s+proc\.|\bin\s+proc(?:eedings)\b|\bin\s+the\s+proceedings\b|\bproceedings\s+of\b|"
    r"\bworkshop\s+on\b|\bconference\s+on\b|\bsymposium\s+on\b|\bjournal\s+of\b|"
    r"\btechnical\s+report\b|\bphd\s+thesis\b|\bmaster'?s\s+thesis\b|\bpreprint\b", re.I)


# A source's own cross-references ("Table 4.4", "Algorithm 8.15", "Equation 3.9"). Structural:
# a generic document-part word followed by a number. No subject-matter vocabulary.
_XREF_RE = re.compile(
    r"\b(?:tables?|figures?|fig\.|algorithms?|equations?|eqs?\.|sections?|chapters?|appendix)"
    r"\s*\d+(?:\.\d+)*",
    re.I)
# Table-of-contents rows: "4.1 Generic formula 3 4.2 Simple meaning 3" - numbered section titles
# repeated on one line, often with dot leaders and trailing page numbers.
_TOC_ENTRY_RE = re.compile(r"(?:^|\s)\d+(?:\.\d+)+\s+[A-Z]")
_TOC_LEADER_RE = re.compile(r"\.\s*\.\s*\.|\u2026")


def is_document_structure_noise(text: str) -> bool:
    """True for table-of-contents rows and passages that are mostly a cross-reference.

    A cross-reference sitting inside otherwise substantive prose is NOT noise - that passage
    still carries content, and the ban on reproducing the reference itself is enforced on the
    drafting side. Only text that says nothing once its structural markers are removed is
    rejected here, so real evidence is never dropped for mentioning a figure.
    """
    s = str(text or "")
    toc_entries = len(_TOC_ENTRY_RE.findall(s))
    if toc_entries >= 2:
        return True
    if toc_entries >= 1 and len(_TOC_LEADER_RE.findall(s)) >= 2:
        return True
    if _XREF_RE.search(s):
        remainder = _XREF_RE.sub(" ", s)
        remainder = re.sub(r"[^A-Za-z0-9]+", " ", remainder).strip()
        # words that carry no content on their own once the pointer is gone
        filler = {"as", "shown", "see", "in", "and", "the", "of", "is", "are", "for", "to",
                  "from", "on", "at", "by", "with", "this", "that", "it", "we", "also", "note",
                  "given", "listed", "described", "summarized", "illustrated", "presented"}
        content_words = [w for w in remainder.lower().split() if w not in filler]
        if len(" ".join(content_words)) < 40:
            return True
    return False


def is_citation_dense(text: str) -> bool:
    """True for survey/listing prose, not for a sentence that merely cites a source once.

    Two or more bracket citations is the listing signature ("...surveys by Buntine [129], Moret
    [166], Murthy [174]..."). A single citation attached to substantive text is ordinary academic
    writing and frequently carries the definition or formula being sought, so it is kept; it is
    rejected only when stripping the citation leaves too little content to be evidence.
    """
    s = str(text or "")
    hits = _INLINE_CITATION_RE.findall(s)
    if not hits:
        return False
    if len(hits) >= 2:
        return True
    return len(_INLINE_CITATION_RE.sub("", s).strip()) < 40


def is_bibliography_entry(text: str) -> bool:
    """True for reference-list entries: venue/pages/volume markers alongside a publication year."""
    s = str(text or "")
    if _VOLPAGE_RE.search(s):
        return True
    if not _YEAR_RE.search(s):
        return False
    return bool(_PAGES_RE.search(s) or _VENUE_RE.search(s))

# OCR/extraction corruption signature: a run of 2+ isolated single-character alphanumeric
# "tokens" (e.g. "m i" or "x i" in "De = m i=1 (xi -yi)2 1"), which is how this corpus's pymupdf
# and docling extraction lanes render lost subscripts/symbols in display equations. MinerU
# extracts the same equations as clean LaTeX. Both lanes are retrieved and ranked independently,
# so near-tied candidates can surface either - this signature lets ranking prefer the clean one
# without needing to match them as duplicates first.
_GARBLED_MATH_RUN_RE = re.compile(r"(?:(?<=^)|(?<=[\s(),=]))[A-Za-z](?:\s+[A-Za-z0-9](?:=\d+)?){1,}(?=[\s(),=]|$)")


# Control characters are what a PDF extractor emits when it cannot map a glyph - a summation sign,
# a radical, a large parenthesis. They are never legitimate content, so they are unambiguous
# evidence that this rendering of the passage is corrupt, and they outweigh the isolated-token
# heuristic below, which also fires on correctly-spaced symbolic text.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def control_char_damage(text: str) -> int:
    """Count of unmappable-glyph control characters - the extractor corruption signature."""
    return len(_CONTROL_CHAR_RE.findall(str(text or "")))


# The extractor stopped mid-formula rather than mangling a glyph: "Euclidean distance = √" with no
# radicand, a trailing bare summation/product sign, a relation with nothing on its right side, or
# a fraction whose bar disappeared and flattened numerator+denominator into one line. Different
# signature from control-character damage, same consequence for a generator handed it.
_TRUNCATED_FORMULA_RE = re.compile(
    r"(?:=|\bis\b)\s*[√∑∏]\s*$|[√∑∏]\s*$|[=<>≤≥+\-−*/·]\s*$|(?:…|\.\.\.)\s*$")

# v44: lost fraction bars and block-spliced display equations. These are deliberately narrow
# structural signatures from the fresh v3_20260812 output, not subject vocabulary:
#   P(Y|X)=P(X|Y)P(Y)P(X)        (Bayes denominator lost)
#   P(Xi=c|y)=nc+1n+v            (Laplace denominator lost)
#   GainRatio(A)=IG(A) SplitInfo(A)
#   AUC = 1 P · N
#   RandIndex = f11 + f00 f11 + ...
#   $$ formula $$ b. unrelated sentence
_PROBABILITY_DENOMINATOR_LOST_RE = re.compile(
    r"P\s*\([^)]*\|[^)]*\)\s*=\s*"
    r"P\s*\([^)]*\|[^)]*\)\s*P\s*\([^)]*\)\s*P\s*\([^)]*\)",
    re.I)
_FUNCTION_FRACTION_BAR_LOST_RE = re.compile(
    r"=\s*[A-Za-z]{2,}\s*\([^)]*\)\s+[A-Za-z]{2,}\s*\([^)]*\)")
_COUNT_FRACTION_BAR_LOST_RE = re.compile(
    r"=\s*[A-Za-z]{1,4}\s*\+\s*\d+\s*[A-Za-z]\s*\+")
# Each trailing letter must be a STANDALONE token - that is what a single-letter variable
# looks like ("AUC = 1 P · N", "= 1 P N"). Without the word boundaries this also matched
# ordinary prose after "= 1": the summation/product bounds "=1 to C" and "=1 to m", and
# "s(x, y) = 1 only if x = y" - correct mathematics, reported as damaged. That accounted for
# 6 of the 10 damaged-math flags on the real data-mining drafts, all false positives.
_ONE_OVER_PRODUCT_BAR_LOST_RE = re.compile(
    r"=\s*1\s+[A-Za-z]\b\s*(?:[·*]\s*)?\b[A-Za-z]\b")
_PAIR_COUNT_DENOMINATOR_BAR_LOST_RE = re.compile(
    r"=\s*(?:[A-Za-z]\d+\s*[+−-]\s*)+[A-Za-z]\d+\s+"
    r"[A-Za-z]\d+\s*[+−-]")
_DISPLAY_MATH_WITH_STRAY_TAIL_RE = re.compile(
    r"\$\$.*?\$\$\s*(?!where\b|with\b|for\b|and\b|,|\.|$)[A-Za-z0-9]",
    re.I | re.S)
_DISPLAY_MATH_ENDING_IN_CONJUNCTION_RE = re.compile(
    r",\s*(?:a\s*n\s*d|and)\s*(?:\\tag\s*\{[^}]*\}\s*)?\$\$\s*$", re.I)
_CURRENCY_DOLLAR_RE = re.compile(r"\$\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_FORMULA_SIGNAL_RE = re.compile(r"[=<>≤≥$\\∑∏√]")
_LEADING_UNMATCHED_CLOSE_RE = re.compile(r"^\s*[\]\)}]")

# v48: structural signatures measured from the formula renderings that survived.
_COMPACT_REPEATED_NAMED_EQUATION_RE = re.compile(r"([a-z]{4,}\([^)]*\))=.*\1=")
_RAW_NUMBER_OF_BAR_LOST_RE = re.compile(
    r"=\s*number\s+of\s+[^=]{4,80}number\s+of\s+", re.I)
_RAW_PROMISED_PROBABILITY_FLATTENED_RE = re.compile(
    r"\b(?:given\s+as|follows:?)\s*P\([^)]*\)\s+[A-Za-z]\d", re.I)
_RAW_TORN_BOOLEAN_FORMULA_RE = re.compile(r"^\s*\d+\s*,\s*}\s*&\s*{\s*[A-Za-z](?:\s+[A-Za-z])+\s*=", re.I)


# The PDF extractor emits a capture marker where it is about to inline a rendered expression. When
# extraction stops at that marker, the passage promises a formula and delivers nothing. Measured on
# the mathematics corpus: 15 of 1,332 admitted evidence items (1.13%) across 13 of 71 units ended
# exactly here, and every v28-v74 damage detector passed them as clean - found by hand-reading
# formula-shaped evidence after the automated check reported the corpus clean. This is an extractor
# artifact, not subject matter: it names no discipline, no unit, and no mathematics.
_DANGLING_CAPTURE_MARKER_RE = re.compile(
    r"\(\s*(?:la)?tex\s*code\s*:?\s*\)?\s*\$?\s*\Z", re.I)


def formula_truncated(text: str) -> bool:
    """True when the text stops mid-expression rather than completing it."""
    raw = str(text or "").strip()
    if not raw:
        return False
    return bool(_TRUNCATED_FORMULA_RE.search(raw)
                or _DANGLING_CAPTURE_MARKER_RE.search(raw))


def formula_delimiters_damaged(text: str) -> bool:
    """True when equation delimiters prove extraction stopped or began mid-expression."""
    raw = str(text or "").strip()
    if not raw or not _FORMULA_SIGNAL_RE.search(raw):
        return False
    # A currency amount is not an opening LaTeX delimiter. Remove only the unambiguous thousands
    # form before checking parity; ordinary inline/display mathematics keeps its dollar markers.
    delimiter_text = _CURRENCY_DOLLAR_RE.sub("", raw)
    if delimiter_text.count("$") % 2:
        return True
    if any(delimiter_text.count(left) != delimiter_text.count(right)
           for left, right in (("(", ")"), ("[", "]"), ("{", "}"))):
        return True
    if _LEADING_UNMATCHED_CLOSE_RE.search(delimiter_text):
        return True
    if _DISPLAY_MATH_ENDING_IN_CONJUNCTION_RE.search(delimiter_text):
        return True
    return False


_LATEX_WRAPPER_MACRO_RE = re.compile(
    r"\\(?:mathsf|mathrm|textrm|mathbf|operatorname\*?|scriptstyle|displaystyle)\s*\{\s*([^{}]*)\s*\}")


def compact_formula_signature(text: str) -> str:
    """Normalize math-rendering wrappers so structural damage survives extractor spelling changes."""
    raw = str(text or "")
    raw = raw.replace("−", "-").replace("·", "*").replace("\\mid", "|")
    raw = re.sub(r"\\tag\s*\{[^}]*\}", "", raw)
    raw = re.sub(r"\\(?:left|right)\b", "", raw)
    prior = None
    while prior != raw:
        prior = raw
        raw = _LATEX_WRAPPER_MACRO_RE.sub(r"\1", raw)
    raw = raw.replace("\\sum", "sum").replace("\\prod", "prod")
    raw = raw.replace("\\frac", "frac").replace("\\sqrt", "sqrt")
    raw = re.sub(r"\s+", "", raw)
    raw = raw.replace("{", "").replace("}", "")
    raw = raw.replace("\\", "")
    return raw.lower()


_COMPACT_PROBABILITY_DENOMINATOR_LOST_RE = re.compile(
    r"p\([^)]*\|[^)]*\)=p\([^)]*\|[^)]*\)p\([^)]*\)p\([^)]*\)")
_COMPACT_CONDITIONAL_RHS_P_LOST_RE = re.compile(
    r"p\([^)]*\|[^)]*\)=\([^)]*,[^)]*\)p\(")
_COMPACT_EUCLIDEAN_NO_SQRT_RE = re.compile(
    r"d\(x,y\)=sum.*\(xk?-yk?\).*2")


def has_explicit_fraction_notation(text: str) -> bool:
    """True only for a visible fraction operator, not prose that happens to say 'fraction'."""
    raw = str(text or "")
    return "/" in raw or bool(re.search(r"\\frac\b|\bdivided\s+by\b", raw, re.I))


# Structural bar-loss signatures. These carry NO metric or subject vocabulary, which is what lets
# them generalise: measured on the real corpus they catch 82 genuinely damaged renderings (TPR, FPR,
# Recall and others) that the previous metric-named regexes missed simply because nobody had written
# a rule for those particular metrics.
_GENERIC_REPEATED_NUMERATOR_RE = re.compile(
    r"=\s*([A-Za-z0-9]{1,6})(?:\s*\+\s*[A-Za-z0-9]{1,6})*\s+\1(?:\s*[+\-*/]|\s*$|\s)")
_GENERIC_BARE_NUMBER_QUOTIENT_RE = re.compile(
    r"=\s*\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s*(?:=|\.|$)")
_GENERIC_JUXTAPOSED_SUBEXPR_RE = re.compile(
    r"\)\s*[-\u2212]?\s*[A-Za-z]{1,12}\s*\([^)]*\)\s+[A-Za-z]{2,12}\s*\(")
# The MINUS and a following digit are REQUIRED. A flattened 1/(n-1) renders as "1n-1"; a
# legitimate summation index bound renders as "=1K" with no minus. Without this the pattern
# matched "i=1K" inside an intact "SSE=<SUM>i=1K<SUM>x..." equation and condemned it - caught
# by the v60 liveness check before it could discard real evidence.
_GENERIC_COMPACT_RUN_BEFORE_SUM_RE = re.compile(
    r"=\s*\d+[A-Za-z]+[-\u2212]\d+\s*(?:\u2211|\u220f|sum\b|prod\b)", re.I)

_GENERIC_BAR_LOSS_PATTERNS = (
    _GENERIC_REPEATED_NUMERATOR_RE,
    _GENERIC_BARE_NUMBER_QUOTIENT_RE,
    _GENERIC_JUXTAPOSED_SUBEXPR_RE,
    _GENERIC_COMPACT_RUN_BEFORE_SUM_RE,
)


def generic_bar_loss_damaged(text: str) -> bool:
    """True when a rendering shows a structural fraction-bar loss, named metric or not."""
    raw = str(text or "").strip()
    if not raw or has_explicit_fraction_notation(raw):
        return False
    return any(pattern.search(raw) for pattern in _GENERIC_BAR_LOSS_PATTERNS)


def formula_bar_or_tail_damaged(text: str) -> bool:
    """True for formula renderings whose fraction structure or block boundary is visibly broken."""
    raw = str(text or "").strip()
    if not raw:
        return False
    # Structural signatures only, deliberately naming no metric: generic_bar_loss_damaged
    # below recognises the same damage class by its signature, which keeps this check working on
    # any corpus rather than only on the metrics one curriculum happens to teach.
    if any(pattern.search(raw) for pattern in (
        _PROBABILITY_DENOMINATOR_LOST_RE,
        _FUNCTION_FRACTION_BAR_LOST_RE,
        _COUNT_FRACTION_BAR_LOST_RE,
        _ONE_OVER_PRODUCT_BAR_LOST_RE,
        _PAIR_COUNT_DENOMINATOR_BAR_LOST_RE,
        _DISPLAY_MATH_WITH_STRAY_TAIL_RE,
        _RAW_NUMBER_OF_BAR_LOST_RE,
        _RAW_PROMISED_PROBABILITY_FLATTENED_RE,
        _RAW_TORN_BOOLEAN_FORMULA_RE,
    )):
        return True
    if generic_bar_loss_damaged(raw):
        return True

    compact = compact_formula_signature(raw)
    if not compact:
        return False
    if _COMPACT_PROBABILITY_DENOMINATOR_LOST_RE.search(compact):
        return True
    if _COMPACT_CONDITIONAL_RHS_P_LOST_RE.search(compact):
        return True
    if (_COMPACT_EUCLIDEAN_NO_SQRT_RE.search(compact)
            and "sqrt" not in compact and "√" not in raw):
        return True
    # Only the generic repeated-named-equation signature belongs here; metric-specific patterns
    # are handled by generic_bar_loss_damaged above, which recognises the same bar-loss
    # signature without naming any metric and so stays corpus-independent.
    if (_COMPACT_REPEATED_NAMED_EQUATION_RE.search(compact)
            and not has_explicit_fraction_notation(raw)):
        return True
    return False


def math_rendering_damaged(text: str) -> bool:
    """Any failure mode that makes a mathematical rendering unusable as evidence."""
    return (bool(control_char_damage(text)) or formula_truncated(text)
            or formula_delimiters_damaged(text) or formula_bar_or_tail_damaged(text))


_DRAFT_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.S)
_DRAFT_INLINE_MATH_RE = re.compile(r"(?<!\$)\$([^$\n]+?)\$(?!\$)")
_DRAFT_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_DRAFT_PROSE_WORD_RE = re.compile(r"[A-Za-z]{3,}")
# A segment carrying a relational operator counts as a formula when this few ordinary words
# surround it. Formulas written in plain text legitimately contain a couple of connectives
# ("sum from i=1 to m of ..."), so the bar is not zero; explanatory sentences carry far more.
_DRAFT_FORMULA_MAX_PROSE_WORDS = 3


def draft_math_spans(text: str) -> List[str]:
    """The mathematical spans of a generated draft: delimited math, plus formula-only segments.

    Segments are sentence-sized on purpose. Every damage predicate assumes a complete formula, so
    a finer split can cut an expression in half and manufacture the truncation and unbalanced-
    delimiter signatures it is meant to detect (measured: 16 false positives on the real drafts).
    A formula does not cross a sentence boundary, so this granularity cannot invent damage.
    """
    raw = str(text or "")
    spans: List[str] = []
    for match in _DRAFT_DISPLAY_MATH_RE.finditer(raw):
        spans.append(match.group(1).strip())
    remainder = _DRAFT_DISPLAY_MATH_RE.sub("\n", raw)
    for match in _DRAFT_INLINE_MATH_RE.finditer(remainder):
        spans.append(match.group(1).strip())
    remainder = _DRAFT_INLINE_MATH_RE.sub(" ", remainder)

    for line in remainder.splitlines():
        for segment in _DRAFT_SENTENCE_SPLIT_RE.split(line):
            segment = segment.strip().lstrip("-*\u2022 ").strip()
            if not segment or not _RELATIONAL_RE.search(segment):
                continue
            if len(_DRAFT_PROSE_WORD_RE.findall(segment)) <= _DRAFT_FORMULA_MAX_PROSE_WORDS:
                spans.append(segment)
    return [s for s in spans if s]


def draft_math_rendering_damaged(text: str) -> bool:
    """math_rendering_damaged(), scoped to a generated draft's own mathematical spans.

    Same damage definitions, correct unit of analysis - see draft_math_spans. Use this for
    model-authored draft text; use math_rendering_damaged directly for corpus evidence.
    """
    return any(math_rendering_damaged(span) for span in draft_math_spans(text))


def garbled_math_penalty(text: str) -> float:
    """0.0 for clean text; grows with visible corruption of the passage's mathematics."""
    raw = str(text or "")
    control = control_char_damage(raw)
    matches = _GARBLED_MATH_RUN_RE.findall(raw)
    if not control and not matches:
        return 0.0
    # a single dropped glyph already makes an equation unreadable, so weight it far above the
    # spacing heuristic, which is a weak signal by comparison
    return min(0.60, 0.20 * control + 0.04 * len(matches))


# A defining equation is short on purpose ("Recall = TP / (TP + FN)" is compact). The generic
# short-fragment floor would discard it, so a sentence the corpus flagged as formula-shaped that
# also carries a relational operator is held to a much lower length bar. Torn prose fragments have
# no operator and are unaffected.
_RELATIONAL_RE = re.compile(r"[=<>\u2264\u2265\u2260]")
MIN_TEXT_CHARS = 25
MIN_FORMULA_TEXT_CHARS = 8


def _min_length_for(sentence: Mapping[str, Any], text: str) -> int:
    if sentence.get("is_formula_like") and _RELATIONAL_RE.search(text):
        return MIN_FORMULA_TEXT_CHARS
    return MIN_TEXT_CHARS


def looks_like_equation(sentence: Mapping[str, Any], text: str) -> bool:
    """Formula-shaped text carrying a relational operator - an equation on its face."""
    return bool(sentence.get("is_formula_like")) and bool(_RELATIONAL_RE.search(text))


def is_structural_junk(sentence: Mapping[str, Any]) -> bool:
    text = str(sentence.get("sentence_text") or "").strip()
    # Wreckage of a formula, not a formula. A generator told to reproduce the mathematics in its
    # evidence will complete a partial rendering rather than report it as unusable, so corrupted
    # renderings are withheld entirely. v24 already prefers an intact variant wherever one exists,
    # so this only bites when every rendering is damaged - and there, no formula is the right
    # answer rather than a reconstructed one.
    if math_rendering_damaged(text):
        return True
    # A boilerplate/meta flag is overridden when the sentence is visibly an equation: the overlay
    # mislabels some formulas as navigation or metadata, and such a sentence would otherwise be
    # discarded before it is ever scored. Every other structural check below still applies.
    if any(sentence.get(f) for f in JUNK_FLAGS) and not looks_like_equation(sentence, text):
        return True
    if len(text) < _min_length_for(sentence, text):
        return True
    if _REFERENCE_RE.match(text) or _PAGE_ARTIFACT_RE.match(text):
        return True
    if is_citation_dense(text):
        return True
    if is_document_structure_noise(text):
        return True
    if is_bibliography_entry(text):
        return True
    return False


def is_mislabeled_formula_pointer(sentence: Mapping[str, Any],
                                 successor_block_text: str) -> bool:
    """A lead-in pointer the overlay mislabeled as meta/boilerplate, whose successor block is a
    formula payload.

    is_structural_junk already overrides a JUNK_FLAG when a row looks_like_equation, for the
    documented reason that "the overlay mislabels some formulas as navigation or metadata, and
    such a sentence would otherwise be discarded before it is ever scored." The identical
    mislabeling hits POINTER sentences ("The lecture defines Spearman as Pearson correlation on
    ranks:"), which are prose and so fall outside that equation-shaped override - so the pointer
    is discarded before the lead_in_payload rescue that depends on it can ever run, and the
    formula it points at is unreachable no matter how the thresholds are set.

    Measured on the real corpus: 221 rows are junk-filtered purely by a flag despite being
    lead-ins; 43 of those point at an actual formula payload. This override covers only that 43 -
    every other structural check still applies unchanged, and an exempted row still has to clear
    the ordinary relevance floor like any other candidate. Exposure is not admission.
    """
    if not any(sentence.get(f) for f in JUNK_FLAGS):
        return False  # not a flag-driven rejection - nothing to override
    text = str(sentence.get("sentence_text") or "").strip()
    if not ends_with_lead_in(text):
        return False
    # The override is ONLY for the mislabeling flag. Every other reason to reject still stands.
    if (math_rendering_damaged(text)
            or len(text) < _min_length_for(sentence, text)
            or _REFERENCE_RE.match(text) or _PAGE_ARTIFACT_RE.match(text)
            or is_citation_dense(text)
            or is_document_structure_noise(text)
            or is_bibliography_entry(text)):
        return False
    # The payload must ASSERT A RELATION, not merely contain mathematical symbols.
    # is_formula_payload accepts a bare expression through its has_mathematics fallback, which
    # is correct for the pre-existing lead_in_payload rescue but too weak to justify OVERRIDING a
    # structural-metadata flag. Measured consequence of the weaker form: for Silhouette Coefficient
    # the fragment "P u in X\{x} d(x, u)" - a numerator with no operator, whose complete form
    # a(x) = sum(...)/(|X|-1) was ALREADY in the packet - was admitted on a packet sitting at the
    # MAX_PASSAGES cap, displacing two rows and costing the drafted text the a(x) formula it
    # previously carried. Requiring a relational operator keeps every genuine recovery
    # (rs = rho(...), Sensitivity = TP/(TP+FN), mu1 = p10 = (7,3), f = FindNextBest(F,U)) and drops
    # exactly the fragment class that caused the regression.
    payload = str(successor_block_text or "")
    if not _RELATIONAL_RE.search(payload):
        return False
    return is_formula_payload(payload)


def shape_of(sentence: Mapping[str, Any]) -> List[str]:
    return [f.replace("is_", "").replace("_like", "")
            for f in SHAPE_FLAGS if sentence.get(f)]


_LATEX_RE = re.compile(r"\$[^$]*\$|\[A-Za-z]+|[{}_^]")
_WS_RE = re.compile(r"[^a-z0-9]+")


# Leading page-number / section-number run on a repeated running header. Anchored to the START of
# the text only - a trailing number is part of the content (a computed value), a leading one is
# nearly always pagination furniture.
_LEADING_PAGENO_RE = re.compile(r"^[\d.\s]{1,12}")


def content_signature(text: str) -> str:
    """Extractor-independent signature of a passage's content.

    The same source paragraph is emitted by pymupdf, docling and mineru with different math
    rendering and spacing, so identical content arrives up to three times and consumes the
    completeness budget. Strip math markup and non-alphanumerics so the variants collapse.
    """
    stripped = _LATEX_RE.sub(" ", str(text or "").lower())
    # A running header is re-emitted once per page it appears on, carrying a different page
    # number each time ("4 Dealing with Missing Values", "78 4 Dealing with Missing Values", ...).
    # Those are different strings, so they produced different signatures and every copy survived
    # deduplication - measured at 72% and 66% of two real packets' entire evidence budget.
    # Only a LEADING run of digits/dots/spaces is removed. Trailing digits are deliberately kept:
    # stripping those is what makes "Precision = 0.750" and "Precision = 0.500" collide, which is
    # a real distinction between two worked examples, not a duplicate.
    stripped = _LEADING_PAGENO_RE.sub("", stripped.strip())
    return _WS_RE.sub("", stripped)


# Mathematics survives extraction either as LaTeX markup or as Unicode operators, depending on the
# extractor. Testing only for LaTeX markers scored every clean docling rendering as prose and let
# raw length decide instead, which favours the more verbose damaged variant.
_UNICODE_MATH_RE = re.compile(
    "[\u2211\u220f\u221a\u222b\u2260\u2264\u2265\u00b1\u00d7\u00f7"
    "\u03b1-\u03c9\u0391-\u03a9\u2208\u2209\u2286\u2287\u221e\u2248]")


def has_mathematics(text: str) -> bool:
    """True when the passage carries mathematics in either surviving notation."""
    raw = str(text or "")
    return ("$" in raw) or ("\\" in raw) or bool(_UNICODE_MATH_RE.search(raw))


def _information_score(passage: Mapping[str, Any]) -> tuple:
    """Prefer the richest, cleanest variant of duplicated content."""
    text = str(passage.get("text") or "")
    has_math = 1 if has_mathematics(text) else 0
    # ranked above has_math below, so an intact rendering always beats a corrupt one regardless of
    # which notation each happens to use
    undamaged = 1 if not math_rendering_damaged(text) else 0
    clean_math = -garbled_math_penalty(text)
    not_heading_only = 0 if passage.get("shapes") == ["heading"] else 1
    return (not_heading_only, undamaged, has_math, clean_math,
            int(passage.get("sentence_count") or 0), len(text))


def deduplicate_passages(passages: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[Any, Dict[str, Any]] = {}
    for idx, p in enumerate(passages):
        sig = content_signature(p.get("text"))
        # v39: a signature this short is too generic to trust as a DEDUPLICATION key - unrelated
        # short passages could coincidentally collapse to the same handful of characters. The
        # original code used this as a reason to DROP the passage outright ("continue"), silently
        # discarding real, short, meaningful content ("p = 0.1", "purity(Z1) = 3") with no
        # admission_basis exemption of any kind, before verify_scorer or rival-stripping ever saw
        # it. A private, never-colliding key (keyed on position, not content) gets the intended
        # "don't deduplicate this" behaviour without also discarding the passage.
        key = sig if len(sig) >= 12 else ("__unique__", idx)
        current = best.get(key)
        if current is None or _information_score(p) > _information_score(current):
            merged = dict(p)
            if current is not None:
                merged["relevance"] = max(float(p.get("relevance") or 0),
                                          float(current.get("relevance") or 0))
                merged["duplicate_variants"] = int(current.get("duplicate_variants") or 1) + 1
                # v41: rescue status is sticky across a merge, the same way it is sticky across
                # every OTHER post-admission check (RESCUE_ADMISSION_BASES) - the merge-winner's
                # own basis is picked on ordinary rendering-quality grounds that have nothing to
                # do with which of the two texts was independently verified as this unit's own
                # equation or promised payload, and losing that status here would silently
                # re-expose the content to the strict floor and to rival-stripping.
                if (merged.get("admission_basis") not in RESCUE_ADMISSION_BASES
                        and current.get("admission_basis") in RESCUE_ADMISSION_BASES):
                    merged["admission_basis"] = current["admission_basis"]
                    merged["ownership_context_text"] = current.get("ownership_context_text")
                elif (merged.get("admission_basis") not in CONTEXT_ADMISSION_BASES
                      and current.get("admission_basis") in CONTEXT_ADMISSION_BASES):
                    merged["admission_basis"] = current["admission_basis"]
                    merged["verification_context_text"] = current.get("verification_context_text")
                    merged["verification_heading"] = current.get("verification_heading")
            best[key] = merged
        else:
            current["duplicate_variants"] = int(current.get("duplicate_variants") or 1) + 1
            current["relevance"] = max(float(current.get("relevance") or 0),
                                       float(p.get("relevance") or 0))
            if (current.get("admission_basis") not in RESCUE_ADMISSION_BASES
                    and p.get("admission_basis") in RESCUE_ADMISSION_BASES):
                current["admission_basis"] = p["admission_basis"]
                current["ownership_context_text"] = p.get("ownership_context_text")
            elif (current.get("admission_basis") not in CONTEXT_ADMISSION_BASES
                  and p.get("admission_basis") in CONTEXT_ADMISSION_BASES):
                current["admission_basis"] = p["admission_basis"]
                current["verification_context_text"] = p.get("verification_context_text")
                current["verification_heading"] = p.get("verification_heading")
    return list(best.values())


def repaired_formula_provenance(sentences: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Repair provenance for an assembled passage, taken from whichever member row was repaired.

    A passage is assembled from several source rows and the repaired row is not necessarily the
    seed, so this reads across the members rather than off the seed. Returns an empty mapping when
    no member was repaired, which keeps the field absent rather than present-and-null on the
    overwhelming majority of passages.
    """
    for sentence in sentences or ():
        if sentence.get("formula_repaired_from_damaged_text"):
            return {
                "formula_repaired_from_doc_id": sentence.get("formula_repaired_from_doc_id"),
                "formula_repaired_from_layer": sentence.get("formula_repaired_from_layer"),
                "formula_repair_locality": sentence.get("formula_repair_locality"),
            }
    return {}


def _block_key(sentence: Mapping[str, Any]) -> Tuple[str, str]:
    """Return an internal key that cannot merge reused extractor block IDs."""
    doc_id = str(sentence.get("doc_id") or "")
    block_id = str(sentence.get("block_id") or sentence.get("patch_id") or "")
    if not block_id:
        return (doc_id, "")
    source_text = str(sentence.get("source_block_text") or "").strip()
    if source_text:
        discriminator = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    else:
        bbox = sentence.get("bbox")
        discriminator_source = repr((sentence.get("page_index"), bbox)) if bbox else ""
        discriminator = (hashlib.sha256(discriminator_source.encode("utf-8")).hexdigest()
                         if discriminator_source else "")
    internal_id = block_id + (("|src=" + discriminator) if discriminator else "")
    return (doc_id, internal_id)


CONTEXT_RELEVANCE_FLOOR = 0.54
CONTEXT_ADMISSION_BASES = frozenset({"context_anchored_relevance"})
_CONTEXT_STOPWORDS = frozenset("""
a an and or the of for in on to with by from as at is are was were be been being its it this that
these those each any all some such into than then where which while during through using used use
approach method model models algorithm algorithms value values point points class classes data set
sets example examples given following unit index measure problem basic standard general
one two three four first second third time test tests tested testing
""".split)


def _context_stem(word: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "", str(word or "").lower())
    if len(token) < 3 or token in _CONTEXT_STOPWORDS:
        return ""
    for suffix in ("ization", "ations", "ation", "ments", "ment", "ness", "ingly", "ing",
                   "edly", "ed", "ies", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            token = token[:-len(suffix)]
            break
    return token


def context_content_terms(text: str) -> set:
    return {stem for raw in re.findall(r"[A-Za-z0-9]+", str(text or ""))
            for stem in [_context_stem(raw)] if stem}


def normalized_label_phrase(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def heading_exactly_names_unit(heading: str, unit_labels: Sequence[str]) -> bool:
    """True only when a heading contains a whole unit label, not a few generic shared words."""
    h = normalized_label_phrase(heading)
    if not h:
        return False
    for label in unit_labels or []:
        candidate = normalized_label_phrase(re.sub(r"\([^)]*\)", "", str(label or ""))).strip()
        if len(candidate) >= 5 and re.search(r"(?:^|\s)" + re.escape(candidate) + r"(?:\s|$)", h):
            return True
    return False


def context_candidate_is_anchored(text: str, context: str, heading: str,
                                  unit_labels: Sequence[str]) -> bool:
    """License context scoring only for a member coherently attached to a unit-bearing anchor."""
    member_terms = context_content_terms(text)
    unit_terms = context_content_terms(" ".join(str(x or "") for x in unit_labels or []))
    if not member_terms or not unit_terms:
        return False
    if member_terms & unit_terms:
        return True
    if heading_exactly_names_unit(heading, unit_labels):
        return True
    anchor_terms = set()
    for part in re.split(r"(?<=[.!?])\s+", str(context or "")):
        terms = context_content_terms(part)
        if terms & unit_terms:
            anchor_terms.update(terms)
    return bool(member_terms & anchor_terms)


DEFINING_EQUATION_FLOOR = 0.45
DEFINING_EQUATION_MAX_PER_UNIT = 3


def defining_equation_patterns(names: Sequence[str]):
    """Compile 'name =' matchers for a unit's own labels.

    The convention "<named quantity> = <expression>" is how a definition is written in any
    quantitative source; nothing here encodes a subject. A trailing parenthetical is tolerated
    ("Entropy(D) = ...") and "==" / "=>" are excluded so comparisons and arrows do not match.
    """
    out = []
    for name in names:
        name = str(name or "").strip()
        if not name:
            continue
        core = r"\s+".join(re.escape(w) for w in name.split())
        out.append(re.compile(
            r"(?<![A-Za-z0-9])" + core + r"\s*(?:\([^)]{0,30}\))?\s*=(?!=|>)", re.I))
    return out


# A single-or-double lowercase-letter index in parens directly after the head noun - "(i)",
# "(i,j)" - is the corpus's own notational convention for a cluster-relative external-validation
# measure. The ordinary same-named classifier-level sibling never carries this: "Precision =
# TP/(TP+FP)" has no parenthetical at all. Requiring it, rather than making the head-noun match
# unconditionally, is what keeps this from re-admitting the wrong sibling's formula.
_INDEX_SUBSCRIPT_RE = re.compile(r"\([a-z](?:\s*,\s*[a-z])?\)")


def compound_index_equation_patterns(names: Sequence[str]):
    """For a compound "X: Y" label, also match Y(index) = ... as this unit's defining equation.

    The corpus regularly drops the qualifier half of a compound name within its own section (an
    "External Index" passage just says "precision(i,j)=...", never "external precision(i,j)=...");
    this recovers exactly that case without loosening admission for any unit whose name is not
    itself compound.
    """
    out = []
    for name in names:
        name = str(name or "")
        if ":" not in name:
            continue
        tail = name.split(":", 1)[1].strip()
        if not tail:
            continue
        core = r"\s+".join(re.escape(w) for w in tail.split())
        # Only the measure name is case-insensitive. The index letters deliberately are not:
        # ordinary decision-tree formulas such as Entropy(D) and Entropy(F) use uppercase data-set
        # symbols, while the external-index convention this rescue owns is lowercase (i) or (i,j).
        # Compiling the whole expression with re.I silently erased that distinction in
        # and protected unrelated node entropy from every later ownership check.
        out.append(re.compile(
            r"(?<![A-Za-z0-9])(?i:" + core
            + r")\s*\([a-z](?:\s*,\s*[a-z])?\)\s*=(?!=|>)"))
    return out


def has_symbolic_rhs(text: str) -> bool:
    """True when what follows the first '=' names other quantities rather than evaluating to a
    number. "Recall = TP TP + FN" is symbolic; "Recall = 0.600" is a worked instance."""
    s = str(text or "")
    idx = s.find("=")
    if idx < 0:
        return False
    rhs = s[idx + 1:]
    return bool(re.search(r"[A-Za-z]", rhs))


# A run of single letters separated by single spaces is one letter-spaced word:
# "P r e c i s i o n" is "Precision". The extractors emit display math this way, so a pattern
# built from a unit's name cannot match its own equation. Measured on the corpus: 582 of 4649
# equation-shaped texts are rendered like this.
_LETTER_SPACED_RUN_RE = re.compile(r"(?:(?<=\s)|^)((?:[A-Za-z] ){2,}[A-Za-z])(?![A-Za-z])")


def collapse_letter_spacing(text: str) -> str:
    """Join letter-spaced words so a name written one character at a time can be recognised."""
    return _LETTER_SPACED_RUN_RE.sub(lambda m: m.group(1).replace(" ", ""), str(text or ""))


# v51/INT-21. A named function in this corpus is usually wrapped in a formatting command -
# "\mathrm { R a n d I n d e x }", "\mathsf { s e p a r a t i o n }", "\operatorname { ... }".
# The wrapper and its braces sit between the name and the "=", so a pattern built from the name
# cannot reach it even once the letter-spacing is collapsed. Replacing each wrapper by its own
# content leaves the name where the pattern expects it.
_LATEX_NAME_WRAPPER_RE = re.compile(
    r"\\(?:mathrm|mathbf|mathit|mathsf|mathtt|mathcal|operatorname\*?|text|textrm|textbf|textsf"
    r"|bf|rm|boxed)\s*\{([^{}]*)\}")
_LATEX_BRACE_RE = re.compile(r"[{}]")


def normalise_equation_text(text: str) -> str:
    """A rendering reduced to where a unit's own name would be legible, if it is present.

    Only ever used to test a unit's OWN defining-equation pattern, so a wrong reduction can fail
    to match but cannot admit a foreign unit's formula - the same argument that makes INT-20's
    letter-spacing collapse safe, and the reason neither is used anywhere else.
    """
    out = str(text or "")
    for _ in range(3):                        # wrappers nest a level or two, not deeply
        replaced = _LATEX_NAME_WRAPPER_RE.sub(lambda m: m.group(1), out)
        if replaced == out:
            break
        out = replaced
    out = _LATEX_BRACE_RE.sub(" ", out)
    return re.sub(r"\s+", " ", collapse_letter_spacing(out)).strip()


@functools.lru_cache(maxsize=1024)
def _word_boundary_tolerant(pattern_text: str, flags: int):
    """The same pattern, tolerating a MISSING space between the name's own words.

    Collapsing letter-spacing merges "R a n d I n d e x" into "RandIndex", which no longer matches
    "Rand\\s+Index". Requiring zero-or-more rather than one-or-more restores it and widens
    nothing else: "Rand\\s*Index" still cannot match "Random Index", because after "Rand" that
    text reads "om".
    """
    return re.compile(pattern_text.replace(r"\s+", r"\s*"), flags)


def is_defining_equation(text: str, patterns) -> bool:
    """True when this text states an equation whose left-hand side is one of `patterns`.

    Tested against the raw text first and, only if that fails, against the same text with
    letter-spacing collapsed. The collapse is safe HERE specifically because the collapsed text
    still has to match this unit's OWN name: a wrong join cannot admit a foreign unit's formula,
    it can only fail to match. Used nowhere else, so no other check inherits the assumption.
    """
    s = str(text or "")
    if any(p.search(s) for p in patterns):
        return True
    # No early exit on "nothing changed". The tolerant pattern differs from the strict one even
    # when the text needs no reduction - "RandIndex = 4" is Rand Index's defining equation and the
    # strict pattern, which requires a space inside the name, cannot see it. Found by sabotage:
    # the guard covering this passed because the early exit answered it first.
    loose = [_word_boundary_tolerant(p.pattern, p.flags) for p in patterns]
    return any(p.search(normalise_equation_text(s)) for p in loose)


def assemble_passages(
    hits: Sequence[Mapping[str, Any]],
    corpus_by_block: Mapping[Tuple[str, str], List[Mapping[str, Any]]],
    *,
    max_passages: int = DEFAULT_MAX_PASSAGES,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_relevance: float = DEFAULT_MIN_RELEVANCE,
    relative_floor: float = DEFAULT_RELATIVE_FLOOR,
    verify_scorer=None,
    unit_labels: Optional[Sequence[str]] = None,
    member_verifier=None,
    context_scorer=None,
    block_successors: Optional[Mapping[Tuple[str, str], Tuple[str, str]]] = None,
    doc_long_sentences: Optional[Mapping[str, Sequence[str]]] = None,
    doc_all_sentences: Optional[Mapping[str, Sequence[str]]] = None,
) -> List[Dict[str, Any]]:
    """Turn ranked sentence hits into ranked, deduplicated, document-ordered passages."""
    # top_score anchors the relative floor, so it must come only from candidates that could
    # actually be admitted - a junk fragment scoring deceptively high must not be allowed to set
    # the bar that then excludes legitimate candidates below it.
    top_score = max(
        (float(h.get("rerank_prob") or 0.0) for h in hits if not is_structural_junk(h["sentence"])),
        default=0.0,
    )
    floor = max(min_relevance, top_score * relative_floor)
    # v34: for a compound "X: Y" name, also recognise Y(index)=... - the corpus regularly
    # drops the qualifier half within its own section ("precision(i,j)=...", never "external"
    # "precision(i,j)=..."), and the index-subscript requirement keeps this from rescuing
    # the wrong same-named sibling formula.
    _defeq_patterns = (defining_equation_patterns(unit_labels or [])
                       + compound_index_equation_patterns(unit_labels or []))
    # Decide up front which defining equations get the lowered floor, preferring symbolic forms
    # over worked numbers so the budget buys the definition rather than arithmetic.
    _defeq_candidates = []
    if _defeq_patterns:
        for _h in hits:
            _s = _h["sentence"]
            _t = str(_s.get("sentence_text") or "")
            _p = float(_h.get("rerank_prob") or 0.0)
            if _p >= min_relevance or _p < DEFINING_EQUATION_FLOOR:
                continue  # already admissible, or too weak to rescue
            if is_defining_equation(_t, _defeq_patterns):
                _defeq_candidates.append((0 if has_symbolic_rhs(_t) else 1, -_p, _block_key(_s)))
    _defeq_candidates.sort()
    _defeq_allowed = {k for _, _, k in _defeq_candidates[:DEFINING_EQUATION_MAX_PER_UNIT]}
    _defeq_keys: set = set()
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for hit in hits:
        prob = float(hit.get("rerank_prob") or 0.0)
        # Formula-shaped passages only need the absolute floor, not the relative one. This
        # cross-encoder consistently scores short symbolic text (an equation) lower than
        # descriptive prose on the same general topic, even when the equation is the one thing
        # actually needed (confirmed: KC_EVAL_BASIC_004's real "Recall = TP / (TP+FN)" formula
        # cleared 0.55 but sat below top_score*0.85 because a generic "Classifier evaluation
        # methods" heading scored higher). The relative floor exists to keep weak, plausibly-
        # wrong-domain PROSE out when strong same-unit evidence exists; a formula doesn't carry
        # that risk the same way - it is either the right symbols or visibly garbled ones, not a
        # fluent-sounding wrong topic.
        is_formula = "formula" in shape_of(hit["sentence"])
        # A passage stating "<this unit's name> = ..." is the unit's own defining equation. The
        # cross-encoder reliably under-scores such terse symbolic text against a short name query,
        # so it gets a lower floor - but still a floor, and only a few per unit.
        is_defeq = _block_key(hit["sentence"]) in _defeq_allowed
        if is_defeq:
            unit_floor = DEFINING_EQUATION_FLOOR
        elif is_formula:
            unit_floor = min_relevance
        else:
            unit_floor = floor
        if prob < unit_floor:
            continue
        if is_defeq and prob < min_relevance:
            _defeq_keys.add(_block_key(hit["sentence"]))
        sentence = hit["sentence"]
        if is_structural_junk(sentence):
            # A mislabeled formula POINTER is kept: discarding it here would silently defeat the
            # lead_in_payload rescue below, which can only see blocks that reached `best`.
            _succ_key = (block_successors or {}).get(_block_key(sentence))
            _succ_members = (corpus_by_block.get(_succ_key) or []) if _succ_key else []
            _succ_text = " ".join(
                str(s.get("sentence_text") or "").strip()
                for s in sorted(_succ_members, key=lambda s: int(s.get("sent_idx") or 0))).strip()
            if not is_mislabeled_formula_pointer(sentence, _succ_text):
                continue
        key = _block_key(sentence)
        if not key[1]:
            continue
        entry = best.get(key)
        score = float(hit.get("rerank_prob") or 0.0) - garbled_math_penalty(sentence.get("sentence_text"))
        if entry is None or score > entry["relevance"]:
            best[key] = {"relevance": score, "seed": sentence, "key": key,
                         "bm25": float(hit.get("bm25_score") or 0.0),
                         "context_score_mode": hit.get("context_score_mode")}

    # A block admitted on a passage that ends in "... is:" or "... given by:" is a promise whose
    # payload sits in the next block. Admit that payload on the pointer's relevance, since the
    # formula itself cannot compete with prose on a name-shaped query. A narrowly recognised
    # numbered formula list may span several consecutive blocks; retain the complete list under
    # the same pointer ownership instead of keeping only its first low-context member.
    if block_successors:
        block_predecessors = {successor: predecessor
                              for predecessor, successor in block_successors.items()}
        for key in list(best.keys()):
            members = corpus_by_block.get(key) or []
            ordered_m = sorted(members, key=lambda s: (int(s.get("sent_idx") or 0)))
            tail_text = " ".join(str(s.get("sentence_text") or "") for s in ordered_m).strip()
            if ends_with_lead_in(tail_text):
                nxt = block_successors.get(key)
                nxt_members = (corpus_by_block.get(nxt) or []) if nxt else []
                nxt_text = " ".join(
                    str(s.get("sentence_text") or "").strip() for s in
                    sorted(nxt_members, key=lambda s: (int(s.get("sent_idx") or 0)))).strip()
                if nxt_members and is_formula_payload(nxt_text):
                    payload_entry = best.get(nxt)
                    if payload_entry is None:
                        best[nxt] = {
                            "relevance": float(best[key]["relevance"]),
                            "seed": nxt_members[0],
                            "key": nxt,
                            "bm25": 0.0,
                            "lead_in_payload": True,
                            "ownership_context_text": tail_text,
                        }
                    else:
                        # Promote, exactly as the structured_list and procedure_list branches
                        # below already do. Promotion must not be made conditional on the payload
                        # being absent from `best`: a payload that clears the floor on its own
                        # would then be skipped, so the promise it fulfils would buy it nothing.
                        # It would keep an ordinary admission basis, be re-tested by the
                        # severed-fragment, structural-junk and rival-claim filters that payload
                        # admission exists to exempt it from, and lose. Whether the reranker also
                        # surfaced the payload independently is not a fact about the promise.
                        payload_entry["lead_in_payload"] = True
                        payload_entry["ownership_context_text"] = tail_text
            if ends_with_structured_list_lead_in(tail_text):
                for payload_key in structured_list_payload_keys(
                        key, block_successors, corpus_by_block):
                    payload_members = corpus_by_block.get(payload_key) or []
                    if not payload_members:
                        continue
                    payload_entry = best.get(payload_key)
                    if payload_entry is None:
                        best[payload_key] = {
                            "relevance": float(best[key]["relevance"]),
                            "seed": payload_members[0],
                            "key": payload_key,
                            "bm25": 0.0,
                            "structured_list_payload": True,
                            "ownership_context_text": tail_text,
                        }
                    else:
                        payload_entry["structured_list_payload"] = True
                        payload_entry["ownership_context_text"] = tail_text

            # A numbered/procedural extractor may preserve only the middle step strongly enough
            # for the reranker. Recover its contiguous siblings when the admitted step can be
            # traced backward to an explicit "as follows" pointer and forward to a formula
            # boundary. This is source-structure ownership, not a lower relevance threshold: the
            # independently admitted step anchors the sequence, and the bounded adjacency checks
            # prevent arbitrary neighboring prose from riding along.
            procedure_keys, procedure_context = procedure_list_payload_keys(
                key, block_predecessors, block_successors, corpus_by_block)
            for payload_key in procedure_keys:
                payload_members = corpus_by_block.get(payload_key) or []
                if not payload_members:
                    continue
                payload_entry = best.get(payload_key)
                if payload_entry is None:
                    best[payload_key] = {
                        "relevance": float(best[key]["relevance"]),
                        "seed": payload_members[0],
                        "key": payload_key,
                        "bm25": 0.0,
                        "procedure_list_payload": True,
                        "ownership_context_text": procedure_context,
                    }
                else:
                    payload_entry["procedure_list_payload"] = True
                    payload_entry["ownership_context_text"] = procedure_context

            # INT-16, the mirror of the lead-in rescue above. A lead-in promises a formula and the
            # payload follows it; a formula's own symbol glossary also follows it, opening
            # "where ...". Nothing admitted the block AFTER a formula, so a packet could hold
            # precision(i,j)=p_ij while the sentence defining p_ij stayed in the corpus - and the
            # draft then states the formula and reports that its symbol is undefined, which is
            # what an external content review of r3 found for three units. Measured over the r2
            # packets: 7 admitted formulas whose qualifier was left behind, 3 already admitted.
            if is_formula_payload(tail_text):
                qualifier_key = block_successors.get(key)
                qualifier_members = ((corpus_by_block.get(qualifier_key) or [])
                                     if qualifier_key else [])
                qualifier_text = " ".join(
                    str(s.get("sentence_text") or "").strip() for s in
                    sorted(qualifier_members,
                           key=lambda s: (int(s.get("sent_idx") or 0)))).strip()
                if qualifier_members and defines_the_symbols_above(qualifier_text):
                    payload_entry = best.get(qualifier_key)
                    if payload_entry is None:
                        best[qualifier_key] = {
                            "relevance": float(best[key]["relevance"]),
                            "seed": qualifier_members[0],
                            "key": qualifier_key,
                            "bm25": 0.0,
                            "formula_qualifier_payload": True,
                            "ownership_context_text": tail_text,
                        }
                    else:
                        payload_entry["formula_qualifier_payload"] = True
                        payload_entry["ownership_context_text"] = tail_text

    # First pass: decide block membership and structural filtering, but do not join text yet -
    # non-seed members still need individual relevance verification, batched in one call.
    block_plan = []
    member_probe_texts: List[str] = []
    member_probe_records: List[Dict[str, str]] = []
    member_probe_index: List[Tuple[int, int]] = []  # (block_plan index, member index)
    for key, entry in best.items():
        members = corpus_by_block.get(key) or [entry["seed"]]
        ordered = sorted(members, key=lambda s: (int(s.get("sent_idx") or 0)))
        # A reference-list entry shattered across single-line blocks can leave an innocuous-
        # looking title fragment as the only surviving member once its year/venue markers score
        # too low to keep. Judge the block's raw, unfiltered membership as a whole - a citation
        # shattered this way is still a citation, whichever fragment happens to be well-scored.
        if not payload_basis(entry):
            _raw_block_text = " ".join(
                str(s.get("sentence_text") or "").strip() for s in ordered).strip()
            if is_bibliography_entry(_raw_block_text) or is_citation_dense(_raw_block_text):
                continue
            # Checked on the SEED sentence specifically, not the joined raw block text: a block
            # can carry an unrelated trailing member (here, 235:16 also holds the start of the
            # NEXT sentence, "Useful guidelines for") that breaks a joined-text substring match
            # even though the seed itself - the sentence that was actually ranked and admitted -
            # is unambiguously a severed fragment of a longer, complete sentence elsewhere in the
            # document. The bibliography check above is joined deliberately, since a shattered
            # citation's identifying markers are spread across the whole block; this one is not,
            # since the fragment's own meaning is severed at the sentence level, not the block
            # level.
            if is_severed_fragment(entry['seed'].get('sentence_text'), key[0], doc_long_sentences):
                continue
            # v35: the forward-truncation mirror of the check above - checked on the same seed
            # text for the same reason (an unrelated trailing block member must not defeat the
            # match against text that was actually ranked and admitted).
            if is_forward_truncated_fragment(entry['seed'].get('sentence_text'), key[0],
                                             doc_all_sentences):
                continue
            # A foreign method name sitting directly behind a definitional-equivalence marker
            # ("as determined by SNN", "Complete Link or MAX or CLIQUE") redefines this unit's own
            # mechanism using a method that is not itself a library unit, so v26's competitive
            # assignment has nothing to lose the passage to. Checked on the raw block text, same
            # reasoning as the bibliography check above: whichever member happens to score well
            # against the query should not matter if the block's own content misattributes the
            # unit's definition to begin with.
            # v49: the raw-block guard intentionally declines blocks over 320 characters, but the
            # sentence that was actually ranked can still be a short, exact misattribution inside
            # such a block. Job 245312 did exactly this for Core Point and DBSCAN Parameters: the
            # 1,022-character block bypassed v33, then its 227-character SNN definition survived.
            # Check both representations so a container-size decision cannot silence the guard.
            _seed_text = str(entry["seed"].get("sentence_text") or "")
            if unit_labels and (
                    attributes_via_definitional_marker(_raw_block_text, unit_labels)
                    or attributes_via_definitional_marker(_seed_text, unit_labels)):
                continue
        seed_id = entry["seed"].get("sentence_id")
        seed_text = entry["seed"].get("sentence_text")
        # a payload block is admitted whole: its members are the formula, and scoring them
        # individually is the very failure this admission exists to correct
        if payload_basis(entry):
            kept = list(ordered) or [entry["seed"]]
        else:
            kept = [s for s in ordered if not is_structural_junk(s)] or [entry["seed"]]
            # Context-aware member retention must not let a non-seed misattribution ride along in
            # an otherwise relevant long block. Apply the same ownership guard to the final member
            # text, after structural filtering, and do not fall back to a rejected member.
            if unit_labels:
                kept = [s for s in kept if not attributes_via_definitional_marker(
                    str(s.get("sentence_text") or ""), unit_labels)]
                if not kept:
                    continue
        plan_idx = len(block_plan)
        # sentence_id alone is not always unique within a block - the source corpus has at least
        # one case (DOC_introduction_to_data_mining:mineru:72:364) where an OCR/segmentation
        # defect assigns the SAME sentence_id to two unrelated sentences. Requiring the text to
        # match too means a genuine id collision no longer exempts an unrelated sentence from
        # member verification just because it shares an id with the real seed.
        _context_text = " ".join(
            str(s.get("sentence_text") or "").strip() for s in ordered).strip()
        block_plan.append({"key": key, "entry": entry, "kept": kept, "is_seed": [
            (s.get("sentence_id") == seed_id and s.get("sentence_text") == seed_text) for s in kept],
            "context_text": _context_text,
            "context_heading": str(entry["seed"].get("patch_heading") or "")})
        if ((member_verifier is not None or context_scorer is not None)
                and not payload_basis(entry)):
            for m_idx, (s, is_seed) in enumerate(zip(kept, block_plan[-1]["is_seed"])):
                if is_seed:
                    continue
                txt = str(s.get("sentence_text") or "").strip()
                if txt:
                    member_probe_texts.append(txt)
                    member_probe_records.append({
                        "text": txt,
                        "context": _context_text,
                        "heading": str(s.get("patch_heading") or entry["seed"].get("patch_heading") or ""),
                    })
                    member_probe_index.append((plan_idx, m_idx))

    # A block member that was never itself judged relevant should not ride along on its seed's
    # score just because it shares a source block - verify each one, batched, against the query
    # actually used for this unit (the caller's verify_scorer/member_verifier closes over it).
    member_keep = {}
    if (member_verifier is not None or context_scorer is not None) and member_probe_texts:
        if context_scorer is not None:
            member_scores = context_scorer(member_probe_records)
            member_floor = CONTEXT_RELEVANCE_FLOOR
        else:
            member_scores = member_verifier(member_probe_texts)
            member_floor = min_relevance
        for (plan_idx, m_idx), score in zip(member_probe_index, member_scores):
            member_keep[(plan_idx, m_idx)] = float(score) >= member_floor

    passages: List[Dict[str, Any]] = []
    for plan_idx, plan in enumerate(block_plan):
        key, entry, kept_all, is_seed = plan["key"], plan["entry"], plan["kept"], plan["is_seed"]
        kept = [s for m_idx, (s, seed) in enumerate(zip(kept_all, is_seed))
               if seed or member_keep.get((plan_idx, m_idx), True)]
        if not kept:
            kept = [entry["seed"]]
        text = " ".join(str(s.get("sentence_text") or "").strip() for s in kept).strip()
        if not text:
            continue
        shapes = sorted({sh for s in kept for sh in shape_of(s)})
        _payload_basis = payload_basis(entry)
        if _payload_basis:
            admission_basis = _payload_basis
        elif key in _defeq_keys:
            admission_basis = "name_anchored_defining_equation"
        elif entry.get("context_score_mode") or (
                context_scorer is not None and any(
                    not seed and member_keep.get((plan_idx, m_idx), False)
                    for m_idx, seed in enumerate(is_seed))):
            admission_basis = "context_anchored_relevance"
        else:
            admission_basis = "cross_encoder_relevance"
        passages.append({
            "doc_id": key[0],
            "block_id": str(entry["seed"].get("block_id") or key[1]),
            "patch_id": entry["seed"].get("patch_id"),
            "page_index": entry["seed"].get("page_index"),
            "patch_heading": entry["seed"].get("patch_heading") or "",
            "relevance": round(entry["relevance"], 6),
            "bm25_score": round(entry["bm25"], 4),
            "shapes": shapes,
            "sentence_count": len(kept),
            "text": text,
            "seed_sentence_id": entry["seed"].get("sentence_id"),
            "admission_basis": admission_basis,
            "verification_context_text": plan.get("context_text") or text,
            "verification_heading": plan.get("context_heading") or "",
            "ownership_context_text": entry.get("ownership_context_text") or "",
            **repaired_formula_provenance(kept),
        })

    # Collapse extractor variants BEFORE spending the budget, so the completeness allowance buys
    # distinct content instead of three renderings of the same paragraph.
    passages = deduplicate_passages(passages)
    # Verify the assembled artifact, not just the sentence that matched. A block that splices in
    # unrelated content (multi-column extraction artefact) still carries its seed's score even
    # though what reaches drafting says something else; re-scoring the assembled text catches it.
    if (verify_scorer is not None or context_scorer is not None) and passages:
        # A lead_in_payload passage (v25) is exempt from this re-score, not merely floored lower.
        # Its admission is already justified by its POINTER, which was independently verified when
        # IT was admitted as a passage - the payload itself is frequently a bare formula, and
        # scored alone it suffers exactly the under-scoring problem the defining-equation floor
        # exists to correct, but with no floor of its own to fall back on. Concretely: without this
        # exemption, Sample Mean and Variance's admitted formula
        # (87188 \mu_j = \bar z = \frac{1}{n}\sum z_r 87188) scored below the floor here and was
        # silently dropped after assemble_passages had already admitted it - the whole point of
        # v25 was defeated by the very re-verification pass that exists to catch splicing, not to
        # re-litigate an admission this function itself just made deliberately.
        to_score = [(i, p) for i, p in enumerate(passages)
                    if p.get("admission_basis") not in POINTER_PAYLOAD_ADMISSION_BASES]
        if context_scorer is not None and to_score:
            verified_scores = context_scorer([{
                "text": str(p.get("text") or ""),
                "context": str(p.get("verification_context_text") or p.get("text") or ""),
                "heading": str(p.get("verification_heading") or ""),
            } for _i, p in to_score])
        else:
            verified_scores = verify_scorer([p["text"] for _i, p in to_score]) if to_score else []
        score_by_index = {i: s for (i, _p), s in zip(to_score, verified_scores)}
        kept: List[Dict[str, Any]] = []
        for i, passage in enumerate(passages):
            if passage.get("admission_basis") in POINTER_PAYLOAD_ADMISSION_BASES:
                kept.append(passage)
                continue
            vscore = score_by_index[i]
            # judge each passage against the floor it was admitted under - a defining equation
            # rescued at the lower floor must not be re-tested against the strict one
            if passage.get("admission_basis") == "name_anchored_defining_equation":
                passage_floor = DEFINING_EQUATION_FLOOR
            elif passage.get("admission_basis") in CONTEXT_ADMISSION_BASES:
                passage_floor = CONTEXT_RELEVANCE_FLOOR
            else:
                passage_floor = min_relevance
            if float(vscore) >= passage_floor:
                passage["verified_relevance"] = float(vscore)
                kept.append(passage)
        passages = kept

    # v42: a rescue-basis passage's relevance is deliberately lower than ordinary admissions -
    # that under-scoring is the entire reason it needed a rescue mechanism in the first place
    # (v25/v34's own reasoning: "this cross-encoder consistently scores short symbolic text lower
    # than descriptive prose... even when the equation is the one thing actually needed"). Sorting
    # by raw relevance alone would let ordinary, lower-value content (a bare heading, a tangential
    # mention) budget-truncate a name-verified formula purely because it happens to score higher -
    # defeating the rescue after every other check already let it through. Rescue-basis passages
    # sort first, unconditionally; ordinary passages still compete on relevance exactly as before,
    # just for what budget remains after the (naturally few, capped) rescues are seated.
    def _admission_sort_rank(p):
        basis = p.get("admission_basis")
        if basis in RESCUE_ADMISSION_BASES:
            return 0
        if basis in CONTEXT_ADMISSION_BASES:
            return 1
        return 2

    passages.sort(key=lambda p: (_admission_sort_rank(p), -p["relevance"]))
    selected: List[Dict[str, Any]] = []
    used = 0
    for p in passages:
        if len(selected) >= max_passages:
            break
        cost = len(p["text"])
        if used + cost > max_chars and selected:
            continue
        selected.append(p)
        used += cost

    # Restore reading order inside each document/page region so procedure steps stay sequential,
    # while keeping the most relevant region first.
    region_rank: Dict[Tuple[str, Any], float] = {}
    for p in selected:
        r = (p["doc_id"], p["page_index"])
        region_rank[r] = max(region_rank.get(r, 0.0), p["relevance"])
    selected.sort(key=lambda p: (-region_rank[(p["doc_id"], p["page_index"])],
                                 p["doc_id"], p["page_index"] or 0,
                                 str(p["block_id"])))
    for i, p in enumerate(selected):
        p["order"] = i
    return selected


# A passage short enough to be a heading, a caption or a stray fragment cannot carry a unit's
# definition however well it scored, so sufficiency is counted over the passages that could.
SUBSTANTIVE_PASSAGE_MIN_WORDS = 8
THIN_EVIDENCE_MAX_PASSAGES = 3
_CONTENT_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]{2,}")


def substantive_passage_count(passages: Sequence[Mapping[str, Any]]) -> int:
    """Passages carrying enough distinct words to establish something about the unit."""
    return sum(1 for p in passages
               if len(set(_CONTENT_WORD_RE.findall(str(p.get("text") or "").lower())))
               >= SUBSTANTIVE_PASSAGE_MIN_WORDS)


def coverage_summary(passages: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    shapes = collections.Counter()
    for p in passages:
        for s in (p.get("shapes") or []):
            shapes[s] += 1
    return {
        "passage_count": len(passages),
        "total_chars": sum(len(p.get("text") or "") for p in passages),
        "sentence_count": sum(int(p.get("sentence_count") or 0) for p in passages),
        "shape_coverage": dict(shapes),
        "has_definition": shapes.get("definition", 0) > 0,
        "has_formula": shapes.get("formula", 0) > 0,
        "has_procedure": shapes.get("procedure", 0) > 0,
        "has_example": shapes.get("example", 0) > 0,
        "distinct_documents": len({p.get("doc_id") for p in passages}),
        # WHICH documents, not only how many. A library whose claim is "grounded in the course
        # source corpus" needs per-unit provenance to state that claim precisely, and a unit whose
        # evidence rests entirely on one document is the case where the claim is narrowest. An
        # external content review of r3 flagged three units as resting on material it could not
        # find in the textbooks; those three are exactly the three units whose admitted evidence
        # comes solely from the guide document, so this reports what a reader had to reconstruct
        # by hand. It is a provenance fact, not a quality judgement: a single-document unit can be
        # perfectly correct, and which documents count as authoritative is not this module's call.
        "evidence_by_document": dict(sorted(
            collections.Counter(str(p.get("doc_id") or "") for p in passages).items())),
        "single_document_evidence": (
            len({p.get("doc_id") for p in passages}) == 1 if passages else False),
        "distinct_pages": len({(p.get("doc_id"), p.get("page_index")) for p in passages}),
        "max_relevance": max([float(p.get("relevance") or 0) for p in passages], default=0.0),
        # A packet this thin, scoring this close to the admission floor, is not solid evidence -
        # flagged so the drafting prompt and the reviewer both know to treat it cautiously rather
        # than as a confidently-grounded unit. Not a forced abstention: a short passage can still
        # be genuinely correct, and forcing abstention would lose that chance.
        "low_confidence": (len(passages) <= 2 and
                           max([float(p.get("relevance") or 0) for p in passages], default=0.0) < 0.60),
        # Sufficiency of the EVIDENCE, reported separately from the drafter's own status, because
        # the two answer different questions and the word "grounded" otherwise carries both. The
        # drafting prompt states its rubric plainly - "Thin evidence, faithfully and completely
        # used, is grounded, not partial" - so status says the draft used what it was given, and
        # says nothing about whether that was enough to teach the unit. Downstream a draft built
        # on one passage and one built on seventeen are indistinguishable.
        # low_confidence does not cover this: it requires few passages AND low relevance, so a
        # thin packet whose single passage scored well passes silently. Measured on the r2
        # packets, 18 units are thin and drafted and unflagged by it, and an external content
        # review of r3 independently named 6 of them materially incomplete, plus 4 more it
        # faulted on other grounds.
        "substantive_passage_count": substantive_passage_count(passages),
        "thin_evidence": substantive_passage_count(passages) <= THIN_EVIDENCE_MAX_PASSAGES,
    }


# A passage ending in one of these is not a statement, it is a promise about what comes next. The
# corpus splits equations into their own blocks, so the promise and its payload are separate
# retrieval units and only the promise reads as relevant to a name-shaped query.
_LEAD_IN_RE = re.compile(
    r"(?:\bis\b|\bare\b|\bgiven by\b|\bdefined as\b|\bas follows\b|\bcomputed as\b"
    r"|\bexpressed as\b|\bfollowing\b)\s*[:.]?\s*$"
    # v36: a bare trailing colon on its own, regardless of the words before it - "...according to
    # the Bayes' theorem:", "...which is known as Bayes theorem:", "...given by Equation 4.11:".
    # The original trigger-word list requires the verb phrase to sit immediately before the colon,
    # which real prose routinely violates by naming its referent in between. Safe to broaden
    # because is_formula_payload on the successor block is the real gate, not this check.
    r"|:\s*$", re.IGNORECASE)

_STRUCTURED_LIST_LEAD_RE = re.compile(
    r"\b(?:the\s+)?following\s+(?:three\s+)?"
    r"(?:properties|conditions|requirements|criteria)\s+"
    r"(?:hold|apply|follow|are\s+(?:required|satisfied))\s*[.:]?\s*$",
    re.IGNORECASE)

_PROCEDURE_LIST_LEAD_RE = re.compile(r"\bas\s+follows\s*[.:]?\s*$", re.IGNORECASE)
_DEFINITION_LIST_LEAD_RE = re.compile(
    r"\b(?:defined|definition|denoted|written)\s+as\s+follows\s*[.:]?\s*$",
    re.IGNORECASE)

_NUMBERED_LIST_HEADING_RE = re.compile(
    r"^\s*(?:\(?\d{1,2}[.)]|[a-z][.)])\s+\S", re.IGNORECASE)

_PAYLOAD_MAX_CHARS = 400


# A reference marker trailing the promise - "...the Laplace estimate:[1, p." - where the source's
# own citation was split across extraction rows. The promise is intact; only the citation debris
# sits after it.
_TRAILING_CITATION_DEBRIS_RE = re.compile(
    r"(?:\[[^\]]*\]?|\((?:[^)]*)\)?)\s*$")


def ends_with_lead_in(text: str) -> bool:
    """True when a passage promises a formula rather than stating one.

    A trailing citation fragment is ignored: the corpus splits references across rows, which
    leaves debris after the promising colon ("...the Laplace estimate:[1, p.") and would otherwise
    hide the lead-in. This widens nothing by itself - is_formula_payload on the successor block
    remains the real gate, per the v36 reasoning on _LEAD_IN_RE.
    """
    raw = str(text or "").strip()
    if _LEAD_IN_RE.search(raw):
        return True
    trimmed = _TRAILING_CITATION_DEBRIS_RE.sub("", raw).strip()
    return bool(trimmed) and trimmed != raw and bool(_LEAD_IN_RE.search(trimmed))


def ends_with_structured_list_lead_in(text: str) -> bool:
    """True only for an explicit promise of a following property/condition list."""
    return bool(_STRUCTURED_LIST_LEAD_RE.search(str(text or "").strip()))


def is_formula_payload(text: str) -> bool:
    """True for compact, formula-shaped text - the kind of block a lead-in points at."""
    raw = str(text or "").strip()
    if not raw or len(raw) > _PAYLOAD_MAX_CHARS:
        return False
    if math_rendering_damaged(raw):
        return False  # a destroyed rendering is not worth inheriting relevance
    # Greek letters or one inline equality inside a prose paragraph made has_mathematics true
    # and turned the whole paragraph into an exempt lead-in payload. In that admitted a
    # 343-character SVM discussion after a stray `ys=...` prefix into Euclidean and Cosine packets.
    # Long non-display payloads must remain symbol-dominant rather than ordinary sentence prose.
    if len(raw) > 240 and not raw.startswith("$$"):
        long_words = re.findall(r"\b[A-Za-z]{4,}\b", raw)
        if len(long_words) >= 18:
            return False
    return bool(_RELATIONAL_RE.search(raw)) or has_mathematics(raw)


# A qualifier sentence says what the symbols of the formula before it mean. In these documents
# it opens with "where", and the mathematics requirement keeps ordinary prose that happens to
# begin with that word out. This is the mirror of _LEAD_IN_RE: that one recognises a promise whose
# payload FOLLOWS, this one recognises a gloss whose formula PRECEDES.
_QUALIFIER_OPENING_RE = re.compile(r"^\s*(?:where|in which|here,)\b", re.IGNORECASE)


def defines_the_symbols_above(text: str) -> bool:
    """True for a glossary block belonging to the formula immediately before it."""
    raw = str(text or "").strip()
    if not raw or len(raw) > _PAYLOAD_MAX_CHARS:
        return False
    if not _QUALIFIER_OPENING_RE.match(raw):
        return False
    return has_mathematics(raw)


def structured_list_payload_keys(
        pointer_key: Tuple[str, str],
        block_successors: Mapping[Tuple[str, str], Tuple[str, str]],
        corpus_by_block: Mapping[Tuple[str, str], List[Mapping[str, Any]]],
        max_blocks: int = 8) -> List[Tuple[str, str]]:
    """Return a consecutive numbered-heading plus formula list owned by a lead passage.

    This is intentionally narrower than generic block continuation. The first successor must be
    a numbered list heading, every later block must be another numbered heading or an intact
    formula payload, and all blocks must remain on the pointer's page/patch. At least one formula
    is required, so chapter lists and ordinary prose enumerations do not receive pointer rescue.
    """
    pointer_members = corpus_by_block.get(pointer_key) or []
    if not pointer_members:
        return []
    pointer_patch = str(pointer_members[0].get("patch_id") or "")
    pointer_page = pointer_members[0].get("page_index")
    current = block_successors.get(pointer_key)
    out: List[Tuple[str, str]] = []
    saw_formula = False
    for position in range(max_blocks):
        if not current:
            break
        members = corpus_by_block.get(current) or []
        if not members:
            break
        member_patch = str(members[0].get("patch_id") or "")
        member_page = members[0].get("page_index")
        if pointer_patch and member_patch != pointer_patch:
            break
        if pointer_page is not None and member_page != pointer_page:
            break
        text = " ".join(
            str(s.get("sentence_text") or "").strip()
            for s in sorted(members, key=lambda s: int(s.get("sent_idx") or 0))).strip()
        numbered_heading = bool(_NUMBERED_LIST_HEADING_RE.match(text)) and len(text) <= 120
        formula_payload = is_formula_payload(text)
        if position == 0:
            if not numbered_heading:
                break
        elif not (numbered_heading or formula_payload):
            break
        out.append(current)
        saw_formula = saw_formula or formula_payload
        current = block_successors.get(current)
    return out if saw_formula else []


def procedure_list_payload_keys(
        anchor_key: Tuple[str, str],
        block_predecessors: Mapping[Tuple[str, str], Tuple[str, str]],
        block_successors: Mapping[Tuple[str, str], Tuple[str, str]],
        corpus_by_block: Mapping[Tuple[str, str], List[Mapping[str, Any]]],
        max_back: int = 6,
        max_forward: int = 8) -> Tuple[List[Tuple[str, str]], str]:
    """Recover a bounded, unnumbered procedure around one independently admitted step.

    Some extraction lanes strip list numbering, so a complete source procedure can become a run
    of short blocks whose middle step alone clears relevance. Recovery is licensed only when the
    anchor belongs to a same-page, same-patch sequence with an explicit ``as follows`` lead-in,
    at least two procedure-shaped blocks, and a terminal formula boundary. The formula is a stop
    marker rather than inherited evidence because its rendering may be the reason it scored low.
    """
    anchor_members = corpus_by_block.get(anchor_key) or []
    if not anchor_members or not any(s.get("is_procedure_like") for s in anchor_members):
        return [], ""
    anchor_patch = str(anchor_members[0].get("patch_id") or "")
    anchor_page = anchor_members[0].get("page_index")

    def same_region(key: Tuple[str, str]) -> bool:
        members = corpus_by_block.get(key) or []
        if not members:
            return False
        patch = str(members[0].get("patch_id") or "")
        page = members[0].get("page_index")
        return ((not anchor_patch or patch == anchor_patch)
                and (anchor_page is None or page == anchor_page))

    pointer = None
    pointer_text = ""
    current = anchor_key
    for _ in range(max_back):
        current = block_predecessors.get(current)
        if not current or not same_region(current):
            break
        members = corpus_by_block.get(current) or []
        text = " ".join(
            str(s.get("sentence_text") or "").strip()
            for s in sorted(members, key=lambda s: int(s.get("sent_idx") or 0))).strip()
        if _PROCEDURE_LIST_LEAD_RE.search(text):
            if _DEFINITION_LIST_LEAD_RE.search(text):
                break
            pointer, pointer_text = current, text
            break
        if len(text) > _PAYLOAD_MAX_CHARS or any(
                s.get("is_formula_like") for s in members):
            break
    if pointer is None:
        return [], ""

    out: List[Tuple[str, str]] = []
    procedure_blocks = 0
    saw_formula_boundary = False
    current = block_successors.get(pointer)
    for position in range(max_forward):
        if not current or not same_region(current):
            break
        members = corpus_by_block.get(current) or []
        text = " ".join(
            str(s.get("sentence_text") or "").strip()
            for s in sorted(members, key=lambda s: int(s.get("sent_idx") or 0))).strip()
        # The overlay's formula flag is intentionally recall-heavy: the real third prose step is
        # marked formula-like merely because it contains ``mi > m0``. A terminal boundary must be
        # equation-dominant, not ordinary prose carrying one relation. This distinction is what
        # keeps the p-value comparison step while stopping before its compact rendered equation.
        long_words = re.findall(r"\b[A-Za-z]{4,}\b", text)
        formula_flagged = any(s.get("is_formula_like") for s in members)
        equation_dominant = (
            text.startswith("$$")
            or (len(long_words) <= 8
                and (formula_flagged or is_formula_payload(text)))
        )
        if equation_dominant:
            saw_formula_boundary = True
            break
        step_shaped = (any(s.get("is_procedure_like") for s in members)
                       or bool(_NUMBERED_LIST_HEADING_RE.match(text)))
        if position == 0 and not step_shaped:
            break
        if not text or len(text) > _PAYLOAD_MAX_CHARS:
            break
        # A source block can carry several sentence records with conflicting shape flags. The
        # real p-value prose block has one auxiliary heading-like record, so ``any`` silently
        # stopped the continuation even though its substantive record is prose. Only a uniformly
        # heading-shaped block is a structural boundary here.
        if all(s.get("is_heading_like") for s in members) and not step_shaped:
            break
        out.append(current)
        procedure_blocks += int(step_shaped)
        current = block_successors.get(current)

    if (anchor_key not in out or len(out) < 3 or procedure_blocks < 2
            or not saw_formula_boundary):
        return [], ""
    return out, pointer_text


def _block_order_key(block_id: str):
    """Sortable position of a block within its document+extractor rendering."""
    parts = str(block_id or "").split(":")
    tail = []
    for p in parts[2:]:
        try:
            tail.append((0, int(p)))
        except (TypeError, ValueError):
            tail.append((1, p))
    return tail


def build_block_successor_index(corpus: Sequence[Mapping[str, Any]]) -> Dict[Tuple[str, str], Tuple[str, str]]:
    """Map each block to the block that immediately follows it in the same rendering.

    Blocks are grouped by document AND extractor, because the three extractors number their
    output independently and interleaving them would produce meaningless adjacency.
    """
    groups: Dict[Tuple[str, str], Dict[str, set]] = collections.defaultdict(
        lambda: collections.defaultdict(set))
    for s in corpus:
        doc = str(s.get("doc_id") or "")
        bid = str(s.get("block_id") or s.get("patch_id") or "")
        if not bid:
            continue
        parts = bid.split(":")
        extractor = parts[1] if len(parts) > 1 else ""
        groups[(doc, extractor)][bid].add(_block_key(s))

    successor: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for (_doc, _extractor), keys_by_bid in groups.items():
        ordered = sorted(keys_by_bid, key=_block_order_key)
        for a, b in zip(ordered, ordered[1:]):
            a_keys, b_keys = keys_by_bid[a], keys_by_bid[b]
            # A reused extractor ID has no unambiguous adjacency. Refuse pointer rescue across
            # either side of it; normal retrieval can still admit each fingerprinted block.
            if len(a_keys) == 1 and len(b_keys) == 1:
                successor[next(iter(a_keys))] = next(iter(b_keys))
    return successor


# Words too generic to indicate two units are about the same thing.
_RIVAL_STOPWORDS = frozenset("""
a an and or the of for in on to with by from as at is are its it this that these those
index measure method approach technique algorithm model function value score rate phase
type types kind form problem basic basics fundamental fundamentals overview introduction
using based general generic simple standard common main core key primary
""".split)

RIVAL_LIMIT = 6
CLAIM_MARGIN = 0.08
MIN_KEEP = 2


def _name_content_words(name: str) -> set:
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", str(name or "").lower())
    return {w for w in words if w not in _RIVAL_STOPWORDS}


# Generic English function words only. This list carries no subject matter: it is the same class of
# list any term-extraction implementation needs in order to reject grammatical collocations, and it
# is corpus-independent.
_TERM_EXTRACTION_STOPWORDS = frozenset("""
a an the of to in for on with and or is are was were be been being this that these those it its as
at by from not no if then than which who whom whose what when where how we you they he she can may
might will would should could must do does did have has had our their his her your my me us them
there here also such other more most some any each per via using used use one two three both all
only same so but into out up down over under again further once about between during before after
few many much less least very just now new old first second next last etc ie eg let given see
figure table example note thus hence therefore however because while does don t s
""".split)

_TERM_TOKEN_RE = re.compile(r"[a-z][a-z0-9-]{1,}")


def build_corpus_term_inventory(corpus: Sequence[Mapping[str, Any]], *,
                                text_key: str = "sentence_text",
                                min_freq: int = 4,
                                max_terms: int = 20000) -> List[str]:
    """Candidate competing concepts, derived from the supplied corpus rather than curated.

    Standard automatic term recognition: contiguous 2-3 token n-grams containing no stop word and
    no short token, kept at min_freq or above, ranked by frequency weighted against the rarest
    constituent unigram (a C-value / PMI-style association score, so that a phrase whose words are
    individually rare outranks an equally frequent phrase built from very common words).

    This exists because find_rival_units only knows about curriculum units, while a corpus
    routinely discusses concepts that are not units at all. A passage about such a concept scores
    well for any unit sharing a word with it, and without the concept in the rival pool the
    adjudication in drop_passages_claimed_by_rivals never gets the chance to disown it.

    Domain agnosticity: the only vocabulary here is generic English function words. Every returned
    term comes from the corpus that was actually supplied.
    """
    unigrams: Dict[str, int] = collections.Counter()
    grams: Dict[str, int] = collections.Counter()
    for row in corpus:
        if not isinstance(row, Mapping):
            continue
        words = _TERM_TOKEN_RE.findall(str(row.get(text_key) or "").lower())
        if not words:
            continue
        unigrams.update(words)
        for size in (2, 3):
            for start in range(len(words) - size + 1):
                gram = words[start:start + size]
                if any(w in _TERM_EXTRACTION_STOPWORDS or len(w) < 3 for w in gram):
                    continue
                grams[" ".join(gram)] += 1

    scored: List[Tuple[float, str]] = []
    for gram, count in grams.items():
        if count < min_freq:
            continue
        rarest = min(unigrams.get(part, 1) for part in gram.split()) or 1
        scored.append((count * (count / float(rarest)), gram))
    scored.sort(reverse=True)
    return [gram for _, gram in scored[:max_terms]]


def find_rival_concepts(unit_name: str, corpus_terms: Sequence[str],
                        all_unit_names: Sequence[str],
                        passages: Optional[Sequence[Mapping[str, Any]]] = None,
                        limit: int = RIVAL_LIMIT) -> List[str]:
    """Corpus-derived concepts that could claim this unit's passages but are not curriculum units.

    Same rivalry condition find_rival_units uses (a shared content word), applied to the
    corpus-derived inventory instead of the unit list. Two exclusions keep this from fighting
    itself: a term whose content words are a subset of the unit's own name would have the unit
    competing against a restatement of itself, and a term already covered by a real curriculum unit
    is left to find_rival_units so a passage is not adjudicated twice against the same concept.

    Ranking is by presence in this unit's OWN candidate passages, not by similarity to its name.
    Name overlap answers the wrong question: a concept that never appears in the pack cannot be
    contaminating it, and a concept that dominates a passage is worth adjudicating even when it
    shares only one word with the unit's name. Measured on the real corpus, ranking by name overlap
    put "jarvis-patrick clustering" outside the cut for "Hierarchical Clustering Complexity" - the
    exact foreign concept that unit's hardcoded rule existed to disown - because it shares only the
    word "clustering", while terms sharing two words crowded it out. Passage presence puts it back.
    """
    own = _name_content_words(unit_name)
    if not own:
        return []
    unit_word_sets = [_name_content_words(other) for other in all_unit_names or []]

    candidates = []
    for term in corpus_terms or []:
        words = _name_content_words(term)
        if not words:
            continue
        shared = own & words
        if not shared:
            continue
        if words <= own:
            continue  # a restatement of this unit's own name, not a competitor
        if own <= words:
            # An ELABORATION of this unit's name ("average gini index" for "Gini Index"), not a
            # competing concept. Measured: a cross-encoder systematically prefers the more specific
            # phrasing of the same concept, so admitting these as rivals produced an 8.9% false-drop
            # rate on already-admitted evidence in validation. A term only competes when
            # the two names diverge, rather than one refining the other.
            continue
        if any(words == other for other in unit_word_sets):
            continue  # a real curriculum unit; find_rival_units() already owns this comparison
        candidates.append((term, len(shared), len(words)))

    if not candidates:
        return []

    haystacks = []
    for passage in passages or []:
        if isinstance(passage, Mapping):
            haystacks.append(normalized_label_phrase(
                "%s %s" % (passage.get("patch_heading") or "", passage.get("text") or "")))
    scored = []
    for term, shared, specificity in candidates:
        phrase = normalized_label_phrase(term)
        present = sum(1 for hay in haystacks if phrase and phrase in hay)
        scored.append((present, shared, specificity, term))
    # A term actually present in the pack outranks any term that merely resembles the unit's name.
    scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    if haystacks and scored and scored[0][0] > 0:
        scored = [row for row in scored if row[0] > 0]
    return [term for _, _, _, term in scored[:limit]]


def find_rival_units(unit_name: str, all_unit_names: Sequence[str],
                     limit: int = RIVAL_LIMIT) -> List[str]:
    """Other units of this library whose names could be confused with this one.

    Two units are rivals when they share a content word, which is exactly the condition under
    which a relevance model scoring a passage about one will also score well for the other.
    """
    own = _name_content_words(unit_name)
    if not own:
        return []
    scored = []
    for other in all_unit_names:
        if not other or other == unit_name:
            continue
        shared = own & _name_content_words(other)
        if shared:
            # prefer the most confusable rivals: most shared words, then most specific name
            scored.append((len(shared), -len(_name_content_words(other)), other))
    scored.sort(reverse=True)
    return [name for _, _, name in scored[:limit]]


_COMPOUND_GENERIC_WORDS = frozenset({"external", "internal", "index", "measure", "metric",
                                     "coefficient", "score"})


def _compound_formula_base(name: str) -> str:
    tail = str(name or "").split(":")[-1]
    words = [w for w in re.findall(r"[A-Za-z0-9]+", tail.lower())
             if w not in _COMPOUND_GENERIC_WORDS]
    return "".join(words)


def _compound_qualifier_terms(compound_name: str) -> set:
    """Content words of a compound unit name's QUALIFIER, i.e. everything but its base.

    "External Index: Precision" -> {"external", "index"}. These words are the generic context test
    for whether a passage naming only the plain base belongs to the compound unit, derived from the
    curriculum's own naming rather than from a curated vocabulary list.
    """
    raw = str(compound_name or "")
    if ":" in raw:
        qualifier = raw.rsplit(":", 1)[0]
    else:
        qualifier = ""
    return _name_content_words(qualifier)


def _split_terms(terms):
    """Hyphen/underscore-joined tokens split into parts, so "Cross-Price" meets "cross price"."""
    out = set()
    for term in terms or ():
        for part in re.split(r"[-\u2013\u2014_/]+", str(term)):
            if part:
                out.add(part)
    return out


def _base_equation_in(raw: str, subject: str) -> bool:
    pattern = (r"(?<![A-Za-z])" + subject
               + r"\s*(?:[_^]?\s*\{?\s*\w{1,4}\s*\}?)?\s*=(?!\s*=)")
    return bool(re.search(pattern, raw, re.I))


def base_defining_equation_present(raw: str, own_base: str) -> bool:
    """True when the passage STATES the base unit's own equation in non-indexed form.

    "F = ...", "F1 = ...", "F_beta = ..." are the base metric defining itself. "F(i,j) = ..." is
    not: a two-index argument form is the qualified variant's own notation, so its presence
    anywhere in the passage disqualifies the passage from base ownership even when it also opens
    with a bare "F =" (e.g. "F = SUM_j (m_j/m) max_i F(i,j)" defines the external index itself).

    Both the raw text and the compacted signature are checked, because LaTeX wrappers hide the
    equation from a raw match ("\\mathsf { F } \\mathsf { B } =") - the same normalisation this
    module already applies wherever structural shape must survive the extractor's spelling.
    """
    subject = re.escape(str(own_base or ""))
    if not subject:
        return False
    if re.search(subject + r"\s*\(\s*[a-z]\s*,\s*[a-z]\s*\)", raw, re.I):
        return False
    return any(_base_equation_in(candidate, subject)
               for candidate in (raw, compact_formula_signature(raw)))


def compound_sibling_formula_owner(text: str, unit_name: str,
                                   rival_names: Sequence[str],
                                   all_unit_names: Sequence[str] = (),
                                   unit_branch_terms: Optional[Mapping[str, Any]] = None
                                   ) -> Optional[str]:
    """Own a passage by the compound unit that qualifies it, not by a plain-named sibling.

    Where a curriculum contains both a plain unit ("Precision") and a qualified one
    ("External Index: Precision"), a passage stating the qualified unit's formula usually names only
    the plain base. Ownership is decided by whether the qualifier's own words are present in the
    passage's context.

    all_unit_names is searched rather than only rival_names because compound units frequently live
    under a different hierarchy branch from their plain counterpart, so rival discovery - which is
    capped at RIVAL_LIMIT and scoped by shared content word - cannot be relied on to surface them.
    This replaced a hardcoded owner map that existed solely to paper over that gap.
    """
    if ":" in str(unit_name or ""):
        return None
    own_base = _compound_formula_base(unit_name)
    if not own_base:
        return None
    raw = str(text or "")
    compact_raw = re.sub(r"[^a-z0-9]+", "", raw.lower())
    # A single-character base cannot be substring-matched reliably (it would hit every word
    # containing that letter), so a short base is required to appear as a named function form.
    if len(own_base) <= 1:
        head_present = bool(re.search(
            r"\b" + re.escape(own_base) + r"\s*-?\s*\w*\b|\b" + re.escape(own_base)
            + r"\s*\(\s*[a-z]\s*(?:,\s*[a-z]\s*)?\)", raw, re.I))
    else:
        head_present = own_base in compact_raw
    if not head_present:
        return None
    owners = [
        str(rival) for rival in rival_names or []
        if ":" in str(rival or "") and _compound_formula_base(rival) == own_base
    ]
    # Compound counterparts often sit on a different hierarchy branch, outside this unit's rival
    # set, so the whole library is searched for them rather than only the rivals.
    for candidate in all_unit_names or []:
        name = str(candidate or "")
        if ":" not in name or name == str(unit_name or ""):
            continue
        if _compound_formula_base(name) == own_base and name not in owners:
            owners.append(name)
    for rival in owners:
        subject = re.escape(own_base)
        indexed_equation = re.search(
            r"\b(?i:" + subject + r")\s*\(\s*[a-z]\s*(?:,\s*[a-z]\s*)?\)\s*=", raw)
        # Context that distinguishes THIS compound sibling's branch from the base unit's own,
        # taken from the curriculum's hierarchy rather than from a word list. Shared ancestry
        # cancels out, so only genuinely discriminating terms can carry a transfer.
        branch_terms = dict(unit_branch_terms or {})
        discriminating = _split_terms(branch_terms.get(rival) or ())
        discriminating -= _split_terms(branch_terms.get(unit_name) or ())
        qualifier_terms = _split_terms(_compound_qualifier_terms(rival))
        passage_terms = _split_terms(_name_content_words(raw))
        external_context = bool(
            (qualifier_terms and qualifier_terms <= passage_terms)
            or (discriminating and (discriminating & passage_terms))
        )
        # Context may transfer a passage that MENTIONS the base; it may not transfer one that
        # STATES the base's own defining equation. The indexed form is the qualified variant's
        # own notation and still transfers.
        if indexed_equation:
            return str(rival)
        if external_context and not base_defining_equation_present(raw, own_base):
            return str(rival)
    return None


def drop_compound_sibling_formulas(passages, unit_name, rival_names,
                                   all_unit_names=(), unit_branch_terms=None):
    kept, dropped = [], []
    for passage in passages or []:
        text = str(passage.get("text") or "")
        ownership_context = str(passage.get("ownership_context_text") or "")
        patch_heading = str(passage.get("patch_heading") or "")
        owned_parts = [text]
        for context in (ownership_context, patch_heading):
            if context and context not in text:
                owned_parts.append(context)
        owned_text = " ".join(owned_parts)
        owner = compound_sibling_formula_owner(
            owned_text, unit_name, rival_names, all_unit_names, unit_branch_terms)
        if owner:
            dropped.append({
                "text": text[:200],
                "rival": owner,
                # Generic label: the mechanism derives the owning compound unit from the curriculum itself,
                # so the reason recorded in output artifacts must not name one curriculum's vocabulary.
                "reason": "compound_sibling_ownership",
            })
        else:
            kept.append(passage)
    return kept, dropped


# Deliberately empty, and the verify suite asserts it stays that way. Listing one curriculum's
# clustering vocabulary here would tie the pipeline to that corpus and could never fire for any
# other, so the empty set is the correct value rather than a placeholder to be filled in.
_STANDARD_DBSCAN_UNITS = frozenset()


def semantic_misbinding_owner(text: str, unit_name: str,
                              rival_names: Sequence[str]) -> Optional[Tuple[str, str]]:
    """Disabled 2026-08-17. Retained as a seam; returns None for every input.

    This function previously held 18 rules of the form
        if compact_name == "<a specific data-mining KC name>" and re.search("<a foreign concept>")
    covering learning phase, querying phase, mutually exclusive classes, cost matrix, hierarchical
    clustering complexity, models of randomness approaches 1 and 2, density connected, euclidean
    distance, cosine similarity, non deterministic search, filter approach, sample mean and
    variance, sse cluster quality and shannon entropy. Each was written against a real observed
    contamination, and each could only ever fire for the one curriculum whose KC happened to be
    named. Measured: 66 drops on data-mining, 0 on sociology, 0 on mathematics - the primary
    evaluation domain was receiving contamination removal the other two never got, which is both a
    false domain-agnosticity claim and a cross-domain confound.

    Two generic replacements were built and REJECTED on measurement rather than assumption
    (DOMAIN_AGNOSTICITY_REMEDIATION.md D-1): a corpus-derived concept-rival mechanism reproduced
    20% then 15% of these drops while FALSELY dropping 8.9% then 6.9% of already-admitted evidence.
    Both are worse than removal, which costs a measured 2.6% evidence increase (66 of 2,556 items,
    touching 20 of 159 units).

    What carries the load instead, all domain-agnostic and all already in place:
      * drop_passages_claimed_by_rivals - cross-encoder adjudication against library units, which
        already performs the majority of drops in every corpus (109/175, 106/108, 23/29).
      * The evidence-first drafting contract's explicit KC boundary, which gives the drafter
        sibling_kc_names and rival_units_considered as contrast and forbids absorbing them.
      * Sociology is the evidence that this suffices: it has a HARDER name-collision profile than
        data-mining (mean 3.24 rivals per unit against 2.16, 36% of units saturating RIVAL_LIMIT
        against 9%) and reached 96.0% grounded with 0 hard failures on the generic mechanism alone,
        while data-mining WITH all 66 rules drafted at 78.0%.

    Kept as a no-op rather than deleted so the call site, its drop-reason plumbing and the
    liveness checks that assert this stays empty all remain meaningful.
    """
    return None

def drop_damaged_math_passages(passages):
    """Apply the math-integrity contract to the final assembled text."""
    kept, dropped = [], []
    for passage in passages or []:
        text = str(passage.get("text") or "")
        if math_rendering_damaged(text):
            dropped.append({
                "text": text,
                "rival": "damaged mathematical rendering",
                "reason": "assembled_passage_math_rendering_damaged",
            })
        else:
            kept.append(passage)
    return kept, dropped


def drop_semantically_misbound_passages(passages, unit_name, rival_names):
    kept, dropped = [], []
    for passage in passages or []:
        text = str(passage.get("text") or "")
        ownership_context = str(passage.get("ownership_context_text") or "")
        owned_text = text + ((" " + ownership_context)
                             if ownership_context and ownership_context not in text else "")
        result = semantic_misbinding_owner(
            owned_text, unit_name, rival_names)
        if result:
            owner, reason = result
            dropped.append({
                "text": text[:200],
                "rival": owner,
                "reason": reason,
            })
        else:
            kept.append(passage)
    return kept, dropped


# Admission bases whose ownership was already established through a mechanism more specific
# than ordinary cross-encoder relevance - a pointer independently verified at admission
# (lead_in_payload, v25) or a pattern anchored to the unit's own label text
# (name_anchored_defining_equation, v34). ANY post-admission re-verification pass added to this
# module - present or future - must check membership in this set before re-litigating relevance
# or ownership for these passages, or it risks silently defeating the very mechanism that admitted
# them. This is not a hypothetical: v25 was silently defeated by verify_scorer before its own
# exemption was added, and v34 was silently defeated by drop_passages_claimed_by_rivals (v26)
# before v37 added ITS exemption - for name_anchored_defining_equation only, which is what left
# THIS gap (lead_in_payload, unexempted from the very same check) for v38 to close. One shared
# constant, checked everywhere a re-verification pass runs, closes the whole class of bug at once
# instead of one instance at a time.
# One tuple, read by every site that treats these bases alike. INT-15 was caused by the
# alternative: three branches enumerated by hand at four separate sites, one of which quietly
# behaved differently from its siblings for as long as nobody compared them. Adding a fourth
# member by hand would invite that defect straight back, so the membership is stated once.
PAYLOAD_ADMISSION_FLAGS = (
    "lead_in_payload", "structured_list_payload", "procedure_list_payload",
    "formula_qualifier_payload",
)


def payload_basis(entry: Mapping[str, Any]) -> Optional[str]:
    """The source-structure basis this entry carries, or None for an ordinary admission."""
    for flag in PAYLOAD_ADMISSION_FLAGS:
        if entry.get(flag):
            return flag
    return None


POINTER_PAYLOAD_ADMISSION_BASES = frozenset(PAYLOAD_ADMISSION_FLAGS)
RESCUE_ADMISSION_BASES = POINTER_PAYLOAD_ADMISSION_BASES | {"name_anchored_defining_equation"}


def drop_passages_claimed_by_rivals(passages, unit_name, rival_names, scorer,
                                    margin: float = CLAIM_MARGIN, min_keep: int = MIN_KEEP):
    """Remove passages another unit of this library claims more strongly than this one.

    scorer(query, texts) -> list of probabilities. Called once per rival over the passage texts,
    so cost is len(rival_names) batched calls regardless of how many passages there are.

    Returns (kept, dropped) where dropped records why, so the decision is auditable rather than
    silently applied.
    """
    if not passages or not rival_names:
        return list(passages), []
    # v37: a name_anchored_defining_equation passage's ownership was already established at
    # admission time by anchoring to the unit's OWN label text - a cross-encoder re-score against
    # a rival's bare (often shorter, more generic) name is systematically biased toward the rival
    # regardless of true ownership, and would silently re-litigate and defeat an admission this
    # project's own equation-recognition pattern already made deliberately. Scored passages exclude
    # these; they are always kept, exactly as lead_in_payload passages are always kept by the OTHER
    # re-verification pass (verify_scorer) for the identical reason.
    scoreable = [(i, p) for i, p in enumerate(passages)
                if p.get("admission_basis") not in RESCUE_ADMISSION_BASES]
    texts = [str(p.get("text") or "") for _i, p in scoreable]
    own_scored = scorer(unit_name, texts) if texts else []
    own = {i: float(s) for (i, _p), s in zip(scoreable, own_scored)}
    best_rival = collections.defaultdict(float)
    best_rival_name = collections.defaultdict(str)
    for rival in rival_names:
        rival_scored = scorer(rival, texts) if texts else []
        for (i, _p), sc in zip(scoreable, rival_scored):
            if float(sc) > best_rival[i]:
                best_rival[i] = float(sc)
                best_rival_name[i] = rival

    ranked = []
    for i, p in enumerate(passages):
        if p.get("admission_basis") in RESCUE_ADMISSION_BASES:
            claimed = False
            own_i = 1.0  # never the weakest passage when min_keep forcing ranks by own strength
        else:
            claimed = best_rival[i] - own[i] > margin
            own_i = own[i]
        ranked.append((claimed, own_i, i, p))

    kept, dropped = [], []
    for claimed, own_score, i, p in ranked:
        if claimed:
            dropped.append({
                "text": str(p.get("text") or "")[:200], "own_score": round(own_score, 4),
                "rival": best_rival_name[i], "rival_score": round(best_rival[i], 4),
            })
        else:
            kept.append(p)
    # never zero a unit out silently - keep its strongest passages and let the packet's own
    # support-state reporting carry the fact that its evidence is contested
    if len(kept) < min_keep and passages:
        by_strength = sorted(ranked, key=lambda r: -r[1])
        forced = [p for _c, _s, _i, p in by_strength[:min_keep]]
        seen = {id(p) for p in kept}
        for p in forced:
            if id(p) not in seen:
                kept.append(p)
                seen.add(id(p))
    order = {id(p): n for n, p in enumerate(passages)}
    kept.sort(key=lambda p: order.get(id(p), 0))
    return kept, dropped


# A properly-cased source's real sentences start with a capital letter. A lowercase start is
# close to unambiguous evidence that this "sentence" is actually a fragment severed from a longer
# one by a PDF line-break, not a judgement about its content - which is exactly why this check
# looks at case and length rather than trying to guess at meaning.
_LOWERCASE_START_RE = re.compile(r"^[a-z]")
_LONG_COMPLETE_MIN_CHARS = 60


def build_document_long_sentences(corpus: Sequence[Mapping[str, Any]]) -> Dict[str, List[str]]:
    """Per document, every sentence long and properly-cased enough to be a real, complete one.

    Used to recognise a short lowercase-starting fragment as literally contained in a fuller
    rendering of the same content from a different extractor - the corpus keeps up to three
    renderings of every passage, and only one of them needs to have kept the sentence whole.
    """
    out: Dict[str, List[str]] = collections.defaultdict(list)
    for s in corpus:
        text = str(s.get("sentence_text") or "").strip()
        if len(text) < _LONG_COMPLETE_MIN_CHARS or _LOWERCASE_START_RE.match(text):
            continue
        out[str(s.get("doc_id") or "")].append(text)
    return dict(out)


# Deliberately narrower than is_formula_payload's own formula-shape test: anchored to the START
# of the text (a short identifier, optionally with a parenthesised subscript/argument, then a
# relational operator, all within roughly the first 80 characters, or a LaTeX "$" delimiter) rather
# than "a relational operator appears anywhere". A prose sentence that merely MENTIONS an
# attribute-value comparison partway through ("...for Marital Status = Married in class...") never
# matches this from position zero; only text that IS a formula from its own first token does.
_FORMULA_START_RE = re.compile(
    r"^[a-z][a-zA-Z0-9_]{0,20}(?:\([^)]{0,60}\))?\s*[=<>\u2264\u2265\u2260]|^\$")


def is_severed_fragment(text: str, doc_id: str,
                        doc_long_sentences: Optional[Mapping[str, Sequence[str]]]) -> bool:
    """True when text is a lowercase-starting fragment contained in a fuller sentence elsewhere.

    Deliberately substring, not fuzzy: a false negative here just leaves a fragment unflagged,
    same as before this check existed; a false positive would suppress real content, so the bar
    for firing is exact containment, not similarity.
    """
    raw = str(text or "").strip()
    if not raw or not _LOWERCASE_START_RE.match(raw) or not doc_long_sentences:
        return False
    # v40: a compact formula ("precision(i,j)=pij.") is routinely ALSO folded into a longer
    # explanatory sentence elsewhere in the same document ("The precision of cluster i ... is
    # precision(i,j)=pij.") - that is the corpus restating its own definition, not a PDF line-break
    # truncating the formula. The lowercase-start signal this check relies on means something
    # different for a formula (a lowercase variable name, e.g. "p...") than for prose (almost
    # always evidence of a severed sentence). Deliberately START-ANCHORED, not "contains a
    # relational operator anywhere" - a library-wide scan found real prose fragments that mention
    # an attribute-value comparison mid-sentence ("raw zero probability for Marital Status =
    # Married in class Y was preventing the stronger income", genuinely truncated) that a looser
    # "contains =" signal would have wrongly exempted from this exact protection.
    if _FORMULA_START_RE.match(raw):
        return False
    candidates = doc_long_sentences.get(str(doc_id or "")) or []
    return any(raw in long_text for long_text in candidates)


# The mirror image of the severed-fragment check above: a PDF line-break can just as easily sever
# a sentence's TAIL as its head, leaving the FRONT half standing alone as its own "sentence" -
# "Bayes theorem can be briefly" where the source continues "...described as follows." on the next
# line. Unlike a severed tail (unambiguous because it starts lowercase), a severed head still
# starts with a capital letter and reads as a plausible sentence on its own, so case alone cannot
# flag it. Two signals together are what's safe: the fragment ends with NO terminal punctuation at
# all (a real complete sentence almost always has one), AND it is a literal, word-boundary-safe
# PREFIX of a longer sentence elsewhere in the same document that ITSELF ends with terminal
# punctuation (confirming that longer sentence really is the complete counterpart). Either signal
# alone is common and harmless - many real headings/labels lack terminal punctuation, and short
# coincidental prefix overlaps happen by chance - but both together, with a verified-complete
# counterpart, is rare and specific.
_TERMINAL_PUNCT_RE = re.compile(r"[.!?:;]\s*$")
_MIN_FRAGMENT_PREFIX_CHARS = 20
_ALL_SENTENCE_MIN_CHARS = 20


def build_document_all_sentences(corpus: Sequence[Mapping[str, Any]]) -> Dict[str, List[str]]:
    """Per document, every sentence at least _ALL_SENTENCE_MIN_CHARS long, regardless of case or
    terminal punctuation - broader than build_document_long_sentences (which additionally requires
    a capital start and 60+ chars, tuned for the SUFFIX-fragment check). The PREFIX-fragment check
    below needs to find genuinely short complete sentences too; it screens for completeness itself
    via the terminal-punctuation requirement inside is_forward_truncated_fragment.
    """
    out: Dict[str, List[str]] = collections.defaultdict(list)
    for s in corpus:
        text = str(s.get("sentence_text") or "").strip()
        if len(text) < _ALL_SENTENCE_MIN_CHARS:
            continue
        out[str(s.get("doc_id") or "")].append(text)
    return dict(out)


def is_forward_truncated_fragment(text: str, doc_id: str,
                                  doc_all_sentences: Optional[Mapping[str, Sequence[str]]]) -> bool:
    """True when text is a headless-but-tailless fragment: no terminal punctuation, and a genuine
    prefix of a longer, verified-complete sentence elsewhere in the same document.
    """
    raw = str(text or "").strip()
    if len(raw) < _MIN_FRAGMENT_PREFIX_CHARS or _TERMINAL_PUNCT_RE.search(raw):
        return False
    if not doc_all_sentences:
        return False
    candidates = doc_all_sentences.get(str(doc_id or "")) or []
    for longer in candidates:
        if len(longer) < len(raw) + 3:
            continue
        if not longer.startswith(raw):
            continue
        if longer[len(raw)] not in (" ", " "):
            continue
        if not _TERMINAL_PUNCT_RE.search(longer):
            continue
        return True
    return False


# Method names are recognised by SHAPE, not from a list. Two shapes carry method names in ordinary
# technical prose: an all-caps acronym, and a hyphenated proper-noun compound (the usual rendering
# of a two-author eponym). Both are corpus-independent.
# Method names are recognised by shape, never by a hard-coded roster of eponyms or acronyms,
# which would tie this to one curriculum's subject matter. The hyphenated form catches
# multi-author eponyms without naming them; single-word eponyms are deliberately given up, since
# "Gini" cannot be distinguished from any other capitalised word without knowing the field.
# Statistics acronyms are eligible as method names rather than excluded - they ARE measure names -
# which is safe because licensed_method_names already exempts whatever the unit's own label
# licenses, so a unit actually named for one of them is unaffected.
_ACRONYM_METHOD_RE = re.compile(r"\b([A-Z]{3,10})\b")
_EPONYM_METHOD_RE = re.compile(r"\b([A-Z][a-z]{2,}-[A-Z][a-z]{2,})\b")
# Generic English function words and sentence-level markers only. No subject matter.
_NON_METHOD_ACRONYMS = frozenset({
    "THE", "AND", "FOR", "NOT", "ARE", "WITH", "THIS", "THAT", "FROM", "ALL", "ANY", "ONE", "TWO",
    "NOTE", "TRUE", "FALSE", "YES", "MAX", "MIN", "AVG", "SUM", "BUT", "WAS", "HAS", "HAD", "CAN",
    "MAY", "USE", "SEE", "NEW", "OLD", "END", "PER", "VIA", "ITS", "OUR", "YOU", "WHO", "HOW",
})


def _method_name_spans(text: str):
    """(start, end, name) for every method-shaped name in text."""
    spans = []
    for m in _ACRONYM_METHOD_RE.finditer(text):
        if m.group(1) not in _NON_METHOD_ACRONYMS:
            spans.append((m.start(), m.end(), m.group(1)))
    for m in _EPONYM_METHOD_RE.finditer(text):
        spans.append((m.start(), m.end(), m.group(1)))
    return spans


# Equivalence/definitional markers ONLY - deliberately excludes comparison and enumeration words
# ("unlike", "such as", "and", "differs from"), since those are exactly what made a broader
# version of this check (v27, measured and rejected) unable to tell a real misattribution from an
# ordinary sibling-method aside like "The methods presented are SFG, SBG, BG, and RG."
_DEFINITIONAL_MARKER_RE = re.compile(
    r"\b(?:as\s+determined\s+by|as\s+measured\s+by|measured\s+by|defined\s+as|"
    r"also\s+(?:called|known\s+as|referred\s+to\s+as)|is\s+known\s+as)\b", re.I)
# "X or Y or Z" / "X, or Y" equivalence-listing, where the marker is the "or" itself
_OR_LIST_RE = re.compile(r"\bor\b", re.I)

_MARKER_PROXIMITY_CHARS = 40


def _unit_head_terms_v33(unit_labels: Sequence[str]) -> List[str]:
    """The content words that identify this unit, from its primary (canonical) label."""
    if not unit_labels:
        return []
    primary = str(unit_labels[0] or "")
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", primary)
             if w.lower() not in _RIVAL_STOPWORDS]
    return sorted(words, key=len, reverse=True)


def mentions_unit(text: str, unit_labels: Sequence[str]) -> bool:
    """True when the passage actually refers to this unit, not merely its neighbourhood."""
    low = str(text or "").lower()
    return any(w.lower() in low for w in _unit_head_terms_v33(unit_labels))


def licensed_method_names(unit_labels: Sequence[str]) -> set:
    """Method names this unit is entitled to talk about: its own name, aliases and ancestry."""
    licensed = set()
    for label in unit_labels or []:
        for m in _ACRONYM_METHOD_RE.finditer(str(label or "")):
            if m.group(1) not in _NON_METHOD_ACRONYMS:
                licensed.add(m.group(1))
        for m in _EPONYM_METHOD_RE.finditer(str(label or "")):
            licensed.add(m.group(0).upper())
        for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", str(label or "")):
            licensed.add(word.upper())
    return licensed


def attributes_via_definitional_marker(text: str, unit_labels: Sequence[str]) -> Optional[str]:
    """Name of a foreign method equated with this unit through a definitional/equivalence marker.

    Fires only when BOTH hold: the passage names this unit (by its own label), and a foreign
    method name sits within a short window immediately after a definitional-equivalence marker -
    "as determined by X", "also called X", "A or X" - not merely co-occurring with the unit
    anywhere in the passage. Comparison and enumeration words are not markers.
    """
    raw = str(text or "")
    if not raw or len(raw) > 320:
        return None
    if not mentions_unit(raw, unit_labels):
        return None
    licensed = licensed_method_names(unit_labels)

    def is_foreign(name: str) -> bool:
        return name.upper() not in licensed

    for m in _DEFINITIONAL_MARKER_RE.finditer(raw):
        window = raw[m.end():m.end() + _MARKER_PROXIMITY_CHARS]
        for start, end, name in _method_name_spans(window):
            if is_foreign(name):
                return name

    # "X or Y or FOREIGN" - an equivalence list, only when the unit's OWN name/alias is itself
    # one of the or-separated items (as "MAX" is in "Complete Link or MAX or CLIQUE"). Requiring
    # this - rather than just co-occurring with a mention of the unit anywhere in the sentence -
    # is what tells a real synonym-equivalence list apart from an ordinary enumeration of related
    # subtypes that happens to share a head noun with the unit's name ("MCAR or MAR missingness
    # mechanisms" enumerates two KINDS of missingness mechanism, it does not claim either one IS
    # the unit called Missingness Mechanism).
    own_tokens = {w.upper() for w in _unit_head_terms_v33(unit_labels)}
    if own_tokens:
        or_list_re = re.compile(
            r"([A-Za-z][A-Za-z0-9-]{2,})(?:\s*(?:,)?\s*or\s+([A-Za-z][A-Za-z0-9-]{2,}))+")
        for m in or_list_re.finditer(raw):
            list_text = m.group(0)
            list_items = {w.upper() for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", list_text)}
            if not (list_items & own_tokens):
                continue  # the unit's own name is not one of the listed items - not an equivalence list
            for start, end, name in _method_name_spans(list_text):
                if is_foreign(name) and name.upper() not in own_tokens:
                    return name
    return None

# A severed display-fraction numerator: it parses as a complete equation but states something
# false, because its denominator became a separate row. Structural only - no subject vocabulary.
_STRANDED_NUMERATOR_RE = re.compile(r"=\s*[^=]*[A-Za-z0-9)\]]\s*$")
_STRANDED_DENOMINATOR_RE = re.compile(r"^[A-Za-z0-9\s+\-*/^_().,\u2212\u00b7]{1,40}$")
_STRANDED_DEN_OPERATOR_RE = re.compile(r"[+\-*/\u2212\u00b7]")


def _stranded_block_ordinal(row: Mapping[str, Any]) -> int:
    match = re.search(r":(\d+)$", str(row.get("block_id") or ""))
    return int(match.group(1)) if match else -1


def build_stranded_numerator_texts(corpus: Sequence[Mapping[str, Any]]) -> set:
    """Texts that are a display fraction's numerator, severed from its denominator.

    Consulted during assembly the same way build_document_long_sentences is: the defect is only
    visible from the neighbouring row, which a single-sentence predicate cannot reach.
    """
    ordered: Dict[Tuple[Any, Any, Any], List[Mapping[str, Any]]] = {}
    for row in corpus or ():
        key = (row.get("doc_id"), row.get("page_index"), row.get("layer"))
        ordered.setdefault(key, []).append(row)
    stranded: set = set()
    for rows_for_page in ordered.values():
        rows_for_page = sorted(
            rows_for_page,
            key=lambda r: (_stranded_block_ordinal(r), int(r.get("sent_idx") or 0)))
        for index in range(len(rows_for_page) - 1):
            first, second = rows_for_page[index], rows_for_page[index + 1]
            if _stranded_block_ordinal(first) == _stranded_block_ordinal(second):
                continue
            head = str(first.get("sentence_text") or "").strip()
            tail = str(second.get("sentence_text") or "").strip()
            if not head or "=" in tail:
                continue
            if not _STRANDED_NUMERATOR_RE.search(head):
                continue
            # Already a complete fraction - nothing was severed from it. Without this the rule
            # drops correct formulas such as "w=1/M" or "wij=1/dist(..)^2/sum(..)".
            if has_explicit_fraction_notation(head):
                continue
            # Prose that merely contains an equals sign is not a severed numerator. A real one is
            # symbol-dominant; this keeps table rows and sentences out ("Complete/MAX and Group
            # Average for C1 = {A, B} ...", "TN = 4" beside a "Predicted +/-" table header).
            if len(re.findall(r"\b[A-Za-z]{3,}\b", head)) > 4:
                continue
            if not _STRANDED_DENOMINATOR_RE.match(tail):
                continue
            # A denominator either carries an operator ("n + v") or is a single term that
            # continues the numerator's own symbols ("P(X)" under "P(Y | X) = P(X, Y)").
            # Requiring an operator alone missed the single-term denominators that probability
            # formulas overwhelmingly use, leaving severed Bayes numerators undetected.
            # A denominator is symbol-dominant either way. Without this a word-internal hyphen
            # satisfies the operator test and ordinary prose is read as a denominator
            # ("positive-negative pairs exist." under "5 x 5 = 25").
            if len(re.findall(r"\b[A-Za-z]{3,}\b", tail)) > 2:
                continue
            if not _STRANDED_DEN_OPERATOR_RE.search(tail):
                tail_letters = set(re.findall(r"[A-Za-z]", tail))
                head_letters = set(re.findall(r"[A-Za-z]", head))
                if not tail_letters or not tail_letters <= head_letters:
                    continue
            stranded.add(head)
    return stranded


def _formula_signature_parts(text):
    """(left-hand side, right-hand side) of a formula, normalised for comparison across layers."""
    compact = compact_formula_signature(str(text or ""))
    compact = re.sub(r"^\d+", "", compact)   # display delimiters normalise to a numeric artefact
    compact = re.sub(r"\d+$", "", compact)
    if "=" not in compact:
        return "", ""
    left, right = compact.split("=", 1)
    keep = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return keep(left), keep(right)


SAME_PAGE = "same_page"
SAME_DOCUMENT = "same_document"
FOREIGN_DOCUMENT = "foreign_document"

# A right-hand side that carries no letter is not a mathematical expression, it is what a
# TRUNCATED row normalises to: "P(S|+) = 0." leaves the single character "0". Containment against
# such a right-hand side is satisfied by almost any intact rendering and therefore proves nothing.
_SYMBOLIC_RHS_RE = re.compile(r"[a-z]")


def formula_twin_locality(damaged_row, twin_row):
    """Where a candidate replacement sits relative to the row it would replace."""
    if damaged_row.get("doc_id") != twin_row.get("doc_id"):
        return FOREIGN_DOCUMENT
    if damaged_row.get("page_index") != twin_row.get("page_index"):
        return SAME_DOCUMENT
    return SAME_PAGE


def twin_corroboration_is_sufficient(locality, damaged_right, damaged_layer, twin_layer):
    """Whether a matched twin is trustworthy enough to stand in for the damaged rendering.

    On the SAME PAGE the page itself corroborates the match: two extraction layers read the same
    region and one of them kept the fraction, so the only additional requirement is that the twin
    really is a different reading and not the same layer's own row.

    Away from that page there is no such corroboration, and the equation text becomes the only
    evidence that the two rows are the same equation. The matched right-hand side must therefore
    be symbolic rather than the bare numeral a truncated row collapses to. Measured on the real
    corpus this single distinction is what separates the correct cross-document repairs (Bayes'
    theorem, matched right-hand side "pxypypx") from the one false match observed, where
    "M_1 = (0." was matched to an unrelated "m1=m/3" on nothing but the character "0".
    """
    if locality == SAME_PAGE:
        return damaged_layer != twin_layer
    return bool(_SYMBOLIC_RHS_RE.search(str(damaged_right or "")))


# v52/INT-22. A word of four or more letters running straight into an equation is a splice:
# "werem A m B merged", "weightedalphaA=...", "whereI(acj|x')isthesummation". The length and the
# requirement that the word occurs on its own elsewhere in the corpus are what separate a splice
# from an ordinary subscripted symbol name - "dN(p,c)", "g-lambda", "Mui-alpha" are none of them
# words. Measured on this corpus: 109 rows, 103 of them from one extractor.
_SPLICED_MATH_RE = re.compile(
    r"(?<![A-Za-z])([a-z]{4,})(?=[\u03b1-\u03c9\u0391-\u03a9]|[A-Z]\s*[=(]|[A-Z]\s[A-Z]\s)")
_STANDALONE_WORD_RE = re.compile(r"(?<![A-Za-z])([a-z]{4,})(?![A-Za-z])")
SPLICE_WORD_MIN_OCCURRENCES = 3
SPLICE_TWIN_MIN_OVERLAP = 0.7


def build_corpus_vocabulary(corpus: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """How often each word of four or more letters appears on its own in the corpus."""
    counts: Dict[str, int] = collections.Counter()
    for row in corpus or ():
        for word in _STANDALONE_WORD_RE.findall(str(row.get("sentence_text") or "").lower()):
            counts[word] += 1
    return counts


def spliced_math_words(text: str, vocabulary: Mapping[str, int]) -> List[str]:
    """The real words this text interrupts with an equation, if any."""
    return [word for word in _SPLICED_MATH_RE.findall(str(text or ""))
            if vocabulary.get(word.lower(), 0) >= SPLICE_WORD_MIN_OCCURRENCES]


def _prose_words(text: str) -> frozenset:
    return frozenset(_STANDALONE_WORD_RE.findall(str(text or "").lower()))


# A fragment of mathematics as the splice leaves it: a run beginning at a Greek letter, or a name
# bound to a value by "=". Short runs are ignored - they carry nothing that could be lost.
_MATH_FRAGMENT_RE = re.compile(r"[\u03b1-\u03c9\u0391-\u03a9][^\s]*"
                               r"|[A-Za-z]\w*\s*=\s*[^\s]+")
MATH_FRAGMENT_MIN_CHARS = 4


# A splice leaves the interrupted word glued to the front of the equation - "weightedalphaA=...".
# Python's \w matches Greek, so the naive fragment carries that word and is unique by
# construction, which would make every splice look as though it orphans content. The prefix is
# removed only when what remains still begins like mathematics, so "errgen(TL)=1" is left alone.
_SPLICE_PREFIX_RE = re.compile(r"^[a-z]{3,}(?=[α-ωΑ-ΩA-Z])")


def math_fragments(text: str) -> frozenset:
    """The mathematical fragments a text carries, whitespace removed so renderings compare."""
    out = set()
    for match in _MATH_FRAGMENT_RE.findall(str(text or "")):
        squashed = re.sub(r"\s+", "", match)
        squashed = _SPLICE_PREFIX_RE.sub("", squashed)
        # Trailing punctuation is a property of the sentence, not of the mathematics. Without
        # this, the same coefficient reads as two different fragments depending on whether a
        # comma followed it, and every repair looks as though it orphans content.
        squashed = squashed.rstrip(".,;:")   # sentence punctuation only, never a closing paren
        if len(squashed) >= MATH_FRAGMENT_MIN_CHARS:
            out.add(squashed)
    return frozenset(out)


def build_math_fragment_index(corpus: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """How many DISTINCT texts carry each mathematical fragment."""
    seen_texts: set = set()
    counts: Dict[str, int] = collections.Counter()
    for row in corpus or ():
        text = str(row.get("sentence_text") or "")
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        for fragment in math_fragments(text):
            counts[fragment] += 1
    return counts


def build_spliced_math_repairs(corpus: Sequence[Mapping[str, Any]],
                               vocabulary: Optional[Mapping[str, int]] = None
                               ) -> Dict[str, str]:
    """Map each splice-damaged text to a clean rendering of the same sentence, where one exists.

    The twin must come from a DIFFERENT extractor, carry no splice of its own, and share most of
    the damaged row's vocabulary. Sharing vocabulary is what makes it the same sentence; requiring
    a different extractor is what makes it an independent rendering rather than the same mistake.
    """
    vocabulary = build_corpus_vocabulary(corpus) if vocabulary is None else vocabulary
    fragment_index = build_math_fragment_index(corpus)
    rows = [(str(r.get("sentence_text") or ""), str(r.get("layer") or "")) for r in corpus or ()]
    clean_by_layer: Dict[str, List[Tuple[frozenset, str]]] = collections.defaultdict(list)
    for text, layer in rows:
        if len(text) <= 40 or spliced_math_words(text, vocabulary):
            continue
        words = _prose_words(text)
        if len(words) >= 6:
            clean_by_layer[layer].append((words, text))

    repairs: Dict[str, str] = {}
    for text, layer in rows:
        if len(text) <= 40 or text in repairs or not spliced_math_words(text, vocabulary):
            continue
        mine = _prose_words(text)
        if len(mine) < 6:
            continue
        best_text, best_overlap = None, 0.0
        for other_layer, entries in clean_by_layer.items():
            if other_layer == layer:
                continue
            for words, candidate in entries:
                union = len(mine | words)
                if not union:
                    continue
                overlap = len(mine & words) / union
                if overlap >= SPLICE_TWIN_MIN_OVERLAP and overlap > best_overlap:
                    best_text, best_overlap = candidate, overlap
        if best_text is None:
            continue
        # A repair must not be the only place some mathematics survives. Every fragment the clean
        # rendering drops has to appear in at least one OTHER text, or this row is left alone -
        # damaged prose that still carries a unique equation is worth more than clean prose that
        # loses it. Measured when this condition was absent: 20 of 83 repairs deleted mathematics
        # found nowhere else, including Z_alpha/2 = Z_1-alpha/2 and N = sum_i n_i.
        dropped = math_fragments(text) - math_fragments(best_text)
        if any(fragment_index.get(fragment, 0) <= 1 for fragment in dropped):
            continue
        repairs[text] = best_text
    return repairs


def apply_spliced_math_repairs(corpus: Sequence[Mapping[str, Any]],
                               repairs: Mapping[str, str]):
    """Return the corpus with each splice-damaged text replaced by its clean twin."""
    if not repairs:
        return list(corpus), 0
    out, replaced = [], 0
    for row in corpus:
        text = str(row.get("sentence_text") or "")
        clean = repairs.get(text)
        if clean is None:
            out.append(row)
            continue
        updated = dict(row)
        updated["sentence_text"] = clean
        updated["spliced_math_repaired_from"] = text
        out.append(updated)
        replaced += 1
    return out, replaced


def build_intact_twin_index(corpus):
    """Index every undamaged, explicitly-fractional rendering in the corpus by left-hand side.

    Built once and shared by every caller: the twin search is the same search whether the row it
    repairs was found by the stranded-numerator detector or by the damage checks, and having one
    index means the safety gates cannot drift apart between the two paths.
    """
    index = collections.defaultdict(list)
    for row in corpus or ():
        text = str(row.get("sentence_text") or "").strip()
        if not text:
            continue
        if not (has_explicit_fraction_notation(text) or "frac" in text):
            continue
        if math_rendering_damaged(text):
            continue
        left, right = _formula_signature_parts(text)
        if left and right:
            index[left].append((text, right, row))
    return index


def find_intact_formula_twin(text, row, twin_index, *, allow_non_local=False):
    """The intact rendering of `text` to use instead of it, plus the agreement record.

    Returns (chosen_text, chosen_row, agreement). `chosen_text` is None when no candidate clears
    every gate. Gates, in order: same normalised left-hand side; the damaged right-hand side
    contained in the candidate's; enough corroboration for the locality the candidate was found
    at. A candidate that shares the left-hand side but not the right-hand side is a DISAGREEMENT
    between renderings, recorded rather than silently skipped, because a reviewer checking a
    formula-heavy unit needs to know a conflicting rendering existed.
    """
    left, right = _formula_signature_parts(text)
    if not left or not right:
        return None, None, None

    agreeing_layers, conflicting_layers = [], []
    chosen_text, chosen_row = None, None
    for cand_text, cand_right, cand in twin_index.get(left, ()):
        if cand_text == text:
            continue
        locality = formula_twin_locality(row, cand)
        if locality != SAME_PAGE and not allow_non_local:
            continue
        if right not in cand_right:
            if locality == SAME_PAGE:
                conflicting_layers.append(str(cand.get("layer") or ""))
            continue
        if not twin_corroboration_is_sufficient(
                locality, right, row.get("layer"), cand.get("layer")):
            continue
        agreeing_layers.append(str(cand.get("layer") or ""))
        if chosen_text is None:
            chosen_text, chosen_row = cand_text, cand

    agreement = None
    if agreeing_layers or conflicting_layers:
        agreement = {
            "extractor_agreement_count": len(agreeing_layers),
            "agreeing_layers": sorted(set(l for l in agreeing_layers if l)),
            "extractor_conflict": bool(conflicting_layers),
            "conflicting_layers": sorted(set(l for l in conflicting_layers if l)),
        }
    return chosen_text, chosen_row, agreement


def _first_rows_for_texts(corpus, texts):
    """The first corpus row carrying each of `texts`, which is where its locality is read from."""
    origin = {}
    for row in corpus or ():
        text = str(row.get("sentence_text") or "").strip()
        if text in texts and text not in origin:
            origin[text] = row
    return origin


def build_intact_formula_substitutions(corpus, stranded_texts, agreement_out=None,
                                       allow_non_local=False):
    """Map each severed numerator to an INTACT rendering of the same equation, where one exists.

    Nothing is invented: the replacement text is already in the corpus, and it must agree on the
    left-hand side and contain the severed numerator's own right-hand side. `allow_non_local`
    widens the search beyond the damaged row's page under the stricter corroboration rule in
    twin_corroboration_is_sufficient; it defaults to False so this function's behaviour for the
    stranded-numerator path is unchanged.
    """
    if not stranded_texts:
        return {}
    twin_index = build_intact_twin_index(corpus)
    substitutions = {}
    for text, row in _first_rows_for_texts(corpus, stranded_texts).items():
        chosen, _chosen_row, agreement = find_intact_formula_twin(
            text, row, twin_index, allow_non_local=allow_non_local)
        if chosen is not None:
            substitutions[text] = chosen
        if agreement_out is not None and agreement is not None:
            agreement_out[text] = agreement
    return substitutions


def build_damaged_formula_repairs(corpus, twin_index=None):
    """Repairs for math-damaged rows that have an intact twin, keyed by the damaged text.

    The stranded-numerator path exists because those rows are INVISIBLE to the damage checks. The
    rows here are the opposite case: the damage checks see them plainly, and until now that meant
    the row was dropped even when the corpus held a correct rendering of the same equation a few
    pages away. Deliberately the same search and the same gates as the stranded path - the twin is
    trustworthy for the same reasons, whichever detector found the row it replaces.

    Each value carries the replacement text and where it came from, so a substitution is never
    silent: provenance travels with the repaired row rather than being asserted by this function.
    """
    if twin_index is None:
        twin_index = build_intact_twin_index(corpus)
    # Exactly the predicate drop_damaged_math_passages drops on, and deliberately nothing
    # narrower. Pairing it with has_mathematics looked like a sensible guard but excluded the
    # very shape this repairs: a bar-loss rendering such as "P(Y|X)=P(X|Y)P(Y)P(X)." is damaged
    # yet carries no symbol has_mathematics recognises. The repair set must be the drop set, or
    # the two passes disagree about what counts as damage.
    damaged = {text for text in (str(row.get("sentence_text") or "").strip()
                                 for row in corpus or ())
               if text and math_rendering_damaged(text)}

    repairs = {}
    for text, row in _first_rows_for_texts(corpus, damaged).items():
        chosen, chosen_row, _agreement = find_intact_formula_twin(
            text, row, twin_index, allow_non_local=True)
        if chosen is None:
            continue
        repairs[text] = {
            "text": chosen,
            "from_doc_id": chosen_row.get("doc_id"),
            "from_page_index": chosen_row.get("page_index"),
            "from_layer": chosen_row.get("layer"),
            "locality": formula_twin_locality(row, chosen_row),
        }
    return repairs


def apply_damaged_formula_repairs(corpus, repairs):
    """A corpus in which every repairable damaged rendering carries its intact twin's text.

    Applied once, before anything reads the corpus, so retrieval, block assembly, the lead-in
    payload rescue and the drop passes all see one consistent text. Repairing at the point of use
    instead would leave each of those paths to remember the repair separately, which is exactly
    how the two math paths drifted apart in the first place.

    The original rendering is kept on the row. A repair that cannot be inspected afterwards is
    indistinguishable from a fabrication.
    """
    if not repairs:
        return list(corpus or ()), 0
    repaired_rows, n = [], 0
    for row in corpus or ():
        text = str(row.get("sentence_text") or "").strip()
        repair = repairs.get(text)
        if repair is None:
            repaired_rows.append(row)
            continue
        updated = dict(row)
        updated["sentence_text"] = repair["text"]
        updated["formula_repaired_from_damaged_text"] = text
        updated["formula_repaired_from_doc_id"] = repair["from_doc_id"]
        updated["formula_repaired_from_page_index"] = repair["from_page_index"]
        updated["formula_repaired_from_layer"] = repair["from_layer"]
        updated["formula_repair_locality"] = repair["locality"]
        repaired_rows.append(updated)
        n += 1
    return repaired_rows, n


def drop_stranded_numerator_passages(passages, stranded_texts, substitutions=None,
                                    agreement=None):
    """Drop passages that are a severed display-fraction numerator.

    Separate named function rather than inline builder code so its behaviour can be tested
    directly - an inline `if` can be disabled in a way that leaves every identifying string still
    present in the source, which defeats any text-matching guard.
    """
    kept, dropped = [], []
    substitutions = substitutions or {}
    for passage in passages or []:
        text = str(passage.get("text") or "").strip()
        if text and text in (stranded_texts or ()):
            replacement = substitutions.get(text)
            if replacement:
                # An intact rendering of the SAME equation exists in another extraction layer.
                # Use it: nothing is invented, the correct text was already in the corpus.
                restored = dict(passage)
                restored["text"] = replacement
                restored["source_block_text"] = replacement
                restored["recovered_from_severed_numerator"] = True
                _agree = (agreement or {}).get(text)
                if _agree:
                    restored["extractor_agreement_count"] = _agree["extractor_agreement_count"]
                    restored["extractor_conflict"] = _agree["extractor_conflict"]
                kept.append(restored)
                dropped.append({
                    "text": text[:200],
                    "rival": "replaced by intact cross-layer rendering",
                    "reason": "stranded_numerator_substituted_intact",
                })
                continue
            dropped.append({
                "text": text[:200],
                "rival": "severed display-fraction numerator",
                "reason": "stranded_numerator_denominator_severed",
            })
        else:
            kept.append(passage)
    return kept, dropped


def build_corpus_block_index(corpus: Sequence[Mapping[str, Any]]) -> Dict[Tuple[str, str], List[Mapping[str, Any]]]:
    index: Dict[Tuple[str, str], List[Mapping[str, Any]]] = collections.defaultdict(list)
    for s in corpus:
        key = _block_key(s)
        if key[1]:
            index[key].append(s)
    return index
