"""
core/systems/devlog.py

DevLog -- compact cryptographic audit log for live dev sessions.

Chained SHA256 hashes. Each entry links to previous via prev_hash.
User writes notes between sessions. Claude parses the chain on session start.
Same provenance contract as Yellow Sign on scenarios.

Usage:
    log = DevLog()
    log.add("decision", "encounter pacing 0.45 threshold")
    log.add("brainstorm", "sprite vs poly confirmed")
    log.save()

    # Next session:
    log = DevLog()
    for entry in log.recent(10):
        print(entry["note"])
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


DEVLOG_PATH = Path(__file__).parent.parent.parent / "data" / "devlog.json"


class DevLog:
    """
    Append-only chained hash audit log.

    Each entry: {ts, hash, type, note, context, prev}
    hash = SHA256(prev + type + note + ts)
    """

    def __init__(self, path: Path = None):
        self._path = path or DEVLOG_PATH
        self._entries = []
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._entries = json.load(open(self._path))
            except (json.JSONDecodeError, IOError):
                self._entries = []

    def add(self, entry_type: str, note: str, context: str = "") -> dict:
        """
        Append an entry. Returns the entry dict.
        Types: decision, brainstorm, bug, milestone, note
        """
        prev = self._entries[-1]["hash"] if self._entries else "genesis"
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")

        raw = json.dumps({
            "prev": prev, "type": entry_type,
            "note": note, "ts": ts,
        }, sort_keys=True)
        entry_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]

        entry = {
            "ts":      ts,
            "hash":    entry_hash,
            "type":    entry_type,
            "note":    note,
            "context": context,
            "prev":    prev,
        }
        self._entries.append(entry)
        return entry

    def save(self):
        """Write log to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._entries, f, indent=2)

    def recent(self, n: int = 10) -> list:
        """Last N entries, newest first."""
        return list(reversed(self._entries[-n:]))

    def all(self) -> list:
        """All entries in chronological order."""
        return list(self._entries)

    def verify_chain(self) -> bool:
        """
        Verify hash chain integrity.
        Returns True if all hashes are valid and chain is unbroken.
        """
        for i, entry in enumerate(self._entries):
            prev = self._entries[i - 1]["hash"] if i > 0 else "genesis"
            raw = json.dumps({
                "prev": prev, "type": entry["type"],
                "note": entry["note"], "ts": entry["ts"],
            }, sort_keys=True)
            expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
            if entry["hash"] != expected or entry["prev"] != prev:
                return False
        return True

    def count(self) -> int:
        return len(self._entries)

    def summary(self) -> str:
        """One-line summary for session start."""
        if not self._entries:
            return "DevLog: empty"
        last = self._entries[-1]
        return (
            f"DevLog: {len(self._entries)} entries, "
            f"last: [{last['type']}] {last['note'][:60]} "
            f"({last['ts']})"
        )
