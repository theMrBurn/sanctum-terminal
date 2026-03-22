# core/registry.py

MANIFEST = {
    "201": {
        "name": "Lantern",
        "tags": ["emissive", "prop"],
        "affordances": ["light", "carry"],
        "constraints": {"must_anchor_to": "401_slab"},
    },
    "403": {
        "name": "Gas Pump",
        "tags": ["structure", "prop", "fuel"],
        "affordances": ["refuel", "explode"],
        "constraints": {"must_anchor_to": "401_slab"},
    },
    "401_slab": {
        "name": "Concrete Slab",
        "tags": ["ground", "foundation"],
        "affordances": ["walk", "anchor"],
        "constraints": {},
    },
    "101": {
        "name": "Data Vault",
        "tags": ["interactive", "objective"],
        "affordances": ["hack", "download"],
        "constraints": {},
    },
    "301": {
        "name": "Void Wall",
        "tags": ["barrier", "hazard"],
        "affordances": ["block"],
        "constraints": {},
    },
}

# The Parameter Logger manifest for "Clean Room" mode
LAB_REGISTRY = {
    "201": {
        "name": "Diagnostic Lantern",
        "dither_step": 0.04,
        "light_radius": 15.0,
        "flicker_hz": 2.5,
        "base_color": (255, 180, 80),
    },
    "403": {
        "name": "Diagnostic Gas Pump",
        "dither_step": 0.08,
        "light_radius": 5.0,
        "flicker_hz": 0.0,
        "base_color": (200, 50, 50),
    },
}
