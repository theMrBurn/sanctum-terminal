"""Tests for kind_config.json integrity and self-emit system."""

import json
from pathlib import Path

import pytest


KIND_CONFIG_PATH = Path(__file__).parent.parent / "godot" / "kind_config.json"


@pytest.fixture(scope="module")
def kind_config():
    with open(KIND_CONFIG_PATH) as f:
        return json.load(f)


# -- Schema integrity ----------------------------------------------------------

class TestKindConfigSchema:
    """kind_config.json is well-formed and internally consistent."""

    def test_file_exists(self):
        assert KIND_CONFIG_PATH.exists()

    def test_valid_json(self):
        with open(KIND_CONFIG_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_global(self, kind_config):
        assert "_global" in kind_config

    def test_global_has_world_grain(self, kind_config):
        wg = kind_config["_global"]["world_grain"]
        assert "grain_scale" in wg
        assert "grain_strength" in wg

    def test_all_kinds_have_class(self, kind_config):
        """Every non-global entry must declare a class."""
        for kind, cfg in kind_config.items():
            if kind.startswith("_"):
                continue
            if not isinstance(cfg, dict):
                continue
            # Some entries are nested under class groups
            if "class" in cfg:
                assert isinstance(cfg["class"], str)


# -- 3-color palette system ----------------------------------------------------

LIGHT_REACTIVE_KINDS = [
    "crystal_cluster", "filament", "exit_lure",
    "moss_patch", "ceiling_moss", "firefly",
    # giant_fungus removed 2026-04-10: light_reactive boost combined with
    # warm pipe color was producing uncanny pink glow against the cavern.
    # Now inherits organic_flora class default (false). Pipes still light
    # it diffusely; the shader self-brightening boost is what was wrong.
]


class TestPalette:
    """3-color flat palette: color_base/shadow/accent per kind."""

    def _resolve_kind(self, kind_config, kind):
        """Resolve a kind's effective config (class defaults + overrides)."""
        kinds = kind_config.get("kinds", {})
        defaults = kind_config.get("_class_defaults", {})
        entry = kinds.get(kind, {})
        cls = entry.get("class", "geological")
        base = defaults.get(cls, {}).copy()
        base.update(entry)
        return base

    def test_all_kinds_have_3_colors(self, kind_config):
        """Every kind must resolve to color_base, color_shadow, color_accent."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            for field in ("color_base", "color_shadow", "color_accent"):
                assert field in params, f"{kind} missing {field}"
                assert len(params[field]) == 3, f"{kind}.{field} must be [r,g,b]"

    def test_no_absolute_black(self, kind_config):
        """No color channel below 0.13 — darkest grey is black."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            for field in ("color_base", "color_shadow", "color_accent"):
                for i, v in enumerate(params[field]):
                    assert v >= 0.13, (
                        f"{kind}.{field}[{i}]={v} is below 0.13 floor")

    def test_shadow_darker_than_base(self, kind_config):
        """Shadow color should be darker than or equal to base."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            cb = params["color_base"]
            cs = params["color_shadow"]
            assert sum(cs) <= sum(cb) + 0.01, (
                f"{kind} shadow {cs} is brighter than base {cb}")

    def test_accent_lighter_than_base(self, kind_config):
        """Accent color should be lighter than or equal to base."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            cb = params["color_base"]
            ca = params["color_accent"]
            assert sum(ca) >= sum(cb) - 0.01, (
                f"{kind} accent {ca} is darker than base {cb}")

    def test_color_spread_within_bounds(self, kind_config):
        """Max spread per channel: 0.15 for deaf kinds, 0.25 for light_reactive."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            cs = params["color_shadow"]
            ca = params["color_accent"]
            limit = 0.25 if params.get("light_reactive", False) else 0.15
            for i in range(3):
                diff = abs(ca[i] - cs[i])
                assert diff <= limit, (
                    f"{kind} channel {i}: accent-shadow spread {diff:.3f} > {limit}")

    def test_light_reactive_kinds(self, kind_config):
        """Known light-reactive kinds must have light_reactive=true."""
        for kind in LIGHT_REACTIVE_KINDS:
            params = self._resolve_kind(kind_config, kind)
            assert params.get("light_reactive", False), (
                f"{kind} should be light_reactive")

    def test_crystal_cluster_muted_register(self, kind_config):
        """crystal_cluster must render as deep mineral blue, not pastel ice.

        Pre-fix the accent channel peaked at B=0.66, making crystals the
        brightest thing in the palette (2× any stone) and popping as
        cartoon ice against the warm cavern ground. This contract pulls
        the max channel down under 0.55 — still clearly blue-dominant,
        still crystalline, but sitting within the stone palette instead
        of fighting it. Emission glow (when pipes return) will brighten
        it dynamically without needing the raw albedo to carry the load.
        """
        params = self._resolve_kind(kind_config, "crystal_cluster")
        for field in ("color_base", "color_shadow", "color_accent"):
            col = params[field]
            max_ch = max(col)
            assert max_ch < 0.55, (
                f"crystal_cluster.{field} max channel {max_ch:.3f} >= 0.55 "
                f"(too bright, reads as pastel ice cartoon)")
            # Should still be blue-dominant to read as crystalline
            assert col[2] >= col[0] and col[2] >= col[1], (
                f"crystal_cluster.{field}={col} should be blue-dominant "
                f"(B >= R and B >= G)")

    def test_grass_muted_register(self, kind_config):
        """grass_tuft must render as muted sage, not cartoon green.

        Billboard grass was popping against the warm stone palette in clean
        room diagnostic mode — the accent channel was G=0.42, brighter than
        any other organic_flora kind. Sable-in-reverse calls for a subdued
        chromatic register where grass sits *within* the stone palette, not
        against it. Encoded here:

          - max channel anywhere in the palette must be < 0.38
          - green dominance (G - max(R,B)) stays <= 0.09 (subtle hue, not saturated)

        These thresholds are the floor for "muted sage." If they need to
        move, update them here and explain why — don't silently drift.
        """
        params = self._resolve_kind(kind_config, "grass_tuft")
        for field in ("color_base", "color_shadow", "color_accent"):
            col = params[field]
            max_ch = max(col)
            assert max_ch < 0.38, (
                f"grass_tuft.{field} max channel {max_ch:.3f} >= 0.38 "
                f"(too bright, reads as cartoon)")
            g_dominance = col[1] - max(col[0], col[2])
            assert g_dominance <= 0.09, (
                f"grass_tuft.{field} green dominance {g_dominance:.3f} > 0.09 "
                f"(too saturated, should be muted sage)")


# -- Per-instance horizontal banding (kind_shader) -----------------------------

# Per-class band_strength contract. Drives kind_shader.gdshader's per-instance
# stratification (3-hash banding). Higher = more visible sediment lines.
# Stone classes get strong bands; living/atmospheric kinds stay smooth.
EXPECTED_BAND_STRENGTH = {
    "structural":    (0.18, 0.30),  # columns/buttress — heavy strata
    "geological":    (0.12, 0.25),  # boulders/stalagmites — visible strata
    "crystalline":   (0.05, 0.18),  # crystals — subtle, facets carry it
    "organic_flora": (0.0,  0.0),   # fungus/moss/grass — no rock layers
    "life":          (0.0,  0.0),
    "atmosphere":    (0.0,  0.0),
    "horizon":       (0.0,  0.0),
}

# Per-class wind_strength contract. Drives kind_shader.gdshader's per-instance
# wind sway (TIME + position hash → vertex X displacement × local_y).
# Stone kinds are inert. Organic/life kinds get subtle motion to feel alive.
EXPECTED_WIND_STRENGTH_DEFAULT_ZERO = {
    "structural", "geological", "crystalline", "horizon",
}
EXPECTED_WIND_STRENGTH_ORGANIC_CAP = 0.10  # upper bound for any kind

# Per-class ghost_chance contract. Drives kind_shader.gdshader's distance-
# based half-opacity reveal. At any moment, a hash-selected fraction of
# instances render as "ghosts" — dither-discarded at distance, becoming
# fully solid as the camera approaches. Gives atmospheric reveal without
# fog tuning. Only some classes benefit: geological stones get the effect,
# landmarks/organics stay solid so the scene anchors remain reliable.
EXPECTED_GHOST_CHANCE = {
    "geological":    (0.20, 0.50),  # boulders/stalagmites ghost at distance
    "structural":    (0.0,  0.0),   # columns are landmarks, never ghost
    "crystalline":   (0.0,  0.0),   # crystals are lures, never ghost
    "organic_flora": (0.0,  0.0),
    "life":          (0.0,  0.0),
    "atmosphere":    (0.0,  0.0),
    "horizon":       (0.0,  0.0),
}


class TestBandStrength:
    """Per-instance banding shader contract: every class declares band_strength.

    Verifies the config-as-code wiring for kind_shader.gdshader's per-instance
    horizontal banding. Without this contract, stone kinds default to the
    shader's hard-coded 0.10 (the subtle setting that drowns in clean room
    mode), and there's no way to tune stratification per kind.
    """

    def _resolve_kind(self, kind_config, kind):
        kinds = kind_config.get("kinds", {})
        defaults = kind_config.get("_class_defaults", {})
        entry = kinds.get(kind, {})
        cls = entry.get("class", "geological")
        base = defaults.get(cls, {}).copy()
        base.update(entry)
        return base

    def test_all_classes_declare_band_strength(self, kind_config):
        defaults = kind_config.get("_class_defaults", {})
        for cls in EXPECTED_BAND_STRENGTH:
            assert cls in defaults, f"missing _class_defaults.{cls}"
            assert "band_strength" in defaults[cls], (
                f"_class_defaults.{cls} missing band_strength")

    def test_class_band_strength_in_expected_range(self, kind_config):
        defaults = kind_config.get("_class_defaults", {})
        for cls, (lo, hi) in EXPECTED_BAND_STRENGTH.items():
            bs = defaults[cls]["band_strength"]
            assert lo <= bs <= hi, (
                f"_class_defaults.{cls}.band_strength={bs} outside [{lo}, {hi}]")

    def test_every_kind_resolves_to_band_strength(self, kind_config):
        """Every concrete kind must resolve a band_strength via class default."""
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            assert "band_strength" in params, (
                f"{kind} does not resolve band_strength from its class")
            assert 0.0 <= params["band_strength"] <= 0.30, (
                f"{kind} band_strength={params['band_strength']} out of bounds")

    def test_organic_kinds_have_zero_bands(self, kind_config):
        """Living things don't get rock layers."""
        organic_classes = {"organic_flora", "life", "atmosphere", "horizon"}
        for kind, entry in kind_config.get("kinds", {}).items():
            cls = entry.get("class", "geological")
            if cls not in organic_classes:
                continue
            params = self._resolve_kind(kind_config, kind)
            # Per-kind override could legitimately raise this, but the default
            # is zero. If a future kind needs bands, override and update test.
            assert params["band_strength"] == 0.0, (
                f"{kind} ({cls}) should default to 0 bands, got {params['band_strength']}")

    def test_stone_kinds_have_visible_bands(self, kind_config):
        """Geological + structural + crystalline kinds must have non-zero
        bands UNLESS they use baked vertex colors. The kind_shader gates
        the banding pass off when use_vertex_colors is true (banding would
        paint horizontal stripes across designed color regions), so for
        those kinds the band_strength value is moot."""
        stone_classes = {"geological", "structural", "crystalline"}
        for kind, entry in kind_config.get("kinds", {}).items():
            cls = entry.get("class", "geological")
            if cls not in stone_classes:
                continue
            params = self._resolve_kind(kind_config, kind)
            if params.get("use_vertex_colors", False):
                continue  # banding gated off in shader for these
            assert params["band_strength"] > 0.0, (
                f"{kind} ({cls}) should have visible bands, got 0")


