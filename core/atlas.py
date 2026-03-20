# core/atlas.py

ARCHETYPES = {
    "URBAN": {
        "sig": 0x01,
        "keys": ["city", "downtown", "building", "concrete", "street"],
    },
    "FOREST": {
        "sig": 0x02,
        "keys": ["woods", "trees", "pine", "portland", "green", "shrub"],
    },
    "DESERT": {"sig": 0x04, "keys": ["sand", "dust", "vegas", "barren", "dry", "heat"]},
    "COAST": {
        "sig": 0x08,
        "keys": ["beach", "ocean", "water", "sea", "coast", "shore"],
    },
}

VOXEL_REGISTRY = {
    "f": {
        "model": "shrub_dense",
        "material": 1,
        "mass": 0.4,
        "on_proximity": "rustle",
        "yields": "bunny_sprite",
    },
    "X": {
        "model": "rock_strata",
        "material": 2,
        "mass": 0.9,
        "on_interact": "lift",
        "audio": "stone_scrape",
    },
    "~": {
        "model": "water_plane",
        "material": 4,
        "mass": 0.0,
        "tags": ["liquid", "reflect"],
    },
    "$": {
        "model": "relic_core",
        "material": 3,
        "mass": 0.0,
        "tags": ["emissive", "hover"],
    },
    ".": {"material": 0, "mass": 0.1},
    "s": {"material": 0, "mass": 0.1},
}


def query_atlas(query):
    q = query.lower()
    # Calculate Archetype scores
    scores = {
        k: sum(1 for word in v["keys"] if word in q) for k, v in ARCHETYPES.items()
    }
    winner = max(scores, key=scores.get)

    if scores[winner] == 0:
        return {"type": "GLITCH", "tags": [0x00]}

    # Start with the base Archetype tag
    tags = [ARCHETYPES[winner]["sig"]]

    # SIGNAL LAYER: Check for environmental modifiers
    if any(w in q for w in ["neon", "light", "glow", "bright"]):
        tags.append(0x10)  # 0x10 = Neon
    if any(w in q for w in ["rain", "wet", "storm", "mist"]):
        tags.append(0x20)  # 0x20 = Rain

    return {"type": winner, "tags": tags}
