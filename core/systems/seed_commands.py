"""Workroom seed command handlers — pure functions over (msg, vault).

Each handler validates the inbound JSON message, mutates the vault as
appropriate, and returns an `ack` dict. The brain socket loop in
`brain_server.py` calls these and writes the ack back to the client;
tests call them directly without a socket harness.

Per `.claude/feature/feat_vector-workroom.md` PR 1.

Contract:
    handler(msg: dict, vault) -> dict
    ack always carries `{ok: bool, cmd: str}`. On success, additional
    keys per command. On failure, `reason: str` describes the rejection.

Mutation flag: each handler returns its ack only — the caller is
responsible for any side effects beyond vault writes (e.g. bumping
`last_wake_ids` to force a manifest tick).
"""
from __future__ import annotations


def handle_seed_create(msg: dict, vault) -> dict:
    """Create a new seed. Required payload fields: biome, kind,
    base_mesh, pos_x, pos_y, pos_z. Optional: yaw_deg, scale,
    color_r/g/b, mesh_edits."""
    payload = msg.get("payload") or {}
    try:
        sid = vault.world_seed_create(payload)
    except (KeyError, ValueError, TypeError) as exc:
        return {"ok": False, "cmd": "seed_create", "reason": str(exc)}
    return {"ok": True, "cmd": "seed_create", "seed_id": int(sid)}


def handle_seed_update(msg: dict, vault) -> dict:
    """Patch fields on an existing seed. Required: seed_id, fields.
    Unknown seed_id → ok: false."""
    seed_id = msg.get("seed_id")
    fields = msg.get("fields") or {}
    if seed_id is None:
        return {"ok": False, "cmd": "seed_update",
                "reason": "missing seed_id"}
    try:
        ok = vault.world_seed_update(int(seed_id), fields)
    except (ValueError, TypeError) as exc:
        return {"ok": False, "cmd": "seed_update", "reason": str(exc)}
    if ok:
        return {"ok": True, "cmd": "seed_update", "seed_id": int(seed_id)}
    return {"ok": False, "cmd": "seed_update",
            "reason": f"unknown seed_id {seed_id}"}


def handle_seed_delete(msg: dict, vault) -> dict:
    """Delete a seed by id. Unknown id → ok: false."""
    seed_id = msg.get("seed_id")
    if seed_id is None:
        return {"ok": False, "cmd": "seed_delete",
                "reason": "missing seed_id"}
    try:
        ok = vault.world_seed_delete(int(seed_id))
    except (ValueError, TypeError) as exc:
        return {"ok": False, "cmd": "seed_delete", "reason": str(exc)}
    if ok:
        return {"ok": True, "cmd": "seed_delete", "seed_id": int(seed_id)}
    return {"ok": False, "cmd": "seed_delete",
            "reason": f"unknown seed_id {seed_id}"}


def handle_seed_list(msg: dict, vault) -> dict:
    """List seeds in a biome. Required: biome."""
    biome = str(msg.get("biome", ""))
    if not biome:
        return {"ok": False, "cmd": "seed_list", "reason": "missing biome"}
    seeds = vault.world_seeds_by_biome(biome)
    return {"ok": True, "cmd": "seed_list", "biome": biome, "seeds": seeds}
