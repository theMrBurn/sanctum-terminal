"""TCP message parsing — line-buffered JSON with partial-record handling."""
from __future__ import annotations

from clients.vector_terminal.manifest_io import parse_lines


def test_parses_single_complete_line():
    blob = b'{"kind": "manifest", "world_revision": 1}\n'
    msgs = list(parse_lines(blob))
    assert msgs == [{"kind": "manifest", "world_revision": 1}]


def test_parses_multiple_complete_lines():
    blob = b'{"a": 1}\n{"a": 2}\n{"a": 3}\n'
    msgs = list(parse_lines(blob))
    assert msgs == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_skips_blank_lines():
    blob = b'{"a": 1}\n\n\n{"a": 2}\n'
    msgs = list(parse_lines(blob))
    assert msgs == [{"a": 1}, {"a": 2}]


def test_skips_invalid_json():
    blob = b'not-json\n{"a": 1}\n'
    msgs = list(parse_lines(blob))
    assert msgs == [{"a": 1}]


def test_handles_unchanged_keepalive():
    blob = b'{"unchanged": true}\n'
    assert list(parse_lines(blob)) == [{"unchanged": True}]


def test_unicode_payload():
    blob = '{"name": "spöre"}\n'.encode("utf-8")
    msgs = list(parse_lines(blob))
    assert msgs == [{"name": "spöre"}]
