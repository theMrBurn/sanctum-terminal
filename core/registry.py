# Blueprints for 'On-Demand' shaping
BLUEPRINTS = {
    "STONE_ROAD": {"type": "plane", "width": 20, "tex": "atlas_grit"},
    "WOOD_WALL":  {"type": "volume", "height": 25, "tex": "atlas_grit"},
    "LANTERN":    {"type": "actor", "light": True, "flicker": True}
}

# Temporary Safe-Mode for fresh session
AVATAR_CONFIG = {
    "speed": 0.0,         # Start at a standstill to check lighting
    "eye_level": 8.0,
    "fov": 70.0,
    "debug_mode": True    # Keep this as a mental note
}