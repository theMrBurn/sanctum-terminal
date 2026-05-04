"""Make-brain command handlers — pure functions over (msg, vault).

Universal command surface for any make-brain instance (ping_pong,
future archery, future puzzle modules). instance_id always travels in
the payload — handlers don't care which make-brain is talking, just
that the vault key (`instance_id`, `profile_name`, `run_id`) is present.

Per `.claude/feature/feat_make-brain-ping-pong.md` PR 1.

Contract matches `core.systems.seed_commands`:
    handler(msg: dict, vault) -> dict
    ack always carries `{ok: bool, cmd: str}`. On success, additional
    keys per command. On failure, `reason: str` describes the rejection.
"""
from __future__ import annotations


def _required(payload: dict, *keys: str) -> str | None:
    """Return the first missing key, or None if all present."""
    for k in keys:
        if not payload.get(k):
            return k
    return None


def handle_profile_save(msg: dict, vault) -> dict:
    """Save (insert-or-update) a make-brain profile.

    Required payload: instance_id, profile_name, params (dict).
    Optional: parent_profile, notes.
    """
    payload = msg.get("payload") or {}
    missing = _required(payload, "instance_id", "profile_name")
    if missing:
        return {"ok": False, "cmd": "profile_save",
                "reason": f"missing {missing}"}
    if "params" not in payload:
        return {"ok": False, "cmd": "profile_save",
                "reason": "missing params"}
    if not isinstance(payload.get("params"), dict):
        return {"ok": False, "cmd": "profile_save",
                "reason": "params must be a dict"}
    try:
        row_id = vault.profile_save(
            instance_id    = str(payload["instance_id"]),
            profile_name   = str(payload["profile_name"]),
            params         = payload["params"],
            parent_profile = payload.get("parent_profile"),
            notes          = str(payload.get("notes") or ""),
        )
    except (ValueError, TypeError) as exc:
        return {"ok": False, "cmd": "profile_save", "reason": str(exc)}
    return {
        "ok":           True,
        "cmd":          "profile_save",
        "profile_id":   int(row_id),
        "instance_id":  str(payload["instance_id"]),
        "profile_name": str(payload["profile_name"]),
    }


def handle_profile_load(msg: dict, vault) -> dict:
    """Load a profile.

    Required: instance_id, profile_name.
    Optional: resolve (bool, default True). When True, returns merged
    params with parent inheritance applied. When False, returns the raw
    row.
    """
    payload = msg.get("payload") or {}
    missing = _required(payload, "instance_id", "profile_name")
    if missing:
        return {"ok": False, "cmd": "profile_load",
                "reason": f"missing {missing}"}
    instance_id  = str(payload["instance_id"])
    profile_name = str(payload["profile_name"])
    resolve = payload.get("resolve", True)
    if resolve:
        try:
            params = vault.profile_resolve(instance_id, profile_name)
        except (LookupError, ValueError) as exc:
            return {"ok": False, "cmd": "profile_load", "reason": str(exc)}
        return {
            "ok":           True,
            "cmd":          "profile_load",
            "instance_id":  instance_id,
            "profile_name": profile_name,
            "params":       params,
            "resolved":     True,
        }
    row = vault.profile_load(instance_id, profile_name)
    if row is None:
        return {"ok": False, "cmd": "profile_load",
                "reason": f"unknown profile {instance_id}:{profile_name}"}
    return {
        "ok":             True,
        "cmd":            "profile_load",
        "instance_id":    instance_id,
        "profile_name":   profile_name,
        "params":         row.get("params") or {},
        "parent_profile": row.get("parent_profile"),
        "notes":          row.get("notes") or "",
        "resolved":       False,
    }


def handle_volley_serve(msg: dict, vault) -> dict:
    """Spawn a stationary ball in the volley chamber. Idempotent — if a
    ball is already in play, replaces it with a fresh serve.

    Required nothing in payload (instance_id is implied; only ping_pong
    handles serves in V1). Returns {ok, ball: {...}} on success.
    """
    from core.systems import make_brain_registry
    try:
        spec = make_brain_registry.get("ping_pong")
    except LookupError:
        return {"ok": False, "cmd": "volley_serve",
                "reason": "ping_pong make-brain not active"}
    handler = spec.handler
    fn = getattr(handler, "on_serve", None)
    if fn is None or not callable(fn):
        return {"ok": False, "cmd": "volley_serve",
                "reason": "handler missing on_serve"}
    ball = fn()
    return {
        "ok": True, "cmd": "volley_serve",
        "ball": {
            "x":  ball.pos[0], "y": ball.pos[1], "z": ball.pos[2],
            "vx": ball.vel[0], "vy": ball.vel[1], "vz": ball.vel[2],
        },
    }


def handle_profile_list(msg: dict, vault) -> dict:
    """List all profiles for an instance.

    Required payload: instance_id.
    """
    payload = msg.get("payload") or {}
    missing = _required(payload, "instance_id")
    if missing:
        return {"ok": False, "cmd": "profile_list",
                "reason": f"missing {missing}"}
    profiles = vault.profile_list(str(payload["instance_id"]))
    summaries = [
        {
            "profile_name":   p.get("profile_name"),
            "parent_profile": p.get("parent_profile"),
            "notes":          p.get("notes") or "",
            "updated_at":     p.get("updated_at"),
        }
        for p in profiles
    ]
    return {
        "ok":          True,
        "cmd":         "profile_list",
        "instance_id": str(payload["instance_id"]),
        "profiles":    summaries,
    }
