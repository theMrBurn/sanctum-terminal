# systems/rosetta_stone.py

VOXEL_REGISTRY = {
    ".": {"type": "floor", "pts": 5, "y": 0.0, "color": (50, 50, 50), "fx": None},
    "#": {
        "type": "wall",
        "pts": 150,
        "y": 15.0,
        "color": (200, 180, 50),
        "fx": "static",
    },
    "^": {"type": "trap", "pts": 20, "y": 0.2, "color": (255, 50, 50), "fx": "glitch"},
    "&": {
        "type": "challenge",
        "pts": 40,
        "y": 1.0,
        "color": (0, 255, 200),
        "fx": "pulse",
    },
    "$": {
        "type": "trigger",
        "pts": 30,
        "y": 0.5,
        "color": (255, 255, 0),
        "fx": "float",
    },
    "X": {"type": "exit", "pts": 100, "y": 2.0, "color": (0, 255, 0), "fx": "gate"},
}
