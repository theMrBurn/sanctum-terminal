"""Schema bump: per-kind `engagement` slot.

Per `design_creature_engagement_v1` — binds a creature kind to a
make-brain-registered engagement type. The slot is optional; absence
means the kind has no engagement (default smash/parley behavior in
brain dispatch). No structural transform is needed — pre-existing
configs are valid as-is after this bump, just labeled at v2.
"""
from __future__ import annotations

from typing import Any

VERSION = 2
DESCRIPTION = "Add optional per-kind engagement slot (V1 spec, audit A8)"


def up(config: dict[str, Any]) -> dict[str, Any]:
    return config


def down(config: dict[str, Any]) -> dict[str, Any]:
    # Strip any engagement blocks added under v2.
    for section_key in ("_class_defaults", "kinds"):
        section = config.get(section_key)
        if not isinstance(section, dict):
            continue
        for k, v in section.items():
            if isinstance(v, dict) and "engagement" in v:
                v.pop("engagement", None)
    return config
