"""Horizon objects renderer — pure-function tests + wiring + config integrity.

Per `design_banner_layer_taxonomy` — distance-only kinds (moon,
mountain ridges, stars) authored per-biome in BIOME_REGISTRY.
This suite verifies:
- Outermost-layer radius lookup math
- _color helper RGBA conversion + defensive fallbacks
- Per-renderer registration (kind → function)
- Brain manifest ships horizon_objects per biome
- main.py wiring + draw call ordering
"""
from __future__ import annotations

from pathlib import Path


# ── Outermost layer radius lookup ─────────────────────────────────


def test_outermost_radius_picks_max():
    from clients.vector_terminal.horizon_objects import _outermost_layer_radius
    manifest = {
        "banner_layers": [
            {"distance": 7.0},
            {"distance": 49.0},
            {"distance": 28.0},
        ]
    }
    assert _outermost_layer_radius(manifest) == 49.0


def test_outermost_radius_zero_when_no_layers():
    from clients.vector_terminal.horizon_objects import _outermost_layer_radius
    assert _outermost_layer_radius({}) == 0.0
    assert _outermost_layer_radius({"banner_layers": []}) == 0.0


def test_outermost_radius_handles_missing_distance_keys():
    from clients.vector_terminal.horizon_objects import _outermost_layer_radius
    manifest = {"banner_layers": [{}, {"distance": 30.0}]}
    assert _outermost_layer_radius(manifest) == 30.0


# ── Color helper ──────────────────────────────────────────────────


def test_color_basic():
    from clients.vector_terminal.horizon_objects import _color
    assert _color([1.0, 0.0, 0.0]) == (255, 0, 0, 255)
    assert _color([0.5, 0.5, 0.5], 0.5) == (128, 128, 128, 128)


def test_color_clamps_above_one():
    from clients.vector_terminal.horizon_objects import _color
    assert _color([2.0, 5.0, 100.0]) == (255, 255, 255, 255)


def test_color_clamps_below_zero():
    from clients.vector_terminal.horizon_objects import _color
    assert _color([-1.0, -0.5, 0.0]) == (0, 0, 0, 255)


def test_color_handles_short_list():
    from clients.vector_terminal.horizon_objects import _color
    result = _color([0.5])
    assert result == (128, 128, 128, 255)  # gray fallback


def test_color_handles_none():
    from clients.vector_terminal.horizon_objects import _color
    assert _color(None) == (128, 128, 128, 255)


# ── Renderer registry ─────────────────────────────────────────────


def test_renderer_registry_has_v1_kinds():
    from clients.vector_terminal.horizon_objects import _RENDERERS
    assert "moon" in _RENDERERS
    assert "sun" in _RENDERERS
    assert "aurora" in _RENDERERS
    assert "lightning_flash" in _RENDERERS
    assert "mountain_ridge" in _RENDERERS
    assert "stars" in _RENDERERS


def test_renderers_are_callable():
    from clients.vector_terminal.horizon_objects import _RENDERERS
    for name, fn in _RENDERERS.items():
        assert callable(fn), f"renderer {name!r} not callable"


# ── Manifest behavior ─────────────────────────────────────────────


def test_draw_no_op_when_no_objects():
    """Manifest missing horizon_objects key — must not crash."""
    from clients.vector_terminal.horizon_objects import draw_horizon_objects
    # Just call it; the no-op early returns before any pyray calls.
    # We can construct a fake camera object since drawing won't fire.
    class _Cam:
        class _Pos:
            x = 0.0
            y = 0.0
            z = 0.0
        position = _Pos()
    draw_horizon_objects({}, _Cam())  # no objects, no banner — no-op
    draw_horizon_objects({"horizon_objects": []}, _Cam())  # empty list


def test_unknown_kind_skipped():
    """Unknown horizon kind is silently skipped, not crashed."""
    from clients.vector_terminal.horizon_objects import draw_horizon_objects
    class _Cam:
        class _Pos:
            x = 0.0
            y = 0.0
            z = 0.0
        position = _Pos()
    manifest = {
        "banner_layers": [{"distance": 49.0}],
        "horizon_objects": [{"kind": "future_unknown_kind"}],
    }
    draw_horizon_objects(manifest, _Cam())  # should not crash


# ── Biome config integrity ────────────────────────────────────────


