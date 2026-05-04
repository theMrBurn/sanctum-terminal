"""Per-seed wireframe-mesh cache for the vector terminal.

A seed's rendered mesh is `replay(base_mesh, mesh_edits)`. Replay is
cheap (5 ops × small meshes) but the manifest re-emits every tick;
without a cache, every frame recomputes the same result. This module
memoizes per seed_id, keyed on a signature of the edit log so undo /
redo / out-of-band edits invalidate cleanly.

V1 keeps it simple: one entry per seed_id, replaced when the log
signature changes. No LRU eviction (worlds with thousands of seeds
will need it later — see PR 5 UAT for the data point).

Per `.claude/feature/feat_vector-workroom.md` PR 3.
"""
from __future__ import annotations

import json

from core.systems.wireframe_edits import replay
from core.systems.wireframe_mesh import WireframeMesh


_Cache = dict[int, tuple[str, str, WireframeMesh]]
# value tuple: (base_mesh_name, log_signature, resolved_mesh)


def _log_signature(log) -> str:
    """Stable string signature of the edit log. Two logs that produce
    the same final mesh under replay should produce the same signature
    only when they're literally the same op sequence — we don't try to
    canonicalize equivalent rewrites."""
    if not log:
        return "[]"
    try:
        return json.dumps(log, sort_keys=True, default=str)
    except (TypeError, ValueError):
        # Defensive: any non-JSON content collapses to a plain repr.
        return repr(log)


class SeedMeshCache:
    """In-memory cache of resolved seed meshes. Single-process, single-
    threaded; the vector terminal main loop owns the only instance."""

    def __init__(self):
        self._entries: _Cache = {}

    def resolve(
        self,
        seed_id: int,
        base_mesh_name: str,
        base_mesh: WireframeMesh,
        mesh_edits,
    ) -> WireframeMesh:
        """Return the resolved mesh for `seed_id`. If the base mesh name
        or edit-log signature has changed since last call, recomputes;
        otherwise returns the cached result.

        Empty `mesh_edits` returns `base_mesh` directly without entering
        the cache — replay would be a no-op.
        """
        if not mesh_edits:
            self._entries.pop(seed_id, None)
            return base_mesh
        sig = _log_signature(mesh_edits)
        cached = self._entries.get(seed_id)
        if cached is not None:
            cached_base, cached_sig, cached_mesh = cached
            if cached_base == base_mesh_name and cached_sig == sig:
                return cached_mesh
        resolved = replay(base_mesh, mesh_edits)
        self._entries[seed_id] = (base_mesh_name, sig, resolved)
        return resolved

    def forget(self, seed_id: int) -> None:
        """Drop a single seed's cache entry. Call when a seed is deleted
        so memory doesn't grow with deleted_id keys forever."""
        self._entries.pop(seed_id, None)

    def clear(self) -> None:
        """Drop all cache entries. Useful on biome change / disconnect."""
        self._entries.clear()

    def size(self) -> int:
        return len(self._entries)
