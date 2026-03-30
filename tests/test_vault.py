"""
tests/test_vault.py

Vault -- unified read/write interface for world state.
One object. Ask it anything.

Tables:
    archive   -- relics (already exists)
    scenarios -- scenario ledger (new)
    objects   -- catalog cache (new, populated from objects.json)
"""
import pytest
import json
from pathlib import Path


@pytest.fixture
def vault(tmp_path):
    from core.vault import vault
    return vault(db_path=tmp_path / "vault.db")


@pytest.fixture
def seeded_vault(tmp_path):
    from core.vault import vault
    v = vault(db_path=tmp_path / "vault.db")
    v.persist("Morning Run",        vibe="Discipline", impact_rating=3)
    v.persist("Launch Side Project", vibe="Ambition",   impact_rating=7)
    v.persist("Dentist",             vibe="Dread",      impact_rating=4)
    return v


# -- Existing interface --------------------------------------------------------

class TestVaultExisting:

    def test_boots(self, vault):
        assert vault is not None

    def test_persist_and_load(self, vault):
        vault.persist("Test Event", vibe="calm", impact_rating=3)
        relics = vault.load_all()
        assert any(r["archetypal_name"] == "Test Event" for r in relics)

    def test_store_retrieve(self, vault):
        vault.store("key", "value")
        assert vault.retrieve("key") == "value"


# -- Scenario ledger -----------------------------------------------------------

class TestVaultScenarios:

    def test_write_scenario(self, vault):
        """Scenario written to ledger with provenance hash."""
        sid = vault.write_scenario({
            "id":              "abc123",
            "type":            "fetch",
            "state":           "ACTIVE",
            "objective":       "Pick up the stone.",
            "provenance_hash": "deadbeef",
        })
        assert sid is not None

    def test_read_scenario_by_id(self, vault):
        vault.write_scenario({
            "id":              "abc123",
            "type":            "fetch",
            "state":           "ACTIVE",
            "objective":       "Pick up the stone.",
            "provenance_hash": "deadbeef",
        })
        result = vault.scenario_by_id("abc123")
        assert result is not None
        assert result["type"] == "fetch"
        assert result["provenance_hash"] == "deadbeef"

    def test_scenario_by_hash(self, vault):
        vault.write_scenario({
            "id":              "abc123",
            "type":            "fetch",
            "state":           "COMPLETE",
            "objective":       "Pick up the stone.",
            "provenance_hash": "deadbeef",
        })
        result = vault.scenario_by_hash("deadbeef")
        assert result is not None
        assert result["id"] == "abc123"

    def test_scenarios_by_state(self, vault):
        vault.write_scenario({"id": "s1", "type": "fetch",
            "state": "COMPLETE",  "objective": "x", "provenance_hash": "h1"})
        vault.write_scenario({"id": "s2", "type": "hunt",
            "state": "ACTIVE",   "objective": "y", "provenance_hash": "h2"})
        vault.write_scenario({"id": "s3", "type": "switch",
            "state": "COMPLETE",  "objective": "z", "provenance_hash": "h3"})
        complete = vault.scenarios_by_state("COMPLETE")
        assert len(complete) == 2
        assert all(s["state"] == "COMPLETE" for s in complete)

    def test_update_scenario_state(self, vault):
        vault.write_scenario({"id": "s1", "type": "fetch",
            "state": "ACTIVE", "objective": "x", "provenance_hash": "h1"})
        vault.update_scenario_state("s1", "COMPLETE")
        result = vault.scenario_by_id("s1")
        assert result["state"] == "COMPLETE"

    def test_all_scenarios(self, vault):
        vault.write_scenario({"id": "s1", "type": "fetch",
            "state": "PENDING", "objective": "a", "provenance_hash": "h1"})
        vault.write_scenario({"id": "s2", "type": "hunt",
            "state": "ACTIVE",  "objective": "b", "provenance_hash": "h2"})
        all_s = vault.all_scenarios()
        assert len(all_s) == 2

    def test_duplicate_hash_raises(self, vault):
        vault.write_scenario({"id": "s1", "type": "fetch",
            "state": "PENDING", "objective": "a", "provenance_hash": "same"})
        with pytest.raises(Exception):
            vault.write_scenario({"id": "s2", "type": "hunt",
                "state": "PENDING", "objective": "b", "provenance_hash": "same"})


# -- Object catalog query ------------------------------------------------------

class TestVaultObjects:

    def test_seed_objects_from_json(self, vault):
        """Vault can ingest objects.json catalog."""
        vault.seed_objects()
        objects = vault.all_objects()
        assert len(objects) > 0

    def test_object_by_id(self, vault):
        vault.seed_objects()
        obj = vault.object_by_id("river_stone")
        assert obj is not None
        assert obj["id"] == "river_stone"

    def test_objects_by_role(self, vault):
        vault.seed_objects()
        edges = vault.objects_by_role("edge")
        assert len(edges) > 0
        assert all(o["role"] == "edge" for o in edges)

    def test_objects_by_category(self, vault):
        vault.seed_objects()
        flora = vault.objects_by_category("flora")
        assert len(flora) > 0
        assert all(o["category"] == "flora" for o in flora)

    def test_object_by_id_unknown_returns_none(self, vault):
        vault.seed_objects()
        assert vault.object_by_id("nonexistent_thing") is None

    def test_seed_objects_idempotent(self, vault):
        """Seeding twice does not duplicate objects."""
        vault.seed_objects()
        vault.seed_objects()
        objects = vault.all_objects()
        ids = [o["id"] for o in objects]
        assert len(ids) == len(set(ids))


# -- Cross-query ---------------------------------------------------------------

class TestVaultCrossQuery:

    def test_scenario_count_by_type(self, vault):
        vault.write_scenario({"id": "s1", "type": "fetch",
            "state": "COMPLETE", "objective": "a", "provenance_hash": "h1"})
        vault.write_scenario({"id": "s2", "type": "fetch",
            "state": "COMPLETE", "objective": "b", "provenance_hash": "h2"})
        vault.write_scenario({"id": "s3", "type": "hunt",
            "state": "ACTIVE",   "objective": "c", "provenance_hash": "h3"})
        counts = vault.scenario_counts_by_type()
        assert counts["fetch"] == 2
        assert counts["hunt"]  == 1

    def test_impact_weighted_scenario_rate(self, seeded_vault):
        """High impact relics should correlate with more scenarios."""
        seeded_vault.write_scenario({"id": "s1", "type": "fetch",
            "state": "COMPLETE", "objective": "a", "provenance_hash": "h1"})
        rate = seeded_vault.completion_rate()
        assert 0.0 <= rate <= 1.0

    def test_completion_rate_zero_when_none_complete(self, vault):
        vault.write_scenario({"id": "s1", "type": "fetch",
            "state": "ACTIVE", "objective": "a", "provenance_hash": "h1"})
        assert vault.completion_rate() == 0.0

    def test_completion_rate_one_when_all_complete(self, vault):
        vault.write_scenario({"id": "s1", "type": "fetch",
            "state": "COMPLETE", "objective": "a", "provenance_hash": "h1"})
        vault.write_scenario({"id": "s2", "type": "hunt",
            "state": "COMPLETE", "objective": "b", "provenance_hash": "h2"})
        assert vault.completion_rate() == 1.0
