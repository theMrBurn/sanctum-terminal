"""Workroom seed commands — handler contract tests.

T2 of `feat_vector-workroom` PR 1. Validates the four brain dispatch
handlers in `core.systems.seed_commands` against a real vault. Each
handler returns an `ack` dict that the brain socket loop forwards to
the client; tests assert the dict shape directly without a socket.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.systems import seed_commands
from core.vault import vault as Vault


@pytest.fixture
def vault(tmp_path: Path):
    return Vault(db_path=tmp_path / "vault.db")


def _create_one(vault, **overrides) -> int:
    payload = {
        "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "spire",
        "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
    }
    payload.update(overrides)
    ack = seed_commands.handle_seed_create({"payload": payload}, vault)
    assert ack["ok"] is True, ack
    return ack["seed_id"]


# ── seed_create ───────────────────────────────────────────────────────


def test_seed_create_succeeds_with_valid_payload(vault):
    ack = seed_commands.handle_seed_create({
        "payload": {
            "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "spire",
            "pos_x": 1.0, "pos_y": 2.0, "pos_z": 3.0,
        }
    }, vault)
    assert ack["ok"] is True
    assert ack["cmd"] == "seed_create"
    assert isinstance(ack["seed_id"], int)


def test_seed_create_persists_to_vault(vault):
    ack = seed_commands.handle_seed_create({
        "payload": {
            "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "cube",
            "pos_x": 5.0, "pos_y": 0.0, "pos_z": -2.0,
        }
    }, vault)
    seeds = vault.world_seeds_by_biome("workroom")
    assert len(seeds) == 1
    assert seeds[0]["id"] == ack["seed_id"]
    assert seeds[0]["base_mesh"] == "cube"


def test_seed_create_rejects_missing_required_field(vault):
    ack = seed_commands.handle_seed_create({
        "payload": {
            "biome": "workroom", "kind": "wireframe_mesh",
            # base_mesh + pos_* missing
        }
    }, vault)
    assert ack["ok"] is False
    assert ack["cmd"] == "seed_create"
    assert "reason" in ack
    assert vault.world_seeds_by_biome("workroom") == []


def test_seed_create_rejects_bad_mesh_edits(vault):
    ack = seed_commands.handle_seed_create({
        "payload": {
            "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "cube",
            "pos_x": 0.0, "pos_y": 0.0, "pos_z": 0.0,
            "mesh_edits": "not-a-list",
        }
    }, vault)
    assert ack["ok"] is False
    assert "mesh_edits" in ack["reason"]


def test_seed_create_rejects_empty_msg(vault):
    """No payload key at all → vault.world_seed_create raises KeyError."""
    ack = seed_commands.handle_seed_create({}, vault)
    assert ack["ok"] is False


# ── seed_update ───────────────────────────────────────────────────────


def test_seed_update_patches_fields(vault):
    sid = _create_one(vault)
    ack = seed_commands.handle_seed_update({
        "seed_id": sid,
        "fields": {"scale": 2.5, "color_r": 0.9},
    }, vault)
    assert ack["ok"] is True
    assert ack["seed_id"] == sid
    s = vault.world_seeds_by_biome("workroom")[0]
    assert s["scale"] == 2.5
    assert s["color_r"] == 0.9


def test_seed_update_unknown_id_returns_false(vault):
    ack = seed_commands.handle_seed_update({
        "seed_id": 9999,
        "fields": {"scale": 2.0},
    }, vault)
    assert ack["ok"] is False
    assert "9999" in ack["reason"]


def test_seed_update_missing_seed_id(vault):
    ack = seed_commands.handle_seed_update({"fields": {"scale": 2.0}}, vault)
    assert ack["ok"] is False
    assert "missing seed_id" in ack["reason"]


def test_seed_update_invalid_fields_value_returns_false(vault):
    sid = _create_one(vault)
    ack = seed_commands.handle_seed_update({
        "seed_id": sid,
        "fields": {"mesh_edits": "not-a-list"},
    }, vault)
    assert ack["ok"] is False
    assert "mesh_edits" in ack["reason"]


def test_seed_update_replaces_mesh_edits(vault):
    sid = _create_one(vault)
    new_edits = [
        {"op": "move_vertex", "i": 0, "to": [9.0, 9.0, 9.0]},
        {"op": "add_edge", "a": 1, "b": 2},
    ]
    ack = seed_commands.handle_seed_update({
        "seed_id": sid,
        "fields": {"mesh_edits": new_edits},
    }, vault)
    assert ack["ok"] is True
    s = vault.world_seeds_by_biome("workroom")[0]
    assert s["mesh_edits"] == new_edits


# ── seed_delete ───────────────────────────────────────────────────────


def test_seed_delete_removes_existing(vault):
    sid = _create_one(vault)
    ack = seed_commands.handle_seed_delete({"seed_id": sid}, vault)
    assert ack["ok"] is True
    assert ack["seed_id"] == sid
    assert vault.world_seeds_by_biome("workroom") == []


def test_seed_delete_unknown_id_returns_false(vault):
    ack = seed_commands.handle_seed_delete({"seed_id": 9999}, vault)
    assert ack["ok"] is False
    assert "9999" in ack["reason"]


def test_seed_delete_missing_seed_id(vault):
    ack = seed_commands.handle_seed_delete({}, vault)
    assert ack["ok"] is False
    assert "missing seed_id" in ack["reason"]


# ── seed_list ─────────────────────────────────────────────────────────


def test_seed_list_returns_seeds_for_biome(vault):
    _create_one(vault, biome="workroom", base_mesh="cube")
    _create_one(vault, biome="workroom", base_mesh="spire")
    _create_one(vault, biome="outdoor",  base_mesh="octahedron")
    ack = seed_commands.handle_seed_list({"biome": "workroom"}, vault)
    assert ack["ok"] is True
    assert ack["biome"] == "workroom"
    assert len(ack["seeds"]) == 2
    meshes = sorted(s["base_mesh"] for s in ack["seeds"])
    assert meshes == ["cube", "spire"]


def test_seed_list_empty_biome_returns_empty_list(vault):
    ack = seed_commands.handle_seed_list({"biome": "nowhere"}, vault)
    assert ack["ok"] is True
    assert ack["seeds"] == []


def test_seed_list_missing_biome(vault):
    ack = seed_commands.handle_seed_list({}, vault)
    assert ack["ok"] is False
    assert "missing biome" in ack["reason"]


# ── End-to-end through handlers ───────────────────────────────────────


def test_full_lifecycle_through_command_handlers(vault):
    """create → list → update → list → delete → list, ack at each step."""
    create_ack = seed_commands.handle_seed_create({
        "payload": {
            "biome": "workroom", "kind": "wireframe_mesh", "base_mesh": "spire",
            "pos_x": 1.0, "pos_y": 0.0, "pos_z": 1.0,
        }
    }, vault)
    sid = create_ack["seed_id"]

    list_ack_1 = seed_commands.handle_seed_list({"biome": "workroom"}, vault)
    assert len(list_ack_1["seeds"]) == 1
    assert list_ack_1["seeds"][0]["scale"] == 1.0

    update_ack = seed_commands.handle_seed_update({
        "seed_id": sid,
        "fields": {"scale": 1.5, "yaw_deg": 45.0},
    }, vault)
    assert update_ack["ok"] is True

    list_ack_2 = seed_commands.handle_seed_list({"biome": "workroom"}, vault)
    s = list_ack_2["seeds"][0]
    assert s["scale"] == 1.5
    assert s["yaw_deg"] == 45.0

    delete_ack = seed_commands.handle_seed_delete({"seed_id": sid}, vault)
    assert delete_ack["ok"] is True

    list_ack_3 = seed_commands.handle_seed_list({"biome": "workroom"}, vault)
    assert list_ack_3["seeds"] == []
