"""BUILD-mode FSM + command composition — T4 of feat/vector-workroom PR 4.

Pyray-driven `handle_input()` requires a window context to run, so these
tests target the pure helpers that compose state and brain payloads:
toggle gate, primitive cycle, selection cycle, command composers,
coordinate conversion, HUD line shape. Visual integration is covered by
the AC's V2–V11 acceptance items run in-engine.
"""
from __future__ import annotations

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _stub_pyray(monkeypatch):
    """build_mode imports pyray at module-load. Real pyray needs a window
    context that pytest can't supply; replace with a minimal stub so the
    module can import cleanly without `rl.init_window`."""
    import types
    stub = types.ModuleType("pyray")
    class _KeyboardKey:
        # Just enough names that build_mode references at import time.
        for name in (
            "KEY_LEFT", "KEY_RIGHT", "KEY_UP", "KEY_DOWN",
            "KEY_PAGE_UP", "KEY_PAGE_DOWN", "KEY_TAB",
            "KEY_LEFT_BRACKET", "KEY_RIGHT_BRACKET",
            "KEY_SPACE", "KEY_DELETE",
            "KEY_KP_ADD", "KEY_KP_SUBTRACT", "KEY_EQUAL", "KEY_MINUS",
            "KEY_COMMA", "KEY_PERIOD",
            "KEY_R", "KEY_G", "KEY_B",
            "KEY_LEFT_SHIFT", "KEY_RIGHT_SHIFT",
        ):
            locals()[name] = name
    stub.KeyboardKey = _KeyboardKey()
    stub.is_key_pressed = lambda *a, **k: False
    stub.is_key_down = lambda *a, **k: False
    class _Vec3:
        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.x, self.y, self.z = x, y, z
    stub.Vector3 = _Vec3
    stub.draw_line_3d = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "pyray", stub)
    yield


from clients.vector_terminal import build_mode  # noqa: E402


# ── Toggle gate ──────────────────────────────────────────────────────


class _FakeCamera:
    def __init__(self, x=0.0, y=2.0, z=0.0):
        import types
        self.position = types.SimpleNamespace(x=x, y=y, z=z)


def test_biome_allows_build_in_any_named_biome():
    """Per `make brain-X` UAT doctrine: BUILD is biome-agnostic. Any
    non-empty biome name permits authoring; empty/missing biome
    (e.g. handshake state before manifest arrives) refuses."""
    assert build_mode.biome_allows_build({"biome": "workroom"}) is True
    assert build_mode.biome_allows_build({"biome": "outdoor"}) is True
    assert build_mode.biome_allows_build({"biome": "cavern"}) is True
    assert build_mode.biome_allows_build({}) is False
    assert build_mode.biome_allows_build({"biome": ""}) is False


def test_toggle_build_silent_no_op_when_biome_missing():
    state = build_mode.BuildState()
    cam = _FakeCamera()
    # Empty manifest (handshake state) — BUILD refuses.
    result = build_mode.toggle_build(state, {}, cam, 0.0)
    assert result is False
    assert state.active is False


def test_toggle_build_enters_in_any_named_biome():
    state = build_mode.BuildState()
    cam = _FakeCamera(x=10.0, y=2.0, z=20.0)
    # Cavern works...
    result = build_mode.toggle_build(state, {"biome": "cavern"}, cam, 0.0)
    assert result is True
    assert state.active is True
    # Cursor placed in front of camera and snapped to 1m grid.
    assert state.cursor_x == 10.0
    assert state.cursor_y == 0.0
    assert state.cursor_z == 24.0


def test_toggle_build_exits_when_already_active():
    state = build_mode.BuildState(active=True)
    cam = _FakeCamera()
    result = build_mode.toggle_build(state, {}, cam, 0.0)
    # Exit succeeds even with no biome — once in BUILD, you can leave.
    assert result is False
    assert state.active is False


# ── Primitive cycling ───────────────────────────────────────────────


def test_cycle_primitive_forward_wraps():
    state = build_mode.BuildState()
    start = state.selected_mesh()
    n = len(build_mode._PRIMITIVE_CYCLE)
    for _ in range(n):
        state.cycle_primitive(1)
    assert state.selected_mesh() == start


def test_cycle_primitive_backward():
    state = build_mode.BuildState()
    state.cycle_primitive(1)
    after_forward = state.selected_mesh()
    state.cycle_primitive(-1)
    assert state.selected_mesh() != after_forward


# ── Coordinate conversion ────────────────────────────────────────────