class TestWindStrength:
    """Per-instance wind sway contract: animate organic kinds, keep stone inert.

    The shader multiplies a TIME-driven sine by wind_strength and local_y,
    producing vertex X displacement that bends objects at the top more than
    the base. Stone kinds must stay at 0.0 (rock doesn't sway). Grass/moss/
    vine kinds get small non-zero values so the cavern feels alive.

    The upper cap (0.10) prevents any kind from animating so hard it breaks
    the low-poly silhouette we spent the last 80% of the project earning.
    """

    def _resolve_kind(self, kind_config, kind):
        kinds = kind_config.get("kinds", {})
        defaults = kind_config.get("_class_defaults", {})
        entry = kinds.get(kind, {})
        cls = entry.get("class", "geological")
        base = defaults.get(cls, {}).copy()
        base.update(entry)
        return base

    def test_all_classes_declare_wind_strength(self, kind_config):
        defaults = kind_config.get("_class_defaults", {})
        for cls in defaults:
            assert "wind_strength" in defaults[cls], (
                f"_class_defaults.{cls} missing wind_strength")

    def test_stone_classes_default_to_zero(self, kind_config):
        defaults = kind_config.get("_class_defaults", {})
        for cls in EXPECTED_WIND_STRENGTH_DEFAULT_ZERO:
            ws = defaults[cls]["wind_strength"]
            assert ws == 0.0, (
                f"_class_defaults.{cls}.wind_strength={ws} — rock doesn't sway")

    def test_no_kind_exceeds_wind_cap(self, kind_config):
        for kind in kind_config.get("kinds", {}):
            params = self._resolve_kind(kind_config, kind)
            ws = params.get("wind_strength", 0.0)
            assert ws <= EXPECTED_WIND_STRENGTH_ORGANIC_CAP, (
                f"{kind} wind_strength={ws} > cap {EXPECTED_WIND_STRENGTH_ORGANIC_CAP}")

    def test_grass_tuft_has_nonzero_wind(self, kind_config):
        """Grass must sway — this is the thing that sold the diagnosis."""
        params = self._resolve_kind(kind_config, "grass_tuft")
        ws = params.get("wind_strength", 0.0)
        assert ws > 0.0, (
            f"grass_tuft.wind_strength={ws} — grass should sway")
        assert ws <= EXPECTED_WIND_STRENGTH_ORGANIC_CAP


