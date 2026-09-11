"""Lossless JSON whitespace compaction at the visible request boundary.

Canonical artifacts, receipts and strings stay untouched. The caller measures
complete prompts, not file size, before accepting a change to framing whitespace.
"""
from __future__ import annotations
import json
import re
_PARTS = re.compile(r'"(?:\\.|[^"\\])*"|[ \t\r\n]+')


def _pairs(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('duplicate JSON keys')
    return result


def _invalid(value):
    raise ValueError('invalid JSON constant')


def compact_json(text, *, max_chars=1_000_000):
    """Remove framing whitespace without rounding numbers or changing strings."""
    if type(text) is not str or type(max_chars) is not int or max_chars < 1:
        raise TypeError('text and a positive bound required')
    if len(text) > max_chars or not text.lstrip().startswith(('{', '[')):
        return text
    try:
        # Validate number grammar without coercing huge or exact numbers to floats.
        json.loads(text, object_pairs_hook=_pairs, parse_int=str, parse_float=str,
                   parse_constant=_invalid)
    except (ValueError, TypeError, RecursionError, OverflowError):
        return text
    return _PARTS.sub(lambda m: m[0] if m[0].startswith('"') else '', text)
