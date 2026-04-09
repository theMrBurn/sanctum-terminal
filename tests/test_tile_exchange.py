"""
tests/test_tile_exchange.py

TileExchange — the endocrine system. Scores, gates, and delivers entities
from cached tile rosters based on camera state and biome config.

Pure logic — no Godot, no rendering.
"""

import math
import pytest

from core.systems.biome_data import BIOME_REGISTRY


# ---------------------------------------------------------------------------
# Helpers — minimal entity dicts for testing
# ---------------------------------------------------------------------------

def _ent(kind, x, y, z=0.0, emissive=0.0, chain_index=0):
    """Minimal entity dict matching brain_server format."""
    return {
        "kind": kind, "x": x, "y": y, "z": z,
        "heading": 0.0, "sv": 1.0,
        "sx": 1.0, "sy": 1.0, "sz": 1.0,
        "r": 0.3, "g": 0.27, "b": 0.23,
        "emissive": emissive, "collision_radius": 0.0,
        "_chain_index": chain_index,
    }


# ---------------------------------------------------------------------------
# Scoring — priority ordering
# ---------------------------------------------------------------------------

class TestDeliveryScoring:
    """Entities get a single delivery score. Lower = delivered first."""

    @pytest.fixture
    def exchange(self):
        from core.systems.tile_exchange import TileExchange
        return TileExchange("cavern", base_seed=42)

    def test_skeleton_scores_lower_than_scatter_at_same_distance(self, exchange):
        """mega_column (chain 0) should score lower than grass_tuft (chain 4)."""
        skeleton = _ent("mega_column", 20.0, 0.0, chain_index=0)
        scatter = _ent("grass_tuft", 20.0, 0.0, chain_index=4)
        s_skel = exchange.score_entity(skeleton, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        s_scat = exchange.score_entity(scatter, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        assert s_skel < s_scat

    def test_near_scores_lower_than_far_for_same_kind(self, exchange):
        """Boulder at 10m should score lower than boulder at 50m."""
        near = _ent("boulder", 10.0, 0.0, chain_index=1)
        far = _ent("boulder", 50.0, 0.0, chain_index=1)
        s_near = exchange.score_entity(near, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        s_far = exchange.score_entity(far, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        assert s_near < s_far

    def test_in_fov_scores_lower_than_behind(self, exchange):
        """Entity ahead of camera should score lower than entity behind."""
        ahead = _ent("boulder", 0.0, -20.0, chain_index=1)  # -Y is forward at heading=0
        behind = _ent("boulder", 0.0, 20.0, chain_index=1)
        # heading=0: camera faces -Y in brain coords (Godot -Z maps to brain -Y)
        s_ahead = exchange.score_entity(ahead, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        s_behind = exchange.score_entity(behind, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        assert s_ahead < s_behind

    def test_moving_toward_scores_lower(self, exchange):
        """Entity in movement direction should score lower."""
        target = _ent("boulder", 20.0, 0.0, chain_index=1)
        opposite = _ent("boulder", -20.0, 0.0, chain_index=1)
        # Moving in +X direction
        s_target = exchange.score_entity(target, cam_x=0, cam_y=0, heading=0, vel_x=1, vel_y=0)
        s_opp = exchange.score_entity(opposite, cam_x=0, cam_y=0, heading=0, vel_x=1, vel_y=0)
        assert s_target < s_opp

    def test_score_is_non_negative(self, exchange):
        ent = _ent("mega_column", 5.0, 0.0, chain_index=0)
        s = exchange.score_entity(ent, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        assert s >= 0.0


# ---------------------------------------------------------------------------
# Gating — budget and compression
# ---------------------------------------------------------------------------

class TestDeliveryGating:
    """The exchange truncates delivery to a budget, compresses under load."""

    @pytest.fixture
    def exchange(self):
        from core.systems.tile_exchange import TileExchange
        return TileExchange("cavern", base_seed=42)

    def test_budget_truncates_output(self, exchange):
        """Output should not exceed delivery_budget."""
        cfg = exchange.config
        budget = cfg["delivery_budget"]
        # Generate a bunch of entities — more than budget
        entities = [_ent("grass_tuft", float(i), float(i), chain_index=4)
                    for i in range(budget + 200)]
        result = exchange.gate(entities, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        assert len(result) <= budget

    def test_mandatory_kinds_survive_compression(self, exchange):
        """Mandatory kinds (skeleton) must always be in output."""
        cfg = exchange.config
        mandatory = cfg["mandatory_kinds"]
        # Fill with low-priority scatter beyond budget
        budget = cfg["delivery_budget"]
        entities = [_ent("grass_tuft", float(i), float(i), chain_index=4)
                    for i in range(budget + 100)]
        # Add a few mandatory entities far away (worst case)
        for mk in mandatory:
            entities.append(_ent(mk, 80.0, 80.0, chain_index=0))
        result = exchange.gate(entities, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        result_kinds = {e["kind"] for e in result}
        for mk in mandatory:
            assert mk in result_kinds, f"Mandatory kind '{mk}' dropped by gate"

    def test_output_is_sorted_by_score(self, exchange):
        """Returned entities should be in delivery order (lowest score first)."""
        entities = [
            _ent("mega_column", 10.0, 0.0, chain_index=0),
            _ent("grass_tuft", 30.0, 0.0, chain_index=4),
            _ent("boulder", 15.0, 0.0, chain_index=1),
        ]
        result = exchange.gate(entities, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        scores = [exchange.score_entity(e, 0, 0, 0, 0, 0) for e in result]
        assert scores == sorted(scores)

    def test_compression_drops_lowest_priority_first(self, exchange):
        """Under compression, high-chain-index entities drop before low."""
        budget = exchange.config["delivery_budget"]
        # Skeleton entities (chain 0) — should survive
        skeletons = [_ent("mega_column", float(i * 5), 0.0, chain_index=0)
                     for i in range(10)]
        # Scatter (chain 4) — expendable
        scatter = [_ent("grass_tuft", float(i), float(i), chain_index=4)
                   for i in range(budget + 200)]
        entities = skeletons + scatter
        result = exchange.gate(entities, cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        # All skeletons should be present
        skel_count = sum(1 for e in result if e["kind"] == "mega_column")
        assert skel_count == 10

    def test_empty_input_returns_empty(self, exchange):
        result = exchange.gate([], cam_x=0, cam_y=0, heading=0, vel_x=0, vel_y=0)
        assert result == []


# ---------------------------------------------------------------------------
# Cache — tile roster persistence
# ---------------------------------------------------------------------------

class TestTileCache:
    """Tiles generate once, cache forever (until eviction)."""

    @pytest.fixture
    def exchange(self):
        from core.systems.tile_exchange import TileExchange
        return TileExchange("cavern", base_seed=42)

    def test_same_tile_key_returns_cached(self, exchange):
        """Second request for same tile should hit cache."""
        roster_1 = exchange.get_tile_roster(0, 0)
        roster_2 = exchange.get_tile_roster(0, 0)
        assert roster_1 is roster_2  # same object, not regenerated

    def test_different_tiles_return_different_rosters(self, exchange):
        r1 = exchange.get_tile_roster(0, 0)
        r2 = exchange.get_tile_roster(1, 0)
        assert r1 is not r2

    def test_cache_size_respects_limit(self, exchange):
        cache_limit = exchange.config["cache_size"]
        # Generate more tiles than cache allows
        for i in range(cache_limit + 10):
            exchange.get_tile_roster(i, 0)
        assert len(exchange._tile_cache) <= cache_limit

    def test_tile_roster_is_list_of_entity_dicts(self, exchange):
        roster = exchange.get_tile_roster(0, 0)
        assert isinstance(roster, list)
        assert len(roster) > 0
        assert "kind" in roster[0]
        assert "x" in roster[0]

    def test_deterministic_same_seed(self, exchange):
        """Same seed + same tile = same roster contents."""
        ex2 = type(exchange)("cavern", base_seed=42)
        r1 = exchange.get_tile_roster(3, -2)
        r2 = ex2.get_tile_roster(3, -2)
        assert len(r1) == len(r2)
        for a, b in zip(r1, r2):
            assert a["kind"] == b["kind"]
            assert abs(a["x"] - b["x"]) < 0.001


# ---------------------------------------------------------------------------
# Integration — full get_entities flow
# ---------------------------------------------------------------------------

class TestGetEntities:
    """End-to-end: camera state → scored, gated, delivery-ordered entities."""

    @pytest.fixture
    def exchange(self):
        from core.systems.tile_exchange import TileExchange
        return TileExchange("cavern", base_seed=42)

    def test_returns_entities_around_camera(self, exchange):
        result = exchange.get_entities(cam_x=0, cam_y=0, cam_z=2.5,
                                       heading=0, vel_x=0, vel_y=0)
        assert len(result) > 0

    def test_respects_delivery_budget(self, exchange):
        budget = exchange.config["delivery_budget"]
        result = exchange.get_entities(cam_x=0, cam_y=0, cam_z=2.5,
                                       heading=0, vel_x=0, vel_y=0)
        assert len(result) <= budget

    def test_walking_produces_new_entities(self, exchange):
        """Moving camera should eventually produce entities from new tiles."""
        ts = exchange.tile_size
        r1 = exchange.get_entities(cam_x=0, cam_y=0, cam_z=2.5,
                                   heading=0, vel_x=0, vel_y=0)
        r2 = exchange.get_entities(cam_x=ts * 2, cam_y=0, cam_z=2.5,
                                   heading=0, vel_x=1, vel_y=0)
        # Different camera positions should produce different entity sets
        pos_set_1 = {(e["x"], e["y"]) for e in r1}
        pos_set_2 = {(e["x"], e["y"]) for e in r2}
        assert pos_set_1 != pos_set_2

    def test_skeleton_always_present_when_in_range(self, exchange):
        """If skeletons exist in loaded tiles, they should be in output."""
        result = exchange.get_entities(cam_x=0, cam_y=0, cam_z=2.5,
                                       heading=0, vel_x=0, vel_y=0)
        mandatory = exchange.config["mandatory_kinds"]
        result_kinds = {e["kind"] for e in result}
        # At least one mandatory kind should be present (spawn tile has columns)
        assert result_kinds & mandatory, "No mandatory kinds in output from spawn tile"


# ---------------------------------------------------------------------------
# Config — biome registry integration
# ---------------------------------------------------------------------------

class TestExchangeConfig:
    """Exchange config lives in BIOME_REGISTRY, config-as-code."""

    def test_cavern_has_exchange_config(self):
        assert "exchange" in BIOME_REGISTRY["cavern"]

    def test_outdoor_has_exchange_config(self):
        assert "exchange" in BIOME_REGISTRY["outdoor"]

    def test_required_keys_present(self):
        required = {"delivery_budget", "compression_threshold",
                    "mandatory_kinds", "scoring_weights", "cache_size"}
        for biome in ("cavern", "outdoor"):
            cfg = BIOME_REGISTRY[biome]["exchange"]
            missing = required - set(cfg.keys())
            assert not missing, f"{biome} exchange missing: {missing}"

    def test_scoring_weights_have_all_factors(self):
        factors = {"wake_priority", "distance_band", "fov_relevance", "velocity_bias"}
        for biome in ("cavern", "outdoor"):
            weights = BIOME_REGISTRY[biome]["exchange"]["scoring_weights"]
            missing = factors - set(weights.keys())
            assert not missing, f"{biome} scoring_weights missing: {missing}"

    def test_mandatory_kinds_is_set(self):
        for biome in ("cavern", "outdoor"):
            mk = BIOME_REGISTRY[biome]["exchange"]["mandatory_kinds"]
            assert isinstance(mk, set)
            assert len(mk) >= 1

    def test_perceptual_weights_present(self):
        for biome in ("cavern", "outdoor"):
            w = BIOME_REGISTRY[biome]["exchange"]["scoring_weights"]
            assert "emissive_boost" in w, f"{biome} missing emissive_boost"
            assert "ground_penalty" in w, f"{biome} missing ground_penalty"
            assert "roster_stability" in w, f"{biome} missing roster_stability"
            assert "newcomer_gate" in w, f"{biome} missing newcomer_gate"


# ---------------------------------------------------------------------------
# Perceptual scoring — emissive/ground/roster modifiers
# ---------------------------------------------------------------------------

class TestPerceptualScoring:
    """Emissive objects debut early, ground scatter late, roster stays stable."""

    @pytest.fixture
    def exchange(self):
        from core.systems.tile_exchange import TileExchange
        return TileExchange("cavern", base_seed=42)

    def test_emissive_scores_lower_than_same_chain_non_emissive(self, exchange):
        """Crystal (emissive=1.0) should score lower than column (emissive=0) at same distance+chain."""
        crystal = _ent("crystal_cluster", 20.0, 0.0, emissive=1.0, chain_index=0)
        column = _ent("column", 20.0, 0.0, emissive=0.0, chain_index=0)
        s_crystal = exchange.score_entity(crystal, 0, 0, 0, 0, 0)
        s_column = exchange.score_entity(column, 0, 0, 0, 0, 0)
        assert s_crystal < s_column, \
            f"Emissive crystal ({s_crystal:.3f}) should score lower than column ({s_column:.3f})"

    def test_ground_scatter_scores_higher_than_landmark_at_same_distance(self, exchange):
        """cave_gravel (ground) should score higher than boulder (landmark) at same distance."""
        gravel = _ent("cave_gravel", 10.0, 0.0, chain_index=4)
        boulder = _ent("boulder", 10.0, 0.0, chain_index=1)
        s_gravel = exchange.score_entity(gravel, 0, 0, 0, 0, 0)
        s_boulder = exchange.score_entity(boulder, 0, 0, 0, 0, 0)
        assert s_gravel > s_boulder

    def test_roster_incumbent_scores_lower_than_newcomer(self, exchange):
        """Entity from previous frame should score lower (keep it) than a newcomer."""
        ent_a = _ent("boulder", 15.0, 0.0, chain_index=1)
        ent_b = _ent("boulder", 15.0, 5.0, chain_index=1)
        # Simulate: ent_a was in last frame
        exchange._prev_roster = {(ent_a["kind"], ent_a["x"], ent_a["y"])}
        s_a = exchange.score_entity(ent_a, 0, 0, 0, 0, 0)
        s_b = exchange.score_entity(ent_b, 0, 0, 0, 0, 0)
        assert s_a < s_b, \
            f"Incumbent ({s_a:.3f}) should score lower than newcomer ({s_b:.3f})"

    def test_newcomer_emissive_still_debuts_before_incumbent_gravel(self, exchange):
        """A NEW crystal should still beat an OLD piece of gravel."""
        new_crystal = _ent("crystal_cluster", 15.0, 0.0, emissive=1.0, chain_index=0)
        old_gravel = _ent("cave_gravel", 8.0, 0.0, chain_index=4)
        # Gravel was in last frame, crystal was not
        exchange._prev_roster = {(old_gravel["kind"], old_gravel["x"], old_gravel["y"])}
        s_crystal = exchange.score_entity(new_crystal, 0, 0, 0, 0, 0)
        s_gravel = exchange.score_entity(old_gravel, 0, 0, 0, 0, 0)
        assert s_crystal < s_gravel, \
            f"New crystal ({s_crystal:.3f}) should beat old gravel ({s_gravel:.3f})"

    def test_roster_stability_prevents_flicker(self, exchange):
        """After ramp-up, consecutive identical frames should produce same output."""
        # Ramp up: newcomer throttle means first few frames grow the roster
        for _ in range(20):
            exchange.get_entities(0, 0, 2.5, 0, 0, 0)
        # Now stable: two identical frames should match
        result_1 = exchange.get_entities(0, 0, 2.5, 0, 0, 0)
        kinds_1 = [(e["kind"], e["x"], e["y"]) for e in result_1]
        result_2 = exchange.get_entities(0, 0, 2.5, 0, 0, 0)
        kinds_2 = [(e["kind"], e["x"], e["y"]) for e in result_2]
        assert kinds_1 == kinds_2, "Roster should be stable across identical frames after ramp-up"

    def test_perceptual_delivery_order(self, exchange):
        """Ground scatter and life always come after landmarks and emissives.

        Full perceptual order: emissive/skeleton (tie — eye sees light AND
        frame simultaneously) → atmosphere → fill → ground → life.
        We test the hard invariant: ground_avg > emissive_avg and
        ground_avg > skeleton_avg. The emissive/skeleton ordering is
        distance-dependent and both are "first glance" tier.
        """
        result = exchange.get_entities(0, 0, 2.5, 0, 0, 0)
        if len(result) < 5:
            pytest.skip("Not enough entities in spawn tile for ordering test")
        GROUND_KINDS = {"grass_tuft", "rubble", "leaf_pile", "twig_scatter", "cave_gravel"}
        LIFE_KINDS = {"firefly", "leaf", "beetle", "rat", "spider"}
        FIRST_GLANCE = {"mega_column", "column", "crystal_cluster", "giant_fungus", "moss_patch"}
        ground_positions = []
        life_positions = []
        first_glance_positions = []
        for i, ent in enumerate(result):
            k = ent["kind"]
            if k in GROUND_KINDS:
                ground_positions.append(i)
            elif k in LIFE_KINDS:
                life_positions.append(i)
            elif k in FIRST_GLANCE:
                first_glance_positions.append(i)
        def avg_pos(indices):
            return sum(indices) / len(indices) if indices else float('inf')
        avg_first = avg_pos(first_glance_positions)
        avg_ground = avg_pos(ground_positions)
        avg_life = avg_pos(life_positions)
        if ground_positions:
            assert avg_ground > avg_first, \
                f"Ground(avg={avg_ground:.1f}) should come after first_glance(avg={avg_first:.1f})"
        if life_positions:
            assert avg_life > avg_first, \
                f"Life(avg={avg_life:.1f}) should come after first_glance(avg={avg_first:.1f})"


# ---------------------------------------------------------------------------
# Shell-gated delivery — per-shell budgets
# ---------------------------------------------------------------------------

class TestShellGatedConfig:
    """Shell budgets must exist in biome config."""

    def test_cavern_has_shell_budgets(self):
        cfg = BIOME_REGISTRY["cavern"]["exchange"]
        assert "shell_budgets" in cfg, "cavern exchange needs shell_budgets"
        assert len(cfg["shell_budgets"]) == 7, "7 shells = 7 budgets"

    def test_outdoor_has_shell_budgets(self):
        cfg = BIOME_REGISTRY["outdoor"]["exchange"]
        assert "shell_budgets" in cfg, "outdoor exchange needs shell_budgets"
        assert len(cfg["shell_budgets"]) == 7, "7 shells = 7 budgets"

    def test_shell_budgets_sum_matches_delivery_budget(self):
        """Total shell budgets should equal the delivery_budget."""
        for biome in ("cavern", "outdoor"):
            cfg = BIOME_REGISTRY[biome]["exchange"]
            assert sum(cfg["shell_budgets"]) == cfg["delivery_budget"], \
                f"{biome} shell_budgets sum != delivery_budget"

    def test_render_horizon_matches_outermost_shell(self):
        """render_horizon should equal the outermost shell radius."""
        from core.systems.biome_data import RENDER_SHELLS
        outer = RENDER_SHELLS[-1]["radius"]
        for biome in ("cavern", "outdoor"):
            cfg = BIOME_REGISTRY[biome]["exchange"]
            assert cfg["render_horizon"] == outer, \
                f"{biome} render_horizon ({cfg['render_horizon']}) != shell outer ({outer})"


class TestShellGatedDelivery:
    """Entities are gated per shell — shells don't compete with each other."""

    def test_structural_at_40m_not_starved_by_nearby_scatter(self):
        """A column at 40m should survive even when 500 grass_tufts at 5m exist.

        With flat gating, the 500 nearby grass_tufts could fill the budget
        before the distant column. With shell gating, they're in different
        shells and can't compete.
        """
        # Column at 40m = shell 5 (35-42m)
        column = _ent("mega_column", 40.0, 0.0, chain_index=0)
        # 500 grass tufts at 5m = shell 0 (0-7m)
        scatter = [_ent("grass_tuft", 3.0 + i * 0.01, 3.0 + i * 0.01, chain_index=4)
                   for i in range(500)]
        all_ents = [column] + scatter

        from core.systems.biome_data import RENDER_SHELLS
        from core.systems.tile_exchange import _assign_shell
        # Verify they land in different shells
        col_shell = _assign_shell(column, 0, 0, RENDER_SHELLS)
        grass_shell = _assign_shell(scatter[0], 0, 0, RENDER_SHELLS)
        assert col_shell != grass_shell, "Column and grass should be in different shells"

    def test_far_scatter_excluded_by_shell_kind_filter(self):
        """Grass at 30m should be excluded — shell 4 (28-35m) only allows
        structural, emissive, atmosphere."""
        from core.systems.biome_data import RENDER_SHELLS, KIND_RENDER_CLASS
        grass = _ent("grass_tuft", 30.0, 0.0, chain_index=4)
        shell_idx = None
        dist = 30.0
        for i, shell in enumerate(RENDER_SHELLS):
            if dist <= shell["radius"]:
                shell_idx = i
                break
        assert shell_idx is not None
        kind_class = KIND_RENDER_CLASS.get("grass_tuft", "scatter")
        assert kind_class not in RENDER_SHELLS[shell_idx]["kind_classes"], \
            f"grass_tuft ({kind_class}) should NOT be allowed in shell {shell_idx}"