class TestGhostFade:
    """Distance-based half-opacity reveal contract.

    A hash-selected fraction of instances render as "ghosts" at distance
    via dither discard, becoming fully solid as the camera approaches.
    This gives atmospheric perspective without fog tuning and without
    breaking the flat-shaded look.

    Only geological stones get the effect — structural kinds are
    landmarks (you need to trust they're there), and organics/life
    don't fade in/out like rock does through mist.
    """

    def _resolve_kind(self, kind_config, kind):
        kinds = kind_config.get("kinds", {})
        defaults = kind_config.get("_class_defaults", {})
        entry = kinds.get(kind, {})
        cls = entry.get("class", "geological")
        base = defaults.get(cls, {}).copy()
        base.update(entry)
        return base

    def test_all_classes_declare_ghost_chance(self, kind_config):
        defaults = kind_config.get("_class_defaults", {})
        for cls in EXPECTED_GHOST_CHANCE:
            assert cls in defaults, f"missing _class_defaults.{cls}"
            assert "ghost_chance" in defaults[cls], (
                f"_class_defaults.{cls} missing ghost_chance")

    def test_class_ghost_chance_in_expected_range(self, kind_config):
        defaults = kind_config.get("_class_defaults", {})
        for cls, (lo, hi) in EXPECTED_GHOST_CHANCE.items():
            gc = defaults[cls]["ghost_chance"]
            assert lo <= gc <= hi, (
                f"_class_defaults.{cls}.ghost_chance={gc} outside [{lo}, {hi}]")

    def test_landmarks_never_ghost(self, kind_config):
        """Structural kinds (column/mega_column/buttress) must NEVER ghost —
        they're dramatic landmarks the composition depends on."""
        for kind, entry in kind_config.get("kinds", {}).items():
            if entry.get("class") != "structural":
                continue
            params = self._resolve_kind(kind_config, kind)
            assert params.get("ghost_chance", 0.0) == 0.0, (
                f"{kind} has ghost_chance > 0 — landmarks must stay solid")

    def test_geological_kinds_ghost(self, kind_config):
        """Every geological kind must inherit non-zero ghost_chance."""
        for kind, entry in kind_config.get("kinds", {}).items():
            if entry.get("class") != "geological":
                continue
            params = self._resolve_kind(kind_config, kind)
            assert params.get("ghost_chance", 0.0) > 0.0, (
                f"{kind} (geological) should ghost at distance")


