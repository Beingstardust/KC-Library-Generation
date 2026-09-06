"""Whether a drafted body describes its SUBJECT or describes its EVIDENCE.

Lives in the package rather than in a verify script because two callers need the same answer and
they must not drift apart:

  * INT-12 reports it as review metadata over finished drafts;
  * the drafting runner uses it to decide whether a repaired draft may be accepted.

Copying the rule into the second caller is exactly the mistake that produced INT-13 - two content
repairs written in one place and never reached from the loop that actually runs.

A model asked to reverse an abstention on thin evidence has two honest options: write what the
evidence supports, or abstain again. It has a third, less honest one - write "the provided
evidence does not define this unit" AS THE DRAFT - which satisfies every structural check while
telling a downstream reader nothing. Measured on the first run with the repair live, 4 of 7
repaired drafts did exactly that.

Nothing here uses subject-matter vocabulary, a unit name, a document name or a corpus path.
"""
from __future__ import annotations

import re
from typing import List, Sequence, Tuple

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z$\\(])")

# The SUBJECT is the evidence itself rather than the unit's topic.
_SOURCE_SUBJECT = (r"(?:source(?:\s+(?:text|material|rendering|passages?))?"
                   r"|(?:the|this|provided|supplied)\s+evidence"
                   r"|evidence\s+(?:items?|coverage)"
                   r"|(?:provided|supplied)\s+(?:text|passages?)"
                   r"|passages?\s+provided|packet|this\s+unit)")
# ... and the PREDICATE is about availability or rendering, not about the subject matter.
# "define" and "definition" were absent from the first version and let the most common shape of
# all escape - "The provided evidence does not DEFINE 'X'" - which is how four repaired drafts
# whose entire body was commentary went unflagged.
_AVAILABILITY_PREDICATE = (r"(?:is|are|was|were|does|do|contains?)\s+not\s+"
                           r"(?:fully\s+|explicitly\s+|clearly\s+)?"
                           r"(?:rendered|legible|provide|provided|specify|specified|state|stated|"
                           r"detail|detailed|given|available|contain|include|written|present|"
                           r"distinguish|clarify|establish|elaborate|define|defined|describe|"
                           r"described|support|supported)"
                           r"|(?:is|are|was|were)\s+(?:incomplete|unreadable|garbled|fragmentary|"
                           r"illegible|missing|absent)"
                           r"|lacks?\s+|missing\s+from|absent\s+from"
                           r"|(?:rendering|text)\s+(?:is|are)\s+"
                           r"(?:incomplete|unreadable|garbled|fragmentary|illegible)"
                           r"|(?:does|do)\s+not\s+(?:contain|include)\s+(?:a|an|any)\s+"
                           r"(?:specific\s+)?(?:definition|description|procedure|formula)")
_SOURCE_SUBJECT_RE = re.compile(r"\b" + _SOURCE_SUBJECT + r"\b", re.IGNORECASE)
_AVAILABILITY_PREDICATE_RE = re.compile(r"\b(?:" + _AVAILABILITY_PREDICATE + r")", re.IGNORECASE)
_CLAUSE_BREAK_RE = re.compile(r"[.;:!?]")


def split_sentences(text: str) -> List[str]:
    """Sentence-ish segments of a drafted body.

    Deliberately simple. A heavier segmenter would buy precision neither caller needs: findings
    are reviewed by a human, and a mis-split sentence costs a glance rather than a wrong verdict.
    """
    parts: List[str] = []
    for block in str(text or "").split("\n"):
        for piece in _SENTENCE_SPLIT_RE.split(block.strip()):
            piece = piece.strip()
            if piece:
                parts.append(piece)
    return parts


def is_source_meta_commentary(sentence: str) -> bool:
    """True when a sentence's subject is the evidence and its predicate is about availability.

    Order and clause membership are checked directly rather than through a character window. The
    source-referring subject must come FIRST with no clause boundary before the predicate, which
    is what separates this from "..., rendering the class impossible to predict regardless of
    other evidence", where the predicate precedes the noun and the noun is subject matter.
    """
    subject = _SOURCE_SUBJECT_RE.search(sentence)
    if not subject:
        return False
    predicate = _AVAILABILITY_PREDICATE_RE.search(sentence, subject.end())
    if not predicate:
        return False
    return not _CLAUSE_BREAK_RE.search(sentence[subject.end():predicate.start()])


def meta_commentary_profile(text: str) -> Tuple[int, int, bool]:
    """(meta sentence count, total sentences, whether the body OPENS with commentary)."""
    sentences = split_sentences(text)
    flags = [is_source_meta_commentary(s) for s in sentences]
    return sum(flags), len(sentences), bool(flags and flags[0])


def body_describes_its_evidence(text: str) -> bool:
    """True when a body is about the sources rather than the subject.

    Two independent signals, either sufficient:

      * it OPENS with commentary. A draft that begins "The provided evidence does not define X"
        has already told the reader it is not a definition, whatever follows.
      * a MAJORITY of its sentences are commentary. Majority rather than a tuned fraction: below
        half the body is a draft carrying a caveat, above half the caveat is the body.

    A draft that merely mentions a gap once, in a body that otherwise describes its subject, is
    not caught by either - and should not be. That is an ordinary, honest partial.
    """
    meta, total, opens_with_meta = meta_commentary_profile(text)
    if not total:
        return False
    return opens_with_meta or (meta * 2 > total)


def find_source_meta_commentary(sentences: Sequence[str]) -> List[dict]:
    """Review-metadata form of the same rule, one finding per offending sentence."""
    return [{"check": "SOURCE_META_COMMENTARY_IN_BODY", "sentence": sentence,
             "why": "within one clause the subject is the evidence and the predicate is about "
                    "its availability or rendering, so the sentence describes the sources rather "
                    "than the unit"}
            for sentence in sentences if is_source_meta_commentary(sentence)]
