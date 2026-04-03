"""
tests/test_spatial_wake.py

Spatial hash + chain-priority wake system.
Pure logic — no Panda3D, no rendering.
"""

import math
import pytest

from core.systems.spatial_wake import SpatialHash, WakeChain, WAKE_CHAINS


# -- Wake chain config ---------------------------------------------------------

class TestWakeChainConfig:

    def test_outdoor_chain_exists(self):
        assert "outdoor" in WAKE_CHAINS

    def test_cavern_chain_exists(self):
        assert "cavern" in WAKE_CHAINS

    def test_chain_has_links(self):
        for biome, chain in WAKE_CHAINS.items():
            assert len(chain) >= 3, f"{biome} chain too short"

    def test_links_have_required_fields(self):
        for biome, chain in WAKE_CHAINS.items():
            for link in chain:
                assert "name" in link, f"{biome} link missing 'name'"
                assert "kinds" in link, f"{biome} link missing 'kinds'"
                assert "radius" in link, f"{biome} link missing 'radius'"

    def test_radii_decrease_down_chain(self):
        """Earlier links should have >= radius than later links."""
        for biome, chain in WAKE_CHAINS.items():
            for i in range(len(chain) - 1):
                assert chain[i]["radius"] >= chain[i + 1]["radius"], \
                    f"{biome}: {chain[i]['name']} radius < {chain[i+1]['name']}"

    def test_no_duplicate_kinds_across_links(self):
        """Each entity kind should appear in exactly one link."""
        for biome, chain in WAKE_CHAINS.items():
            seen = set()
            for link in chain:
                for kind in link["kinds"]:
                    assert kind not in seen, f"{biome}: '{kind}' in multiple links"
                    seen.add(kind)


# -- Spatial hash --------------------------------------------------------------

class TestSpatialHash:

    def test_insert_and_query(self):
        sh = SpatialHash(cell_size=20.0)
        sh.insert("ent_1", 10.0, 10.0, chain_index=0)
        sh.insert("ent_2", 15.0, 12.0, chain_index=1)
        result = sh.query(10.0, 10.0, radius=25.0)
        ids = [r[0] for r in result]
        assert "ent_1" in ids
        assert "ent_2" in ids

    def test_query_respects_radius(self):
        sh = SpatialHash(cell_size=20.0)
        sh.insert("near", 5.0, 5.0, chain_index=0)
        sh.insert("far", 200.0, 200.0, chain_index=0)
        result = sh.query(0.0, 0.0, radius=30.0)
        ids = [r[0] for r in result]
        assert "near" in ids
        assert "far" not in ids

    def test_query_returns_chain_index(self):
        sh = SpatialHash(cell_size=20.0)
        sh.insert("a", 10.0, 10.0, chain_index=2)
        result = sh.query(10.0, 10.0, radius=25.0)
        assert result[0] == ("a", 2)

    def test_results_sorted_by_chain_index(self):
        """Priority: lower chain_index first."""
        sh = SpatialHash(cell_size=20.0)
        sh.insert("detail", 10.0, 10.0, chain_index=4)
        sh.insert("skeleton", 11.0, 11.0, chain_index=0)
        sh.insert("feature", 12.0, 12.0, chain_index=1)
        result = sh.query(10.0, 10.0, radius=25.0)
        indices = [r[1] for r in result]
        assert indices == sorted(indices), "Results should be sorted by chain_index"

    def test_empty_query(self):
        sh = SpatialHash(cell_size=20.0)
        result = sh.query(100.0, 100.0, radius=10.0)
        assert result == []

    def test_remove(self):
        sh = SpatialHash(cell_size=20.0)
        sh.insert("a", 10.0, 10.0, chain_index=0)
        sh.remove("a", 10.0, 10.0)
        result = sh.query(10.0, 10.0, radius=25.0)
        assert len(result) == 0

    def test_large_entity_count(self):
        """Performance: 10K entities should insert and query fast."""
        sh = SpatialHash(cell_size=20.0)
        import random
        rng = random.Random(42)
        for i in range(10000):
            sh.insert(f"e_{i}", rng.uniform(-500, 500), rng.uniform(-500, 500),
                      chain_index=i % 5)
        result = sh.query(0.0, 0.0, radius=40.0)
        # Should find some entities near origin
        assert len(result) > 0
        # Should be sorted by chain_index
        indices = [r[1] for r in result]
        assert indices == sorted(indices)


# -- WakeChain processor -------------------------------------------------------

class TestWakeChain:

    def setup_method(self):
        self.chain = WakeChain(WAKE_CHAINS["outdoor"])
        self.hash = SpatialHash(cell_size=20.0)

    def test_classify_kind(self):
        """Entity kinds map to chain link indices."""
        idx = self.chain.chain_index("mega_column")
        assert idx == 0  # skeleton
        idx = self.chain.chain_index("grass_tuft")
        assert idx >= 2  # ground cover or later

    def test_unknown_kind_gets_last_index(self):
        idx = self.chain.chain_index("unknown_entity")
        assert idx == len(WAKE_CHAINS["outdoor"]) - 1

    def test_decide_wake_respects_chain_radius(self):
        """Skeleton wakes at full radius, detail only at close range."""
        skeleton_r = WAKE_CHAINS["outdoor"][0]["radius"]
        detail_r = WAKE_CHAINS["outdoor"][-1]["radius"]
        # Skeleton at 35m should wake (radius ~40)
        assert self.chain.should_wake("mega_column", distance=35.0)
        # Detail at 35m should NOT wake (radius ~18)
        last_kind = list(WAKE_CHAINS["outdoor"][-1]["kinds"])[0]
        assert not self.chain.should_wake(last_kind, distance=35.0)

    def test_decide_wake_budget_aware(self):
        """When budget is exhausted, only higher-priority links wake."""
        # With max_links=1, only skeleton should wake
        wake_list = self.chain.compute_wake_set(
            self.hash, cam_x=0, cam_y=0, max_links=1)
        # Should only contain chain_index 0 entities (if any in hash)
        for entity_id, chain_idx in wake_list:
            assert chain_idx == 0