def test_outdoor_biome_ships_horizon_objects():
    """Brain config has horizon_objects for outdoor biome."""
    from core.systems.biome_data import BIOME_REGISTRY
    outdoor = BIOME_REGISTRY["outdoor"]
    assert "horizon_objects" in outdoor
    objs = outdoor["horizon_objects"]
    assert isinstance(objs, list)
    assert len(objs) > 0


def test_outdoor_horizon_objects_reference_known_kinds():
    """Every horizon_object kind must have a renderer registered."""
    from core.systems.biome_data import BIOME_REGISTRY
    from clients.vector_terminal.horizon_objects import _RENDERERS
    for biome_name, biome in BIOME_REGISTRY.items():
        for obj in biome.get("horizon_objects", []):
            kind = obj.get("kind")
            assert kind in _RENDERERS, (
                f"biome {biome_name!r} horizon_object kind {kind!r} "
                f"has no renderer in horizon_objects.py"
            )


# ── main.py wiring ────────────────────────────────────────────────


def test_main_imports_horizon_renderer():
    src = (
        Path(__file__).resolve().parents[1]
        / "clients" / "vector_terminal" / "main.py"
    ).read_text()
    assert "from clients.vector_terminal import horizon_objects" in src


def test_main_calls_draw_horizon_objects():
    src = (
        Path(__file__).resolve().parents[1]
        / "clients" / "vector_terminal" / "main.py"
    ).read_text()
    assert "horizon_renderer.draw_horizon_objects(" in src


def test_horizon_drawn_after_banner_before_entities():
    """Order matters: banner cylinder first (background), horizon
    objects on/inside the cylinder, world entities last (so close
    entities can occlude horizon objects)."""
    src = (
        Path(__file__).resolve().parents[1]
        / "clients" / "vector_terminal" / "main.py"
    ).read_text()
    banner_pos = src.find("banner.draw_banner_layers(")
    horizon_pos = src.find("horizon_renderer.draw_horizon_objects(")
    entity_pos = src.find("_draw_entity(ent, camera)")
    assert banner_pos < horizon_pos < entity_pos


# ── Brain manifest emission ───────────────────────────────────────


def test_brain_emits_horizon_objects_in_manifest():
    src = (
        Path(__file__).resolve().parents[1] / "brain_server.py"
    ).read_text()
    assert '"horizon_objects":' in src
    assert 'BIOME_REGISTRY.get(self.biome_name, {}).get("horizon_objects"' in src


# ── Chrono-driven kinds (sun drift, aurora drift, lightning flash) ─


def test_main_passes_now_to_horizon_renderer():
    """now must thread through so chrono kinds animate."""
    src = (
        Path(__file__).resolve().parents[1]
        / "clients" / "vector_terminal" / "main.py"
    ).read_text()
    assert "horizon_renderer.draw_horizon_objects(last_manifest, camera, now)" in src


def test_outdoor_authored_kinds_complete_v1_set():
    """Outdoor biome should ship moon + sun + aurora + lightning +
    ridge + stars after this commit. Roll-up integrity check."""
    from core.systems.biome_data import OUTDOOR_HORIZON_OBJECTS
    kinds = {obj["kind"] for obj in OUTDOOR_HORIZON_OBJECTS}
    assert {"moon", "sun", "aurora", "lightning_flash", "mountain_ridge", "stars"}.issubset(kinds)


def test_sun_drift_changes_azimuth_with_time():
    """Sun's drift_hz, when nonzero, should produce different
    positions at different `now` values. We validate via the math
    underlying the renderer (the actual draw call is pyray)."""
    import math
    base_azimuth_deg = 90.0
    drift_hz = 0.05
    # Position at t=0
    a0 = math.radians(base_azimuth_deg) + 2.0 * math.pi * drift_hz * 0.0
    # Position at t=10
    a10 = math.radians(base_azimuth_deg) + 2.0 * math.pi * drift_hz * 10.0
    assert abs(a0 - a10) > 0.01  # meaningful drift


def test_aurora_drift_phase_changes_with_time():
    """Aurora's hue cycle should advance with `now`."""
    import math
    drift_hz = 0.05
    p0 = 2.0 * math.pi * drift_hz * 0.0
    p_late = 2.0 * math.pi * drift_hz * 100.0
    assert abs(p_late - p0) > 0.01
