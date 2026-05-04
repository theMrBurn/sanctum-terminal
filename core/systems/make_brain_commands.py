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


def handle_volley_reset_rally(msg: dict, vault) -> dict:
    """Discard active ball + rally counter. Match state preserved."""
    from core.systems import make_brain_registry
    try:
        spec = make_brain_registry.get("ping_pong")
    except LookupError:
        return {"ok": False, "cmd": "volley_reset_rally",
                "reason": "ping_pong make-brain not active"}
    fn = getattr(spec.handler, "reset_rally", None)
    if fn is None or not callable(fn):
        return {"ok": False, "cmd": "volley_reset_rally",
                "reason": "handler missing reset_rally"}
    fn()
    return {"ok": True, "cmd": "volley_reset_rally"}


def handle_volley_reset_match(msg: dict, vault) -> dict:
    """Hard reset — fresh match, no ball, no rally."""
    from core.systems import make_brain_registry
    try:
        spec = make_brain_registry.get("ping_pong")
    except LookupError:
        return {"ok": False, "cmd": "volley_reset_match",
                "reason": "ping_pong make-brain not active"}
    fn = getattr(spec.handler, "reset_match", None)
    if fn is None or not callable(fn):
        return {"ok": False, "cmd": "volley_reset_match",
                "reason": "handler missing reset_match"}
    fn()
    return {"ok": True, "cmd": "volley_reset_match"}


def _vec3(payload: dict, key: str) -> tuple[float, float, float] | None:
    """Pull a {x,y,z} or [x,y,z] vector out of a payload sub-dict."""
    v = payload.get(key)
    if v is None:
        return None
    try:
        if isinstance(v, dict):
            return (float(v["x"]), float(v["y"]), float(v["z"]))
        return (float(v[0]), float(v[1]), float(v[2]))
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def handle_volley_strike(msg: dict, vault) -> dict:
    """Apply a paddle strike to the active ball.

    Required payload: paddle_pos, paddle_normal, paddle_velocity (each as
    {x,y,z} or [x,y,z]).

    Returns:
      {ok: True,  cmd: ..., hit: True,  ball: {...}, contact: {...}}  on hit
      {ok: True,  cmd: ..., hit: False}                                on miss (no ball-in-range)
      {ok: False, cmd: ..., reason: "..."}                             on validation/handler error
    """
    payload = msg.get("payload") or {}
    paddle_pos      = _vec3(payload, "paddle_pos")
    paddle_normal   = _vec3(payload, "paddle_normal")
    paddle_velocity = _vec3(payload, "paddle_velocity")
    if paddle_pos is None:
        return {"ok": False, "cmd": "volley_strike",
                "reason": "missing or malformed paddle_pos"}
    if paddle_normal is None:
        return {"ok": False, "cmd": "volley_strike",
                "reason": "missing or malformed paddle_normal"}
    if paddle_velocity is None:
        # Allow zero-velocity strike (poke). Default to (0,0,0).
        paddle_velocity = (0.0, 0.0, 0.0)

    from core.systems import make_brain_registry
    try:
        spec = make_brain_registry.get("ping_pong")
    except LookupError:
        return {"ok": False, "cmd": "volley_strike",
                "reason": "ping_pong make-brain not active"}
    handler = spec.handler
    fn = getattr(handler, "on_strike", None)
    if fn is None or not callable(fn):
        return {"ok": False, "cmd": "volley_strike",
                "reason": "handler missing on_strike"}

    contact = fn(paddle_pos, paddle_normal, paddle_velocity)
    if contact is None:
        return {"ok": True, "cmd": "volley_strike", "hit": False}

    ball = handler.ball
    return {
        "ok":   True,
        "cmd":  "volley_strike",
        "hit":  True,
        "ball": {
            "x":  ball.pos[0], "y": ball.pos[1], "z": ball.pos[2],
            "vx": ball.vel[0], "vy": ball.vel[1], "vz": ball.vel[2],
        },
        "contact": {
            "contact_point":   list(contact.contact_point),
            "incoming_v":      list(contact.incoming.vel),
            "outgoing_v":      list(contact.outgoing.vel),
            "paddle_normal":   list(contact.paddle_normal),
            "paddle_velocity": list(contact.paddle_velocity),
            "coupling_factor": contact.coupling_factor,
            "contact_kind":    contact.contact_kind,
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
