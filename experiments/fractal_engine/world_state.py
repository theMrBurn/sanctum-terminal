"""Delta-state ledger for the Unified Fractal Engine.

Procedural generation is *the default*. We never persist the generated
world — only the user's deviations from it. A node's "true" state at
runtime is `procedural(seed) + delta(ledger_key)`.

Ledger keys come from GridNode.ledger_key() so they're stable across
zoom in/out cycles. That's how a dungeon you looted stays looted after
you walk back up to the overworld and re-enter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from grid_node import GridNode


@dataclass
class Delta:
    """One user-driven change at a specific node.

    `kind` is freeform — "remove", "place", "tag", "consume". The
    runtime decides what each kind means; the ledger doesn't care.

    `tile` is optional: deltas can apply to the whole node ("dungeon
    cleared") or to a specific tile inside it ("torch lit at (3, 7)").
    """

    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    tile: tuple[int, int] | None = None


@dataclass
class WorldState:
    """Append-only-ish ledger keyed by GridNode.ledger_key().

    "Ish" because we expose mutation helpers — but the underlying
    semantics are: the ledger only ever grows. No GC at this layer.
    Compaction is a future problem.
    """

    deltas: dict[str, list[Delta]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def record(self, node: GridNode, delta: Delta) -> None:
        key = node.ledger_key()
        self.deltas.setdefault(key, []).append(delta)

    def get(self, node: GridNode) -> list[Delta]:
        return list(self.deltas.get(node.ledger_key(), ()))

    def has_changes(self, node: GridNode) -> bool:
        return bool(self.deltas.get(node.ledger_key()))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(
            {
                key: [
                    {"kind": d.kind, "payload": d.payload, "tile": d.tile}
                    for d in deltas
                ]
                for key, deltas in self.deltas.items()
            },
            sort_keys=True,
            indent=2,
        )

    @classmethod
    def from_json(cls, raw: str) -> "WorldState":
        data = json.loads(raw)
        out = cls()
        for key, entries in data.items():
            out.deltas[key] = [
                Delta(
                    kind=e["kind"],
                    payload=e.get("payload", {}),
                    tile=tuple(e["tile"]) if e.get("tile") else None,
                )
                for e in entries
            ]
        return out

    def save(self, path: Path) -> None:
        path.write_text(self.to_json())

    @classmethod
    def load(cls, path: Path) -> "WorldState":
        if not path.exists():
            return cls()
        return cls.from_json(path.read_text())
