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
