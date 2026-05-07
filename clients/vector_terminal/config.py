"""Vector terminal tuning knobs — keep all behavioral literals here.

Per `feedback_no_hardcoded_tunables`: any literal controlling render or
movement behavior lives at the top of a config file, not buried in
function bodies.
"""
from __future__ import annotations

# Window / loop
WIDTH = 1280
HEIGHT = 720
TARGET_FPS = 60
EYE_HEIGHT = 1.7

# Movement
MOVE_SPEED = 5.0
MOUSE_SENS = 0.003

# Brain TCP
BRAIN_HOST = "127.0.0.1"
BRAIN_PORT = 9877
CAM_UPDATE_DT = 0.1  # match godot/main.gd UPDATE_INTERVAL (10Hz)

# Palette — period-correct CRT amber. RGB only; alpha is always 255.
AMBER_RGB = (255, 176, 0)

# Distance intensity falloff (Battlezone "phosphor decay with distance").
# Lines stay full bright within NEAR_DIST, fade linearly to MIN_GLOW at FAR_FADE.
# Per PR 16: NEAR_DIST and FAR_FADE are FALLBACK values. The brain's
# TensionCycle drives manifest.fog.near/far per frame, and
# `distance_fade.set_bounds()` overrides these when the manifest
# carries fog. These constants apply only before the first manifest is
# received OR when a biome/state emits no fog (workroom, volley_chamber).
#
# MIN_GLOW lowered 0.15 → 0.06 → 0.04 (2026-05-07) — paired with
# quadratic falloff in `distance_fade.intensity` for phosphor-curve
# contrast. Mid-distance lines stay bright longer (lit through
# atmosphere), then drop sharply near the far edge. Floor at 0.04 is
# the minimum that still preserves the "never fully dark" identity
# while letting the horizon cliff contrast hard against near wires.
NEAR_DIST = 4.0
FAR_FADE = 60.0
MIN_GLOW = 0.04

# Terrain — wireframe floor / ceiling grid that snaps to camera so it
# reads as infinite without exploding the line count.
FLOOR_GRID_SPACING = 2.0
FLOOR_GRID_EXTENT = 60.0
CEILING_GRID_SPACING = 4.0  # ceiling sparser than floor — less visual weight
CAVERN_CEILING_HEIGHT = 8.0
DRAW_CEILING_GRID = False  # darkness IS the ceiling per design_render_dome
FLOOR_BLOCKOUT_Y = -0.01  # opaque plane below the walking plane to hide subterranean geometry
FLOOR_BLOCKOUT_EXTENT = 200.0  # large enough that the camera never sees its edge in normal play

# Player-vs-entity collision (using each entity's collision_radius from the manifest).
PLAYER_COLLISION_RADIUS = 0.3  # ~human shoulder width
COLLISION_CULL_DIST = 8.0  # entities outside this horizontal range are skipped per frame

# Jump / sprint physics — pure client-side, brain doesn't care about y.
JUMP_VELOCITY = 5.0  # m/s upward impulse
GRAVITY = 14.0       # m/s²
SPRINT_MULTIPLIER = 1.5

# Interact targeting (F key)
INTERACT_RANGE_M = 3.0
INTERACT_RADIUS_HEURISTIC = 0.6  # default targeting halo for entities w/o collision_radius

# Visual feedback durations
CLICK_PING_DURATION = 0.3   # seconds
CLICK_PING_RADIUS_PX = 32   # final outer radius at end of fade
INTERACT_FLASH_DURATION = 0.5

# Inventory modal layout
INV_MODAL_X = 200
INV_MODAL_Y = 100
INV_MODAL_LINE_HEIGHT = 28

# Envelope ring (playable_envelope.radius) — single circle at floor level.
ENVELOPE_RING_SEGMENTS = 96

# Entity classes that are cosmetic/atmospheric in Godot's render — skip them
# in vector terminal so the air doesn't fill with non-representative geometry.
# Sourced from config/kind_config.json class field.
SKIP_ENTITY_CLASSES = frozenset({"atmosphere", "horizon", "debug"})

# HUD layout (2D screen space, post end_mode_3d)
HUD_FONT_SIZE = 18
HUD_LINE_HEIGHT = 22
HUD_X = 16
HUD_Y = 12
HUD_ENCOUNTER_Y = 12 + 22 * 8  # below the 7-line main HUD with one-line gap
HUD_OBJECTIVE_MAX_CHARS = 60
HUD_MSG_MAX_CHARS = 60
HUD_INV_MAX_CHARS = 60
CROSSHAIR_SIZE = 8

# Smart ENTER target table. Post PR 5 collapse (2026-05-02) the legacy
# 5-state mission loop is gone; ENTER no longer drives state transitions
# from HUB. Free exploration replaces "in a mission instance"; engage_*
# verbs (F on fridge / pillar) drive REFLECTIVE / CHARACTER_CREATION.
# Empty dict = ENTER is a no-op outside overlays (journal toggle,
# dial commit) which intercept it before this lookup runs.
ENTER_TARGETS: dict[str, str] = {}
