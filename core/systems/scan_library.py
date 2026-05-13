"""Read-only consumer for the image_scan primitive library.

The library lives at `~/.local/share/sanctum-os/image_scan/library/`
and is built by the `image_scan` app (per
`~/git/sanctum-os/docs/specs/18_app_image_scan.md`). This module
is sanctum-terminal's bridge to it — no cross-repo import, just
JSON + file reads against the standard path.

Per `design_brain_ground_truth`: this module is read-only at
runtime. Library writes happen during curation via `image-scan`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _library_root() -> Path:
    """Where the image_scan app stores its accepted library.

    Honors SANCTUM_OS_HOME for dev / test overrides; otherwise the
    standard XDG path."""
    raw = os.environ.get("SANCTUM_OS_HOME", "").strip()
    if raw:
        return Path(raw).expanduser() / "image_scan" / "library"
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else (Path.home() / ".local" / "share")
    return base / "sanctum-os" / "image_scan" / "library"


def _geometry_dir() -> Path:
    return _library_root() / "geometry"


def _textures_dir() -> Path:
    return _library_root() / "textures"


def _noise_dir() -> Path:
    return _library_root() / "noise"


def _ramps_dir() -> Path:
    return _library_root() / "ramps"


# ── Public read API (mirrors image_scan.library) ────────────────


def get_geometry(name: str) -> dict[str, Any] | None:
    p = _geometry_dir() / f"{name}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def list_geometries() -> list[str]:
    d = _geometry_dir()
    if not d.exists():
        return []
    return sorted(p.stem for p in d.iterdir() if p.suffix == ".json")


def get_texture_path(name: str) -> str | None:
    p = _textures_dir() / f"{name}.jpg"
    return str(p) if p.exists() else None


def get_noise_paths(name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    edge = _noise_dir() / f"{name}.edge.png"
    disp = _noise_dir() / f"{name}.disp.png"
    if edge.exists():
        out["edge"] = str(edge)
    if disp.exists():
        out["displacement"] = str(disp)
    return out


def get_ramp(name: str) -> dict[str, Any] | None:
    p = _ramps_dir() / f"{name}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def get_texture_bundle(name: str) -> dict[str, Any] | None:
    """Aggregate: texture path + noise paths + ramp."""
    tex_path = get_texture_path(name)
    if tex_path is None:
        return None
    return {
        "name":    name,
        "texture": tex_path,
        "noise":   get_noise_paths(name),
        "ramp":    get_ramp(name),
    }


def stats() -> dict[str, int]:
    return {
        "geometry": len(list_geometries()),
        "texture":  len([
            p for p in (_textures_dir().iterdir() if _textures_dir().exists() else [])
            if p.suffix == ".jpg"
        ]),
    }


def is_available() -> bool:
    """True iff the library root exists and has at least one entry.
    Consumers can gate behavior on this."""
    return _library_root().exists() and (
        len(list_geometries()) > 0
        or any(_textures_dir().iterdir()) if _textures_dir().exists() else False
    )
