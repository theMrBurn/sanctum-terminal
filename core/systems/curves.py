"""
core/systems/curves.py

Normalized curve functions and threshold detection.
Everything is a float 0.0-1.0.
State changes emerge from threshold crossings — never hardcoded triggers.
"""


# ── Threshold table ───────────────────────────────────────────────────────────
# All numeric values are floats. Direction: "below" means threshold fires
# when the value drops below, "above" fires when it rises above.

THRESHOLDS = {
    "dungeon_unlock": {
        "encounter_density": 0.7,
    },
    "ascent_visible": {
        "karma":              0.3,
        "encounter_density":  0.5,
    },
    "biome_edge_shift": {
        "heat":               0.8,
        "moisture":           0.2,
    },
    "campaign_ready": {
        "karma":              0.4,
        "encounter_density":  0.4,
        "days_played":        3,
    },
    "torch_upgrade": {
        "depth_score":        2,
    },
    "rare_torch": {
        "depth_score":        3,
    },
}

# ── Scale curve definitions ───────────────────────────────────────────────────
# Each scale key maps a normalized float to a set of downstream parameters.
# No magic numbers outside this file.

_SCALE_CURVES = {
    "weight": {
        # How heavy is it? 0=light 1=crushing
        "encounter_density": lambda s: s,
        "impact_rating":     lambda s: max(1, min(10, int(1 + s * 9))),
        "spawn_radius":      lambda s: int(20 + (1 - s) * 40),
        "karma_baseline":    lambda s: s * 0.6,
    },
    "fatigue": {
        # How long awake? 0=rested 1=exhausted
        "karma_baseline":    lambda s: s * 0.8,
        "karma_decay_rate":  lambda s: max(0.02, 0.2 - s * 0.18),
        "ambient_intensity": lambda s: max(0.15, 1.0 - s * 0.6),
    },
    "time": {
        # Time of day: 0=midnight 1=noon
        "ambient_intensity": lambda s: max(0.1, s),
        "heat":              lambda s: s * 0.6,
        "light":             lambda s: s,
    },
    "pace": {
        # How you move: 0=very slow 1=very fast
        "camera_speed":      lambda s: 20.0 + s * 60.0,
        "karma_decay_rate":  lambda s: max(0.02, 0.2 - s * 0.15),
    },
    "enclosure": {
        # Open vs enclosed: 0=wide open 1=fully enclosed
        "spawn_radius":      lambda s: int(60 - s * 45),
        "moisture":          lambda s: s * 0.5,
    },
    "energy": {
        # Energy/temperature: 0=cold/low 1=hot/high
        "heat":              lambda s: s,
        "ambient_intensity": lambda s: 0.3 + s * 0.5,
    },
    "flow": {
        # Stuck vs flowing: 0=stuck 1=flowing freely
        "moisture":          lambda s: s,
        "karma_decay_rate":  lambda s: 0.05 + s * 0.15,
    },
}

# Default output keys with neutral values
_DEFAULTS = {
    "encounter_density": 0.3,
    "impact_rating":     3,
    "spawn_radius":      40,
    "karma_baseline":    0.3,
    "karma_decay_rate":  0.08,
    "ambient_intensity": 0.5,
    "heat":              0.5,
    "moisture":          0.5,
    "light":             0.5,
    "camera_speed":      40.0,
}


# ── Public API ────────────────────────────────────────────────────────────────

def normalize(value):
    """Clamp a value to [0.0, 1.0]."""
    return max(0.0, min(1.0, float(value)))


def apply_scale(key, scale):
    """
    Map a normalized scale (0.0-1.0) to downstream parameters.
    Returns a dict of parameter values for the given curve key.
    Unknown keys return defaults.
    """
    scale  = normalize(scale)
    result = dict(_DEFAULTS)
    curves = _SCALE_CURVES.get(key, {})
    for param, fn in curves.items():
        result[param] = fn(scale)
    return result


def check_thresholds(state, thresholds=None):
    """
    Check which thresholds have been crossed given current state.
    Returns list of threshold names that are currently active.
    State changes emerge naturally — no explicit triggers needed.
    """
    if thresholds is None:
        thresholds = THRESHOLDS

    crossed = []
    for name, conditions in thresholds.items():
        if _conditions_met(state, conditions):
            crossed.append(name)
    return crossed


def _conditions_met(state, conditions):
    """
    Returns True if all conditions in the threshold are satisfied.
    Numeric conditions: state value must be >= threshold value.
    Special keys: days_min, depth_score use >= comparison.
    biome_edge_shift moisture uses <= (must be below threshold).
    """
    if not state:
        return False

    for key, threshold in conditions.items():
        val = state.get(key)
        if val is None:
            return False

        # moisture in biome_edge_shift fires when LOW
        if key == "moisture":
            if float(val) > float(threshold):
                return False
        # karma in ascent_visible fires when LOW
        elif key == "karma" and "ascent" in str(conditions):
            if float(val) > float(threshold):
                return False
        # karma in campaign_ready fires when LOW
        elif key == "karma":
            if float(val) > float(threshold):
                return False
        # days_min — integer minimum
        elif key == "days_played":
            if int(val) < int(threshold):
                return False
        # depth_score — integer minimum
        elif key == "depth_score":
            if int(val) < int(threshold):
                return False
        # all other keys fire when value >= threshold
        else:
            if float(val) < float(threshold):
                return False

    return True
