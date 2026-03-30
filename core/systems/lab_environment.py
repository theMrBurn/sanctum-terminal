"""
core/systems/lab_environment.py

Environment register data + building functions for creation lab.

Extracted from creation_lab.py to reduce god-object size.
ENVIRONMENT_REGISTERS defines per-register palettes for floor, walls,
grid, lighting, fog. Build/apply functions manage scene graph nodes.
"""

from __future__ import annotations

from panda3d.core import Vec4, Fog

from core.systems.geometry import make_box as _make_box_geom, make_plane as _make_plane_geom


def _load_lab_config():
    """Load lab config -- duplicated here to avoid circular import."""
    import json
    from pathlib import Path
    path = Path(__file__).parent.parent.parent / "config" / "manifest.json"
    raw = json.load(open(path)).get("lab", {})
    atm = raw.get("atmosphere", {})
    return {
        "bg":          tuple(atm.get("background",  [0.05, 0.04, 0.04])),
        "floor_color": tuple(atm.get("floor_color", [0.14, 0.12, 0.10])),
        "wall_color":  tuple(atm.get("wall_color",  [0.18, 0.16, 0.14])),
        "grid_color":  tuple(atm.get("grid_color",  [0.20, 0.18, 0.15])),
        "light_sun":   tuple(atm.get("light_sun",   [1.4,  0.94, 0.82])),
        "light_fill":  tuple(atm.get("light_fill",  [0.08, 0.10, 0.16])),
        "light_amb":   tuple(atm.get("light_amb",   [0.06, 0.055, 0.05])),
        "wall_height": atm.get("wall_height", 14.0),
    }


_CFG = _load_lab_config()

ENVIRONMENT_REGISTERS = {
    "survival": {
        "background": _CFG["bg"],
        "floor":      _CFG["floor_color"],
        "wall":       _CFG["wall_color"],
        "grid":       _CFG["grid_color"],
        "ambient":    (0.05, 0.04, 0.06),           # slightly purple ambient
        "sun":        (1.3, 0.85, 0.55),             # warm golden sun (pushed)
        "fill":       (0.06, 0.12, 0.20),            # cool blue fill (contrasts sun)
        "fog":        (0.06, 0.05, 0.05),
        "fog_range":  (20.0, 80.0),
    },
    "tron": {
        "background": (0.0,  0.0,  0.02),
        "floor":      (0.02, 0.02, 0.04),
        "wall":       (0.03, 0.03, 0.06),
        "grid":       (0.0,  0.35, 0.55),
        "ambient":    (0.01, 0.03, 0.06),
        "sun":        (0.2,  0.5,  0.8),
        "fill":       (0.0,  0.08, 0.18),
        "fog":        (0.0,  0.02, 0.04),
        "fog_range":  (15.0, 60.0),
    },
    "tolkien": {
        "background": (0.04, 0.03, 0.02),
        "floor":      (0.18, 0.14, 0.08),
        "wall":       (0.25, 0.20, 0.14),
        "grid":       (0.22, 0.18, 0.12),
        "ambient":    (0.08, 0.06, 0.04),
        "sun":        (1.2,  0.85, 0.55),
        "fill":       (0.06, 0.05, 0.03),
        "fog":        (0.05, 0.04, 0.03),
        "fog_range":  (25.0, 90.0),
    },
    "sanrio": {
        "background": (0.35, 0.28, 0.32),
        "floor":      (0.85, 0.70, 0.78),
        "wall":       (0.75, 0.62, 0.72),
        "grid":       (0.90, 0.75, 0.82),
        "ambient":    (0.25, 0.20, 0.28),
        "sun":        (1.0,  0.85, 0.90),
        "fill":       (0.30, 0.25, 0.35),
        "fog":        (0.40, 0.32, 0.38),
        "fog_range":  (30.0, 100.0),
    },
}


def build_environment(layer_structure, register, lab_x, lab_y_n, lab_y_s):
    """
    Build floor, walls, grid geometry for the given register.
    Returns list of NodePaths (caller stores as _env_nodes).
    """
    reg = ENVIRONMENT_REGISTERS.get(register, ENVIRONMENT_REGISTERS["survival"])
    depth = abs(lab_y_s - lab_y_n)
    width = lab_x * 2
    fc = reg["floor"]
    wc = reg["wall"]
    gc = reg["grid"]
    wt = 0.3
    wh = _CFG["wall_height"]

    env_nodes = []

    # Floor
    fn = _make_plane_geom(int(width), int(depth), fc)
    floor_np = layer_structure.attachNewNode(fn)
    floor_np.setPos(0, 0, 0)
    env_nodes.append(floor_np)

    # Grid lines
    for i in range(-5, 6):
        gn = _make_box_geom(0.03, 0.008, width, gc)
        np = layer_structure.attachNewNode(gn)
        np.setPos(i * 2, 0, 0.003)
        env_nodes.append(np)
        gn2 = _make_box_geom(depth, 0.008, 0.03, gc)
        np2 = layer_structure.attachNewNode(gn2)
        np2.setPos(0, i * 2, 0.003)
        env_nodes.append(np2)

    # Walls (visual)
    for dims, pos in [
        ((width, wt, wh), (0,      lab_y_n, wh/2)),
        ((width, wt, wh), (0,      lab_y_s, wh/2)),
        ((wt, depth, wh), (lab_x,  0,       wh/2)),
        ((wt, depth, wh), (-lab_x, 0,       wh/2)),
    ]:
        np = layer_structure.attachNewNode(_make_box_geom(*dims, wc))
        np.setPos(*pos)
        env_nodes.append(np)

    return env_nodes, reg


def update_lighting(sun_light, fill_light, amb_light, reg):
    """Update light colors from register palette."""
    s = reg["sun"]
    sun_light.setColor(Vec4(s[0], s[1], s[2], 1))
    f = reg["fill"]
    fill_light.setColor(Vec4(f[0], f[1], f[2], 1))
    a = reg["ambient"]
    amb_light.setColor(Vec4(a[0], a[1], a[2], 1))


def update_fog(fog_node, render, reg):
    """
    Set linear fog from register palette.
    Creates fog if fog_node is None. Returns the fog node.
    """
    fc = reg.get("fog", (0.05, 0.05, 0.05))
    fr = reg.get("fog_range", (20.0, 80.0))
    if fog_node is None:
        fog_node = Fog("scene_fog")
        render.setFog(fog_node)
    fog_node.setColor(Vec4(fc[0], fc[1], fc[2], 1.0))
    fog_node.setLinearRange(fr[0], fr[1])
    return fog_node
