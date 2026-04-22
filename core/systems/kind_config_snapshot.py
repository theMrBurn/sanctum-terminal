"""Snapshot diffing for config/kind_config.json — config-lock #3.

Schema validation (#1) catches structural breakage; the snapshot catches
value drift. A change from `collision_radius: 0.8` to `0.3` passes every
type check yet silently breaks creature contact. The snapshot is a frozen,
canonical dump of the last approved config; drift is surfaced by flattening
both to dotted-path leaves and listing adds/removes/changes.

Snapshot file: `config/kind_config.snapshot.json`. Updated explicitly via
`scripts/snapshot_kind_config.py --update` — never hand-edited. Matches
(canonical) means the current config has been acknowledged; mismatch means
somebody edited values without running the script, so the change isn't yet
reviewed against intent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = _REPO_ROOT / "config" / "kind_config.snapshot.json"
CONFIG_PATH = _REPO_ROOT / "config" / "kind_config.json"


class SnapshotMissing(FileNotFoundError):
    """Raised when the snapshot file doesn't exist."""


# --- Canonical form --------------------------------------------------------


def canonical_dumps(data: Any) -> str:
    """Stable JSON dump: sorted keys, 2-space indent, trailing newline.

    Two configs that are semantically equal will produce byte-identical
    canonical dumps regardless of key insertion order or whitespace.
    """
    return json.dumps(data, sort_keys=True, indent=2) + "\n"


# --- Flattening + diff -----------------------------------------------------


def flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts into dotted-path keys. Lists are kept as leaves.

    {"a": {"b": 1, "c": [1, 2]}} -> {"a.b": 1, "a.c": [1, 2]}

    Lists stay intact because the common cases (colors, vectors, ordered
    pools) only matter as whole values — per-index diffs would be noisier
    than useful.
    """
    out: dict[str, Any] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(flatten(v, key))
            else:
                out[key] = v
    else:
        out[prefix] = data
    return out


def diff(old_flat: dict[str, Any], new_flat: dict[str, Any]) -> dict[str, Any]:
    """Return {added, removed, changed} given two flattened configs.

    - added:   keys present in new but not old          {key: new_value}
    - removed: keys present in old but not new          {key: old_value}
    - changed: keys in both with different values       {key: (old, new)}
    """
    old_keys = set(old_flat)
    new_keys = set(new_flat)
    added = {k: new_flat[k] for k in sorted(new_keys - old_keys)}
    removed = {k: old_flat[k] for k in sorted(old_keys - new_keys)}
    changed = {
        k: (old_flat[k], new_flat[k])
        for k in sorted(old_keys & new_keys)
        if old_flat[k] != new_flat[k]
    }
    return {"added": added, "removed": removed, "changed": changed}


def format_diff(d: dict[str, Any]) -> str:
    """One line per change, sorted by section. Empty string if no drift."""
    lines: list[str] = []
    for k, v in d["removed"].items():
        lines.append(f"- {k} = {json.dumps(v)}")
    for k, v in d["added"].items():
        lines.append(f"+ {k} = {json.dumps(v)}")
    for k, (old, new) in d["changed"].items():
        lines.append(f"~ {k}: {json.dumps(old)} -> {json.dumps(new)}")
    return "\n".join(lines)


def is_empty(d: dict[str, Any]) -> bool:
    return not (d["added"] or d["removed"] or d["changed"])


# --- File operations -------------------------------------------------------


def load_snapshot(path: Path | None = None) -> dict[str, Any]:
    path = path or SNAPSHOT_PATH
    if not path.exists():
        raise SnapshotMissing(f"snapshot not found: {path}")
    with path.open() as f:
        return json.load(f)


def save_snapshot(config: dict[str, Any], path: Path | None = None) -> None:
    path = path or SNAPSHOT_PATH
    path.write_text(canonical_dumps(config))


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or CONFIG_PATH
    with path.open() as f:
        return json.load(f)


def diff_against_snapshot(
    config: dict[str, Any] | None = None,
    snapshot_path: Path | None = None,
) -> dict[str, Any]:
    """Return the flat diff (current config) - (snapshot).

    Raises SnapshotMissing if the snapshot file doesn't exist.
    """
    if config is None:
        config = load_config()
    snapshot = load_snapshot(snapshot_path)
    return diff(flatten(snapshot), flatten(config))


def matches_snapshot(
    config: dict[str, Any] | None = None,
    snapshot_path: Path | None = None,
) -> bool:
    """Byte-identical canonical form of config vs snapshot file."""
    path = snapshot_path or SNAPSHOT_PATH
    if config is None:
        config = load_config()
    if not path.exists():
        return False
    return canonical_dumps(config) == path.read_text()
