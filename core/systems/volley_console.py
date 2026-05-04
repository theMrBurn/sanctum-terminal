"""Volley console — command parser + executor.

Pure functions over (line, vault, handler) → list[str] output. Brain
dispatch wraps this in `handle_console_exec`. Tested independently.

Per `.claude/feature/feat_make-brain-ping-pong.md` PR 7.

## Grammar (V1)

Whitespace-separated tokens, single line, no quoting.

    <param> <value>             — set a scalar profile param
    save   <name> [from parent] — snapshot active profile under <name>
    load   <name>               — switch active_profile to <name>
    list                        — list profiles for ping_pong
    help                        — show this command list

Multi-value params (e.g. `serve_offset` is a 3-tuple) are not settable
in V1 — defer until the user actually wants to dial them.

## Side effects

- Setters: write to vault.profiles via profile_save (overwrite). Handler
  detects `updated_at` change on next solver query → rebuild.
- save / load: vault writes + handler.active_profile mutation.
- list / help: pure read.

Output is a list of strings — one line per element. Caller (HUD overlay)
appends them to its scrollback.
"""
from __future__ import annotations

from typing import Any


INSTANCE_ID = "ping_pong"


# Settable scalar params + their type. Anything not listed is rejected
# at parse time. Tunable by extending this dict.
_SCALAR_PARAMS: dict[str, type] = {
    "ball_mass":             float,
    "ball_radius":            float,
    "ball_drag_coeff":        float,
    "ball_magnus_coeff":      float,
    "gravity_y":              float,
    "wall_restitution":       float,
    "coupling_factor":        float,
    "paddle_hitbox_radius":   float,
    "paddle_arm_length":      float,
    "swing_velocity":         float,
    "cube_size":              float,
    "long_rally_threshold":   int,
    "out_of_bounds_y":        float,
}


def execute(line: str, vault, handler) -> list[str]:
    """Run one console command. Returns output lines (already stripped of
    leading prompt characters; caller renders them as-is)."""
    if line is None:
        return []
    tokens = line.strip().split()
    if not tokens:
        return []
    verb = tokens[0]
    args = tokens[1:]

    if verb == "help":
        return _help()
    if verb == "list":
        return _list(vault)
    if verb == "load":
        return _load(args, vault, handler)
    if verb == "save":
        return _save(args, vault, handler)

    if verb in _SCALAR_PARAMS:
        return _setter(verb, args, vault, handler)

    return [f"unknown: {verb} (try `help`)"]


# ----------------------------------------------------------------------
# Verbs
# ----------------------------------------------------------------------


def _help() -> list[str]:
    return [
        "commands:",
        "  <param> <value>             set a scalar param on active profile",
        "  save  <name> [from parent]  snapshot active params under <name>",
        "  load  <name>                switch active profile to <name>",
        "  list                        show all profiles",
        "  help                        this list",
        "  scalar params: " + ", ".join(sorted(_SCALAR_PARAMS.keys())),
    ]


def _list(vault) -> list[str]:
    profiles = vault.profile_list(INSTANCE_ID)
    if not profiles:
        return ["no profiles"]
    lines: list[str] = ["profiles:"]
    for p in profiles:
        parent = p.get("parent_profile") or "—"
        lines.append(f"  {p['profile_name']:<14} parent={parent}")
    return lines


def _load(args: list[str], vault, handler) -> list[str]:
    if len(args) != 1:
        return ["usage: load <name>"]
    name = args[0]
    row = vault.profile_load(INSTANCE_ID, name)
    if row is None:
        return [f"unknown profile: {name}"]
    handler.active_profile = name
    return [f"loaded {name}"]


def _save(args: list[str], vault, handler) -> list[str]:
    """`save <name>` clones active profile params into <name>.
       `save <name> from <parent>` adds parent inheritance."""
    if len(args) == 1:
        name = args[0]
        parent = None
    elif len(args) == 3 and args[1] == "from":
        name = args[0]
        parent = args[2]
    else:
        return ["usage: save <name> [from <parent>]"]

    if parent is not None and vault.profile_load(INSTANCE_ID, parent) is None:
        return [f"unknown parent profile: {parent}"]

    # Snapshot the active profile's resolved params (so save captures the
    # full effective shape, not just the current overrides).
    try:
        params = vault.profile_resolve(INSTANCE_ID, handler.active_profile)
    except (LookupError, ValueError) as exc:
        return [f"resolve failed: {exc}"]
    vault.profile_save(
        INSTANCE_ID, name,
        params=params,
        parent_profile=parent,
        notes=f"console snapshot from {handler.active_profile}",
    )
    handler.active_profile = name
    return [f"saved {name}" + (f" (from {parent})" if parent else "")]


def _setter(param: str, args: list[str], vault, handler) -> list[str]:
    if len(args) != 1:
        return [f"usage: {param} <value>"]
    raw = args[0]
    expected = _SCALAR_PARAMS[param]
    try:
        value: Any = expected(raw)
    except ValueError:
        return [f"bad value for {param}: {raw!r} (expected {expected.__name__})"]

    # Mutate the active profile via vault — keeps the row's updated_at
    # current so the handler's solver cache invalidates.
    row = vault.profile_load(INSTANCE_ID, handler.active_profile)
    if row is None:
        return [f"active profile missing in vault: {handler.active_profile}"]
    new_params = dict(row.get("params") or {})
    new_params[param] = value
    vault.profile_save(
        INSTANCE_ID, handler.active_profile,
        params=new_params,
        parent_profile=row.get("parent_profile"),
        notes=row.get("notes") or "",
    )
    return [f"{param} = {value}"]
