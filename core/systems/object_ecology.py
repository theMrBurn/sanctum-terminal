"""
core/systems/object_ecology.py

Object ecology registry — WHERE things naturally occur.

Every placeable object carries ecological tags that describe its natural
habitat, geological context, and placement affinity. The procedural
placement engine consumes these tags to make context-aware decisions.

Tags are relational, not absolute. A boulder doesn't just exist — it
exists BECAUSE of glaciers, rivers, erosion, gravity. The tag system
captures that causality so placement can be predictive.

Usage:
    registry = ObjectEcology()
    registry.register("boulder", {
        "terrain": ["river_valley", "glacier_valley", "canyon", ...],
        "geology": ["erosion", "glacial_deposit", "rockfall"],
        ...
    })
    score = registry.affinity("boulder", terrain="canyon", elevation=0.8)
"""


class ObjectEcology:
    """Registry of object types and their ecological placement tags."""

    def __init__(self):
        self._objects = {}

    def register(self, name, spec):
        """Register an object type with its ecological spec.

        spec keys:
            terrain: list[str]    — where it naturally occurs
            geology: list[str]    — what geological process created it
            elevation: (min, max) — normalized 0-1 range
            moisture: (min, max)  — normalized 0-1 range
            density: str          — "sparse", "scattered", "clustered", "fields"
            scale_range: (min, max) — meters, natural size variation
            companions: list[str] — objects that co-occur nearby
            avoids: list[str]     — objects/terrain it never appears with
            surface: str          — material quality ("stone", "mineral", "organic")
            weight: str           — visual mass ("light", "heavy", "massive")
            age: str              — weathering state ("fresh", "weathered", "ancient")
            lore: str             — what this object means in the world
        """
        self._objects[name] = spec

    def get(self, name):
        """Get the full ecological spec for an object type."""
        return self._objects.get(name)

    def affinity(self, name, **context):
        """Score how well an object fits a placement context. Returns 0.0-1.0.

        context keys: terrain, elevation, moisture, nearby_objects
        """
        spec = self._objects.get(name)
        if not spec:
            return 0.0

        score = 0.0
        checks = 0

        # Terrain match
        if "terrain" in context and "terrain" in spec:
            checks += 1
            if context["terrain"] in spec["terrain"]:
                score += 1.0

        # Elevation range
        if "elevation" in context and "elevation" in spec:
            checks += 1
            lo, hi = spec["elevation"]
            e = context["elevation"]
            if lo <= e <= hi:
                score += 1.0
            elif e < lo:
                score += max(0, 1.0 - (lo - e) * 3)
            else:
                score += max(0, 1.0 - (e - hi) * 3)

        # Moisture range
        if "moisture" in context and "moisture" in spec:
            checks += 1
            lo, hi = spec["moisture"]
            m = context["moisture"]
            if lo <= m <= hi:
                score += 1.0
            elif m < lo:
                score += max(0, 1.0 - (lo - m) * 3)
            else:
                score += max(0, 1.0 - (m - hi) * 3)

        # Avoidance
        if "nearby_objects" in context and "avoids" in spec:
            checks += 1
            avoided = set(spec["avoids"]) & set(context["nearby_objects"])
            score += 0.0 if avoided else 1.0

        # Companion bonus
        if "nearby_objects" in context and "companions" in spec:
            checks += 1
            companions = set(spec["companions"]) & set(context["nearby_objects"])
            score += min(1.0, len(companions) * 0.5)

        return score / max(1, checks)

    def list_objects(self):
        """All registered object type names."""
        return list(self._objects.keys())

    def find_for_context(self, **context):
        """Return all objects sorted by affinity for a given context."""
        scored = []
        for name in self._objects:
            a = self.affinity(name, **context)
            if a > 0:
                scored.append((name, a))
        scored.sort(key=lambda x: -x[1])
        return scored


# -- Default registry with built-in object types ------------------------------

