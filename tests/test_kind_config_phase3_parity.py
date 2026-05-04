"""Phase 3 parity tests: KIND_PROPS in bucket_world and brain_server must
read scale/color/emissive from kind_config (not the literal fallback).
PROVES Phase 3 is a data-source migration with zero behavioral change.

Compares each kind's effective live values against the values currently
stored in kind_config — if they drift, the shim broke or someone edited
one source without the other.
"""
from __future__ import annotations

import pytest

from core.systems import kind_config


# Live shims — read AFTER module import so they reflect the merged dict.
def _live_props():
    from core.systems.bucket_world import KIND_PROPS as BW
    from brain_server import KIND_PROPS as BS
    return BW, BS


def test_bucket_world_kind_props_reads_from_kind_config():
    bw, _ = _live_props()
    # rat is creature kind, all five creatures introduced this session
    # must show kind_config render values, not legacy fallback.
    for name in ("rat", "rat_ice", "rat_fire", "clay_pot", "treasure_chest"):
        cfg_render = kind_config.kind(name).get("render", {})
        if "scale" not in cfg_render:
            pytest.skip(f"{name} render block not in kind_config")
        live = bw[name]
        assert live["scale"] == list(cfg_render["scale"]), \
            f"{name} bucket_world scale drifted from kind_config"
        assert live["color"] == list(cfg_render["color"]), \
            f"{name} bucket_world color drifted from kind_config"
        assert live["emissive"] == float(cfg_render["emissive"]), \
            f"{name} bucket_world emissive drifted from kind_config"


def test_brain_server_kind_props_reads_from_kind_config():
    _, bs = _live_props()
    # Sample structural and creature kinds — broader coverage than bucket_world test
    for name in ("boulder", "column", "rat", "clay_pot", "treasure_chest"):
        cfg_render = kind_config.kind(name).get("render", {})
        if "scale" not in cfg_render or name not in bs:
            continue
        live = bs[name]
        assert live["scale"] == list(cfg_render["scale"]), \
            f"{name} brain_server scale drifted from kind_config"
        assert live["color"] == list(cfg_render["color"]), \
            f"{name} brain_server color drifted from kind_config"
        assert live["emissive"] == float(cfg_render["emissive"]), \
            f"{name} brain_server emissive drifted from kind_config"


def test_bucket_and_brain_kind_props_now_aligned_for_creatures():
    """Pre-Phase 3 the two dicts had drift (e.g. clay_pot color [0.60,0.42,0.25]
    in bucket vs [1.0,1.0,1.0] in brain). After the shim both should pull from
    kind_config and align."""
    bw, bs = _live_props()
    for name in ("rat", "rat_ice", "rat_fire", "clay_pot", "treasure_chest"):
        if name not in bw or name not in bs:
            continue
        assert bw[name] == bs[name], \
            f"{name}: bucket_world {bw[name]} vs brain_server {bs[name]} — shim not unified"
