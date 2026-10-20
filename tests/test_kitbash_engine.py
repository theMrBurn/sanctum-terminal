"""
tests/test_kitbash_engine.py

KitbashEngine (Persona A) -- renderer-agnostic assembly core + vault assembly
ledger (spec_kitbash_greeble.md §1-2).

Pure logic: no Panda3D / bpy / headless machinery needed.

Coverage:
  (a) determinism / reproducibility  -- TEST: fixed base + signal + parts ->
      identical AssemblyResult; re-deriving the hash from the ledger row alone
      reproduces the stored provenance_hash (the acceptance bar).
  (b) compatibility rejection        -- TEST: incompatible socket_type and
      incompatible scale reject; a compatible pair accepts.
  (c) high-entropy vs stable bias    -- TEST: stable <= high distinct-category
      count (uniform same-kit vs scavenged/mismatched).
  (d) schema add is a MIGRATION      -- MIGRATION: old vault loads; assemblies
      appears and pre-existing tables still query.
"""

import pytest

from core.systems.kitbash_engine import (
    KitbashEngine,
    Base,
    Socket,
    Part,
    AssemblyResult,
)


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    from core.vault import vault
    return vault(db_path=tmp_path / "vault.db")


@pytest.fixture
def base():
    """A base with three named attach points across two scale classes."""
    return Base(
        base_id="hull_alpha",
        sockets=(
            Socket(name="dorsal",     socket_type="mount",  scale_class="medium"),
            Socket(name="port_wing",  socket_type="mount",  scale_class="medium"),
            Socket(name="antenna",    socket_type="spire",  scale_class="small"),
        ),
    )


@pytest.fixture
def parts():
    """Small fixture parts table -- NOT the real library. Two kits (categories):
    'industrial' and 'organic', plus a spire part in each."""
    return [
        Part("ind_mount_a", frozenset({"mount"}), "medium", category="industrial"),
        Part("ind_mount_b", frozenset({"mount"}), "medium", category="industrial"),
        Part("ind_spire",   frozenset({"spire"}), "small",  category="industrial"),
        Part("org_mount_a", frozenset({"mount"}), "medium", category="organic"),
        Part("org_mount_b", frozenset({"mount"}), "medium", category="organic"),
        Part("org_spire",   frozenset({"spire"}), "small",  category="organic"),
    ]


# -- (a) determinism / reproducibility ----------------------------------------

class TestDeterminism:

    def test_same_inputs_same_result(self, base, parts):
        eng = KitbashEngine()
        signal = {"entropy": 0.0, "atmosphere": "still"}
        r1 = eng.assemble(base, parts, signal, seed=7)
        r2 = eng.assemble(base, parts, signal, seed=7)
        assert isinstance(r1, AssemblyResult)
        assert r1.base_id == "hull_alpha"
        assert r1.bindings == r2.bindings
        assert r1.signal_snapshot == r2.signal_snapshot
        # bindings sorted by socket name, one per socket that had a candidate
        names = [b[0] for b in r1.bindings]
        assert names == sorted(names)
        assert len(r1.bindings) == 3

    def test_reproducible_from_ledger_row(self, base, parts, vault):
        eng = KitbashEngine()
        signal = {"entropy": 0.2, "atmosphere": "still"}
        result = eng.assemble(base, parts, signal, seed=7)

        h1 = vault.record_assembly(result)
        # INSERT OR IGNORE: replay of the identical result no-ops to same hash
        h2 = vault.record_assembly(result)
        assert h1 == h2

        row = vault.assembly_by_hash(h1)
        assert row is not None
        assert row["base_id"] == "hull_alpha"
        assert row["socket_bindings"] == [list(b) for b in result.bindings]

        # Reproduce the hash FROM THE ROW ALONE (the acceptance bar): feed the
        # deserialized columns back through the same canonicalize+hash path.
        rebuilt = AssemblyResult(
            base_id=row["base_id"],
            bindings=[tuple(b) for b in row["socket_bindings"]],
            signal_snapshot=row["signal_snapshot"],
        )
        base_id, pl, sb, ss = vault._canonical_assembly(rebuilt)
        recomputed = vault._assembly_hash(base_id, pl, sb, ss)
        assert recomputed == row["provenance_hash"] == h1

    def test_hash_is_time_free(self, base, parts, tmp_path):
        """Two vaults on different dbs record the same result -> same hash
        (created_at differs, hash does not)."""
        from core.vault import vault as VaultClass
        eng = KitbashEngine()
        signal = {"entropy": 0.0}
        result = eng.assemble(base, parts, signal, seed=1)
        v1 = VaultClass(db_path=tmp_path / "a.db")
        v2 = VaultClass(db_path=tmp_path / "b.db")
        assert v1.record_assembly(result) == v2.record_assembly(result)