def test_raylib_brain_round_trip():
    rx, ry, rz = 1.5, 2.5, 3.5
    bx, by, bz = build_mode.raylib_to_brain(rx, ry, rz)
    assert (bx, by, bz) == (1.5, 3.5, 2.5)
    rx2, ry2, rz2 = build_mode.brain_to_raylib(bx, by, bz)
    assert (rx2, ry2, rz2) == (rx, ry, rz)


# ── Selection cycle ─────────────────────────────────────────────────


def _seed(sid, x, y, z, **kw):
    base = {
        "id": sid, "biome": "workroom", "kind": "wireframe_mesh",
        "base_mesh": "cube",
        "pos_x": x, "pos_y": y, "pos_z": z,
        "yaw_deg": 0.0, "scale": 1.0,
        "color_r": 0.7, "color_g": 0.7, "color_b": 0.7,
        "mesh_edits": [],
    }
    base.update(kw)
    return base


def test_cycle_selection_empty_manifest_clears_selection():
    state = build_mode.BuildState(active=True, selected_seed_id=42)
    build_mode.cycle_selection(state, {"seeds": []})
    assert state.selected_seed_id is None


def test_cycle_selection_picks_nearest_first_when_unset():
    # Two seeds in raylib coords: nearest is the one at z=1 from cursor (z=0).
    seeds = [
        _seed(11, x=0.0, y=10.0, z=0.0),  # brain pos_y=10 → raylib z=10
        _seed(22, x=0.0, y=1.0,  z=0.0),  # brain pos_y=1  → raylib z=1
    ]
    state = build_mode.BuildState(active=True, cursor_x=0.0, cursor_z=0.0)
    build_mode.cycle_selection(state, {"seeds": seeds})
    assert state.selected_seed_id == 22


def test_cycle_selection_advances_through_sorted_order():
    seeds = [
        _seed(11, x=0.0, y=1.0, z=0.0),   # raylib z=1
        _seed(22, x=0.0, y=2.0, z=0.0),   # raylib z=2
        _seed(33, x=0.0, y=3.0, z=0.0),   # raylib z=3
    ]
    state = build_mode.BuildState(active=True, cursor_x=0.0, cursor_z=0.0,
                                   selected_seed_id=11)
    build_mode.cycle_selection(state, {"seeds": seeds}, step=1)
    assert state.selected_seed_id == 22
    build_mode.cycle_selection(state, {"seeds": seeds}, step=1)
    assert state.selected_seed_id == 33
    build_mode.cycle_selection(state, {"seeds": seeds}, step=1)
    assert state.selected_seed_id == 11  # wrap


# ── adopt_seed_into_state ───────────────────────────────────────────


def test_adopt_seed_copies_color_scale_yaw():
    state = build_mode.BuildState(active=True)
    seed = _seed(99, x=0.0, y=0.0, z=0.0,
                 color_r=0.3, color_g=0.4, color_b=0.5,
                 scale=1.7, yaw_deg=90.0)
    build_mode.adopt_seed_into_state(state, seed)
    assert state.color_r == 0.3
    assert state.color_g == 0.4
    assert state.color_b == 0.5
    assert state.scale == 1.7
    assert state.yaw_deg == 90.0


# ── Command composition ─────────────────────────────────────────────


def test_compose_create_carries_full_state():
    state = build_mode.BuildState(
        active=True,
        cursor_x=5.0, cursor_y=1.5, cursor_z=-3.0,
        primitive_index=0,  # whatever is first in cycle
        scale=2.0, yaw_deg=45.0,
        color_r=0.1, color_g=0.5, color_b=0.9,
    )
    cmd = build_mode._compose_create(state, biome="cavern")
    assert cmd["cmd"] == "seed_create"
    p = cmd["payload"]
    assert p["biome"] == "cavern"  # honors the passed-in biome
    assert p["kind"] == "wireframe_mesh"
    assert p["base_mesh"] == state.selected_mesh()
    # raylib (5, 1.5, -3) → brain (5, -3, 1.5).
    assert p["pos_x"] == 5.0
    assert p["pos_y"] == -3.0
    assert p["pos_z"] == 1.5
    assert p["yaw_deg"] == 45.0
    assert p["scale"] == 2.0
    assert p["color_r"] == 0.1
    assert p["color_g"] == 0.5
    assert p["color_b"] == 0.9


