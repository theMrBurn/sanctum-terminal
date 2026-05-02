"""Vector terminal banner renderer — pure-function tests + wiring.

The drawing path uses pyray (raylib bindings) which needs a window
context — not testable in unit. So we test:
- The pure color math (`_layer_color` clamping + tuple shape)
- The wiring (main.py imports banner; render loop calls it)

The visual behavior (cylinders appearing camera-anchored, layers in
correct depth order) is covered by VISUAL UAT.
"""
from __future__ import annotations

from pathlib import Path


def test_layer_color_basic_high_opacity():
    """Opacity 1.0 * boost 6.0 caps at 1.0 → alpha 255."""
    from clients.vector_terminal.banner import _layer_color
    assert _layer_color([1.0, 0.0, 0.0], 1.0) == (255, 0, 0, 255)


def test_layer_color_alpha_boost_amplifies_low_opacity():
    """Config opacity 0.05 (typical inner banner layer) gets boosted
    6x to 0.30, resulting alpha ~76-77. Without the boost it would be
    ~13 (invisible against black)."""
    from clients.vector_terminal.banner import _layer_color
    result = _layer_color([1.0, 1.0, 1.0], 0.05)
    # 0.05 * 6 ≈ 0.30, > floor 0.25, so ~0.30 * 255 ≈ 76-77 (float-precision sensitive)
    assert 75 <= result[3] <= 78


def test_layer_color_alpha_floor_kicks_in_for_near_zero_opacity():
    """Config opacity 0.02 (outermost-bright layer) below floor; uses
    floor of 0.25 → alpha 64. Visibility guaranteed."""
    from clients.vector_terminal.banner import _layer_color
    result = _layer_color([1.0, 1.0, 1.0], 0.02)
    # 0.02 * 6 = 0.12 < floor 0.25, so floor used: 0.25 * 255 = 64
    assert result[3] == 64


def test_layer_color_outermost_layer_caps_at_full_alpha():
    """Outermost banner layer (opacity 0.21) boosted 6x = 1.26, caps
    to 1.0 → alpha 255. Outer cylinder reads as solid horizon."""
    from clients.vector_terminal.banner import _layer_color
    result = _layer_color([1.0, 1.0, 1.0], 0.21)
    assert result[3] == 255


def test_layer_color_clamps_rgb_above_one():
    """Defensive: tint values above 1.0 clamp to 255, not overflow."""
    from clients.vector_terminal.banner import _layer_color
    result = _layer_color([2.0, 5.0, 100.0], 1.0)
    assert result[0] == 255 and result[1] == 255 and result[2] == 255


def test_layer_color_clamps_rgb_below_zero():
    """Defensive: negative tint clamps to 0, not negative bytes."""
    from clients.vector_terminal.banner import _layer_color
    result = _layer_color([-1.0, -5.0, 0.0], 1.0)
    assert result[0] == 0 and result[1] == 0


def test_layer_color_negative_opacity_uses_floor():
    """Negative opacity gets floored to 0.25 (visibility minimum)."""
    from clients.vector_terminal.banner import _layer_color
    result = _layer_color([1.0, 1.0, 1.0], -0.5)
    assert result[3] == 64  # floor 0.25 * 255 = 64


def test_layer_color_handles_short_tint():
    """Defensive against config drift — a tint with fewer than 3 entries
    falls back to gray, doesn't crash."""
    from clients.vector_terminal.banner import _layer_color
    result = _layer_color([0.5], 1.0)
    # tint falls back to (0.5, 0.5, 0.5) gray; alpha = boost(1.0) = 1.0 → 255
    assert result == (128, 128, 128, 255)


def test_layer_color_handles_non_list_tint():
    from clients.vector_terminal.banner import _layer_color
    result = _layer_color(None, 1.0)
    assert result == (128, 128, 128, 255)


def test_layer_color_returns_int_tuple():
    """raylib expects ints; floats break the bindings silently."""
    from clients.vector_terminal.banner import _layer_color
    result = _layer_color([0.123, 0.456, 0.789], 0.321)
    assert all(isinstance(v, int) for v in result)


# ── Wiring static checks ──────────────────────────────────────────


def test_main_imports_banner_module():
    src = (
        Path(__file__).resolve().parents[1]
        / "clients" / "vector_terminal" / "main.py"
    ).read_text()
    assert "from clients.vector_terminal import banner" in src


def test_main_calls_draw_banner_layers():
    src = (
        Path(__file__).resolve().parents[1]
        / "clients" / "vector_terminal" / "main.py"
    ).read_text()
    assert "banner.draw_banner_layers(" in src


def test_banner_called_before_entity_draw():
    """Cylinders should be drawn BEFORE the entity loop so they sit
    behind world geometry visually (the depth buffer handles correct
    occlusion either way; this ordering is also defensive against
    future alpha-blended layers)."""
    src = (
        Path(__file__).resolve().parents[1]
        / "clients" / "vector_terminal" / "main.py"
    ).read_text()
    banner_pos = src.find("banner.draw_banner_layers(")
    entity_pos = src.find("_draw_entity(ent, camera)")
    assert banner_pos > 0
    assert entity_pos > 0
    assert banner_pos < entity_pos


def test_banner_module_no_op_on_missing_layers():
    """Manifest without banner_layers (older brain, tests, transitional
    states) should return without error — we just won't render
    cylinders."""
    # Test this by importing the function and inspecting its early-return.
    import inspect
    from clients.vector_terminal import banner
    source = inspect.getsource(banner.draw_banner_layers)
    # The function must read banner_layers defensively.
    assert "manifest.get(\"banner_layers\")" in source
    # It must short-circuit on empty.
    assert "if not layers:" in source
    assert "return" in source
