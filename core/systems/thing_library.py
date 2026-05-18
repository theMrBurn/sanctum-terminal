"""Thing library read API — consumer-side bridge to library/things/.

Stateless module. Walks `library/things/*.json` on demand, parses
via `thing_schema`, and offers tag-based + name-based query.

This is the shape the Blender consumes — it's what makes "give me a
weapon for this biome's register" actually return a Thing instead of
a stub. Mirrors the pattern in `core/systems/scan_library.py` (the
legacy image_scan reader) but points at the new `library/things/`
path.

Honors SANCTUM_THINGS_DIR env for dev overrides; otherwise reads
from `<repo>/library/things/`.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from core.systems import thing_schema
from core.systems.thing_schema import Thing


def things_dir() -> Path:
    """Where the library lives."""
    raw = os.environ.get("SANCTUM_THINGS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parents[2] / "library" / "things"


def stamps_dir() -> Path:
    """Where the stamp library lives. Stamps are 'big things' —
    architecture, multi-meter assemblies (bridges, ladders, stairs,
    doors). Same JSON schema as things; separated by directory so
    tag filters can't cross-contaminate (per the 2026-05-17 'stamps
    as data' promotion)."""
    raw = os.environ.get("SANCTUM_STAMPS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parents[2] / "library" / "stamps"


# ── Listing + direct lookup ──────────────────────────────────────


def list_names() -> list[str]:
    """Sorted names of every thing currently in the library."""
    d = things_dir()
    if not d.exists():
        return []
    out: list[str] = []
    for p in sorted(d.iterdir()):
        if p.suffix == ".json":
            out.append(p.stem)
    return out


def get(name: str) -> Thing | None:
    """Load one thing by name. Returns None if missing or invalid."""
    d = things_dir()
    p = d / f"{name}.json"
    if not p.exists():
        return None
    try:
        return thing_schema.load_thing(p)
    except (ValueError, Exception):                        # noqa: BLE001
        return None


def get_all() -> dict[str, Thing]:
    """Load every valid thing in the library. Invalid files skipped
    silently (the thing_schema loader emits to stderr on its own)."""
    d = things_dir()
    if not d.exists():
        return {}
    return thing_schema.load_things_from_dir(d)


# ── Tag-based query ────────────────────────────────────────────


def find_by_tags(
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    *,
    match_all: bool = False,
) -> list[Thing]:
    """Return Things whose tags satisfy the query.

    - `include` and `exclude` are sets of tags. None / empty = ignored.
    - `match_all = False` (default): a thing matches if it has AT LEAST
      ONE of the include tags AND NONE of the exclude tags.
    - `match_all = True`: must have ALL include tags AND no exclude.

    The "no include filter" case (include is None) returns everything
    that doesn't carry an excluded tag — useful for "anything but…"
    queries.
    """
    include_set = {t for t in (include or []) if t}
    exclude_set = {t for t in (exclude or []) if t}

    matches: list[Thing] = []
    for thing in get_all().values():
        thing_tags = set(thing.tags or [])
        if exclude_set & thing_tags:
            continue
        if not include_set:
            matches.append(thing)
            continue
        if match_all:
            if include_set.issubset(thing_tags):
                matches.append(thing)
        else:
            if include_set & thing_tags:
                matches.append(thing)
    return matches


# ── Stats / introspection ────────────────────────────────────────


def all_tags() -> dict[str, int]:
    """Tag → count of things carrying it. Useful for sanity
    ('what tags do I have to work with?')."""
    out: dict[str, int] = {}
    for thing in get_all().values():
        for tag in (thing.tags or []):
            out[tag] = out.get(tag, 0) + 1
    return out


def stats() -> dict[str, int]:
    """Top-level counts."""
    things = get_all()
    return {
        "total":      len(things),
        "tagged":     sum(1 for t in things.values() if t.tags),
        "untagged":   sum(1 for t in things.values() if not t.tags),
        "unique_tags": len(all_tags()),
    }


# ── Stamp library ─────────────────────────────────────────────────
#
# Stamps share the Thing schema but live in `library/stamps/`. They
# represent multi-meter architecture — bridges, ladders, staircases,
# doorways — composed of the same primitives as things, just at a
# larger scale. Per the 2026-05-17 "stamps as data" PR.
#
# Kept as separate accessors (not merged into get_all()) so a biome's
# things filter never accidentally pulls in a stamp.


def list_stamp_names() -> list[str]:
    d = stamps_dir()
    if not d.exists():
        return []
    return [p.stem for p in sorted(d.iterdir()) if p.suffix == ".json"]


def get_stamp(name: str) -> Thing | None:
    d = stamps_dir()
    p = d / f"{name}.json"
    if not p.exists():
        return None
    try:
        return thing_schema.load_thing(p)
    except (ValueError, Exception):                          # noqa: BLE001
        return None


def get_all_stamps() -> dict[str, Thing]:
    d = stamps_dir()
    if not d.exists():
        return {}
    return thing_schema.load_things_from_dir(d)


def find_stamps_by_tags(
    include: Iterable[str] | None = None,
    exclude: Iterable[str] | None = None,
    *,
    match_all: bool = False,
) -> list[Thing]:
    """Same semantics as find_by_tags(), but queries the stamp library."""
    include_set = {t for t in (include or []) if t}
    exclude_set = {t for t in (exclude or []) if t}
    matches: list[Thing] = []
    for stamp in get_all_stamps().values():
        stamp_tags = set(stamp.tags or [])
        if exclude_set & stamp_tags:
            continue
        if not include_set:
            matches.append(stamp)
            continue
        if match_all:
            if include_set.issubset(stamp_tags):
                matches.append(stamp)
        else:
            if include_set & stamp_tags:
                matches.append(stamp)
    return matches