def test_compose_update_carries_seed_id_and_fields():
    state = build_mode.BuildState(active=True, selected_seed_id=7)
    cmd = build_mode._compose_update(state, {"scale": 1.5, "color_r": 0.9})
    assert cmd == {
        "cmd": "seed_update",
        "seed_id": 7,
        "fields": {"scale": 1.5, "color_r": 0.9},
    }


# ── Color clamping ──────────────────────────────────────────────────


def test_color_clamp():
    assert build_mode._clamp_color(-0.5) == 0.0
    assert build_mode._clamp_color(1.5) == 1.0
    assert build_mode._clamp_color(0.5) == 0.5


def test_scale_clamp():
    assert build_mode._clamp_scale(0.001) == 0.05
    assert build_mode._clamp_scale(99.0) == 20.0
    assert build_mode._clamp_scale(1.0) == 1.0


# ── HUD lines ───────────────────────────────────────────────────────


def test_hud_lines_inactive_returns_empty():
    state = build_mode.BuildState(active=False)
    assert build_mode.hud_lines(state, {}) == []


def test_hud_lines_active_returns_block():
    state = build_mode.BuildState(active=True)
    lines = build_mode.hud_lines(state, {
        "biome": "workroom",
        "seeds": [_seed(1, 0, 0, 0)],
    })
    assert lines  # non-empty
    assert lines[0].startswith("WORKROOM")
    assert any("KIND" in row for row in lines)
    assert any("COUNT" in row for row in lines)


def test_hud_lines_biome_label_reflects_active_biome():
    """The first HUD row uses the manifest's biome name as a prefix —
    any biome the brain serves shows up in the BUILD overlay header."""
    state = build_mode.BuildState(active=True)
    cavern_lines = build_mode.hud_lines(state, {"biome": "cavern", "seeds": []})
    assert cavern_lines[0].startswith("CAVERN")
    outdoor_lines = build_mode.hud_lines(state, {"biome": "outdoor", "seeds": []})
    assert outdoor_lines[0].startswith("OUTDOOR")


def test_hud_lines_count_pluralizes():
    state = build_mode.BuildState(active=True)
    lines_single = build_mode.hud_lines(state, {"seeds": [_seed(1, 0, 0, 0)]})
    lines_multi = build_mode.hud_lines(state, {
        "seeds": [_seed(1, 0, 0, 0), _seed(2, 0, 0, 0)]
    })
    assert any("1 seed" in row and "1 seeds" not in row for row in lines_single)
    assert any("2 seeds" in row for row in lines_multi)


def test_hud_lines_shows_selection_id_or_dash():
    state_no_sel = build_mode.BuildState(active=True)
    lines_a = build_mode.hud_lines(state_no_sel, {"seeds": []})
    assert any("SEL —" in row for row in lines_a)

    state_sel = build_mode.BuildState(active=True, selected_seed_id=42)
    lines_b = build_mode.hud_lines(state_sel, {"seeds": []})
    assert any("SEL #42" in row for row in lines_b)


# ── EDIT sub-mode FSM ────────────────────────────────────────────────


def test_enter_edit_requires_selected_seed():
    """Without a selected seed, PLACE→EDIT is silently refused."""
    state = build_mode.BuildState(active=True, sub_mode="place")
    ok = build_mode.enter_edit(state)
    assert ok is False
    assert state.sub_mode == "place"


def test_enter_edit_with_selected_seed_swaps_sub_mode():
    state = build_mode.BuildState(
        active=True, sub_mode="place", selected_seed_id=7,
    )
    ok = build_mode.enter_edit(state)
    assert ok is True
    assert state.sub_mode == "edit"
    assert state.edit_vertex_idx == 0
    assert state.edit_prev_vertex_idx is None


def test_exit_edit_returns_to_place():
    state = build_mode.BuildState(
        active=True, sub_mode="edit", selected_seed_id=7,
        edit_vertex_idx=4, edit_prev_vertex_idx=3,
    )
    build_mode.exit_edit(state)
    assert state.sub_mode == "place"
    assert state.edit_prev_vertex_idx is None


def test_set_vertex_idx_wraps_and_tracks_previous():
    """_set_vertex_idx mod-wraps the index and preserves the previous
    target as the implicit edge anchor."""
    from core.systems.wireframe_mesh import get_builtin
    cube = get_builtin("cube")
    state = build_mode.BuildState(
        active=True, sub_mode="edit", selected_seed_id=1, edit_vertex_idx=0,
    )
    build_mode._set_vertex_idx(state, 1, cube)
    assert state.edit_vertex_idx == 1
    assert state.edit_prev_vertex_idx == 0
    build_mode._set_vertex_idx(state, 8, cube)  # wraps (cube has 8 verts)
    assert state.edit_vertex_idx == 0
    assert state.edit_prev_vertex_idx == 1