# -- (b) compatibility rejection ----------------------------------------------

class TestCompatibility:

    def test_type_mismatch_rejected(self):
        eng = KitbashEngine()
        socket = Socket("s", socket_type="mount", scale_class="medium")
        part   = Part("p", frozenset({"spire"}), "medium")   # wrong type
        assert eng._compatible(part, socket) is False

    def test_scale_mismatch_rejected(self):
        eng = KitbashEngine()
        socket = Socket("s", socket_type="mount", scale_class="tiny")
        part   = Part("p", frozenset({"mount"}), "huge")     # 4 bands apart
        assert eng._compatible(part, socket) is False

    def test_compatible_pair_accepts(self):
        eng = KitbashEngine()
        socket = Socket("s", socket_type="mount", scale_class="medium")
        part   = Part("p", frozenset({"mount"}), "large")    # 1 band -> within tol
        assert eng._compatible(part, socket) is True

    def test_socket_with_no_candidate_is_skipped(self, parts):
        """A socket with no compatible part is omitted (partial assembly)."""
        eng = KitbashEngine()
        base = Base("b", sockets=(
            Socket("dorsal",  socket_type="mount",   scale_class="medium"),
            Socket("exotic",  socket_type="unknown", scale_class="medium"),
        ))
        result = eng.assemble(base, parts, {"entropy": 0.0}, seed=0)
        names = [b[0] for b in result.bindings]
        assert names == ["dorsal"]        # 'exotic' skipped


# -- (c) high-entropy vs stable bias ------------------------------------------

class TestSelectionBias:

    def test_stable_no_more_diverse_than_high(self, base, parts):
        eng = KitbashEngine()
        stable = eng.assemble(base, parts, {"entropy": 0.0}, seed=3)
        high   = eng.assemble(base, parts, {"entropy": 1.0}, seed=3)

        def distinct_categories(result):
            by_id = {p.part_id: p.category for p in parts}
            return {by_id[pid] for _, pid in result.bindings}

        stable_cats = distinct_categories(stable)
        high_cats   = distinct_categories(high)
        # Stable biases uniform same-kit; high biases scavenged/mismatched.
        assert len(stable_cats) <= len(high_cats)
        # With this fixture (two mount kits + two spire kits) the extremes are
        # unambiguous: stable collapses to one kit, high spreads to both.
        assert len(stable_cats) == 1
        assert len(high_cats) == 2


# -- (d) schema add is a MIGRATION --------------------------------------------

class TestAssemblyLedgerMigration:

    def test_old_vault_loads_and_assemblies_appears(self, tmp_path):
        from core.vault import vault as VaultClass
        db = tmp_path / "vault.db"
        v1 = VaultClass(db_path=db)
        # write a pre-existing table's row, then reopen (simulates a bump)
        v1.write_scenario({"id": "s1", "type": "fetch", "state": "ACTIVE",
                           "objective": "x", "provenance_hash": "h1"})
        v2 = VaultClass(db_path=db)
        import sqlite3
        with sqlite3.connect(db) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='assemblies'"
            ).fetchone()
        assert row is not None
        # pre-existing data still queryable after the schema add
        assert v2.scenario_by_id("s1")["type"] == "fetch"
