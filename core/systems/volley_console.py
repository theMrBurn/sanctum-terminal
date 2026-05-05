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
    if verb == "mode":
        return _mode(args, handler)
    if verb == "sets":
        return _sets(handler)
    if verb == "data":
        return _data(handler)
    if verb == "runs":
        return _runs(vault)
    if verb == "export":
        return _export(args, handler)

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
        "  mode  <set_name>            switch brick set (control / experimental_v1)",
        "  sets                        show all brick sets + per-set round stats",
        "  data                        dump current run's round log",
        "  runs                        list past vault.runs rows + summaries",
        "  export [path]               write round log JSON snapshot to disk",
        "  help                        this list",
        "  scalar params: " + ", ".join(sorted(_SCALAR_PARAMS.keys())),
    ]


def _export(args: list[str], handler) -> list[str]:
    """Snapshot the current run's per-set round logs to a JSON file.

    Default path: data/volley_runs/run_<timestamp>.json. Override with
    `export <path>`. Includes per-set summaries so analysis tools have
    pre-computed avg/min/max alongside raw rounds.
    """
    import json as _json
    import time as _time
    from pathlib import Path
    if args:
        path = Path(args[0])
    else:
        ts = _time.strftime("%Y%m%d_%H%M%S")
        path = Path(f"data/volley_runs/run_{ts}.json")
    log_by_set = getattr(handler, "brick_round_log_by_set", None) or {}
    summaries = {
        name: handler.brick_round_summary(set_name=name)
        for name in log_by_set
    }
    payload = {
        "exported_at":     _time.time(),
        "exported_at_iso": _time.strftime("%Y-%m-%dT%H:%M:%S"),
        "active_profile":  handler.active_profile,
        "active_set":      handler.brick_set,
        "rounds_by_set":   log_by_set,
        "summaries":       summaries,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps(payload, indent=2))
    except OSError as exc:
        return [f"export failed: {exc}"]
    total = sum(len(rounds) for rounds in log_by_set.values())
    return [f"exported {total} rounds → {path}"]


def _mode(args: list[str], handler) -> list[str]:
    if len(args) != 1:
        return ["usage: mode <set_name>   (try `sets` to see options)"]
    try:
        handler.switch_brick_set(args[0])
    except ValueError as exc:
        return [str(exc)]
    return [f"switched to brick set: {args[0]}"]


def _data(handler) -> list[str]:
    """Dump current run's brick-round log per set. Combat-math source data."""
    log_by_set = getattr(handler, "brick_round_log_by_set", None) or {}
    if not any(log_by_set.values()):
        return ["no rounds logged yet — play + win or press R to log an attempt"]
    out: list[str] = ["round log (current run):"]
    for name, rounds in log_by_set.items():
        if not rounds:
            continue
        out.append(f"  [{name}] {len(rounds)} rounds:")
        for r in rounds[-20:]:
            mark = "✓" if r.get("reason") == "win" else "✗"
            out.append(
                f"    R{r.get('round_id'):>3}  {mark}  "
                f"{r.get('contacts'):>3} hits  "
                f"{float(r.get('duration_s', 0)):>5.1f}s  "
                f"score {r.get('score')}"
            )
    return out


def _runs(vault) -> list[str]:
    """Show last 5 vault.runs rows for ping_pong + their summaries."""
    runs = vault.runs_by_instance(INSTANCE_ID)
    if not runs:
        return ["no runs logged in vault.db"]
    out: list[str] = [f"vault.runs ({len(runs)} total, showing last 5):"]
    for r in runs[:5]:
        rid = (r.get("run_id") or "?")[:14]
        prof = r.get("profile_name") or "?"
        term = r.get("terminal_state") or "in-progress"
        metrics = r.get("metrics") or {}
        rounds_by_set = metrics.get("brick_rounds_by_set") or {}
        if rounds_by_set:
            stats = []
            for setname, rounds in rounds_by_set.items():
                wins = sum(1 for x in rounds if x.get("reason") == "win")
                stats.append(f"{setname}={wins}w/{len(rounds)}r")
            stats_str = ", ".join(stats)
        else:
            stats_str = "no rounds"
        out.append(f"  {rid}  {prof:<14}  {term:<12}  {stats_str}")
    return out


def _sets(handler) -> list[str]:
    rows = handler.list_brick_sets()
    if not rows:
        return ["no brick sets registered"]
    out: list[str] = ["brick sets:"]
    for r in rows:
        marker = "*" if r["active"] else " "
        line = (f"  {marker} {r['name']:<18} HP={r['total_hp']:>2} "
                f"thr={r['threshold']:>4} wins={r['wins']:>3}/{r['rounds']:>3} (target {r['target']})")
        if "avg_contacts" in r:
            line += f"  avg {r['avg_contacts']}h / {r['avg_duration_s']}s"
        out.append(line)
        out.append(f"      ↳ {r['label']}")
    return out


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