# ── EDIT-mode op composers ─────────────────────────────────────────


def test_compose_seed_update_edits_carries_log():
    state = build_mode.BuildState(active=True, selected_seed_id=42)
    log = [
        {"op": "move_vertex", "i": 0, "to": [1.0, 2.0, 3.0]},
        {"op": "add_edge", "a": 0, "b": 5},
    ]
    cmd = build_mode._compose_seed_update_edits(state, log)
    assert cmd == {
        "cmd": "seed_update",
        "seed_id": 42,
        "fields": {"mesh_edits": log},
    }


def test_compose_seed_update_edits_copies_log():
    """The returned dict's mesh_edits should be a copy, so mutating the
    caller's log after building the command doesn't change what's sent."""
    state = build_mode.BuildState(active=True, selected_seed_id=1)
    log = [{"op": "move_vertex", "i": 0, "to": [0.0, 0.0, 0.0]}]
    cmd = build_mode._compose_seed_update_edits(state, log)
    log.append({"op": "add_edge", "a": 0, "b": 1})
    assert len(cmd["fields"]["mesh_edits"]) == 1


# ── HUD: EDIT sub-mode line ────────────────────────────────────────


def test_hud_lines_edit_appends_edit_row():
    state = build_mode.BuildState(
        active=True, sub_mode="edit", selected_seed_id=1,
        edit_vertex_idx=2, edit_prev_vertex_idx=1,
    )
    manifest = {"seeds": [_seed(1, 0, 0, 0, mesh_edits=[
        {"op": "move_vertex", "i": 0, "to": [1.0, 2.0, 3.0]},
    ])]}
    lines = build_mode.hud_lines(state, manifest)
    assert any(row.startswith("EDIT") for row in lines), lines
    edit_row = [r for r in lines if r.startswith("EDIT")][0]
    assert "v2" in edit_row     # current vertex idx
    assert "prev 1" in edit_row  # previous vertex idx
    assert "log 1" in edit_row   # log length


def test_hud_lines_place_no_edit_row():
    state = build_mode.BuildState(active=True, sub_mode="place")
    lines = build_mode.hud_lines(state, {"seeds": []})
    assert not any(row.startswith("EDIT") for row in lines)


# ── EDIT-mode resolver ─────────────────────────────────────────────


class _FakeCache:
    """Minimal SeedMeshCache stand-in — passes through to replay every call."""

    def resolve(self, seed_id, base_mesh_name, base_mesh, mesh_edits):
        from core.systems.wireframe_edits import replay
        return replay(base_mesh, mesh_edits)

    def forget(self, seed_id):
        pass


def test_resolve_selected_mesh_returns_seed_and_resolved_mesh():
    state = build_mode.BuildState(active=True, selected_seed_id=1)
    manifest = {"seeds": [_seed(1, 0, 0, 0, base_mesh="cube", mesh_edits=[
        {"op": "move_vertex", "i": 0, "to": [9.0, 9.0, 9.0]},
    ])]}
    sel, mesh = build_mode._resolve_selected_mesh(state, manifest, _FakeCache())
    assert sel is not None
    assert mesh is not None
    assert mesh.vertices[0] == (9.0, 9.0, 9.0)  # edit applied


def test_resolve_selected_mesh_handles_missing_seed():
    state = build_mode.BuildState(active=True, selected_seed_id=999)
    manifest = {"seeds": []}
    sel, mesh = build_mode._resolve_selected_mesh(state, manifest, _FakeCache())
    assert sel is None
    assert mesh is None


def test_resolve_selected_mesh_handles_unknown_base_mesh():
    state = build_mode.BuildState(active=True, selected_seed_id=1)
    manifest = {"seeds": [_seed(1, 0, 0, 0, base_mesh="not_a_real_mesh")]}
    sel, mesh = build_mode._resolve_selected_mesh(state, manifest, _FakeCache())
    assert sel is not None
    assert mesh is None


def test_snap_to_vertex_grid():
    """0.1m snap rounds nearest."""
    assert build_mode._snap_to_vertex_grid(0.13) == pytest.approx(0.1)
    assert build_mode._snap_to_vertex_grid(0.16) == pytest.approx(0.2)
    assert build_mode._snap_to_vertex_grid(-0.05) == pytest.approx(-0.0)