def create_default_ecology():
    """Pre-populated ecology with core object types."""
    eco = ObjectEcology()

    eco.register("boulder", {
        "terrain": [
            "river_valley", "glacier_valley", "canyon",
            "mountain_plain_transition", "high_peak", "scree_field",
            "cavern_floor", "ravine", "coastal_cliff",
        ],
        "geology": [
            "glacial_deposit", "erosion", "rockfall",
            "freeze_thaw", "river_transport", "tectonic_uplift",
        ],
        "elevation": (0.0, 0.9),
        "moisture": (0.1, 0.8),
        "density": "scattered",
        "scale_range": (0.5, 5.0),
        "companions": ["pebble", "rubble", "moss", "lichen"],
        "avoids": ["deep_water", "dense_forest"],
        "surface": "stone",
        "weight": "massive",
        "age": "ancient",
        "lore": "carried here by forces larger than memory",
    })

    eco.register("stalactite", {
        "terrain": ["cavern_ceiling", "cave_entrance", "underground_river"],
        "geology": ["mineral_deposit", "water_erosion", "calcification"],
        "elevation": (0.6, 1.0),  # high = ceiling
        "moisture": (0.5, 1.0),
        "density": "clustered",
        "scale_range": (0.1, 2.0),
        "companions": ["stalagmite", "puddle", "mineral_vein"],
        "avoids": ["open_sky", "dry_sand"],
        "surface": "mineral",
        "weight": "heavy",
        "age": "ancient",
        "lore": "time made visible, one drip at a time",
    })

    eco.register("chest", {
        "terrain": [
            "cavern_floor", "ruin_interior", "dead_end",
            "hidden_alcove", "camp_remnant",
        ],
        "geology": [],
        "elevation": (0.0, 0.5),
        "moisture": (0.0, 0.6),
        "density": "sparse",
        "scale_range": (0.3, 0.6),
        "companions": ["bone_pile", "rubble", "cobweb"],
        "avoids": ["open_field", "water"],
        "surface": "wood_metal",
        "weight": "heavy",
        "age": "weathered",
        "lore": "someone left this here on purpose",
    })

    eco.register("fungi_cluster", {
        "terrain": [
            "cavern_floor", "cavern_wall", "dead_wood",
            "damp_corner", "underground_river_bank",
        ],
        "geology": ["organic_decay", "moisture_accumulation"],
        "elevation": (0.0, 0.4),
        "moisture": (0.6, 1.0),
        "density": "clustered",
        "scale_range": (0.05, 0.3),
        "companions": ["moss", "puddle", "bone_pile", "dead_wood"],
        "avoids": ["dry_sand", "high_wind"],
        "surface": "organic",
        "weight": "light",
        "age": "fresh",
        "lore": "life that feeds on endings",
    })

    eco.register("bone_pile", {
        "terrain": [
            "cavern_floor", "dead_end", "predator_den",
            "canyon_floor", "ruin_interior",
        ],
        "geology": [],
        "elevation": (0.0, 0.3),
        "moisture": (0.0, 0.5),
        "density": "sparse",
        "scale_range": (0.2, 1.0),
        "companions": ["cobweb", "fungi_cluster", "rubble"],
        "avoids": ["open_sky", "water"],
        "surface": "bone",
        "weight": "light",
        "age": "ancient",
        "lore": "something ended here",
    })

    eco.register("rubble", {
        "terrain": [
            "cavern_floor", "ruin_interior", "canyon_floor",
            "collapsed_passage", "earthquake_zone",
        ],
        "geology": ["structural_collapse", "erosion", "rockfall"],
        "elevation": (0.0, 0.5),
        "moisture": (0.0, 0.7),
        "density": "scattered",
        "scale_range": (0.1, 0.8),
        "companions": ["boulder", "dust", "cobweb"],
        "avoids": ["pristine_surface"],
        "surface": "stone",
        "weight": "heavy",
        "age": "weathered",
        "lore": "what's left when structure fails",
    })

    eco.register("puddle", {
        "terrain": [
            "cavern_floor", "canyon_floor", "cave_entrance",
            "underground_river_bank", "damp_corner",
        ],
        "geology": ["water_accumulation", "condensation", "seepage"],
        "elevation": (0.0, 0.2),
        "moisture": (0.7, 1.0),
        "density": "scattered",
        "scale_range": (0.3, 2.0),
        "companions": ["stalactite", "fungi_cluster", "moss"],
        "avoids": ["dry_sand", "high_elevation"],
        "surface": "water",
        "weight": "light",
        "age": "fresh",
        "lore": "the cave is always drinking",
    })

    return eco
