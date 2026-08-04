"""
Validate untrusted input headed for graph queries.

Two consumers share these validators:

- The WDQS closure CONSTRUCT (``wikidata_closure.closure_query``) is
  still SPARQL, which has no parameterized-query mechanism — the seed
  Q-ID and mirror language tags are interpolated into the query text and
  must be validated first.
- The Memgraph Cypher queries take real Bolt parameters for values, but
  Cypher cannot parameterize relationship *types* — every PID that
  becomes a ``[:P{n}]`` type is interpolated and must pass
  ``validate_pid`` first (see ``wikidata_closure.apply_closure``).
"""

import re

_QID_RE = re.compile(r"^Q[1-9]\d{0,19}$")
_PID_RE = re.compile(r"^P[1-9]\d{0,19}$")
_LANG_TAG_RE = re.compile(r"^[a-zA-Z]{1,8}(-[a-zA-Z0-9]{1,8})*$")


class UnsafeSparqlInput(ValueError):
    """Raised when input cannot be safely placed into a query string."""


def validate_qid(qid):
    """Return ``qid`` if it matches the Wikidata Q-ID grammar; else raise."""
    if not isinstance(qid, str) or not _QID_RE.match(qid):
        raise UnsafeSparqlInput(f"invalid Wikidata Q-ID: {qid!r}")
    return qid


def looks_like_qid(value):
    """Predicate form of ``validate_qid`` for use as a branch condition."""
    return isinstance(value, str) and bool(_QID_RE.match(value))


def looks_like_pid(value):
    """True if ``value`` matches the Wikidata property-ID grammar (``P123``)."""
    return isinstance(value, str) and bool(_PID_RE.match(value))


def validate_pid(pid):
    """Return ``pid`` if it matches the Wikidata property-ID grammar; else raise.

    The raising twin of ``looks_like_pid``, for the spots where a PID is
    interpolated into Cypher text as a relationship type.
    """
    if not isinstance(pid, str) or not _PID_RE.match(pid):
        raise UnsafeSparqlInput(f"invalid Wikidata P-ID: {pid!r}")
    return pid


def validate_language_tag(lang):
    """Return ``lang`` if it matches the BCP47 language-tag grammar; else raise."""
    if not isinstance(lang, str) or not _LANG_TAG_RE.match(lang):
        raise UnsafeSparqlInput(f"invalid BCP47 language tag: {lang!r}")
    return lang
