"""Blender consumer wiring against the image_scan library.

PR 5 — proves the World Blender can read library entries written by
the image_scan app and produce a manifest-shape composition dict.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.systems import scan_library
from core.systems.blender import default_blender


@pytest.fixture(autouse=True)
def isolated_library(tmp_path: Path, monkeypatch):
    """Each test gets a fresh library tree under SANCTUM_OS_HOME."""
    monkeypatch.setenv("SANCTUM_OS_HOME", str(tmp_path))
    # Library root we expect scan_library to read from
    root = tmp_path / "image_scan" / "library"
    for sub in ("geometry", "textures", "noise", "ramps"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    yield


def _write_geometry(name: str, subparts: list[dict] | None = None) -> None:
    root = Path(scan_library._library_root())
    if subparts is None:
        subparts = [
            {"primitive": "chain", "role": "post",
             "position": "center_vertical", "scale": 1.0, "tier": "silhouette"},
            {"primitive": "orb", "role": "head",
             "position": "on_top", "scale": 0.4, "tier": "mid"},
        ]
    (root / "geometry" / f"{name}.json").write_text(json.dumps({
        "name":         name,
        "anchor":       subparts[0]["role"],
        "subparts":     subparts,
        "source_image": "/sources/x.jpg",
        "image_hash":   "abc123",
    }))


def _write_texture(name: str) -> None:
    root = Path(scan_library._library_root())
    (root / "textures" / f"{name}.jpg").write_bytes(b"jpg")
    (root / "noise" / f"{name}.edge.png").write_bytes(b"edge")
    (root / "noise" / f"{name}.disp.png").write_bytes(b"disp")
    (root / "ramps" / f"{name}.json").write_text(json.dumps({
        "name": name, "colors": ["#aaa", "#bbb"], "source": "/sources/x.jpg",
    }))


# ── scan_library bridge ─────────────────────────────────────────


def test_scan_library_reads_geometry():
    _write_geometry("scarecrow")
    g = scan_library.get_geometry("scarecrow")
    assert g is not None
    assert g["name"] == "scarecrow"


def test_scan_library_lists_geometries_alpha_sorted():
    _write_geometry("zebra")
    _write_geometry("apple")
    _write_geometry("mango")
    assert scan_library.list_geometries() == ["apple", "mango", "zebra"]


def test_scan_library_get_texture_path():
    _write_texture("flannel")
    p = scan_library.get_texture_path("flannel")
    assert p is not None
    assert p.endswith("flannel.jpg")


def test_scan_library_get_texture_bundle_full():
    _write_texture("flannel")
    b = scan_library.get_texture_bundle("flannel")
    assert b is not None
    assert b["texture"].endswith("flannel.jpg")
    assert "edge" in b["noise"]
    assert b["ramp"]["name"] == "flannel"


def test_scan_library_unknown_returns_none():
    assert scan_library.get_geometry("ghost") is None
    assert scan_library.get_texture_path("ghost") is None
    assert scan_library.get_ramp("ghost") is None
    assert scan_library.get_texture_bundle("ghost") is None


# ── Blender compose_library_kind ────────────────────────────────


def test_blender_compose_library_kind_geometry_only():
    _write_geometry("scarecrow")
    b = default_blender()
    out = b.compose_library_kind("scarecrow")
    assert out is not None
    assert out["kind_name"] == "scarecrow"
    assert out["anchor"] == "post"
    assert len(out["subparts"]) == 2
    assert "texture" not in out


def test_blender_compose_library_kind_with_texture():
    _write_geometry("scarecrow")
    _write_texture("flannel")
    b = default_blender()
    out = b.compose_library_kind("scarecrow", texture_name="flannel")
    assert out is not None
    assert "texture" in out
    assert out["texture"]["name"] == "flannel"
    assert out["texture"]["texture"].endswith("flannel.jpg")


def test_blender_compose_returns_none_for_unknown_geometry():
    b = default_blender()
    assert b.compose_library_kind("nobody") is None


def test_blender_compose_silently_omits_unknown_texture():
    """If texture_name doesn't exist, the geometry still composes —
    just without a texture bundle. No exception."""
    _write_geometry("scarecrow")
    b = default_blender()
    out = b.compose_library_kind("scarecrow", texture_name="ghost_tex")
    assert out is not None
    assert "texture" not in out


def test_blender_library_kinds_lists_geometries():
    _write_geometry("scarecrow")
    _write_geometry("skull")
    b = default_blender()
    kinds = b.library_kinds()
    assert "scarecrow" in kinds
    assert "skull" in kinds


def test_blender_library_kinds_empty_when_no_library():
    b = default_blender()
    assert b.library_kinds() == []


def test_blender_preserves_existing_methods_unchanged():
    """Sanity — the existing npc_for_role / encounter_template still work."""
    b = default_blender()
    sheet = b.npc_for_role("watcher", seed=42)
    assert sheet.name == "Watcher"   # fallback (lexicon stub is empty)
    enc = b.encounter_template(biome="cavern", tension="open", role="watcher", seed=1)
    assert enc["kind"] == "watcher"
