"""
core/systems/biome_renderer.py

Procedural biome scene renderer.
Geometry functions live in geometry.py -- this module handles scene composition.
"""

import random

from panda3d.core import NodePath

from core.systems.geometry import (
    make_box as _make_box_geom,
    make_plane as _make_plane_geom,
    make_wedge as _make_wedge_geom,
    make_spike as _make_spike_geom,
    make_arch as _make_arch_geom,
    _noisy_color,
    VERTEX_NOISE,
)


# ── Biome visual signatures ───────────────────────────────────────────────────

BIOME_PALETTE = {
    "VOID": {"floor": (0.05, 0.05, 0.08), "accent": (0.2, 0.1, 0.3), "scale": 1.0},
    "NEON": {"floor": (0.05, 0.0, 0.15), "accent": (0.8, 0.0, 1.0), "scale": 0.8},
    "IRON": {"floor": (0.2, 0.15, 0.1), "accent": (0.5, 0.35, 0.2), "scale": 1.2},
    "SILICA": {"floor": (0.7, 0.65, 0.5), "accent": (0.9, 0.85, 0.7), "scale": 0.6},
    "FROZEN": {"floor": (0.6, 0.75, 0.9), "accent": (0.9, 0.95, 1.0), "scale": 1.1},
    "SULPHUR": {"floor": (0.3, 0.28, 0.0), "accent": (0.7, 0.6, 0.0), "scale": 0.9},
    "BASALT": {"floor": (0.08, 0.04, 0.04), "accent": (0.4, 0.1, 0.05), "scale": 1.3},
    "VERDANT": {"floor": (0.1, 0.25, 0.1), "accent": (0.3, 0.6, 0.2), "scale": 0.7},
    "MYCELIUM": {"floor": (0.15, 0.08, 0.18), "accent": (0.6, 0.3, 0.7), "scale": 0.9},
    "CHROME": {"floor": (0.6, 0.6, 0.65), "accent": (1.0, 1.0, 1.0), "scale": 1.0},
}

DEFAULT_PALETTE = BIOME_PALETTE["VOID"]


class BiomeRenderer:
    """
    Procedural Panda3D geometry renderer for biome scenes.
    No texture dependencies. Pure colored geometry.
    Lo-fi PS1/PS2 flat-shaded aesthetic.
    """

    def __init__(self, render_root, biome_key="VOID", seed=42):
        self.render_root = render_root
        self.palette = BIOME_PALETTE.get(biome_key, DEFAULT_PALETTE)
        self.rng = random.Random(seed)
        self.nodes = []

    def clear(self):
        """Remove all rendered geometry."""
        for np in self.nodes:
            np.removeNode()
        self.nodes = []

    def render_floor(self, radius=60):
        """Renders the ground plane."""
        node = _make_plane_geom(radius * 2, radius * 2, self.palette["floor"])
        np = self.render_root.attachNewNode(node)
        np.setPos(0, 0, 0)
        self.nodes.append(np)
        return np

    def render_scatter(self, count=20, radius=40):
        """
        Scatters accent-colored boxes around origin.
        Count and scale driven by biome palette.
        """
        scale = self.palette["scale"]
        color = self.palette["accent"]

        for _ in range(count):
            w = self.rng.uniform(0.5, 3.0) * scale
            h = self.rng.uniform(0.5, 5.0) * scale
            d = self.rng.uniform(0.5, 3.0) * scale

            x = self.rng.uniform(-radius, radius)
            y = self.rng.uniform(-radius, radius)

            if abs(x) < 3 and abs(y) < 3:
                x += 5 * (1 if x >= 0 else -1)

            node = _make_box_geom(w, h, d, color)
            np = self.render_root.attachNewNode(node)
            np.setPos(x, y, h / 2)
            np.setHpr(
                self.rng.uniform(0, 360),
                self.rng.uniform(-5, 5),
                self.rng.uniform(-5, 5),
            )
            self.nodes.append(np)

        return self.nodes

    def render_scene(self, encounter_density=0.3, seed=None):
        """
        Full scene render — floor + scatter.
        encounter_density (0-1) scales object count.
        """
        if seed is not None:
            self.rng = random.Random(seed)

        count = int(5 + encounter_density * 40)
        self.render_floor()
        self.render_scatter(count=count)
        return self.nodes
