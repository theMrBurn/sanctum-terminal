"""
tests/test_devlog.py

DevLog -- chained hash audit log for dev sessions.
"""
import pytest
from pathlib import Path
import tempfile


@pytest.fixture
def log():
    from core.systems.devlog import DevLog
    tmp = Path(tempfile.mktemp(suffix=".json"))
    dl = DevLog(path=tmp)
    yield dl
    if tmp.exists():
        tmp.unlink()


class TestDevLog:

    def test_importable(self):
        from core.systems.devlog import DevLog
        assert DevLog is not None

    def test_starts_empty(self, log):
        assert log.count() == 0

    def test_add_entry(self, log):
        entry = log.add("decision", "test note")
        assert entry["type"] == "decision"
        assert entry["note"] == "test note"
        assert log.count() == 1

    def test_entry_has_hash(self, log):
        entry = log.add("note", "something")
        assert len(entry["hash"]) == 16

    def test_first_entry_prev_is_genesis(self, log):
        entry = log.add("note", "first")
        assert entry["prev"] == "genesis"

    def test_chain_links(self, log):
        e1 = log.add("note", "first")
        e2 = log.add("note", "second")
        assert e2["prev"] == e1["hash"]

    def test_save_and_reload(self, log):
        log.add("decision", "test persistence")
        log.save()
        from core.systems.devlog import DevLog
        log2 = DevLog(path=log._path)
        assert log2.count() == 1

    def test_verify_chain_valid(self, log):
        log.add("note", "one")
        log.add("note", "two")
        log.add("decision", "three")
        assert log.verify_chain() is True

    def test_recent_returns_newest_first(self, log):
        log.add("note", "old")
        log.add("note", "new")
        recent = log.recent(2)
        assert recent[0]["note"] == "new"
        assert recent[1]["note"] == "old"

    def test_summary(self, log):
        log.add("milestone", "session 10 complete")
        s = log.summary()
        assert "milestone" in s
        assert "session 10" in s

    def test_context_field(self, log):
        entry = log.add("brainstorm", "idea", context="while eating dinner")
        assert entry["context"] == "while eating dinner"
