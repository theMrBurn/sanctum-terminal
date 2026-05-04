"""Kind → render bounds lookup.

Reads config/kind_config.json via the brain-side loader (single source of
truth per design_kind_config_single_source). Exposes a thin function that
returns absolute base scale per kind; the renderer multiplies by the
manifest's per-entity sx/sy/sz.
"""
from __future__ import annotations

from typing import Any

from core.systems import kind_config


_FALLBACK = (1.0, 1.0, 1.0)


def bounds_for(kind: str) -> tuple[float, float, float]:
    """Return (sx, sy, sz) absolute base bounds for a kind.

    Falls back to 1×1×1m if the kind is missing or has no render.scale.
    """
    cfg = kind_config.kind(kind)
    scale = cfg.get("render", {}).get("scale")
    return _coerce(scale)


def class_for(kind: str) -> str:
    """Return the kind's class field (e.g. 'atmosphere', 'geological') or ''."""
    return kind_config.kind(kind).get("class", "")


def _coerce(scale: Any) -> tuple[float, float, float]:
    if isinstance(scale, (list, tuple)) and len(scale) == 3:
        try:
            return float(scale[0]), float(scale[1]), float(scale[2])
        except (TypeError, ValueError):
            pass
    if isinstance(scale, (int, float)):
        v = float(scale)
        return v, v, v
    return _FALLBACK
