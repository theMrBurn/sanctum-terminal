"""Silhouette projection — pure-function tests + wiring.

Per `design_banner_layer_taxonomy` Tier 1 (2026-05-02): entities in
outer render shells project as silhouettes on the matching banner
cylinder. The drawing path uses pyray which needs a window context —
we test the pure radius lookup + the wiring static checks.
"""
from __future__ import annotations

from pathlib import Path


def test_radius_for_known_shell_index():
    from clients.vector_terminal.silhouette import (
        _SHELL_RADII,
        _radius_for_shell,
    )
    # Brain assigns shell_idx 0..6 corresponding to 7m..49m radii.
    for i in range(7):
        assert _radius_for_shell(i, 0.0, 0.0, 100.0, 100.0) == _SHELL_RADII[i]


def test_radius_falls_back_to_actual_when_shell_missing():
    """No shell_idx → use actual entity distance, capped at outermost."""
    from clients.vector_terminal.silhouette import _radius_for_shell
    # Entity 30m east at (30, 0); camera at (0, 0). Actual dist 30 < 49.
    result = _radius_for_shell(None, 0.0, 0.0, 30.0, 0.0)
    assert abs(result - 30.0) < 1e-6


def test_radius_clamps_to_outermost_when_actual_far():
    from clients.vector_terminal.silhouette import (
        _SHELL_RADII,
        _radius_for_shell,
    )
    # Entity 100m away — exceeds outermost shell (49m).
    result = _radius_for_shell(None, 0.0, 0.0, 100.0, 0.0)
    assert result == _SHELL_RADII[-1]


def test_radius_falls_back_when_shell_out_of_range():
    """Defensive: a future shell_idx 99 doesn't crash, falls back."""
    from clients.vector_terminal.silhouette import _radius_for_shell
    # Out-of-range shell → falls back to actual distance.
    result = _radius_for_shell(99, 0.0, 0.0, 20.0, 0.0)
    assert abs(result - 20.0) < 1e-6


def test_radius_handles_non_int_shell():
    """Shell idx can be None, missing, or non-int — must not crash."""
    from clients.vector_terminal.silhouette import _radius_for_shell
    assert _radius_for_shell("invalid", 0.0, 0.0, 10.0, 0.0) > 0
    assert _radius_for_shell(None, 0.0, 0.0, 10.0, 0.0) > 0


# ── main.py wiring static checks ──────────────────────────────────


def test_main_imports_silhouette_renderer():
    src = (
        Path(__file__).resolve().parents[1]
        / "clients" / "vector_terminal" / "main.py"
    ).read_text()
    assert "from clients.vector_terminal import silhouette" in src


def test_main_dispatches_render_mode():
    """Entity loop must read render_mode and route to the right path."""
    src = (
        Path(__file__).resolve().parents[1]
        / "clients" / "vector_terminal" / "main.py"
    ).read_text()
    # The dispatch on render_mode field.
    assert 'render_mode = str(ent.get("render_mode"' in src
    assert 'if render_mode == "geometry":' in src
    assert 'silhouette_renderer.draw_silhouette(' in src


# ── RENDER_SHELLS modes updated ───────────────────────────────────


def test_render_shells_all_geometry():
    """2026-05-02: outer-shell silhouette/atmosphere modes reverted —
    binary geometry↔silhouette switch produced disruptive pop-in.
    All shells are geometry until smooth-blend LOD lands. Silhouette
    primitive still available for explicit-silhouette kinds."""
    from core.systems.biome_data import RENDER_SHELLS
    for shell in RENDER_SHELLS:
        assert shell["mode"] == "geometry"


def test_shell_radii_match_silhouette_module():
    """The vector terminal module hardcodes shell radii to mirror brain
    config. Drift between them = silhouettes projecting at wrong depth."""
    from clients.vector_terminal.silhouette import _SHELL_RADII
    from core.systems.biome_data import RENDER_SHELLS
    brain_radii = tuple(float(s["radius"]) for s in RENDER_SHELLS)
    assert _SHELL_RADII == brain_radii
