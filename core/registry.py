# core/registry.py
VOXEL_REGISTRY = {
    ".": {"type": "floor", "color": (50, 50, 50), "walkable": True},
    "#": {"type": "wall", "color": (200, 180, 50), "walkable": False},
    "^": {"type": "trap", "color": (255, 50, 50), "walkable": True},
    "&": {"type": "challenge", "color": (0, 255, 200), "walkable": True},
    "$": {"type": "trigger", "color": (255, 255, 0), "walkable": True},
    "X": {"type": "exit", "color": (0, 255, 0), "walkable": True},
}