class TestVertexColors:
    """Designed-kind vertex color contract.

    Kinds authored via tools/gen_kind_mesh.py bake per-region colors
    into their mesh (COLOR vertex attribute). The shader reads those
    baked colors directly when use_vertex_colors is true, bypassing
    the facet-normal 3-color palette path.

    Class default is false (stone kinds keep the palette path so
    banding and facet stratification still work). Designed kinds
    override to true explicitly.
    """

    def _resolve_kind(self, kind_config, kind):
        kinds = kind_config.get("kinds", {})
        defaults = kind_config.get("_class_defaults", {})
        entry = kinds.get(kind, {})
        cls = entry.get("class", "geological")
        base = defaults.get(cls, {}).copy()
        base.update(entry)
        return base

    def test_all_classes_default_to_facet_palette(self, kind_config):
        """No class default should silently flip to vertex colors —
        designed kinds must opt in per-kind."""
        defaults = kind_config.get("_class_defaults", {})
        for cls in defaults:
            assert "use_vertex_colors" in defaults[cls], (
                f"_class_defaults.{cls} missing use_vertex_colors")
            assert defaults[cls]["use_vertex_colors"] is False, (
                f"_class_defaults.{cls}.use_vertex_colors should default "
                f"to false — flipped on unexpectedly")

    def test_toadstool_uses_vertex_colors(self, kind_config):
        """toadstool is the first designed kind — mesh authored via
        tools/gen_kind_mesh.py with baked per-region colors."""
        params = self._resolve_kind(kind_config, "toadstool")
        assert params.get("use_vertex_colors") is True, (
            "toadstool must have use_vertex_colors=true so the shader "
            "reads its baked red cap / white spots / dark base ring")

    def test_spore_pod_uses_vertex_colors(self, kind_config):
        """spore_pod is the partner-type kind to giant_fungus, also
        authored via tools/gen_kind_mesh.py with baked dusty mauve."""
        params = self._resolve_kind(kind_config, "spore_pod")
        assert params.get("use_vertex_colors") is True, (
            "spore_pod must have use_vertex_colors=true for baked palette")
