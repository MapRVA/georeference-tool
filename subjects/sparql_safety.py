"""Safely place untrusted input into SPARQL queries.

SPARQL has no parameterized-query mechanism, so we escape per the
SPARQL 1.1 string literal grammar and tightly validate the IRI fragments
we accept. Use these helpers anywhere user-derived input (request data
or model values that originated from user submissions) lands in a SPARQL
query string.

The SPARQL 1.1 string-literal escape rules (STRING_LITERAL2, §19.2 of the
spec):

    "  -> \\"
    \\  -> \\\\
    plus the named control-character escapes (\\n \\r \\t \\b \\f).

We additionally *reject* raw control characters (U+0000..U+001F) rather
than escaping them, since they shouldn't appear in legitimate
autocomplete input and rejecting them defends against odd injection
shapes (e.g., a literal newline trying to break out of a comment).
"""

import re

_QID_RE = re.compile(r"^Q[1-9]\d{0,19}$")
_LANG_TAG_RE = re.compile(r"^[a-zA-Z]{1,8}(-[a-zA-Z0-9]{1,8})*$")
_MAX_FREE_TEXT_LEN = 100

WIKIDATA_ENTITY_IRI_BASE = "http://www.wikidata.org/entity/"


class UnsafeSparqlInput(ValueError):
    """Raised when input cannot be safely placed into a SPARQL query."""


def validate_qid(qid):
    """Return ``qid`` if it matches the Wikidata Q-ID grammar; else raise."""
    if not isinstance(qid, str) or not _QID_RE.match(qid):
        raise UnsafeSparqlInput(f"invalid Wikidata Q-ID: {qid!r}")
    return qid


def looks_like_qid(value):
    """Predicate form of ``validate_qid`` for use as a branch condition."""
    return isinstance(value, str) and bool(_QID_RE.match(value))


def sparql_wikidata_entity_iri(qid):
    """Validate ``qid`` and return its IRI in SPARQL angle-bracket form."""
    validate_qid(qid)
    return f"<{WIKIDATA_ENTITY_IRI_BASE}{qid}>"


def sparql_string_literal(value, lang=None):
    """Return a SPARQL string literal, escaped per SPARQL 1.1.

    Raises ``UnsafeSparqlInput`` if ``value`` exceeds the length cap or
    contains a raw control character.
    """
    if not isinstance(value, str):
        raise UnsafeSparqlInput("string literal value must be a str")
    if len(value) > _MAX_FREE_TEXT_LEN:
        raise UnsafeSparqlInput(f"value exceeds {_MAX_FREE_TEXT_LEN}-char limit")
    for ch in value:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise UnsafeSparqlInput(f"control character U+{ord(ch):04X} not allowed")

    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    out = f'"{escaped}"'
    if lang is not None:
        if not _LANG_TAG_RE.match(lang):
            raise UnsafeSparqlInput(f"invalid BCP47 language tag: {lang!r}")
        out = f"{out}@{lang}"
    return out
