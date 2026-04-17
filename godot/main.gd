extends Node3D

## Sanctum Terminal — Godot viewer for Python brain manifests.
## Connects to brain_server.py via TCP for live streaming manifests.
## Falls back to static manifest.json if server isn't running.

const MOVE_SPEED := 8.0
const MOUSE_SENS := 0.002
const EYE_HEIGHT := 2.5
const SERVER_HOST := "127.0.0.1"
const SERVER_PORT := 9877

# Debug toggles. CREATURE_VERBOSE prints per-creature dist/flee heartbeats
# once per second for every active creature. Off by default because at
# 20+ creatures it dominates the stdout log and nudges frame time.
const CREATURE_VERBOSE := false

# FarCry/Skyrim-style FPS extensions — additive layer over the base camera
# controller. See godot/player/fps_player.gd for the standalone prototype
# this mirrors. Tuning knobs kept adjacent for easy in-place tweaking.
const SPRINT_MULTIPLIER: float         = 1.6
const JUMP_VELOCITY: float             = 5.0
const GRAVITY: float                   = 14.0
const CROUCH_HEIGHT_OFFSET: float      = 0.55
const LEAN_DISTANCE: float             = 0.35
const LEAN_TILT_DEG: float             = 8.0
const GAMEPAD_LOOK_SENS: float         = 2.5   # radians/sec at full deflection
const CAMERA_LERP_SMOOTHNESS: float    = 10.0
const PITCH_MIN := -80.0 * PI / 180.0
const PITCH_MAX :=  80.0 * PI / 180.0

# Flip to true to drive player movement through a real CharacterBody3D +
# move_and_slide instead of the hand-rolled Camera3D push-out. Both paths
# live side-by-side during the physics migration so we can UAT both and
# fall back by flipping the const if the new path misbehaves. Planned
# removal: once UAT passes at commit 1, delete the old branch + this flag.
const USE_PHYSICS_RIG := true
# Player capsule — matches godot/player/fps_player.tscn.
const PLAYER_CAPSULE_RADIUS: float = 0.4
const PLAYER_CAPSULE_HEIGHT: float = 1.8
# Entity colliders — cylinder height is a hardcoded approximation for the
# first physics pass (kind_config doesn't yet carry per-kind collider height).
# Spawn-radius cull keeps creation cost bounded on large tile rebuilds;
# entities outside the radius still emit the legacy dict for creature
# push-out, they just don't get a StaticBody3D.
const ENTITY_COLLIDER_HEIGHT: float = 6.0
const ENTITY_COLLIDER_SPAWN_R: float = 80.0

const MoteMaterials = preload("res://mote_materials.gd")
const MoteArrangements = preload("res://mote_arrangements.gd")

# Plane-attachment architecture (Design Law #14, Phase 3).
# Canonical ceiling height is now config-driven: resolved from the manifest's
# `planes` array at spawn time and cached in `active_ceiling_y`. The constant
# remains as the legacy fallback if the manifest omits planes entirely.
const CEILING_PLANE_Y_DEFAULT: float = 15.0
var active_ceiling_y: float = CEILING_PLANE_Y_DEFAULT

var camera: Camera3D
# Physics rig — when USE_PHYSICS_RIG, camera is a grand-child (rig → neck →
# camera). player_rig drives world XZ + yaw via move_and_slide, neck carries
# pitch + crouch lerp, camera carries lean offsets. Reads that want world
# position should use camera.global_position (works in both modes).
var player_rig: CharacterBody3D
var neck: Node3D
# StaticBody3D colliders for every real entity + colliders under the
# floor/wall planes. These hold the actual physics shapes the rig collides
# against. Rebuilt whenever _rebuild_entities fires.
var entity_colliders_root: Node3D
var plane_colliders_root: Node3D
var env_node: WorldEnvironment
var godot_env: Environment
var manifest: Dictionary
var mouse_captured := true

# FPS state — populated by physics process + gamepad polling.
var vertical_velocity: float = 0.0         # for jump arc + gravity
var cam_base_local_y: float = 0.0          # neutral local-Y for crouch lerp
var cam_base_local_x: float = 0.0          # neutral local-X for lean offset
var lean_state: float = 0.0                # -1 (L), 0 (none), 1 (R)

# Collision
var collision_objects: Array[Dictionary] = []

# Spatial cull — player physics iterates nearby_colliders instead of the full
# collision_objects (which can be 800+ entries). Refreshed when the player
# drifts more than COLLIDER_CULL_REFRESH meters from the cached position or
# when _rebuild_entities swaps the underlying set.
var nearby_colliders: Array[Dictionary] = []
var last_cull_pos: Vector2 = Vector2(INF, INF)
const COLLIDER_CULL_RADIUS: float = 15.0
const COLLIDER_CULL_REFRESH: float = 5.0

# Mesh cache
var mesh_cache: Dictionary = {}
var mesh_bounds: Dictionary = {}

# Live connection
var tcp: StreamPeerTCP
var connected := false
var encounter_hud: Node = null
var buf: String = ""
var update_timer: float = 0.0
const UPDATE_INTERVAL := 0.1  # send camera 10x/sec

# MultiMesh nodes per kind (for live rebuild)
var kind_nodes: Dictionary = {}

# Plane-attachment architecture: tag → {node, follow} dict, driven by
# manifest.planes. Ground/ceiling/future walls all live here.
var plane_nodes: Dictionary = {}

# Stone density texture — small grid covering ±DENSITY_WORLD_RADIUS around
# the player, with each pixel holding accumulated density from nearby
# stone-class entities. Sampled by ground.gdshader to bias mark polarity
# (light marks cluster where stones are, dark marks elsewhere). Rebuilt
# inside _rebuild_entities so it stays in sync with visible entities.
const DENSITY_TEX_SIZE := 32
const DENSITY_WORLD_RADIUS := 100.0  # texture covers a 200×200m square
const STONE_KINDS_FOR_DENSITY := {
	"boulder": true, "stalagmite": true, "rubble": true, "cave_gravel": true,
	"mega_column": true, "column": true, "buttress": true, "bone_pile": true,
}
var stone_density_tex: ImageTexture = null
var stone_density_buffer := PackedByteArray()
var stone_density_origin: Vector2 = Vector2.ZERO

# HUD
var hud_label: Label

# -- Expedition state (read from manifest['expedition']) ---------------------
# The render-manifest doctrine: brain owns truth, manifest carries it,
# we paint what we see. We do NOT maintain our own expedition state —
# this cache is just the latest snapshot the brain sent us, plus a tiny
# bit of local bookkeeping for tag dispatch and toast dedup.
var expedition_cache: Dictionary = {}
var expedition_active: bool = false
var expedition_last_message: String = ""
# Tag sidecars awaiting deposit. Keyed by tag_id. Cleared when a deposit
# intent is accepted, or when the expedition completes.
var pending_tag_intents: Dictionary = {}
# Deposit proximity radius — how close the player must get to a deposit
# point before Godot auto-sends a deposit_intent for each pending tag.
const EXPEDITION_DEPOSIT_RADIUS := 15.0  # covers the hub interior (~30m across)


func _ready() -> void:
	_load_kind_config()
	_load_mesh_bounds()

	# Try static manifest first (for initial scene while connecting)
	var path := "res://manifest.json"
	var file := FileAccess.open(path, FileAccess.READ)
	if file:
		var json_parser := JSON.new()
		if json_parser.parse(file.get_as_text()) == OK:
			manifest = json_parser.data
		file.close()
	else:
		manifest = {"entities": [], "fog": {"near": 10, "far": 40, "color": [0.1, 0.1, 0.1]},
			"ambient": [0.3, 0.22, 0.15], "bg_color": [0.12, 0.08, 0.12],
			"sun": {"color": [1, 0.55, 0.2], "scale": 5.0}, "moon": {"scale": 0.0},
			"camera": {"x": 0, "y": 0, "z": 2.5}}

	_setup_environment()
	_setup_camera()
	_setup_outline()
	# Collider parents — single Node3D each so _rebuild_entities can free
	# all per-instance bodies in one sweep. Created before _spawn_planes /
	# _spawn_entities so those calls can freely add_child onto them.
	entity_colliders_root = Node3D.new()
	entity_colliders_root.name = "EntityColliders"
	add_child(entity_colliders_root)
	plane_colliders_root = Node3D.new()
	plane_colliders_root.name = "PlaneColliders"
	add_child(plane_colliders_root)
	_spawn_planes()
	_spawn_entities()
	_update_motes()
	_setup_hud()
	_aim_spawn_heading()  # Point camera at nearest natural landmark for spawn composition

	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

	# Encounter HUD — Tartarus-mode encounter overlay, ported from
	# vector_viewer. Stamps the validated primitive into make brain-cavern.
	encounter_hud = preload("res://encounter_hud.gd").new()
	add_child(encounter_hud)
	encounter_hud.setup(camera)
	encounter_hud.action_chosen.connect(_on_encounter_action_chosen)
	encounter_hud.portal_requested.connect(_on_encounter_portal)
	encounter_hud.hub_arrival_needed.connect(_on_encounter_hub_arrival)

	# Connect to brain server
	_connect_to_brain()


func _on_encounter_action_chosen(name: String) -> void:
	if not connected or tcp == null:
		return
	var s := JSON.stringify({"cmd": "encounter_action", "action": name}) + "\n"
	tcp.put_data(s.to_utf8_buffer())


func _on_encounter_portal() -> void:
	if not connected or tcp == null:
		return
	var s := JSON.stringify({"cmd": "encounter_portal"}) + "\n"
	tcp.put_data(s.to_utf8_buffer())


func _on_encounter_hub_arrival() -> void:
	if not connected or tcp == null:
		return
	var s := JSON.stringify({"cmd": "encounter_hub_arrival"}) + "\n"
	tcp.put_data(s.to_utf8_buffer())


var kind_config: Dictionary = {}

func _load_kind_config() -> void:
	var path := "res://kind_config.json"
	var file := FileAccess.open(path, FileAccess.READ)
	if file:
		var jp := JSON.new()
		if jp.parse(file.get_as_text()) == OK:
			kind_config = jp.data
		file.close()
	print("Kind config: %d kinds loaded" % kind_config.get("kinds", {}).size())
	# Phase 4: derive CREATURE_KINDS from kind_config behavior blocks.
	_load_creature_kinds()


func _get_kind_params(kind: String) -> Dictionary:
	"""Resolve kind config: class defaults merged with per-kind overrides."""
	var kinds: Dictionary = kind_config.get("kinds", {})
	var defaults: Dictionary = kind_config.get("_class_defaults", {})
	var kind_entry: Dictionary = kinds.get(kind, {})
	var kind_class: String = kind_entry.get("class", "geological")
	var base: Dictionary = defaults.get(kind_class, {}).duplicate(true)
	# Merge per-kind overrides on top of class defaults
	for key: String in kind_entry:
		if key == "class":
			continue
		if kind_entry[key] is Dictionary and base.has(key) and base[key] is Dictionary:
			var merged: Dictionary = base[key].duplicate(true)
			for k2: String in kind_entry[key]:
				merged[k2] = kind_entry[key][k2]
			base[key] = merged
		else:
			base[key] = kind_entry[key]
	return base


func _resolve_surface(kind: String) -> Dictionary:
	"""Look up the surface_library entry a kind should render with.

	Resolution: kinds[kind].surface → class_defaults[class].surface →
	library 'default'. Returns the library entry dict (albedo/normal paths
	plus default grain_scale/strength/normal_strength tuning).
	"""
	var library: Dictionary = kind_config.get("_global", {}).get("surface_library", {})
	var kind_entry: Dictionary = kind_config.get("kinds", {}).get(kind, {})
	var kind_class: String = kind_entry.get("class", "geological")
	var class_defaults: Dictionary = kind_config.get("_class_defaults", {}).get(kind_class, {})

	var surface_name: String = kind_entry.get("surface",
		class_defaults.get("surface", "default"))
	if library.has(surface_name):
		return library[surface_name]
	if library.has("default"):
		return library["default"]
	# Library missing entirely — return hardcoded fallback so rendering still works
	return {
		"albedo": "res://world_grain.png",
		"normal": "res://world_grain_normal.png",
		"grain_scale": 0.35,
		"grain_strength": 0.45,
		"normal_strength": 0.5,
	}


func _resolve_surface_by_name(surface_name: String) -> Dictionary:
	"""Look up a named surface in the library (used by planes, not kinds)."""
	var library: Dictionary = kind_config.get("_global", {}).get("surface_library", {})
	if library.has(surface_name):
		return library[surface_name]
	if library.has("default"):
		return library["default"]
	return {
		"albedo": "res://world_grain.png",
		"normal": "res://world_grain_normal.png",
		"grain_scale": 0.35,
		"grain_strength": 0.45,
		"normal_strength": 0.5,
	}


func _create_kind_material(kind: String) -> Material:
	"""Create a ShaderMaterial configured from kind_config for this kind.
	3-color flat shader: color_base/shadow/accent + light_reactive flag.
	"""
	var params: Dictionary = _get_kind_params(kind)
	var shader: Shader = load("res://kind_shader.gdshader")
	if not shader:
		var fallback := StandardMaterial3D.new()
		fallback.cull_mode = BaseMaterial3D.CULL_DISABLED
		return fallback

	var mat := ShaderMaterial.new()
	mat.shader = shader

	# 3-color palette
	var cb: Array = params.get("color_base", [0.30, 0.27, 0.23])
	var cs: Array = params.get("color_shadow", [0.26, 0.23, 0.19])
	var ca: Array = params.get("color_accent", [0.34, 0.30, 0.25])
	mat.set_shader_parameter("color_base", Color(cb[0], cb[1], cb[2]))
	mat.set_shader_parameter("color_shadow", Color(cs[0], cs[1], cs[2]))
	mat.set_shader_parameter("color_accent", Color(ca[0], ca[1], ca[2]))

	# Light reactivity
	mat.set_shader_parameter("light_reactive", 1.0 if params.get("light_reactive", false) else 0.0)

	# Vertex shape — only what earns its pixels
	mat.set_shader_parameter("taper_strength", params.get("taper_strength", 0.0))
	mat.set_shader_parameter("twist_amount", params.get("twist_amount", 0.0))

	# Per-instance horizontal banding — strength per kind class.
	# Stone kinds (structural/geological) get visible stratification;
	# organic/life/atmosphere default to 0 (no rock layers on living things).
	mat.set_shader_parameter("band_strength", params.get("band_strength", 0.0))

	# Per-instance wind sway — organic kinds animate, stone kinds stay inert.
	# Stamped for grass/moss/vine/atmosphere via kind_config class defaults.
	mat.set_shader_parameter("wind_strength", params.get("wind_strength", 0.0))

	# Per-instance ghost fade — distance-based dither discard on a hash-
	# selected fraction of instances. Geological kinds ghost at distance;
	# structural landmarks and everything else stay solid.
	mat.set_shader_parameter("ghost_chance", params.get("ghost_chance", 0.0))

	# Vertex color path — designed kinds (toadstool, shrubs, fauna) bake
	# color regions into mesh vertex data. When true, shader skips the
	# facet-normal palette and reads COLOR directly. Stone kinds default
	# to false so they keep banding + facet stratification.
	mat.set_shader_parameter("use_vertex_colors",
		1.0 if params.get("use_vertex_colors", false) else 0.0)

	return mat


func _load_mesh_bounds() -> void:
	var bpath := "res://meshes/bounds.json"
	var file := FileAccess.open(bpath, FileAccess.READ)
	if file:
		var jp := JSON.new()
		if jp.parse(file.get_as_text()) == OK:
			mesh_bounds = jp.data
		file.close()


const NUM_VARIANTS := 4

const MESH_ALIAS := {
	"buttress": "boulder",        # buttress = rounded mass (foundation archetype)
	"mega_column": "stalagmite",  # column = inverted stalagmite (tapered spike archetype)
	"column": "stalagmite",       # same — shared shape language with stalagmites, just flipped
}

func _get_mesh_for_kind(kind: String, variant: int = 0) -> Mesh:
	var mesh_kind: String = MESH_ALIAS.get(kind, kind)
	var cache_key: String = "%s_v%d" % [mesh_kind, variant]
	if mesh_cache.has(cache_key):
		return mesh_cache[cache_key]

	# Try variant file first, fall back to base name
	var glb_path := "res://meshes/%s_v%d.glb" % [mesh_kind, variant]
	if not ResourceLoader.exists(glb_path):
		glb_path = "res://meshes/%s.glb" % mesh_kind  # legacy fallback

	if ResourceLoader.exists(glb_path):
		# CACHE_MODE_IGNORE forces ResourceLoader to reload from disk
		# instead of returning a process-wide cached copy. Without this,
		# changing a .glb on disk doesn't take effect until Godot is
		# fully restarted — even Stop+Play in the editor keeps the old
		# in-memory resource. The per-scene mesh_cache above still
		# prevents redundant loads within a single session.
		var scene: PackedScene = ResourceLoader.load(glb_path, "", ResourceLoader.CACHE_MODE_IGNORE)
		if scene:
			var instance := scene.instantiate()
			var mi := _find_mesh_instance(instance)
			if mi:
				mesh_cache[cache_key] = mi.mesh
				instance.queue_free()
				return mi.mesh
			instance.queue_free()

	var box := BoxMesh.new()
	box.size = Vector3.ONE
	mesh_cache[cache_key] = box
	return box


func _find_mesh_instance(node: Node) -> MeshInstance3D:
	if node is MeshInstance3D:
		return node
	for child in node.get_children():
		var found := _find_mesh_instance(child)
		if found:
			return found
	return null


func _setup_environment() -> void:
	godot_env = Environment.new()

	var fog: Dictionary = manifest.get("fog", {})
	var fc: Array = fog.get("color", [0.1, 0.1, 0.1])
	var fog_far: float = fog.get("far", 55.0)

	# Atmospheric mode — fog ON, depth fade across distance.
	godot_env.fog_enabled = true
	godot_env.fog_light_color = Color(fc[0], fc[1], fc[2])
	godot_env.fog_density = 0.015
	godot_env.fog_sky_affect = 1.0
	godot_env.fog_aerial_perspective = 0.4

	# Background = ceiling plane color from manifest (biome_data is single source of truth).
	# Falls back to project.godot clear_color if no ceiling plane found.
	var bg := Color(0.10, 0.09, 0.08)
	var planes: Array = manifest.get("planes", [])
	for p in planes:
		if p.get("kind", "") == "ceiling":
			var cb: Array = p.get("material", {}).get("color_base", [])
			if cb.size() >= 3:
				bg = Color(cb[0], cb[1], cb[2])
			break
	godot_env.background_mode = Environment.BG_COLOR
	godot_env.background_color = bg

	# Atmospheric mode — low warm ambient. Light pools from pipes carry
	# the rest of the lighting. Memory: design_light_pipes (3 fixed pipes
	# per biome, drift to nearest emissive cluster).
	godot_env.ambient_light_color = Color(0.55, 0.50, 0.45)  # warm cream tint
	godot_env.ambient_light_energy = 0.18                    # was 1.0 (clean room)
	godot_env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR

	godot_env.tonemap_mode = 2
	godot_env.tonemap_white = 5.0

	# Bloom — emissives carry the highlights now (Sable in reverse).
	godot_env.glow_enabled = true
	godot_env.glow_intensity = 1.4
	godot_env.glow_strength = 1.1
	godot_env.glow_bloom = 0.30
	godot_env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SOFTLIGHT
	godot_env.glow_hdr_threshold = 0.85
	godot_env.glow_hdr_scale = 2.0

	godot_env.adjustment_enabled = false
	godot_env.volumetric_fog_enabled = false

	# SSAO — killed. Contact shadow Decals handle ground darkening per-kind.
	# SSAO was doubling up, making object bases darker than intended.
	godot_env.ssao_enabled = false

	# SSIL — disabled. Decal pools + rim light handle indirect fill cheaper.
	# Re-enable when perf budget allows; the visual was subtle vs the cost.
	godot_env.ssil_enabled = false

	env_node = WorldEnvironment.new()
	env_node.environment = godot_env
	add_child(env_node)


func _setup_camera() -> void:
	var cam_data: Dictionary = manifest.get("camera", {})
	var spawn_x: float = cam_data.get("x", 0.0)
	var spawn_z: float = cam_data.get("y", 0.0)
	var spawn_heading: float = cam_data.get("heading", 0.0)

	camera = Camera3D.new()
	camera.rotation_degrees.x = 10.0  # upward tilt — catches stalactites + ceiling features naturally

	# Armor glow — warm omnidirectional bloom at waist height.
	# Not a flashlight — a lantern. Lights ground AND objects equally from
	# player's body, like bioluminescent armor plating. Soft dome of presence.
	var armor_glow := OmniLight3D.new()
	armor_glow.name = "ArmorGlow"
	armor_glow.light_color = Color(0.95, 0.78, 0.52)  # warm lantern amber
	armor_glow.light_energy = 0.45  # subtle waist lantern, not a flashlight
	armor_glow.omni_range = 6.0
	armor_glow.omni_attenuation = 1.4
	armor_glow.shadow_enabled = false
	armor_glow.position = Vector3(0.0, -1.2, 0.0)  # waist height below camera
	camera.add_child(armor_glow)

	if USE_PHYSICS_RIG:
		# CharacterBody3D rig — body owns world XZ + yaw, neck owns pitch +
		# crouch lerp, camera sits at neck origin carrying lean offset only.
		# Capsule collider is centered at y = height/2 so the feet hit y=0.
		player_rig = CharacterBody3D.new()
		player_rig.name = "PlayerRig"
		player_rig.position = Vector3(spawn_x, 0.0, spawn_z)
		player_rig.rotation_degrees.y = spawn_heading
		add_child(player_rig)

		var cs := CollisionShape3D.new()
		var cap := CapsuleShape3D.new()
		cap.radius = PLAYER_CAPSULE_RADIUS
		cap.height = PLAYER_CAPSULE_HEIGHT
		cs.shape = cap
		cs.position.y = PLAYER_CAPSULE_HEIGHT * 0.5
		player_rig.add_child(cs)

		neck = Node3D.new()
		neck.name = "Neck"
		neck.position.y = EYE_HEIGHT
		player_rig.add_child(neck)

		# Camera local transform is identity — pitch goes on the neck, yaw on
		# the rig, lean X offset + roll go on the camera (set by _physics_process).
		neck.add_child(camera)
	else:
		# Legacy path — camera IS the root. Kept for regression A/B while
		# USE_PHYSICS_RIG rolls out. Deleted in commit 2.
		camera.position = Vector3(spawn_x, EYE_HEIGHT, spawn_z)
		camera.rotation_degrees.y = spawn_heading
		add_child(camera)

	# iso camera setup deferred to _finalize_spawn_scene so the first-person
	# camera is already in the scene tree and explicitly current when iso
	# is added. Otherwise Godot auto-activates whichever camera is added
	# first and both cameras can end up rendering into the same viewport.


# --- Player world-pos / yaw helpers -----------------------------------------
# Callers that want "where is the player in the world" ask these helpers
# instead of touching `camera.position` / `camera.rotation` directly. They
# resolve correctly whether the camera is a root Node3D (legacy) or a
# grand-child of the CharacterBody3D rig (USE_PHYSICS_RIG).
func _player_pos() -> Vector3:
	return camera.global_position

func _player_yaw() -> float:
	return player_rig.rotation.y if USE_PHYSICS_RIG else camera.rotation.y

func _player_pitch() -> float:
	return neck.rotation.x if USE_PHYSICS_RIG else camera.rotation.x

# Teleport helper — writes to the right node depending on rig mode. Resets
# velocity on teleport so a mid-fall zap doesn't carry momentum into the
# destination. heading_rad and pitch_rad in radians.
func _teleport_player(pos: Vector3, heading_rad: float, pitch_rad: float = 0.0) -> void:
	if USE_PHYSICS_RIG:
		# Rig y=0 is feet; spawn at pos.x/z regardless of pos.y (feet grounded).
		player_rig.position = Vector3(pos.x, 0.0, pos.z)
		player_rig.rotation.y = heading_rad
		neck.rotation.x = pitch_rad
		player_rig.velocity = Vector3.ZERO
	else:
		camera.position = Vector3(pos.x, EYE_HEIGHT, pos.z)
		camera.rotation.y = heading_rad
		camera.rotation.x = pitch_rad

# --- Player avatar (iso-only) ------------------------------------------------
# Tall dark silhouette placed at the first-person camera's XZ. Visible only
# when the iso dev camera is active, so first-person POV stays clean per
# design_first_person.md. Currently a capsule primitive — placeholder for
# a future monk GLB. Kept as a cloak-column shape (narrow + tall) so even
# from iso the "facing" direction is ambiguous, matching our Plato's-Cave
# doctrine: the avatar is a silhouette first, detail never.
const AVATAR_HEIGHT_M: float = 3.5
const AVATAR_RADIUS_M: float = 0.9
# Pale bone — contrasts cavern browns so the avatar reads from iso zoom-out
# as a clear landmark, not a dark blob lost in darker ground.
const AVATAR_COLOR := Color(0.85, 0.80, 0.65)

var player_avatar: Node3D


func _setup_player_avatar() -> void:
	var avatar := MeshInstance3D.new()
	avatar.name = "PlayerAvatar"
	var mesh := CapsuleMesh.new()
	mesh.radius = AVATAR_RADIUS_M
	mesh.height = AVATAR_HEIGHT_M
	avatar.mesh = mesh
	var mat := StandardMaterial3D.new()
	mat.albedo_color = AVATAR_COLOR
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	avatar.set_surface_override_material(0, mat)
	avatar.visible = false   # hidden until iso camera is active
	player_avatar = avatar
	add_child(avatar)

	# Forward arrow — small bright cone in front of the avatar along its
	# local -Z (Godot's default forward). Capsule is rotationally symmetric,
	# so without this arrow the player has no way to tell which direction
	# they're facing in iso view. Pointer = this arrow, not the crosshair.
	var arrow := MeshInstance3D.new()
	arrow.name = "FacingArrow"
	var cone := CylinderMesh.new()
	cone.top_radius = 0.0
	cone.bottom_radius = 0.28
	cone.height = 0.7
	arrow.mesh = cone
	var arrow_mat := StandardMaterial3D.new()
	arrow_mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	arrow_mat.albedo_color = Color(1.0, 0.85, 0.4)
	arrow_mat.emission_enabled = true
	arrow_mat.emission = Color(1.0, 0.85, 0.4)
	arrow_mat.emission_energy_multiplier = 1.8
	arrow.set_surface_override_material(0, arrow_mat)
	# Parent under the avatar so it inherits rotation. Cylinder default is
	# along Y; rotate 90° around X so it lies flat pointing toward -Z.
	arrow.rotation.x = -PI / 2.0
	# Push forward 1.3m along avatar's local -Z, down to ground level.
	arrow.position = Vector3(0, -AVATAR_HEIGHT_M * 0.5 + 0.1, -1.3)
	avatar.add_child(arrow)


func _update_player_avatar() -> void:
	# Sit the capsule's BASE on the floor by raising its center to
	# height/2. Follows the first-person camera's XZ; Y is fixed at the
	# floor + avatar halfway so motion doesn't bob vertically.
	# Rotation follows the FP camera yaw so in iso view the player can
	# see which way they're pointing (the crosshair + avatar facing agree).
	if not is_instance_valid(player_avatar):
		return
	var p: Vector3 = _player_pos()
	player_avatar.position = Vector3(p.x, AVATAR_HEIGHT_M * 0.5, p.z)
	player_avatar.rotation.y = _player_yaw()


# --- Iso dev camera ----------------------------------------------------------
# Dev tool, not gameplay — KEY_I toggles between first-person and top-down
# orthographic 3/4 view for silhouette evaluation + composition audits.
# Two Camera3Ds in the same scene; whichever has current=true renders.
# Iso camera follows the first-person camera's XZ each frame so the view
# stays centered on the player's current position regardless of teleports.
# Tuned toward Drova-style readability (2026-04-16):
#   - Higher + steeper pitch → less mid-ground geometry blocking the player
#   - Closer pull-back → less stuff between camera and avatar
#   - Wider ortho size → more world visible, fewer "zoomed in" moments
# If objects still occlude the player, the next step is a shader-based
# camera-to-player occlusion fade (not yet wired).
const ISO_HEIGHT_M: float = 28.0       # raised from 20 (more top-down)
const ISO_DISTANCE_M: float = 14.0     # pulled in from 18 (less mid-ground between cam and avatar)
const ISO_PITCH_DEG: float = -62.0     # steeper than 55 (more top-down, Drova-ish)
const ISO_YAW_DEG: float = 45.0        # 45° rotate (classic iso)
const ISO_ORTHO_SIZE_M: float = 42.0   # widened from 34 (Drova-feel viewport span)

var iso_camera: Camera3D
var iso_active: bool = false


func _setup_iso_camera() -> void:
	iso_camera = Camera3D.new()
	iso_camera.name = "IsoDevCamera"
	iso_camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	iso_camera.size = ISO_ORTHO_SIZE_M
	iso_camera.near = 0.1
	iso_camera.far = 600.0
	iso_camera.rotation_degrees = Vector3(ISO_PITCH_DEG, ISO_YAW_DEG, 0.0)
	iso_camera.current = false
	add_child(iso_camera)


func _update_iso_camera_position() -> void:
	# Offset iso camera along its yaw axis by ISO_DISTANCE_M so the
	# first-person camera sits near the center of the iso viewport.
	var yaw_rad: float = deg_to_rad(ISO_YAW_DEG)
	var ox: float = -sin(yaw_rad) * ISO_DISTANCE_M
	var oz: float = cos(yaw_rad) * ISO_DISTANCE_M
	var p: Vector3 = _player_pos()
	iso_camera.position = Vector3(p.x + ox, ISO_HEIGHT_M, p.z + oz)


func _toggle_iso_camera() -> void:
	iso_active = not iso_active
	if iso_active:
		_update_iso_camera_position()
		_update_player_avatar()
		iso_camera.current = true
		if is_instance_valid(player_avatar):
			player_avatar.visible = true
		# Hide center crosshair — doesn't mean "facing" in iso view.
		# The avatar's forward arrow carries direction.
		if encounter_hud:
			encounter_hud.set_crosshair_visible(false)
		_show_toast("ISO dev camera")
	else:
		camera.current = true
		if is_instance_valid(player_avatar):
			player_avatar.visible = false
		if encounter_hud:
			encounter_hud.set_crosshair_visible(true)
		_show_toast("First-person")


func _aim_spawn_heading() -> void:
	"""Spawn ritual — position and orient the camera for first frame.

	Cavern biome: player emerges through the SOUTH arch of the origin hub
	at world (0, -14), facing +Y (north) into the hub. The hub is
	hand-authored in biome_data.ORIGIN_HUB with four cardinal arches at
	~12m radius, and stamp_world.stamp_at() places it deterministically
	at slot (0, 0).

	Other biomes: fall back to the legacy "find nearest mega_column and
	frame it peripheral" landmark search.

	Both branches finalize via _finalize_spawn_scene() which handles
	camera attachment, light pipes, and banner cylinders.
	"""
	var biome_name: String = manifest.get("biome", "cavern")

	if biome_name == "cavern":
		# Hub spawn — enter the hub from the SOUTH arch (world y=-14) facing
		# north (+Y in brain → +Z in Godot). _teleport_player writes to rig or
		# camera depending on USE_PHYSICS_RIG and clears any stale velocity.
		_teleport_player(Vector3(0.0, 0.0, -14.0), PI, deg_to_rad(8.0))
		print("Hub spawn: player at (0, -14) facing north (180°)")
	else:
		_legacy_landmark_aim()

	_finalize_spawn_scene()


func _legacy_landmark_aim() -> void:
	"""Rotates the camera to frame the nearest mega_column in the right
	peripheral. Used by non-cavern biomes that don't yet have an
	authored hub. Leaves camera.position alone (set by _setup_camera
	from manifest.camera)."""
	const SPAWN_CLEARANCE: float = 18.0
	const IDEAL_MIN_DIST: float = 18.0
	const IDEAL_MAX_DIST: float = 32.0
	var p: Vector3 = _player_pos()
	var cam_x: float = p.x
	var cam_z: float = p.z
	var best_dist: float = 9999.0
	var best_x: float = 0.0
	var best_z: float = 0.0
	var found: bool = false
	for ent: Dictionary in manifest.get("entities", []):
		if ent.get("kind", "") != "mega_column":
			continue
		var ex: float = ent.get("x", 0.0)
		var ez: float = ent.get("y", 0.0)
		var dx: float = ex - cam_x
		var dz: float = ez - cam_z
		var dist: float = sqrt(dx * dx + dz * dz)
		if dist < SPAWN_CLEARANCE:
			continue  # skip anything inside clearance (shouldn't be any, but safety)
		# Prefer landmarks in the ideal framing range
		var score: float = dist
		if dist < IDEAL_MIN_DIST:
			score = IDEAL_MIN_DIST + (IDEAL_MIN_DIST - dist) * 2.0  # penalty for too close
		elif dist > IDEAL_MAX_DIST:
			score = dist  # mild penalty for too far
		if score < best_dist:
			best_dist = score
			best_x = ex
			best_z = ez
			found = true
	if not found:
		print("Spawn aim: no mega_column found, keeping default heading")
		return
	# Compute heading to face landmark, then offset 35° so it sits in right peripheral
	var dx: float = best_x - cam_x
	var dz: float = best_z - cam_z
	var landmark_heading: float = atan2(dx, -dz)
	var peripheral_offset: float = deg_to_rad(-35.0)
	var final_heading: float = landmark_heading + peripheral_offset
	if USE_PHYSICS_RIG:
		player_rig.rotation.y = final_heading
	else:
		camera.rotation.y = final_heading
	print("Spawn aim: landmark at (%.1f, %.1f), dist %.1fm, heading %.1f°" % [
		best_x, best_z, sqrt(dx*dx + dz*dz), rad_to_deg(final_heading)])


func _finalize_spawn_scene() -> void:
	"""Attach the camera to the scene tree and initialize light pipes +
	banner cylinders. Shared by both spawn modes (hub + legacy landmark).
	Must run exactly once per scene setup — do not call from _process."""
	var fog_data: Dictionary = manifest.get("fog", {})
	camera.far = fog_data.get("far", 55.0) * 2.5  # extended for skeleton silhouettes
	camera.fov = 62.0  # wider peripheral — catches ceiling features + passive pull cues
	# Camera is already parented inside _setup_camera (rig branch → neck.add_child,
	# legacy branch → add_child). Don't re-parent here — Godot warns on duplicate.
	camera.current = true   # explicit — iso camera added next mustn't take over
	_setup_iso_camera()
	_setup_player_avatar()

	# Initialize light pipes — 3 fixed OmniLights, created once, live forever.
	# Each pipe covers a color family. Positions lerp to nearest matching emissive.
	var biome_name: String = manifest.get("biome", "cavern")
	var pipe_cfgs: Array = BIOME_LIGHT_PIPES.get(biome_name, BIOME_LIGHT_PIPES["cavern"])
	var pstart: Vector3 = _player_pos()
	for pipe_cfg: Dictionary in pipe_cfgs:
		var primary := OmniLight3D.new()
		primary.light_color = pipe_cfg["color"]
		primary.light_energy = pipe_cfg["energy"]
		primary.omni_range = pipe_cfg["range"]
		primary.omni_attenuation = pipe_cfg["attenuation"]
		primary.shadow_enabled = false
		primary.position = pstart  # start at player, drift to nearest match
		add_child(primary)

		var fill := OmniLight3D.new()
		fill.light_color = pipe_cfg["color"]
		fill.light_energy = pipe_cfg["energy"] * 0.15
		fill.omni_range = pipe_cfg["range"] * 0.5
		fill.omni_attenuation = pipe_cfg["attenuation"] * 1.3
		fill.shadow_enabled = false
		fill.position = pstart
		add_child(fill)

		light_pipes.append({
			"node": primary, "fill_node": fill, "cfg": pipe_cfg,
			"target_pos": pstart, "active": false,
		})

	# Banner cylinders — projection layers fake atmospheric depth where
	# geometry stops. Each ring is a translucent inside-facing cylinder.
	var banner_layers: Array = manifest.get("banner_layers", [])
	for bl: Dictionary in banner_layers:
		var cyl_mesh := CylinderMesh.new()
		cyl_mesh.top_radius = bl.get("distance", 20.0)
		cyl_mesh.bottom_radius = bl.get("distance", 20.0)
		cyl_mesh.height = bl.get("height", 15.0)
		cyl_mesh.radial_segments = 14  # 2×7
		cyl_mesh.rings = 1

		var mat := StandardMaterial3D.new()
		var tint: Array = bl.get("tint", [0.05, 0.05, 0.08])
		mat.albedo_color = Color(tint[0], tint[1], tint[2], bl.get("opacity", 0.1))
		mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		mat.cull_mode = BaseMaterial3D.CULL_FRONT  # render inside face only
		mat.no_depth_test = true
		cyl_mesh.material = mat

		var mi := MeshInstance3D.new()
		mi.mesh = cyl_mesh
		mi.name = "Banner_%s" % bl.get("role", "layer")
		var bp: Vector3 = _player_pos()
		mi.position = Vector3(bp.x, bl.get("height", 15.0) * 0.3, bp.z)
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(mi)
		banner_cylinders.append(mi)


var outline_material: ShaderMaterial
var outline_mode: int = 2  # 0=Moebius, 1=Manga, 2=Sable
const OUTLINE_MODE_NAMES := ["Moebius", "Manga", "Sable"]

func _setup_outline() -> void:
	# DISABLED — CanvasLayer+ColorRect approach doesn't work on this Metal/Godot 4
	# setup. hint_screen_texture returns white. Need to solve outlines via a
	# different method (compositor effect, SubViewport, or per-material outlines).
	print("Outline shader: DISABLED (screen texture broken on this setup)")


func _cycle_outline_mode() -> void:
	outline_mode = (outline_mode + 1) % 3
	if outline_material:
		outline_material.set_shader_parameter("outline_mode", outline_mode)
	print("Outline: %s" % OUTLINE_MODE_NAMES[outline_mode])
	_show_toast("Outline: %s" % OUTLINE_MODE_NAMES[outline_mode])


func _spawn_planes() -> void:
	# Phase 3: plane-attachment architecture is fully config-driven.
	# Each biome declares its planes in biome_data.BIOME_PLANES; the brain
	# streams them in manifest.planes; we instantiate one MeshInstance3D per
	# entry. Adding a new plane (wall, sky dome, mezzanine floor) is a pure
	# config edit — zero lines of renderer code.
	var planes: Array = manifest.get("planes", [])
	if planes.is_empty():
		# Legacy fallback: manifest omitted planes (static JSON, old server).
		# Synthesize a cavern default so the scene still renders.
		planes = _legacy_cavern_planes()
	for p in planes:
		_spawn_plane(p)


func _legacy_cavern_planes() -> Array:
	return [
		{
			"tag": "ground_near", "kind": "ground",
			"normal": [0.0, 0.0, 1.0], "offset": 0.0, "layer": "near",
			"size": 2000.0, "follow_camera": true,
			"material": {
				"color_base": [0.58, 0.55, 0.50], "grain_scale": 0.22,
				"grain_strength": 0.0, "normal_strength": 0.0,
			},
		},
		{
			"tag": "ceiling_near", "kind": "ceiling",
			"normal": [0.0, 0.0, -1.0], "offset": CEILING_PLANE_Y_DEFAULT, "layer": "near",
			"size": 2000.0, "follow_camera": true,
			"material": {
				"color_base": [0.12, 0.11, 0.09], "grain_scale": 0.22,  # must match biome_data ceiling
				"grain_strength": 0.55, "normal_strength": 1.1,
			},
		},
	]


func _spawn_plane(p: Dictionary) -> void:
	var tag: String = p.get("tag", "untagged")
	var size: float = p.get("size", 2000.0)

	var mesh := PlaneMesh.new()
	mesh.size = Vector2(size, size)
	mesh.subdivide_width = 4
	mesh.subdivide_depth = 4
	mesh.material = _create_plane_material(p.get("material", {}), p.get("kind", ""))

	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.name = "Plane_" + tag

	# Normal in brain-space (z-up). Godot PlaneMesh default faces +Y.
	# Floor  [0,0,+1] → no rotation, position.y = offset
	# Ceiling [0,0,-1] → 180° X rotation, position.y = offset
	# Wall-L [+1,0,0] → 90° Z rotation, position.x = offset
	# Wall-R [-1,0,0] → -90° Z rotation, position.x = offset
	# Wall-B [0,+1,0] → 90° X rotation, position.z = offset (brain Y → godot Z)
	# Wall-F [0,-1,0] → -90° X rotation, position.z = offset
	var normal: Array = p.get("normal", [0.0, 0.0, 1.0])
	var nx: float = float(normal[0]) if normal.size() >= 1 else 0.0
	var ny: float = float(normal[1]) if normal.size() >= 2 else 0.0
	var nz: float = float(normal[2]) if normal.size() >= 3 else 1.0
	var offset: float = float(p.get("offset", 0.0))

	var is_floor: bool = abs(nz) > 0.5 and nz > 0.0
	var is_ceiling: bool = abs(nz) > 0.5 and nz < 0.0
	var is_wall: bool = abs(nx) > 0.5 or abs(ny) > 0.5

	if abs(nz) > 0.5:
		# Floor or ceiling — vertical plane
		if nz < 0.0:
			mi.rotation_degrees.x = 180.0
		mi.position.y = offset
	elif abs(nx) > 0.5:
		# Left/right wall — rotate so the PlaneMesh's +Y default face lands
		# on the biome-declared inward normal. Kept for any future biome
		# that opts back into wall planes; cavern no longer uses them.
		mi.rotation_degrees.z = -90.0 if nx > 0.0 else 90.0
		mi.position.x = offset
	elif abs(ny) > 0.5:
		# Front/back wall — rotate around X (brain Y = godot Z).
		mi.rotation_degrees.x = 90.0 if ny > 0.0 else -90.0
		mi.position.z = offset
	add_child(mi)

	# Physics collider — floors + walls get a StaticBody3D so the rig stands
	# on real ground. Ceilings skip: head-bumps aren't a gameplay concern in
	# a cavern and the planes extend forever, so colliding on them only
	# produces weird jump caps. Body is a child of plane_colliders_root so
	# rebuilds don't orphan shapes.
	if (is_floor or is_wall) and is_instance_valid(plane_colliders_root):
		var sb := StaticBody3D.new()
		sb.name = "PlaneCollider_" + tag
		var cs := CollisionShape3D.new()
		var box := BoxShape3D.new()
		if is_floor:
			# Horizontal slab — thin in Y, extends to plane size in X/Z.
			box.size = Vector3(size, 0.5, size)
			sb.position = Vector3(0.0, offset - 0.25, 0.0)
		elif abs(nx) > 0.5:
			# X-normal wall — thin in X, tall, extends in Y/Z.
			box.size = Vector3(0.5, size, size)
			sb.position = Vector3(offset, 0.0, 0.0)
		else:
			# Y-normal wall (brain) = Z-normal in Godot — thin in Z, extends X/Y.
			box.size = Vector3(size, size, 0.5)
			sb.position = Vector3(0.0, 0.0, offset)
		cs.shape = box
		sb.add_child(cs)
		plane_colliders_root.add_child(sb)

	plane_nodes[tag] = {
		"node": mi,
		"follow": bool(p.get("follow_camera", true)),
		"kind": p.get("kind", "ground"),
		"offset": offset,
		"collider_parent": plane_colliders_root if (is_floor or is_wall) else null,
	}

	# Cache canonical ceiling Y for kinds that resolve attachment by tag.
	if tag == "ceiling_near":
		active_ceiling_y = float(p.get("offset", CEILING_PLANE_Y_DEFAULT))


func _create_plane_material(m: Dictionary, plane_kind: String = "") -> Material:
	# Resolve texture paths through the surface library if the plane material
	# declares a `surface` field; otherwise fall back to world_grain. Per-plane
	# grain_scale/strength/normal_strength still override whatever the surface
	# library entry suggests, so biome_data stays in full control of tuning.
	var surface_name: String = String(m.get("surface", ""))
	var surface_entry: Dictionary = _resolve_surface_by_name(surface_name) if surface_name != "" else {}
	var albedo_path: String = surface_entry.get("albedo", "res://world_grain.png")
	var normal_path: String = surface_entry.get("normal", "res://world_grain_normal.png")

	var shader := load("res://ground.gdshader")
	if shader:
		var mat := ShaderMaterial.new()
		mat.shader = shader
		var cb: Array = m.get("color_base", [0.18, 0.15, 0.12])
		mat.set_shader_parameter("color_base", Color(cb[0], cb[1], cb[2]))
		# Distance fade = ground color darkened — same family, not a separate fog system
		mat.set_shader_parameter("fog_color", Color(cb[0] * 0.55, cb[1] * 0.55, cb[2] * 0.55))
		var grain: Texture2D = load(albedo_path)
		if grain:
			mat.set_shader_parameter("grain_tex", grain)
		var nmap: Texture2D = load(normal_path)
		if nmap:
			mat.set_shader_parameter("normal_tex", nmap)
		mat.set_shader_parameter("grain_scale",
			float(m.get("grain_scale", surface_entry.get("grain_scale", 0.22))))
		mat.set_shader_parameter("grain_strength",
			float(m.get("grain_strength", surface_entry.get("grain_strength", 0.65))))
		mat.set_shader_parameter("normal_strength",
			float(m.get("normal_strength", surface_entry.get("normal_strength", 1.3))))
		mat.set_shader_parameter("roughness_val",
			float(m.get("roughness", 0.95)))
		# Optional config overrides for the sparse-mark system. Ground
		# planes set these to bigger values so iso view reads tonal
		# patches; near-ceiling/walls can keep defaults or opt in.
		if m.has("mark_grid_size"):
			mat.set_shader_parameter("mark_grid_size",
				float(m["mark_grid_size"]))
		if m.has("mark_chance"):
			mat.set_shader_parameter("mark_chance",
				float(m["mark_chance"]))
		if m.has("mark_strength"):
			mat.set_shader_parameter("mark_strength",
				float(m["mark_strength"]))
		# Plane kind routing — three states: floor (Voronoi), ceiling
		# (smooth, no Voronoi), wall (vertical projection + darken). Both
		# floor and ceiling are non-vertical, so a third bool isolates floor.
		var is_wall: bool = plane_kind == "wall"
		var is_floor: bool = plane_kind == "ground"
		mat.set_shader_parameter("vertical_surface", is_wall)
		mat.set_shader_parameter("is_floor", is_floor)
		mat.set_shader_parameter("height_darken", 0.8 if is_wall else 0.0)
		return mat
	var fallback := StandardMaterial3D.new()
	var cb: Array = m.get("color_base", [0.18, 0.15, 0.12])
	fallback.albedo_color = Color(cb[0], cb[1], cb[2])
	fallback.roughness = 0.95
	return fallback


func _spawn_entities() -> void:
	var by_kind: Dictionary = {}
	collision_objects.clear()

	for ent: Dictionary in manifest.get("entities", []):
		var kind: String = ent.get("kind", "unknown")
		# Roaming orbs owned by encounter_hud — skip main's render path.
		if kind == "orb":
			continue
		# Creatures always skip MultiMesh — they need per-instance transform
		# updates for flee/scatter behavior. Visual is _spawn_creatures' GLB
		# child or atom fallback (CREATURE_USE_GLB_PATH switches inside).
		if CREATURE_KINDS.has(kind):
			continue
		if not by_kind.has(kind):
			by_kind[kind] = []
		by_kind[kind].append(ent)

	# Per-instance collision is emitted inside _create_multimesh_variant
	# using the actual applied xform — brain's single collision_radius
	# couldn't match Godot's per-instance p_hash XZ variance, leaving mega
	# kinds clip-throughable. See biome_data.py PLAYER_COLLISION_RADII
	# comment for the deferred-refactor history.
	for kind: String in by_kind:
		_create_multimesh_for_kind(kind, by_kind[kind])
	# Initial cull window — player physics reads this instead of the full
	# collision_objects set (spatial cull for perf, see _refresh_nearby_colliders).
	var p0: Vector3 = _player_pos()
	_refresh_nearby_colliders(p0.x, p0.z)
	_spawn_contact_shadows(by_kind)


# Kinds that get dark contact shadow Decals at their base.
# Radius multiplier scales with the kind's visual footprint.
# Contact shadow radius per kind (multiplied by ent.sv at spawn). Values
# roughly match the kind's visual_radius × 1.2 so the shadow hugs the hull
# with a soft fringe. OLD values were 2-3× too big (calibrated when
# visual_radius was under-sized by the AABB projection formula) and
# produced "invisible object casting a shadow" artifacts at middle
# distance where the entity was off-frame or occluded but its shadow
# spilled onto visible ground.
const CONTACT_SHADOW_KINDS := {
	"mega_column":     2.4,   # was 5.0; visual_radius 4.5 → half that + sv scaling
	"column":          1.4,   # was 3.5
	"boulder":         1.0,   # was 2.5
	"stalagmite":      0.7,   # was 1.5
	"giant_fungus":    1.1,   # was 2.0
	"crystal_cluster": 1.4,   # was 1.8
	"dead_log":        1.2,   # was 1.5
	"buttress":        1.5,   # was 2.5
}

var contact_shadow_decals: Array[Decal] = []

func _spawn_contact_shadows(by_kind: Dictionary) -> void:
	# Atmospheric mode: dark radial Decals at entity bases for ambient
	# occlusion / contact shadow grounding.
	# Remove old
	for d: Decal in contact_shadow_decals:
		if is_instance_valid(d):
			d.queue_free()
	contact_shadow_decals.clear()

	# Dark radial Decal at entity base — visually merges object with ground.
	# Uses a dark tint (near-black) so it reads as ambient occlusion / contact shadow.
	var shadow_tint := Color(0.02, 0.02, 0.03)
	var shadow_tex: GradientTexture2D = _get_decal_texture(shadow_tint)

	for kind: String in CONTACT_SHADOW_KINDS:
		if not by_kind.has(kind):
			continue
		var base_radius: float = CONTACT_SHADOW_KINDS[kind]
		for ent: Dictionary in by_kind[kind]:
			# Skip ceiling-attached entities — they don't touch the ground
			if ent.get("attachment_plane", "") == "ceiling":
				continue
			var sv: float = ent.get("sv", 1.0)
			var radius: float = base_radius * sv
			var decal := Decal.new()
			decal.size = Vector3(radius * 2.0, 3.0, radius * 2.0)
			decal.texture_albedo = shadow_tex
			decal.albedo_mix = 0.45   # strong darkening where object meets ground
			decal.emission_energy = 0.0
			decal.modulate = Color(1.0, 1.0, 1.0, 0.6)
			decal.upper_fade = 0.1
			decal.lower_fade = 0.9
			decal.normal_fade = 0.5
			decal.position = Vector3(ent.get("x", 0.0), 0.1, ent.get("y", 0.0))
			add_child(decal)
			contact_shadow_decals.append(decal)


func _create_multimesh_for_kind(kind: String, ents: Array) -> void:
	# Split entities into variant groups based on their seed/position hash
	var by_variant: Dictionary = {}
	for ent: Dictionary in ents:
		var hash_val: float = abs(sin(ent.get("x", 0.0) * 12.9898 + ent.get("y", 0.0) * 78.233))
		var vi: int = int(hash_val * NUM_VARIANTS) % NUM_VARIANTS
		if not by_variant.has(vi):
			by_variant[vi] = []
		by_variant[vi].append(ent)

	for vi: int in by_variant:
		_create_multimesh_variant(kind, by_variant[vi], vi)


func _create_multimesh_variant(kind: String, ents: Array, variant: int) -> void:
	var base_mesh: Mesh = _get_mesh_for_kind(kind, variant)
	# Bounds lookup: prefer the ORIGINAL kind's bounds (for correct sizing),
	# fall back to alias only if the original kind has no entry. This lets
	# mega_column/column use stalagmite mesh geometry at their own native scale
	# (45m / 12m) instead of stalagmite's small scale (4.5m).
	var bounds_key: String = kind if mesh_bounds.has(kind) else MESH_ALIAS.get(kind, kind)
	var bounds: Dictionary = mesh_bounds.get(bounds_key, {})
	var has_real_mesh: bool = bounds.size() > 0 and not (base_mesh is BoxMesh)

	# Real mesh: normalized to max_dim=1.0. To restore original builder size,
	# multiply uniformly by orig_scale. Then per-instance variation from manifest
	# is a small multiplier around 1.0 (the 0.75-1.25 seed variation).
	var orig_scale: float = bounds.get("scale", 1.0)

	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	# CRITICAL: when use_colors is true, MultiMesh routes per-instance color
	# into the shader's COLOR built-in, *replacing* the mesh's COLOR_0 stream.
	# Kinds with use_vertex_colors: true in kind_config want their authored
	# mesh vertex colors to drive rendering, so we must DISABLE use_colors
	# for them. The trade-off is loss of per-instance color jitter on those
	# kinds — acceptable because variant_count handles meaningful variation
	# and the authored palette is the whole point.
	var kind_params_for_mm: Dictionary = _get_kind_params(kind)
	mm.use_colors = not bool(kind_params_for_mm.get("use_vertex_colors", false))
	mm.use_custom_data = true  # Phase 2 — per-instance layer membership
	mm.mesh = base_mesh
	mm.instance_count = ents.size()

	for i in range(ents.size()):
		var ent: Dictionary = ents[i]
		var heading: float = deg_to_rad(ent.get("heading", 0.0))
		var emissive: float = ent.get("emissive", 0.0)
		# Per-instance scale variation (from manifest seed rng, ~0.75-1.25)
		var sv: float = ent.get("sv", 1.0)

		var xform := Transform3D()
		var effective_y_height: float = 1.0  # tracks visible Y extent for burial cap
		var inversion_y_offset: float = 0.0   # compensate for 180° rotation on inverted kinds
		if has_real_mesh:
			# kind_config world_scale_mult lets a kind override the bounds-derived
			# world size without regenerating the GLB. Use for creatures which
			# need to render much bigger than their authored ~0.2m primitive size
			# (rat 4× → waist height; pot/chest 13× → eye level).
			var world_mult: float = float(kind_params_for_mm.get("world_scale_mult", 1.0))
			var base_s: float = orig_scale * sv * world_mult
			var p_hash: float = abs(sin(ent.get("x", 0.0) * 3.17 + ent.get("y", 0.0) * 7.31))
			var p_hash2: float = abs(sin(ent.get("x", 0.0) * 11.9 + ent.get("y", 0.0) * 5.47))
			# Columns use stalagmite mesh via MESH_ALIAS (shared shape language).
			# Per-instance roll: 70% stay upright (standard column = wide-base stalagmite
			# shape = classical column), 30% become STALACTITE VARIANTS hanging from
			# the ceiling (inverted, narrow tip pointing down, wide base at ceiling).
			# Together these create the real eroded-cavern look: stalagmites rising
			# from the floor AND stalactites hanging from above.
			if kind == "mega_column" or kind == "column":
				# Brain is authoritative — spike spatial_class emits
				# attachment_plane per instance (see tile_exchange.py
				# _roll_spike_ceiling). No Godot-side hash fallback: if the
				# field is missing we trust that as intentionally upright.
				var is_stalactite: bool = ent.get("attachment_plane", "") == "ceiling"
				if is_stalactite:
					# Stalactite variant — narrow hanging form, elongated not fat
					var sx_sc: float = base_s * (0.40 + p_hash * 0.25)   # 0.40-0.65
					var sz_sc: float = base_s * (0.40 + p_hash2 * 0.25)
					var sy_sc: float = base_s * (0.55 + p_hash * 0.35)   # 0.55-0.90
					effective_y_height = sy_sc
					xform = Transform3D().scaled(Vector3(sx_sc, sy_sc, sz_sc))
					xform = xform.rotated(Vector3.RIGHT, PI)  # flip 180° around X
					# Ceiling height offset: 15m above ground (was 20m). Lower ceiling
					# puts stalactite base in clearer view at default pitch +10°.
					# After rotation, wide base sits at y=15, narrow tip dangles toward
					# (15 - sy_sc_scaled). Tip clamped to stay ≥ 4m above ground
					# so it doesn't clip player head height (2.5m).
					var mesh_height_world: float = sy_sc
					# Attach to the canonical ceiling plane — stalactites now bind to
					# a real rendered surface resolved from the manifest plane list.
					var tip_min_y: float = 4.0
					var base_y: float = max(active_ceiling_y, tip_min_y + mesh_height_world)
					inversion_y_offset = base_y
				else:
					# Standard column — eroded geological spire, asymmetric.
					# X/Z decoupled so columns read as weathered, not manufactured.
					var sx_col: float = base_s * (0.40 + p_hash * 0.45)   # 0.40-0.85 (wider range)
					var sz_col: float = base_s * (0.40 + p_hash2 * 0.50)  # 0.40-0.90 (asymmetric)
					var sy_col: float = base_s * (1.00 + p_hash * 0.70)   # 1.00-1.70 (height varies more)
					effective_y_height = sy_col
					xform = xform.scaled(Vector3(sx_col, sy_col, sz_col))
			elif kind == "buttress":
				# Buttress: manifest-driven per-axis scale (lean arm proportions)
				var bs_x: float = base_s * ent.get("scale_x", 1.0)
				var bs_y: float = base_s * ent.get("scale_z", 2.5)  # Z brain = Y up Godot
				var bs_z: float = base_s * ent.get("scale_y", 1.0)
				effective_y_height = bs_y
				xform = xform.scaled(Vector3(bs_x, bs_y, bs_z))
			elif kind == "boulder":
				# Boulder: irregular geological mass — some tall, some wide, never spherical.
				# p_hash drives which axis dominates, creating natural variety.
				var stretch_axis: float = p_hash * 3.0  # 0-1: tall, 1-2: wide, 2-3: deep
				var b_x: float = base_s * (0.55 + p_hash * 0.35)     # 0.55-0.90
				var b_y: float = base_s * (0.50 + p_hash2 * 0.55)    # 0.50-1.05
				var b_z: float = base_s * (0.55 + (1.0 - p_hash) * 0.35)
				effective_y_height = b_y
				xform = xform.scaled(Vector3(b_x, b_y, b_z))
			elif kind == "stalagmite":
				# Stalagmite: narrow base variance, heavy height variance
				var sm_xz: float = base_s * (0.80 + p_hash * 0.40)
				var sm_y: float = base_s * (0.75 + p_hash2 * 0.95)   # 0.75-1.70
				effective_y_height = sm_y
				xform = xform.scaled(Vector3(sm_xz, sm_y, sm_xz * (0.9 + p_hash2 * 0.2)))
			elif kind == "rubble":
				# Rubble: always flat, X/Z ratios vary
				var r_x: float = base_s * (0.80 + p_hash * 0.50)
				var r_y: float = base_s * (0.40 + p_hash2 * 0.25)    # always short
				var r_z: float = base_s * (0.70 + p_hash2 * 0.60)
				effective_y_height = r_y
				xform = xform.scaled(Vector3(r_x, r_y, r_z))
			elif kind == "grass_tuft":
				# Grass: aggressive per-axis hash. Height has the widest range
				# (0.60-1.60) so the silhouette breaks hardest. Width stays
				# narrower (0.80-1.30) so the tuft still reads as grass, not
				# shrub. Combined with Y-rotation (below) + wind sway (shader)
				# to kill uniform silhouette repetition at distance.
				var g_xz: float = base_s * (0.80 + p_hash * 0.50)    # 0.80-1.30
				var g_y:  float = base_s * (0.60 + p_hash2 * 1.00)   # 0.60-1.60
				effective_y_height = g_y
				xform = xform.scaled(Vector3(g_xz, g_y, g_xz * (0.85 + p_hash2 * 0.30)))
			elif kind == "giant_fungus":
				# Fungus: radially symmetric cap, so couple XZ (no oval squish).
				# Decouple width from height so we get squat short, tall narrow,
				# average stubby, lanky — all independent via the two hashes.
				# Range narrower than grass — fungus is a big silhouette, too
				# much stretch reads as "broken mushroom" not "natural variety".
				var gf_xz: float = base_s * (0.80 + p_hash * 0.45)    # 0.80-1.25
				var gf_y:  float = base_s * (0.80 + p_hash2 * 0.55)   # 0.80-1.35
				effective_y_height = gf_y
				xform = xform.scaled(Vector3(gf_xz, gf_y, gf_xz))
			elif kind == "monolith":
				# Standing stones: dramatic per-instance silhouette variance.
				# Wide range so even the same variant looks different from
				# its neighbors — no two menhirs in a circle should match.
				# XZ coupled (radially symmetric base), Y independent.
				var mn_xz: float = base_s * (0.70 + p_hash * 0.55)    # 0.70-1.25
				var mn_y:  float = base_s * (0.65 + p_hash2 * 0.85)   # 0.65-1.50
				effective_y_height = mn_y
				xform = xform.scaled(Vector3(mn_xz, mn_y, mn_xz))
			else:
				effective_y_height = base_s
				xform = xform.scaled(Vector3.ONE * base_s)
		else:
			var sx: float = ent.get("sx", 1.0)
			var sy: float = ent.get("sy", 1.0)
			var sz: float = ent.get("sz", 1.0)
			xform = xform.scaled(Vector3(sx, sz, sy))
		# Random rotation for geological kinds, grass, fungus, and the
		# new architectural kinds. Doorframes get full hash rotation so
		# stamps don't all face the same way; monoliths similarly for
		# silhouette variety in distance vistas.
		var final_heading: float = heading
		if kind == "mega_column" or kind == "column" or kind == "boulder" \
				or kind == "stalagmite" or kind == "rubble" or kind == "bone_pile" \
				or kind == "grass_tuft" or kind == "giant_fungus" \
				or kind == "doorframe" or kind == "monolith":
			var rot_hash: float = sin(ent.get("x", 0.0) * 4.73 + ent.get("y", 0.0) * 9.11)
			final_heading = rot_hash * PI
		xform = xform.rotated(Vector3.UP, final_heading)
		# Filament/vine tilt — lean at random angles so they read as organic
		# stalks, not parallel ladder rungs. Hash-driven per position.
		if kind == "filament" or kind == "hanging_vine":
			var tilt_hash: float = sin(ent.get("x", 0.0) * 6.17 + ent.get("y", 0.0) * 11.3)
			var tilt_angle: float = tilt_hash * 0.5  # up to ~28° lean
			var tilt_axis := Vector3(cos(heading), 0.0, sin(heading)).normalized()
			xform = xform.rotated(tilt_axis, tilt_angle)
		# Ceiling-attached emissives — flip upside-down so they hang from above.
		# Same inversion as stalactites but for crystal_cluster, giant_fungus, etc.
		# Columns/mega_columns handle their own inversion above.
		if ent.get("attachment_plane", "") == "ceiling" \
				and kind != "mega_column" and kind != "column":
			xform = xform.rotated(Vector3.RIGHT, PI)
		# Buttress lean — tilt the arm toward the parent column after yaw rotation
		# Heading already points lean direction; tilt local X axis forward
		if kind == "buttress":
			var lean_deg: float = ent.get("lean_angle", 40.0)
			var lean_rad: float = deg_to_rad(lean_deg)
			# Local tilt axis perpendicular to lean direction (heading + 90°)
			var tilt_axis := Vector3(cos(heading + PI * 0.5), 0.0, sin(heading + PI * 0.5))
			xform = xform.rotated(tilt_axis.normalized(), lean_rad)

		# Position: manifest (x, y, z) → Godot (x, z_up, y_forward)
		# Erosion physics: burial config comes from kind_config.json per-kind.
		# Each kind that erodes declares a "burial" block with min_frac/max_frac.
		# Per-instance position hash picks a burial depth in that range →
		# natural bouldering variance (some exposed, some mostly buried).
		var y_offset: float = 0.0 if has_real_mesh else ent.get("sz", 1.0) * 0.5
		var sink: float = 0.0
		if has_real_mesh:
			var bounds_scale: float = bounds.get("scale", 1.0) * sv
			var kind_params: Dictionary = _get_kind_params(kind)
			var burial_cfg: Dictionary = kind_params.get("burial", {})
			if burial_cfg.size() > 0:
				# Config-driven burial — deterministic per-position hash in min-max range
				var burial_hash: float = abs(sin(ent.get("x", 0.0) * 8.31 + ent.get("y", 0.0) * 14.7))
				var min_frac: float = burial_cfg.get("min_frac", 0.15)
				var max_frac: float = burial_cfg.get("max_frac", 0.35)
				var burial_frac: float = min_frac + burial_hash * (max_frac - min_frac)
				var raw_sink: float = bounds_scale * burial_frac
				# BURIAL CAP — visible above-ground height must stay above per-kind
				# minimum from kind_config.json. Prevents stubby-dome silhouettes.
				var min_above_ground: float = burial_cfg.get("min_above_ground", 1.0)
				var max_allowed_sink: float = max(0.3, effective_y_height - min_above_ground)
				sink = -min(raw_sink, max_allowed_sink)
			elif kind == "moss_patch" or kind == "leaf_pile" or kind == "twig_scatter" or kind == "cave_gravel":
				sink = -0.05  # ground cover sinks into floor (not erosion — placement)
		var pos := Vector3(
			ent.get("x", 0.0),
			ent.get("z", 0.0) + y_offset + sink + inversion_y_offset,
			ent.get("y", 0.0)
		)
		xform.origin = pos

		# Per-instance collision — brain emits visual_radius × sv directly
		# in ent.collision_radius (single source of truth: kind_config.
		# physics.visual_radius). No AABB math, no mesh-bounds lookup. One
		# number per kind × per-instance scale. Ceiling-attached skip.
		var brain_r: float = float(ent.get("collision_radius", 0.0))
		var is_ceiling_att: bool = ent.get("attachment_plane", "") == "ceiling"
		if brain_r > 0.0 and not is_ceiling_att:
			# Dict-mirror — creatures still iterate collision_objects for their
			# own manual push-out. Kept alongside the physics body so the
			# rig + creature paths stay independent.
			collision_objects.append({
				"x": ent.get("x", 0.0),
				"z": ent.get("y", 0.0),
				"r": brain_r,
			})
			# Real physics body — CharacterBody3D rig collides against this.
			# Cylinder approximation of the visual silhouette (no trimesh bake;
			# the project has no authored meshes — see plan file for rationale).
			# Height hard-coded to 6m so jumps can't clear mid-size props; future
			# pass may per-kind this from kind_config. Cull far entities for
			# creation cost — Godot's broadphase handles resting bodies fine
			# but spawn churn adds up at 800+.
			var ent_x: float = ent.get("x", 0.0)
			var ent_z: float = ent.get("y", 0.0)
			var _pb: Vector3 = _player_pos()
			var body_dx: float = ent_x - _pb.x
			var body_dz: float = ent_z - _pb.z
			if body_dx * body_dx + body_dz * body_dz < ENTITY_COLLIDER_SPAWN_R * ENTITY_COLLIDER_SPAWN_R:
				var sb := StaticBody3D.new()
				sb.position = Vector3(ent_x, 0.0, ent_z)
				var cs := CollisionShape3D.new()
				var cyl := CylinderShape3D.new()
				cyl.radius = brain_r
				cyl.height = ENTITY_COLLIDER_HEIGHT
				cs.shape = cyl
				cs.position.y = ENTITY_COLLIDER_HEIGHT * 0.5
				sb.add_child(cs)
				entity_colliders_root.add_child(sb)

		mm.set_instance_transform(i, xform)

		# Phase 2 — encode layer membership into custom data (per instance).
		# r=near, g=mid, b=far, a=void. Shader reads via INSTANCE_CUSTOM and
		# applies atmospheric perspective fade (near=crisp, void=nearly invisible).
		var lm: Dictionary = ent.get("layer_membership", {"near": 1.0})
		var custom := Color(
			lm.get("near", 0.0),
			lm.get("mid", 0.0),
			lm.get("far", 0.0),
			lm.get("void", 0.0)
		)
		mm.set_instance_custom_data(i, custom)

		var r: float = ent.get("r", 0.5)
		var g: float = ent.get("g", 0.5)
		var b: float = ent.get("b", 0.5)
		if emissive > 0.0:
			# Emissive kinds get their natural color — light pipes illuminate them.
			# No self-boost. The object is a SURFACE, the pipe is the LIGHT.
			mm.set_instance_color(i, Color(r, g, b))
		else:
			var avg: float = (r + g + b) / 3.0
			if avg > 0.01:
				var tint_r: float = 0.7 + (r / avg) * 0.3
				var tint_g: float = 0.7 + (g / avg) * 0.3
				var tint_b: float = 0.7 + (b / avg) * 0.3
				mm.set_instance_color(i, Color(tint_r, tint_g, tint_b))
			else:
				mm.set_instance_color(i, Color(0.9, 0.9, 0.9))

	# Config-driven material from kind_config.json
	var mat: Material = _create_kind_material(kind)

	# CRITICAL RENDERING SPLIT: MultiMesh with use_colors=true replaces
	# the mesh's per-vertex COLOR_0 stream with per-instance color. Kinds
	# with authored vertex colors (toadstool, boulder, buttress, etc.) lose
	# their entire palette. There's no way around this in Godot 4's MultiMesh.
	#
	# Fix: vertex-color kinds render as individual MeshInstance3D nodes.
	# The MultiMesh was still used above to compute all transforms (burial,
	# per-axis scale, heading, etc.) — we just extract the transforms and
	# create individual meshes instead of one MultiMeshInstance3D. This
	# reuses 100% of the transform logic with zero duplication.
	#
	# Cost: ~25 extra draw calls (~6 buttress + 8 boulder + 6 monolith +
	# 3 spore_pod + 1 toadstool + 1 doorframe) on top of ~55 existing.
	# At 208fps / 7-14× headroom, trivially affordable.
	var node_key: String = "Kind_%s_v%d" % [kind, variant]
	var uses_vertex_colors: bool = bool(kind_params_for_mm.get("use_vertex_colors", false))

	if uses_vertex_colors:
		# Individual MeshInstance3D per entity — vertex colors flow through
		# COLOR naturally without MultiMesh overriding them.
		var parent := Node3D.new()
		parent.name = node_key
		for i in range(mm.instance_count):
			var mi := MeshInstance3D.new()
			mi.mesh = base_mesh
			mi.transform = mm.get_instance_transform(i)
			mi.material_override = mat
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
			parent.add_child(mi)
		add_child(parent)
		kind_nodes[node_key] = parent
	else:
		# Standard MultiMesh path — facet-palette kinds render via instance
		# color + 3-color shader. Efficient batching, no vertex colors needed.
		var mmi := MultiMeshInstance3D.new()
		mmi.multimesh = mm
		mmi.name = node_key
		mmi.material_override = mat
		add_child(mmi)
		kind_nodes[node_key] = mmi


var toast_label: Label
var toast_timer: float = 0.0

func _show_toast(msg: String) -> void:
	if toast_label:
		toast_label.text = msg
		toast_label.modulate.a = 1.0
		toast_timer = 2.0

func _setup_hud() -> void:
	var overlay_cfg: Dictionary = kind_config.get("_global", {}).get("screenshot_overlay", {})
	var font_size: int = overlay_cfg.get("font_size", 24)
	var color_arr: Array = overlay_cfg.get("color", [0.7, 0.65, 0.55, 1.0])
	var text_color := Color(color_arr[0], color_arr[1], color_arr[2], color_arr[3] if color_arr.size() > 3 else 1.0)
	hud_label = Label.new()
	hud_label.name = "HUD"
	hud_label.position = Vector2(12, 8)
	hud_label.add_theme_font_size_override("font_size", font_size)
	hud_label.add_theme_color_override("font_color", text_color)
	toast_label = Label.new()
	toast_label.name = "Toast"
	toast_label.position = Vector2(12, 30)
	toast_label.add_theme_font_size_override("font_size", 16)
	toast_label.add_theme_color_override("font_color", Color(1.0, 0.9, 0.6))
	toast_label.modulate.a = 0.0
	var canvas := CanvasLayer.new()
	canvas.add_child(hud_label)
	canvas.add_child(toast_label)
	add_child(canvas)
	_update_hud()


func _update_hud() -> void:
	var overlay_cfg: Dictionary = kind_config.get("_global", {}).get("screenshot_overlay", {})
	if not overlay_cfg.get("enabled", true):
		hud_label.text = ""
		return
	var p: Vector3 = _player_pos()
	var cx: float = snapped(p.x, 0.1)
	var cy: float = snapped(p.z, 0.1)
	var ch: float = snapped(rad_to_deg(_player_yaw()), 0.1)
	var tension_st: String = manifest.get("tension_state", "?")
	var vis: int = manifest.get("entities", []).size()
	hud_label.text = _build_overlay_line(overlay_cfg, cx, cy, ch, tension_st, vis)


# Snapshot of Godot's Performance singleton — used by both the HUD overlay
# and the tag telemetry sidecar. Read once per caller to keep the values
# coherent across all consumers in the same frame.
func _read_perf() -> Dictionary:
	return {
		"fps":          int(Engine.get_frames_per_second()),
		"frame_ms":     snapped(Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0, 0.01),
		"physics_ms":   snapped(Performance.get_monitor(Performance.TIME_PHYSICS_PROCESS) * 1000.0, 0.01),
		"draw_calls":   int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)),
		"objects":      int(Performance.get_monitor(Performance.RENDER_TOTAL_OBJECTS_IN_FRAME)),
		"primitives":   int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)),
		"static_mem_mb": snapped(Performance.get_monitor(Performance.MEMORY_STATIC) / (1024.0 * 1024.0), 0.1),
	}


# -- Brain server connection ---------------------------------------------------

func _connect_to_brain() -> void:
	tcp = StreamPeerTCP.new()
	tcp.connect_to_host(SERVER_HOST, SERVER_PORT)
	print("Connecting to brain server %s:%d..." % [SERVER_HOST, SERVER_PORT])


func _process(delta: float) -> void:
	# Toast fade
	if toast_timer > 0.0:
		toast_timer -= delta
		if toast_timer <= 0.0 and toast_label:
			toast_label.modulate.a = 0.0
		elif toast_timer < 0.5 and toast_label:
			toast_label.modulate.a = toast_timer / 0.5

	# Poll TCP connection
	if tcp:
		tcp.poll()
		var status := tcp.get_status()

		if status == StreamPeerTCP.STATUS_CONNECTED:
			if not connected:
				connected = true
				print("Connected to brain server!")
				_update_hud()

			# Send camera position periodically
			update_timer += delta
			if update_timer >= UPDATE_INTERVAL:
				update_timer = 0.0
				_send_camera()

			# Read responses
			var available := tcp.get_available_bytes()
			if available > 0:
				var data := tcp.get_data(available)
				if data[0] == OK:
					buf += data[1].get_string_from_utf8()
					_process_responses()

		elif status == StreamPeerTCP.STATUS_ERROR:
			if connected:
				print("Lost connection to brain server")
				connected = false
				_update_hud()
			# Retry
			tcp = StreamPeerTCP.new()
			tcp.connect_to_host(SERVER_HOST, SERVER_PORT)

		elif status == StreamPeerTCP.STATUS_CONNECTING:
			pass  # waiting

	# Expedition proximity + visuals — only after first manifest arrived
	if connected and expedition_active:
		_check_expedition_proximity()
		_update_expedition_visuals(delta)

	# Future atmospheric layers go here (light sheet, dust motes, etc.)
	# Added one at a time after confirming the breathing headlamp reads right.


func _send_camera() -> void:
	if not connected:
		return
	# Camera position: Godot (x, y_up, z) → manifest (x, z_forward, y_up)
	var p: Vector3 = _player_pos()
	var msg := {
		"cam_x": p.x,
		"cam_y": p.z,   # Godot Z → manifest Y
		"cam_z": p.y,   # Godot Y → manifest Z
		"heading": rad_to_deg(_player_yaw()),
		"pitch": rad_to_deg(_player_pitch()),
		"dt": UPDATE_INTERVAL,
	}
	var json_str := JSON.stringify(msg) + "\n"
	tcp.put_data(json_str.to_utf8_buffer())


func _process_responses() -> void:
	while buf.find("\n") >= 0:
		var idx := buf.find("\n")
		var line := buf.substr(0, idx)
		buf = buf.substr(idx + 1)

		if line.strip_edges().is_empty():
			continue

		var jp := JSON.new()
		if jp.parse(line) != OK:
			continue
		var data: Dictionary = jp.data

		if data.get("unchanged", false):
			continue

		# Deposit intent / walk-through ack — these arrive out of band
		# (not a manifest) so handle them before the full-manifest
		# branch. They carry their own top-level keys.
		if data.has("deposit_result"):
			_on_deposit_result(data["deposit_result"])
			continue
		if data.has("resolution"):
			_on_expedition_resolution(data)
			continue

		# Encounter acks — single-key payloads from brain, routed to HUD.
		if data.has("encounter_action"):
			if encounter_hud:
				encounter_hud.on_action_ack(data["encounter_action"])
			continue
		if data.has("encounter_portal"):
			continue
		if data.has("encounter_consolidate"):
			continue
		if data.has("encounter_error"):
			print("encounter_error: ", data["encounter_error"])
			continue

		# Full manifest update — brain sent new data, rebuild entities.
		# The brain handles dirty detection via "unchanged" flag above.
		# If we got here, the scene HAS changed — always rebuild.
		manifest = data
		_rebuild_entities()
		_update_atmosphere()
		_update_hud()
		# Forward encounter snapshot + orb entities to the HUD module.
		if encounter_hud:
			encounter_hud.update_snapshot(manifest.get("encounter", {}))
			encounter_hud.sync_orb_entities(manifest.get("entities", []))
		_on_expedition_manifest_field(data.get("expedition", {}))
		# Elemental reactions — brain emits reaction_events when a cast
		# lands near an entity whose kind_config.elemental_reactions maps
		# the element to a pattern. Godot paints the visual; brain never
		# renders. One-shot per event — not persistent state.
		var reaction_events: Array = data.get("reaction_events", [])
		for r: Dictionary in reaction_events:
			_apply_reaction_event(r)


func _rebuild_entities() -> void:
	# Incremental: only rebuild kinds whose entity lists changed
	var new_by_kind: Dictionary = {}
	collision_objects.clear()
	# Free all per-instance physics bodies so _create_multimesh_variant can
	# re-emit a clean set. Queue-free is fine — Godot finishes the frees at
	# end-of-frame before next _physics_process reads the set.
	if is_instance_valid(entity_colliders_root):
		for c in entity_colliders_root.get_children():
			c.queue_free()

	var silhouette_ents: Array = []  # render_mode silhouette/hint → banner projection
	for ent: Dictionary in manifest.get("entities", []):
		var kind: String = ent.get("kind", "unknown")
		# Roaming orbs owned by encounter_hud — skip main's render path.
		if kind == "orb":
			continue
		# Creatures always skip MultiMesh — handled by _spawn_creatures.
		if CREATURE_KINDS.has(kind):
			continue
		# Shadow-lab fixtures skip MultiMesh — handled by _spawn_shadow_orbs.
		# Each fixture gets an individual Node3D so its Decal child can
		# animate/vary per entity.
		if SHADOW_ORB_KINDS.has(kind):
			continue
		var render_mode: String = ent.get("render_mode", "geometry")

		# Non-geometry entities skip MultiMesh — they project onto banner cylinders
		if render_mode == "silhouette" or render_mode == "hint":
			silhouette_ents.append(ent)
			continue

		if not new_by_kind.has(kind):
			new_by_kind[kind] = []
		new_by_kind[kind].append(ent)
		# Collision emission moved to _create_multimesh_variant — per-instance
		# xform gives accurate radius for mega kinds (mirrors _spawn_entities).

	# Remove kinds no longer present
	var old_kinds := kind_nodes.keys()
	for kind: String in old_kinds:
		if not new_by_kind.has(kind):
			if is_instance_valid(kind_nodes[kind]):
				kind_nodes[kind].queue_free()
			kind_nodes.erase(kind)

	# Always rebuild — brain gates updates via "unchanged" flag,
	# so if we're here the manifest HAS changed. Count comparison
	# masked tile transitions (same count, different positions).
	for kind: String in new_by_kind:
		var ents: Array = new_by_kind[kind]
		if kind_nodes.has(kind) and is_instance_valid(kind_nodes[kind]):
			kind_nodes[kind].queue_free()
		_create_multimesh_for_kind(kind, ents)

	# Collision set just changed; refresh the spatial-cull window around
	# the current camera position so player physics reads the new set.
	var p_rb: Vector3 = _player_pos()
	_refresh_nearby_colliders(p_rb.x, p_rb.z)

	# Stone density texture — refresh from current entity positions
	# and push to all ground plane materials so the ground shader can
	# cluster light marks where stones are likely to occur.
	_build_stone_density_texture(new_by_kind)

	# Silhouette shell — flat dark instances on outer shells.
	# These are cheap: no grain, no normal, no decal, no mote.
	# Just dark shapes at distance for spatial reading.
	_rebuild_silhouettes(silhouette_ents)

	# Contact shadow Decals — grounding for geometry entities only
	_spawn_contact_shadows(new_by_kind)

	# Motes: only rebuild when scene actually changes.
	# Check entity count + tension state as dirty triggers.
	var ent_count: int = manifest.get("entities", []).size()
	var t_state: String = manifest.get("tension_state", "open")
	if ent_count != last_entity_count or t_state != last_tension_state:
		mote_dirty = true
	# Creatures spawn independently — don't gate on mote_dirty.
	_spawn_creatures()
	# Shadow-lab fixtures (decal_projector sandbox). Same diff-by-id pattern
	# as creatures so the lab doesn't flicker on each manifest tick.
	_spawn_shadow_orbs()
	if mote_dirty:
		_update_motes()
		mote_dirty = false
		last_entity_count = ent_count
		last_tension_state = t_state


func _build_stone_density_texture(by_kind: Dictionary) -> void:
	# Splat each stone-class entity into a small density grid centered on
	# the player. The ground shader samples this texture and uses it to
	# bias mark polarity (light marks cluster where density is high).
	# Per-rebuild cost: ~3000 entities × 9 pixel writes = ~27k buffer ops,
	# trivially fast since we use PackedByteArray indexing instead of
	# Image.set_pixel.
	stone_density_buffer.resize(DENSITY_TEX_SIZE * DENSITY_TEX_SIZE)
	for i in range(stone_density_buffer.size()):
		stone_density_buffer[i] = 0

	# Center the texture on the player. Brain x/y → Godot x/z.
	var cam_pos: Vector3 = camera.global_position if camera else Vector3.ZERO
	stone_density_origin = Vector2(cam_pos.x, cam_pos.z)

	var pixels_per_meter: float = float(DENSITY_TEX_SIZE) / (DENSITY_WORLD_RADIUS * 2.0)

	for kind: String in by_kind:
		if not STONE_KINDS_FOR_DENSITY.has(kind):
			continue
		for ent: Dictionary in by_kind[kind]:
			# Brain coordinates: ent.x is world X, ent.y is world Z (depth).
			var rel_x: float = float(ent.get("x", 0.0)) - stone_density_origin.x
			var rel_z: float = float(ent.get("y", 0.0)) - stone_density_origin.y
			if abs(rel_x) > DENSITY_WORLD_RADIUS or abs(rel_z) > DENSITY_WORLD_RADIUS:
				continue
			var nx: float = (rel_x + DENSITY_WORLD_RADIUS) * pixels_per_meter
			var nz: float = (rel_z + DENSITY_WORLD_RADIUS) * pixels_per_meter
			var px: int = int(nx)
			var pz: int = int(nz)
			# Splat 3x3 with center weighted heavier — accumulate up to 255
			for dx in range(-1, 2):
				for dz in range(-1, 2):
					var tx: int = px + dx
					var tz: int = pz + dz
					if tx < 0 or tz < 0 or tx >= DENSITY_TEX_SIZE or tz >= DENSITY_TEX_SIZE:
						continue
					var idx: int = tz * DENSITY_TEX_SIZE + tx
					var add: int = 80 if (dx == 0 and dz == 0) else 35
					var existing: int = stone_density_buffer[idx]
					stone_density_buffer[idx] = min(255, existing + add)

	# Build/update the ImageTexture
	var img := Image.create_from_data(
		DENSITY_TEX_SIZE, DENSITY_TEX_SIZE, false,
		Image.FORMAT_R8, stone_density_buffer
	)
	if stone_density_tex == null:
		stone_density_tex = ImageTexture.create_from_image(img)
	else:
		stone_density_tex.update(img)

	# Push to all ground-plane materials. Ceiling and walls are skipped
	# because their materials don't sample the density texture.
	for tag: String in plane_nodes:
		var entry: Dictionary = plane_nodes[tag]
		if entry.get("kind", "") != "ground":
			continue
		var node = entry.get("node")
		if node == null or not is_instance_valid(node):
			continue
		if node.mesh == null:
			continue
		var mat: Material = node.mesh.surface_get_material(0)
		if mat == null:
			mat = node.material_override
		if mat is ShaderMaterial:
			var smat: ShaderMaterial = mat
			smat.set_shader_parameter("stone_density_tex", stone_density_tex)
			smat.set_shader_parameter("stone_density_origin", stone_density_origin)
			smat.set_shader_parameter("stone_density_radius", DENSITY_WORLD_RADIUS)
			smat.set_shader_parameter("stone_density_enabled", true)


var silhouette_nodes: Dictionary = {}  # kind → MultiMeshInstance3D for silhouette shell

func _rebuild_silhouettes(sil_ents: Array) -> void:
	"""Rebuild silhouette-mode entities as flat dark shapes.

	No grain, no normal, no decals, no motes. Just the mesh in flat dark color
	so structural forms read as silhouettes at mid-distance. Cheaper than full
	geometry: unshaded material, no per-instance effects.
	"""
	# Group by kind
	var by_kind: Dictionary = {}
	for ent: Dictionary in sil_ents:
		var kind: String = ent.get("kind", "unknown")
		if not by_kind.has(kind):
			by_kind[kind] = []
		by_kind[kind].append(ent)

	# Remove old silhouette nodes for kinds no longer present
	for kind: String in silhouette_nodes.keys():
		if not by_kind.has(kind):
			if is_instance_valid(silhouette_nodes[kind]):
				silhouette_nodes[kind].queue_free()
			silhouette_nodes.erase(kind)

	for kind: String in by_kind:
		var ents: Array = by_kind[kind]
		# Check if rebuild needed (count changed)
		if silhouette_nodes.has(kind) and is_instance_valid(silhouette_nodes[kind]):
			var old_mm: MultiMesh = silhouette_nodes[kind].multimesh
			if old_mm and old_mm.instance_count == ents.size():
				continue  # same count, skip
			silhouette_nodes[kind].queue_free()

		var base_mesh: Mesh = _get_mesh_for_kind(kind, 0)
		var bounds_key: String = kind if mesh_bounds.has(kind) else MESH_ALIAS.get(kind, kind)
		var bounds: Dictionary = mesh_bounds.get(bounds_key, {})
		var orig_scale: float = bounds.get("scale", 1.0)

		var mm := MultiMesh.new()
		mm.transform_format = MultiMesh.TRANSFORM_3D
		mm.use_colors = true
		mm.mesh = base_mesh
		mm.instance_count = ents.size()

		for i in range(ents.size()):
			var ent: Dictionary = ents[i]
			var sv: float = ent.get("sv", 1.0)
			var base_s: float = orig_scale * sv
			var heading: float = deg_to_rad(ent.get("heading", 0.0))
			var xform := Transform3D()
			xform = xform.scaled(Vector3(base_s, base_s, base_s))
			xform = xform.rotated(Vector3.UP, heading)
			var ez: float = ent.get("z", 0.0)
			var is_ceil: bool = ent.get("attachment_plane", "") == "ceiling"
			if is_ceil:
				xform = xform.rotated(Vector3.RIGHT, PI)
				ez += base_s * 0.5
			xform.origin = Vector3(ent.get("x", 0.0), ez, ent.get("y", 0.0))
			mm.set_instance_transform(i, xform)
			# Dark mass color — visible against fog but darker than lit geometry.
			# Must read as a solid shape, not disappear into the background.
			var render_mode: String = ent.get("render_mode", "silhouette")
			var brightness: float = 0.12 if render_mode == "silhouette" else 0.06
			mm.set_instance_color(i, Color(brightness, brightness * 0.9, brightness * 0.85))

		# Flat unshaded material — cheapest possible rendering.
		# vertex_color_use_as_albedo makes instance COLOR the actual surface brightness.
		var mat := StandardMaterial3D.new()
		mat.albedo_color = Color(1.0, 1.0, 1.0)
		mat.vertex_color_use_as_albedo = true
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		mat.cull_mode = BaseMaterial3D.CULL_BACK
		mat.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF

		var mi := MultiMeshInstance3D.new()
		mi.multimesh = mm
		mi.material_override = mat
		mi.name = "Sil_%s" % kind
		mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(mi)
		silhouette_nodes[kind] = mi


func _update_atmosphere() -> void:
	if not godot_env:
		return

	var fog: Dictionary = manifest.get("fog", {})
	var fc: Array = fog.get("color", [0.1, 0.1, 0.1])
	var fog_far: float = fog.get("far", 55.0)
	# Distant fog band tracks manifest color
	godot_env.fog_light_color = Color(fc[0], fc[1], fc[2])
	godot_env.fog_density = 0.8 / max(fog_far, 1.0)
	# Test: disable fog entirely to confirm per-fragment fog attenuation
	# is what kills surface flatness. Sable-style refs have NO atmospheric
	# gradient — distant geometry just hard-cuts to sky. Flip back true
	# after comparison.
	godot_env.fog_enabled = false

	var amb: Array = manifest.get("ambient", [0.3, 0.22, 0.15])
	godot_env.ambient_light_color = Color(amb[0], amb[1], amb[2])
	# Base visibility — every object shows texture, lights add character
	godot_env.ambient_light_energy = 0.40

	# Chronometer modulation — subtle, never fight the cavern's ambient floor
	var chrono: Dictionary = manifest.get("chronometer", {})
	var night_w: float = chrono.get("night_weight", 0.0)
	# Night: barely perceptible dim from the ambient floor
	godot_env.ambient_light_energy = 0.12 - night_w * 0.01

	# Tension visual effects — PARKED. System proven as PoC, but modulating
	# bloom/fog/saturation/FOV fights the baseline rendering we're stabilizing.
	# Re-enable when game engine state changes are wired in. Until then, fixed baseline.
	# (Tension state still tracked in manifest for telemetry/tags — just no visual effect.)
	camera.fov = lerpf(camera.fov, 62.0, 0.05)  # was 52 — ghost delta regression
	camera.rotation_degrees.z = lerpf(camera.rotation_degrees.z, 0.0, 0.1)

	# Update camera far clip
	camera.far = fog_far * 1.5


# -- Creatures (scurry/crawl behavior) -----------------------------------------

# Baseline scope for creature visibility. Magic-show trick: render every
# creature as ONE fat emissive heptagon at a known size. Reads as "thing
# here" from any distance. Backwards compatible — CREATURE_KINDS still
# holds per-kind arrangement/mote_size; the baseline overrides them at
# spawn when CREATURE_BASELINE_DEBUG is true. Flip false to restore
# meta-pixel arrangements.
# Render path toggle. The orb pipeline (_spawn_creatures + _update_creatures)
# always runs — it owns BEHAVIOR (flee, scatter, debris). Per-creature visual
# is swappable:
#   true  = each creature loads the per-kind GLB as its child (proper voxel
#           rat/pot/chest visuals, behavior intact)
#   false = atom-orb visual fallback (debug fixture, single-color spheres)
# MultiMesh path is bypassed either way — creatures need per-instance
# transform updates that MultiMesh can't deliver per frame.
const CREATURE_USE_GLB_PATH: bool = true
const CREATURE_BASELINE_DEBUG: bool = false  # off: use real per-kind arrangements
const CREATURE_BASELINE_ARRANGEMENT: String = "solo"
const CREATURE_BASELINE_MOTE_SIZE: float = 0.5  # ~50cm orb — cat-sized creature
# mote_arrangements.gd offsets were authored for ~5cm motes. With orbs at
# 50cm we need to spread them apart so atoms read as a CLUSTER not a blob.
# 8.0 = roughly proportional. Drop for tighter clumps, raise for spread shatter.
const CREATURE_ARRANGEMENT_SCALE: float = 8.0
# Vertical clearance above the entity's ground z. ORB visuals need lift
# because the spheres are waist-height MARKERS (no ground geometry of
# their own). GLB visuals have ground-relative geometry built in, so they
# sit at z=0 — hover of 0 puts feet on the floor.
const CREATURE_ORB_HOVER_M: float = 1.2  # orbs float at waist for visibility
const CREATURE_GLB_HOVER_M: float = 0.0  # GLB seated on ground at entity z
# Legacy alias — used by the test bounds. Renamed in main.gd usage to
# the per-path constant. Keep until test is updated to assert both.
const CREATURE_BASELINE_HOVER_M: float = 1.2
# Emission multiplier — 3.0 = ambient register (creature reads as creature,
# not as beacon). Raise to 8.0 for unmissable tension/encounter mode.
const CREATURE_BASELINE_EMISSION: float = 3.0
# no_depth_test false = atoms occlude correctly behind walls. Flip true
# only when debugging visibility (magic-show fallback).
const CREATURE_BASELINE_NO_DEPTH: bool = false
# Proximity (meters) at which destructible creatures shatter. 2.0 = player
# bumps into them. Drop to 0.5 for "must touch" feel, raise for area effect.
const CREATURE_DESTRUCT_RADIUS_M: float = 2.0
# Alpha fade rate for debris atoms after shatter. 0.3 = ~3sec fade.
# Set 0.0 to keep debris on the ground permanently (path-memory scars).
# Set 1.0 to clear quickly.
const CREATURE_DEBRIS_FADE_RATE: float = 0.0
# When debris fully fades, free the parent? false = keep tombstone (scarred
# ground stays). true = clean up. Pairs with CREATURE_DEBRIS_FADE_RATE.
const CREATURE_DEBRIS_FREE_PARENT: bool = false

# Phase 5: CREATURE_KINDS derives entirely from kind_config.json behavior
# blocks. Single source of truth. If a creature is missing a behavior block
# in kind_config it silently won't be in CREATURE_KINDS — add it there.
var CREATURE_KINDS: Dictionary = {}

# Shadow-lab fixtures: kinds whose render path is "orb + decal_projector".
# Skipped by the MultiMesh path so their individual Decal children can
# animate/vary per entity. Derived dynamically in _load_shadow_orb_kinds.
var SHADOW_ORB_KINDS: Dictionary = {}
var shadow_orb_nodes: Array[Dictionary] = []  # {node, id, kind}


func _load_creature_kinds() -> void:
	# Walk kind_config.kinds and harvest any kind with class=life AND a
	# behavior block. Convert mote_color array -> Godot Color for ergonomics.
	CREATURE_KINDS.clear()
	var cfg_kinds: Dictionary = kind_config.get("kinds", {})
	for kname: String in cfg_kinds:
		var k: Dictionary = cfg_kinds[kname]
		if k.get("class", "") != "life":
			continue
		var b: Dictionary = k.get("behavior", {})
		if b.is_empty():
			continue
		var entry: Dictionary = b.duplicate()
		var mc = entry.get("mote_color")
		if mc is Array and mc.size() >= 3:
			entry["mote_color"] = Color(float(mc[0]), float(mc[1]), float(mc[2]))
		CREATURE_KINDS[kname] = entry
	print("Creature kinds: %d loaded from kind_config" % CREATURE_KINDS.size())
	_load_shadow_orb_kinds()


func _load_shadow_orb_kinds() -> void:
	# Any kind with a decal_projector block becomes a shadow-lab fixture,
	# routed to _spawn_shadow_orbs instead of MultiMesh. Keeps the primitive
	# reusable — any future kind can opt in just by adding the block.
	SHADOW_ORB_KINDS.clear()
	var cfg_kinds: Dictionary = kind_config.get("kinds", {})
	for kname: String in cfg_kinds:
		var k: Dictionary = cfg_kinds[kname]
		if k.has("decal_projector"):
			SHADOW_ORB_KINDS[kname] = k["decal_projector"]
	print("Shadow-orb kinds: %d loaded from kind_config" % SHADOW_ORB_KINDS.size())


# --- Shadow-orb sandbox ------------------------------------------------------
# decal_projector is the composition primitive: a source point + one or more
# silhouette decals projected along a config vector onto the nearest surface.
# This entry-point spawns the orb (visible source), attaches Decal children
# per layer, and applies the multiplier (prism fan). Kept simple on purpose —
# the point of the sandbox is to see the effect, then iterate knobs from
# config alone without touching this function.
const SHADOW_ORB_BASE_RADIUS: float = 0.2   # Visual sphere radius. Scaled by ent.sv.


func _shadow_orb_id(kind: String, x: float, y: float) -> String:
	return "shadow_orb|%s|%.2f|%.2f" % [kind, x, y]


func _attach_decal_projector(host: Node3D, cfg: Dictionary) -> Array:
	# Universal: attach decal layers to any Node3D. Shadow orbs, creatures,
	# anything with a decal_projector block in kind_config.
	# Returns the Decal nodes created so callers can animate or track them.
	var decals: Array = []
	var layers: Array = cfg.get("layers", [])
	var proj: Dictionary = cfg.get("projection", {})
	var mult: Dictionary = cfg.get("multiplier", {})
	var max_dist: float = float(proj.get("max_distance", 6.0))
	var fan_count: int = int(mult.get("fan", 1))
	var spread_deg: float = float(mult.get("spread_deg", 0.0))

	for layer: Dictionary in layers:
		var tint_arr: Array = layer.get("tint", [0.02, 0.02, 0.03])
		var tint := Color(float(tint_arr[0]), float(tint_arr[1]),
			float(tint_arr[2]))
		var decal_size: float = float(layer.get("size", 1.6))
		for i in range(fan_count):
			var decal := Decal.new()
			decal.texture_albedo = _get_decal_texture(tint)
			decal.size = Vector3(decal_size, max_dist, decal_size)
			decal.position = Vector3(0.0, -max_dist * 0.5, 0.0)
			if fan_count > 1 and spread_deg != 0.0:
				var tilt_deg: float = spread_deg * 0.5
				var yaw_deg: float = 360.0 * float(i) / float(fan_count)
				decal.rotate_object_local(Vector3.UP, deg_to_rad(yaw_deg))
				decal.rotate_object_local(Vector3.RIGHT,
					deg_to_rad(tilt_deg))
			decal.albedo_mix = 1.0
			decal.emission_energy = 0.0
			host.add_child(decal)
			decals.append(decal)
	return decals


# --- Reaction pulse fallbacks ------------------------------------------------
# Pattern body lives in kind_config._global.reaction_patterns (config-as-code).
# These constants are defaults used when the pattern doesn't specify. Move
# to per-pattern config when a new pattern needs different values.
const REACTION_PULSE_RADIUS_M: float = 0.25   # spawn sphere radius
const REACTION_PULSE_HEIGHT_M: float = 1.5    # waist-height offset from floor
const REACTION_PULSE_SCALE_PEAK: float = 4.0  # tween scale multiplier at end
const REACTION_PULSE_PEAK_ENERGY_DEFAULT: float = 3.0
const REACTION_PULSE_DURATION_DEFAULT: float = 1.0


func _apply_reaction_event(r: Dictionary) -> void:
	# Spawn a short-lived emissive sphere at the reaction target. Visual
	# only — brain already decided which entity reacts and which pattern
	# applies. Pattern body lives in kind_config._global.reaction_patterns,
	# so adding a new reaction is pure config.
	var pattern_id: String = r.get("pattern", "")
	var patterns: Dictionary = kind_config.get("_global", {}) \
		.get("reaction_patterns", {})
	var pattern: Dictionary = patterns.get(pattern_id, {})
	if pattern.is_empty():
		return
	var tint_arr: Array = pattern.get("color_tint", [1.0, 1.0, 1.0])
	var tint := Color(float(tint_arr[0]), float(tint_arr[1]),
		float(tint_arr[2]))
	var peak_energy: float = float(pattern.get("peak_energy",
		REACTION_PULSE_PEAK_ENERGY_DEFAULT))
	var duration: float = float(pattern.get("duration",
		REACTION_PULSE_DURATION_DEFAULT))
	var spawn_radius: float = float(pattern.get("spawn_radius",
		REACTION_PULSE_RADIUS_M))
	var height_offset: float = float(pattern.get("height_offset",
		REACTION_PULSE_HEIGHT_M))
	var scale_peak: float = float(pattern.get("scale_peak",
		REACTION_PULSE_SCALE_PEAK))
	# Brain coords: x,y are world XZ. Raise to waist so the pulse reads at
	# eye-level regardless of entity scale; per-pattern height_offset
	# overrides for ceiling/ground-hugging reactions.
	var pos := Vector3(float(r.get("x", 0.0)), height_offset,
		float(r.get("y", 0.0)))

	var pulse := MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = spawn_radius
	sphere.height = spawn_radius * 2.0
	pulse.mesh = sphere
	var mat := StandardMaterial3D.new()
	mat.albedo_color = tint
	mat.emission_enabled = true
	mat.emission = tint
	mat.emission_energy_multiplier = peak_energy
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	pulse.set_surface_override_material(0, mat)
	pulse.position = pos
	add_child(pulse)

	# Tween: grow + fade over duration.
	var tw := create_tween()
	tw.set_parallel(true)
	tw.tween_property(pulse, "scale", Vector3.ONE * scale_peak, duration)
	tw.tween_property(mat, "albedo_color:a", 0.0, duration)
	tw.tween_property(mat, "emission_energy_multiplier", 0.0, duration)
	tw.chain().tween_callback(pulse.queue_free)

	print("REACTION: kind=%s element=%s pattern=%s at (%s,%s)" % [
		r.get("kind", ""), r.get("element", ""), pattern_id,
		str(r.get("x", 0)), str(r.get("y", 0))])


func _hide_mesh_children(node: Node) -> void:
	# Recursively hide MeshInstance3D descendants. Used when a kind's
	# decal_projector carries hide_source=true — the source geometry is
	# replaced entirely by its projected silhouette.
	for child in node.get_children():
		if child is MeshInstance3D:
			(child as MeshInstance3D).visible = false
		if child.get_child_count() > 0:
			_hide_mesh_children(child)


func _spawn_shadow_orbs() -> void:
	# Diff by stable id like _spawn_creatures so the lab doesn't flicker.
	var manifest_ids: Dictionary = {}  # id -> ent dict
	for ent: Dictionary in manifest.get("entities", []):
		var k: String = ent.get("kind", "")
		if not SHADOW_ORB_KINDS.has(k):
			continue
		var sid: String = _shadow_orb_id(k, ent.get("x", 0.0), ent.get("y", 0.0))
		manifest_ids[sid] = ent

	# Free shadow orbs no longer in manifest
	var kept: Array[Dictionary] = []
	for s: Dictionary in shadow_orb_nodes:
		if manifest_ids.has(s.get("id", "")):
			kept.append(s)
			manifest_ids.erase(s["id"])
		else:
			if is_instance_valid(s["node"]):
				s["node"].queue_free()
	shadow_orb_nodes = kept

	# Spawn new ones
	for sid: String in manifest_ids:
		var ent: Dictionary = manifest_ids[sid]
		var kind: String = ent.get("kind", "")
		var cfg: Dictionary = SHADOW_ORB_KINDS[kind]
		var altitude: float = float(cfg.get("altitude", 2.0))

		var parent := Node3D.new()
		parent.name = "ShadowOrb_%s_%d" % [kind, shadow_orb_nodes.size()]
		parent.position = Vector3(
			float(ent.get("x", 0.0)),
			float(ent.get("z", 0.0)) + altitude,
			float(ent.get("y", 0.0)))

		# Visible source sphere (emissive white by default, ent color tint)
		var sphere_inst := MeshInstance3D.new()
		var sphere := SphereMesh.new()
		var sv: float = float(ent.get("sv", 1.0))
		sphere.radius = SHADOW_ORB_BASE_RADIUS * sv
		sphere.height = SHADOW_ORB_BASE_RADIUS * 2.0 * sv
		sphere_inst.mesh = sphere
		var mat := StandardMaterial3D.new()
		mat.albedo_color = Color(
			float(ent.get("r", 1.0)),
			float(ent.get("g", 1.0)),
			float(ent.get("b", 1.0)))
		mat.emission_enabled = true
		mat.emission = mat.albedo_color
		mat.emission_energy_multiplier = 2.0
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		sphere_inst.set_surface_override_material(0, mat)
		parent.add_child(sphere_inst)

		# Attach decal layer(s) per config via the universal helper.
		_attach_decal_projector(parent, cfg)

		add_child(parent)
		# Capture base position + drift params so _update_shadow_orbs can
		# animate the parent each frame. Drift = [amp_x, amp_z, period_sec];
		# zero period disables motion for that orb.
		var anim: Dictionary = cfg.get("animation", {})
		var drift: Array = anim.get("drift", [0.0, 0.0, 0.0])
		var phase_offset: float = fposmod(float(ent.get("x", 0.0)) * 0.17
			+ float(ent.get("y", 0.0)) * 0.23, TAU)
		shadow_orb_nodes.append({
			"node": parent,
			"id": sid,
			"kind": kind,
			"base_pos": parent.position,
			"drift_amp_x": float(drift[0]) if drift.size() > 0 else 0.0,
			"drift_amp_z": float(drift[1]) if drift.size() > 1 else 0.0,
			"drift_period": float(drift[2]) if drift.size() > 2 else 0.0,
			"phase_offset": phase_offset,
		})
		print("SHADOW_ORB SPAWN: %s at (%s, %s) alt=%s drift=%s" % [
			kind, str(ent.get("x", 0)), str(ent.get("y", 0)),
			str(altitude), str(drift)])


func _update_shadow_orbs(delta: float) -> void:
	# Horizontal elliptical drift: x = base + amp_x*sin(2πt/period + phase),
	# z = base + amp_z*cos(...). Decals are children of the parent Node3D,
	# so they track the source for free — this IS the in-motion test.
	if shadow_orb_nodes.is_empty():
		return
	var t: float = Time.get_ticks_msec() / 1000.0
	for s: Dictionary in shadow_orb_nodes:
		var period: float = s.get("drift_period", 0.0)
		if period <= 0.0:
			continue
		if not is_instance_valid(s["node"]):
			continue
		var angle: float = (t / period) * TAU + s["phase_offset"]
		var base_pos: Vector3 = s["base_pos"]
		var amp_x: float = s["drift_amp_x"]
		var amp_z: float = s["drift_amp_z"]
		s["node"].position = Vector3(
			base_pos.x + amp_x * sin(angle),
			base_pos.y,
			base_pos.z + amp_z * cos(angle))


var creature_nodes: Array[Dictionary] = []  # {node, home_x, home_z, kind, fleeing}

func _creature_id(kind: String, x: float, y: float) -> String:
	# Identity = kind + home position. Brain ships the same creature with
	# the same anchor coords across manifest updates, so this is stable.
	# Two creatures of the same kind at the same home will collapse into
	# one (intentional — they ARE the same anchor stamp instance).
	return "%s|%.2f|%.2f" % [kind, x, y]


func _spawn_creatures() -> void:
	# Diff manifest creatures against existing nodes by stable id. Keep
	# matching ones (preserves flee/scatter state across manifest updates).
	# Spawn only new ids, free only departed ids. Without this every step
	# the player takes triggers a manifest tick that resets all creatures
	# back to home with no behavior state.
	var manifest_ids: Dictionary = {}  # id -> ent dict
	for ent: Dictionary in manifest.get("entities", []):
		var kind_check: String = ent.get("kind", "")
		if not CREATURE_KINDS.has(kind_check):
			continue
		var cid: String = _creature_id(kind_check, ent.get("x", 0.0), ent.get("y", 0.0))
		manifest_ids[cid] = ent

	# Free creatures no longer in manifest
	var kept: Array[Dictionary] = []
	for c: Dictionary in creature_nodes:
		if manifest_ids.has(c.get("id", "")):
			kept.append(c)
			manifest_ids.erase(c["id"])  # mark as already-present
		else:
			if is_instance_valid(c["node"]):
				c["node"].queue_free()
	creature_nodes = kept

	# Spawn new creatures (only those left in manifest_ids after the keep pass)
	for cid: String in manifest_ids:
		var ent: Dictionary = manifest_ids[cid]
		var kind: String = ent.get("kind", "")
		var cfg: Dictionary = CREATURE_KINDS[kind]

		# Atom-cluster rendering: each creature is a parent Node3D holding
		# N heptagonal mote atoms at arrangement offsets. The parent moves
		# (flee/drift). The atoms ride with it. Destruction = atoms scatter.
		var parent := Node3D.new()
		# Hover offset depends on visual: GLB has ground-relative geometry
		# (sit at z), orbs are floating markers (lift to waist). Flight
		# kinds start mid-cruise so they don't pop from floor on first
		# tick (altitude clamp would otherwise snap y=0 → alt_min).
		var ground_z: float = ent.get("z", 0.0)
		var hover: float = CREATURE_GLB_HOVER_M if CREATURE_USE_GLB_PATH else CREATURE_ORB_HOVER_M
		var spawn_y: float = ground_z + hover
		if cfg.get("behavior_mode", "ground") == "flight":
			var alt_lo: float = float(cfg.get("cruise_alt_min", 5.0))
			var alt_hi: float = float(cfg.get("cruise_alt_max", 11.0))
			spawn_y = lerpf(alt_lo, alt_hi, randf())
		parent.position = Vector3(
			ent.get("x", 0.0),
			spawn_y,
			ent.get("y", 0.0))
		parent.name = "Creature_%s_%d" % [kind, creature_nodes.size()]

		# Atom clusters size themselves via mote_size + arrangement offsets.
		# Don't inherit ent.sx — bucket_world ships 0.12 for creatures, which
		# collapses the cluster to ~4cm wide (invisible). The arrangement IS
		# the scale.
		var creature_scale: float = 1.0
		parent.scale = Vector3.ONE

		var arrangement_name: String = cfg.get("mote_arrangement", "solo")
		var mote_color: Color = cfg.get("mote_color", Color(0.5, 0.4, 0.3))
		var mote_size: float = cfg.get("mote_size", 0.05)
		if CREATURE_BASELINE_DEBUG:
			# Magic-show baseline: collapse to one fat heptagon per creature
			# so we have a known visible reference. Tune mote_size up/down,
			# THEN re-enable arrangements once baseline reads cleanly.
			arrangement_name = CREATURE_BASELINE_ARRANGEMENT
			mote_size = CREATURE_BASELINE_MOTE_SIZE
		var atom_nodes: Array = []  # untyped — typed arrays can silently reject
		var offsets: Array = []  # populated by orb path; empty for GLB path

		if CREATURE_USE_GLB_PATH:
			# GLB visual: load per-kind voxel mesh, scale by world_scale_mult
			# from kind_config. Single MeshInstance3D as the parent's visual
			# child. Behavior (flee, scatter on shatter) operates on parent
			# Node3D; the GLB rides along.
			var variant: int = abs(int(ent.get("x", 0.0) * 31.0 + ent.get("y", 0.0) * 17.0)) % NUM_VARIANTS
			var glb_mesh: Mesh = _get_mesh_for_kind(kind, variant)
			var inst := MeshInstance3D.new()
			inst.mesh = glb_mesh
			var k_params: Dictionary = _get_kind_params(kind)
			var world_mult: float = float(k_params.get("world_scale_mult", 1.0))
			var bounds: Dictionary = mesh_bounds.get(kind, {})
			var orig_scale: float = bounds.get("scale", 1.0)
			inst.scale = Vector3.ONE * (orig_scale * world_mult)
			parent.add_child(inst)
			atom_nodes.append(inst)
			# Flight kinds get procedural wing children for stop-motion
			# flap. Wings live in world meters so their flap rotation is
			# independent of the body GLB's world_scale_mult.
			if cfg.get("behavior_mode", "ground") == "flight":
				_attach_bat_wings(parent, cfg)
			print("CREATURE SPAWN: %s glb at (%s, %s) world_scale=%s" % [
				kind, str(ent.get("x", 0)), str(ent.get("y", 0)),
				str(orig_scale * world_mult)])
		else:
			# Atom-orb fallback: pre-GLB debug visual.
			var raw_offsets: Array = MoteArrangements.get_offsets(arrangement_name)
			for o in raw_offsets:
				offsets.append((o as Vector3) * CREATURE_ARRANGEMENT_SCALE)
			print("CREATURE SPAWN: %s atoms at (%s, %s) atoms=%d mote_size=%s" % [
				kind, str(ent.get("x", 0)), str(ent.get("y", 0)),
				offsets.size(), str(mote_size)])
			for offset in offsets:
				var atom := MeshInstance3D.new()
				var sphere := SphereMesh.new()
				sphere.radius = mote_size
				sphere.height = mote_size * 2.0
				atom.mesh = sphere
				var mat := StandardMaterial3D.new()
				mat.albedo_color = mote_color
				mat.emission_enabled = true
				mat.emission = mote_color
				mat.emission_energy_multiplier = CREATURE_BASELINE_EMISSION
				mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
				mat.no_depth_test = CREATURE_BASELINE_NO_DEPTH
				atom.set_surface_override_material(0, mat)
				atom.position = offset
				parent.add_child(atom)
				atom_nodes.append(atom)

		# Shadow-is-entity doctrine: if this kind's kind_config carries a
		# decal_projector block, attach projected silhouettes. When
		# hide_source=true the source geometry disappears entirely — the
		# shadow IS the creature. Orthogonal to everything above; any kind
		# (creature, shadow_orb, future) can opt in via config alone.
		var kind_full_cfg: Dictionary = kind_config.get("kinds", {}).get(kind, {})
		if kind_full_cfg.has("decal_projector"):
			var dp_cfg: Dictionary = kind_full_cfg["decal_projector"]
			if bool(dp_cfg.get("hide_source", false)):
				_hide_mesh_children(parent)
			_attach_decal_projector(parent, dp_cfg)

		add_child(parent)
		print("  -> added %d atoms, parent at %s scale %s" % [
			atom_nodes.size(), str(parent.position), str(parent.scale)])
		creature_nodes.append({
			"id": cid,  # stable across manifest updates — dedupe key
			"node": parent,
			"atom_nodes": atom_nodes,
			"atom_offsets": offsets.duplicate(),  # formation positions
			"home_x": ent.get("x", 0.0),
			"home_z": ent.get("y", 0.0),
			"kind": kind,
			"fleeing": false,
			"flee_dir_x": 0.0,
			"flee_dir_z": 0.0,
			"flee_timer": 0.0,
			# Destruction state
			"state": "intact",  # intact | breaking | debris
			"atom_velocities": [],  # populated on break
		})
	if creature_nodes.size() > 0:
		_show_toast("CREATURES: %d active" % creature_nodes.size())


func _update_creatures(delta: float) -> void:
	for c: Dictionary in creature_nodes:
		if not is_instance_valid(c["node"]):
			continue
		var cfg: Dictionary = CREATURE_KINDS[c["kind"]]
		var node: Node3D = c["node"]

		# -- Flight branch (bats, future: birds) --------------------------------
		# behavior_mode: "flight" swaps the ground-based flee/home state
		# machine for a soft-steering waypoint cruiser that leads the
		# player. Flight creatures skip collision push-out (cruising above
		# scenery) and own their Y-axis bobbing.
		if cfg.get("behavior_mode", "ground") == "flight":
			_update_flight_creature(c, cfg, node, delta)
			continue

		# -- Destruction state machine -----------------------------------------
		if c["state"] == "breaking":
			# Each atom flies away from center with gravity
			var all_settled: bool = true
			var atoms: Array = c.get("atom_nodes", [])
			var vels: Array = c.get("atom_velocities", [])
			var scatter_grav: float = cfg.get("scatter_gravity", 6.0)
			for i in range(atoms.size()):
				if i >= vels.size():
					break
				var atom: MeshInstance3D = atoms[i]
				if not is_instance_valid(atom):
					continue
				var vel: Vector3 = vels[i]
				# Apply gravity
				vel.y -= scatter_grav * delta
				vels[i] = vel
				atom.position += vel * delta
				# Settle when atom reaches actual world ground.
				# Atom positions are LOCAL to parent (which floats at hover
				# height), so ground in local coords is -hover.
				var ground_local_y: float = -CREATURE_BASELINE_HOVER_M
				if atom.position.y <= ground_local_y:
					atom.position.y = ground_local_y
					vels[i] = Vector3.ZERO
				else:
					all_settled = false
			if all_settled:
				c["state"] = "debris"
			continue

		if c["state"] == "debris":
			# Atoms on the ground. Fade rate 0 = scars persist (path-memory).
			if CREATURE_DEBRIS_FADE_RATE <= 0.0:
				continue  # leave debris on ground forever
			var atoms: Array = c.get("atom_nodes", [])
			var all_gone: bool = true
			for atom in atoms:
				if not is_instance_valid(atom):
					continue
				var mat: StandardMaterial3D = atom.get_surface_override_material(0)
				if mat:
					mat.albedo_color.a -= delta * CREATURE_DEBRIS_FADE_RATE
					if mat.albedo_color.a <= 0.0:
						atom.queue_free()
					else:
						all_gone = false
			if all_gone and CREATURE_DEBRIS_FREE_PARENT:
				node.queue_free()
			continue

		# -- Intact behavior ---------------------------------------------------
		var _pp: Vector3 = _player_pos()
		var dx: float = node.position.x - _pp.x
		var dz: float = node.position.z - _pp.z
		var dist: float = sqrt(dx * dx + dz * dz)
		if CREATURE_VERBOSE and Engine.get_process_frames() % 60 == 0:
			print("CREATURE %s dist=%.1f flee_radius=%.1f speed=%.1f fleeing=%s" % [
				c["kind"], dist, cfg.get("flee_radius", 0.0), cfg.get("speed", 0.0), str(c["fleeing"])])

		# Destructible check: break on proximity (placeholder for cast/hit)
		if cfg.get("destructible", false) and dist < CREATURE_DESTRUCT_RADIUS_M and c["state"] == "intact":
			c["state"] = "breaking"
			var atoms: Array = c.get("atom_nodes", [])
			var vels: Array = []
			var scatter_spd: float = cfg.get("scatter_speed", 3.0)
			for atom in atoms:
				if not is_instance_valid(atom):
					vels.append(Vector3.ZERO)
					continue
				# Scatter direction: outward from entity center + upward
				var dir: Vector3 = atom.position.normalized()
				if dir.length() < 0.01:
					dir = Vector3(randf() - 0.5, 0.5, randf() - 0.5).normalized()
				dir.y = abs(dir.y) + 0.5  # bias upward
				vels.append(dir * scatter_spd * (0.7 + randf() * 0.6))
			c["atom_velocities"] = vels
			_show_toast("*crack*")
			continue

		var k_params: Dictionary = _get_kind_params(c["kind"])
		# Creature's OWN body radius — prefer visual_radius (the new single-
		# source-of-truth collision field), fall back to legacy
		# physics.collision_radius for kinds that haven't been migrated.
		# 0.3m default matches a rat-sized footprint.
		var coll_r: float = float(k_params.get(
			"visual_radius",
			k_params.get("physics", {}).get("collision_radius", 0.3)))
		if coll_r <= 0.0:
			coll_r = 0.3
		if c["fleeing"]:
			c["flee_timer"] -= delta
			node.position.x += c["flee_dir_x"] * cfg["speed"] * delta
			node.position.z += c["flee_dir_z"] * cfg["speed"] * delta
			if c["flee_timer"] <= 0.0:
				c["fleeing"] = false
		elif dist < cfg["flee_radius"] and cfg["speed"] > 0.0:
			c["fleeing"] = true
			c["flee_timer"] = 1.5
			var flee_len: float = max(dist, 0.1)
			c["flee_dir_x"] = dx / flee_len
			c["flee_dir_z"] = dz / flee_len
		elif cfg["speed"] > 0.0:
			var hx: float = c["home_x"] - node.position.x
			var hz: float = c["home_z"] - node.position.z
			node.position.x += hx * 0.3 * delta
			node.position.z += hz * 0.3 * delta
		# Push-out runs EVERY frame regardless of movement state. Static
		# creatures (speed=0 like clay_pot/treasure_chest) that spawned
		# embedded in geometry still get ejected. Moving creatures get
		# corrected against any spike they drift into during flee/return.
		node.position = _push_out_of_collision(node.position, coll_r)


# Discrete flap poses — three frames (wings down / level / up).
# The classic sprite-flip trick: hold each pose for ~1/(flap_hz × 3)
# seconds, then snap to the next. Wings never tween — the snap IS
# the visual. L and R hold the same pose, but we offset their phase
# slightly so the silhouette has asymmetry mid-cycle.
const BAT_WING_POSES: Array[float] = [
	-0.55,  # down (radians ≈ -31°)
	 0.0,   # level
	 0.55,  # up
]

func _attach_bat_wings(parent: Node3D, cfg: Dictionary) -> void:
	# Build two wing children — flat triangle quads extending in ±Y from
	# the body. World-meter dimensions from kind_config so iteration is
	# config-driven (no rebake to resize wings).
	var span: float = float(cfg.get("wing_span", 0.8))
	var chord: float = float(cfg.get("wing_chord", 0.25))
	var sweep: float = float(cfg.get("wing_sweep", -0.15))
	var color_arr = cfg.get("mote_color", [0.18, 0.16, 0.14])
	var col := Color(float(color_arr[0]), float(color_arr[1]), float(color_arr[2]))

	for side in [1, -1]:  # +Y = left wing, -Y = right wing
		var pivot := Node3D.new()
		pivot.name = "bat_wing_" + ("L" if side == 1 else "R")
		var inst := MeshInstance3D.new()
		var mesh := ArrayMesh.new()
		var arr := []
		arr.resize(Mesh.ARRAY_MAX)
		# Quad verts: shoulder_front, shoulder_back, wingtip, mid_trail
		var verts := PackedVector3Array([
			Vector3( chord * 0.5, 0.0, 0.0),                     # shoulder front
			Vector3(-chord * 0.5, 0.0, 0.0),                     # shoulder back
			Vector3(sweep,             0.0, side * span),        # wingtip
			Vector3(sweep - chord * 0.4, 0.0, side * span * 0.55), # mid trailing
		])
		var indices: PackedInt32Array
		if side == 1:
			indices = PackedInt32Array([0, 2, 1,  1, 2, 3])
		else:
			indices = PackedInt32Array([0, 1, 2,  1, 3, 2])  # flip winding for mirror
		arr[Mesh.ARRAY_VERTEX] = verts
		arr[Mesh.ARRAY_INDEX] = indices
		mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arr)
		inst.mesh = mesh
		var mat := StandardMaterial3D.new()
		mat.albedo_color = col
		mat.cull_mode = BaseMaterial3D.CULL_DISABLED  # wings visible from below AND above
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_PER_PIXEL
		inst.set_surface_override_material(0, mat)
		pivot.add_child(inst)
		parent.add_child(pivot)


func _update_flight_creature(c: Dictionary, cfg: Dictionary, node: Node3D, delta: float) -> void:
	# Guide-creature loop: pick a target point ahead of the player, steer
	# toward it with soft velocity blending, bob vertically, bank into
	# turns. Player never "catches" the bat — when proximity closes, the
	# waypoint is regenerated further ahead so the bat keeps leading.
	#
	# State fields lazily initialized on first tick so spawn doesn't need
	# to know about flight:
	#   vel (Vector3)    current velocity
	#   target (Vector3) current waypoint in world space
	#   bob_phase (float) time accumulator for y-bob
	if not c.has("vel"):
		c["vel"] = Vector3.ZERO
		c["target"] = _player_pos()
		c["bob_phase"] = randf() * TAU  # desync flock
		c["flap_phase"] = randf() * 3.0  # 0..3, integer part = pose index
		c["flap_pose_l"] = -1
		c["flap_pose_r"] = -1
	var vel: Vector3 = c["vel"]
	var target: Vector3 = c["target"]
	var bob_phase: float = c["bob_phase"]

	var speed: float = float(cfg.get("speed", 3.5))
	var alt_min: float = float(cfg.get("cruise_alt_min", 5.0))
	var alt_max: float = float(cfg.get("cruise_alt_max", 11.0))
	var waypoint_dist: float = float(cfg.get("waypoint_distance", 18.0))
	var waypoint_wobble: float = float(cfg.get("waypoint_wobble", 6.0))
	var steer: float = float(cfg.get("steer_strength", 1.6))
	var bank_k: float = float(cfg.get("bank_strength", 0.8))
	var bob_amp: float = float(cfg.get("bob_amplitude", 0.4))
	var bob_hz: float = float(cfg.get("bob_hz", 1.3))

	# Regenerate target when reached or when player has drifted far from it.
	# The bat leads the player — target is ahead of player's facing direction.
	var _ppos: Vector3 = _player_pos()
	var to_target: Vector3 = target - node.position
	var dist_to_target: float = to_target.length()
	var player_to_target: float = _ppos.distance_to(target)
	if dist_to_target < 3.0 or player_to_target > waypoint_dist * 2.0:
		var fwd: Vector3 = -camera.global_transform.basis.z
		fwd.y = 0.0
		if fwd.length_squared() < 0.01:
			fwd = Vector3.FORWARD
		fwd = fwd.normalized()
		# Wobble perpendicular to heading so the flight path meanders.
		var perp: Vector3 = Vector3(-fwd.z, 0.0, fwd.x)
		var wobble: float = (randf() - 0.5) * 2.0 * waypoint_wobble
		var cruise_alt: float = lerpf(alt_min, alt_max, randf())
		target = _ppos + fwd * waypoint_dist + perp * wobble
		target.y = cruise_alt
		c["target"] = target
		to_target = target - node.position

	# Soft steer: blend velocity toward desired direction rather than snap.
	if to_target.length() > 0.01:
		var desired: Vector3 = to_target.normalized() * speed
		vel = vel.lerp(desired, clampf(steer * delta, 0.0, 1.0))

	# Vertical bob — ambient life sign, separate from steered Y.
	bob_phase += bob_hz * TAU * delta
	var bob_offset: float = sin(bob_phase) * bob_amp * delta
	c["bob_phase"] = bob_phase

	node.position += vel * delta
	node.position.y += bob_offset

	# Clamp altitude to cruise band — prevents drift into floor/ceiling.
	node.position.y = clampf(node.position.y, alt_min, alt_max)

	# Visual bank: roll the GLB child based on lateral velocity relative
	# to facing. Positive vel.x = banking right → +z roll.
	var atoms: Array = c.get("atom_nodes", [])
	if atoms.size() > 0 and is_instance_valid(atoms[0]):
		var visual: Node3D = atoms[0]
		# Face direction of travel (yaw only, pitch stays level).
		var face_vec: Vector3 = Vector3(vel.x, 0.0, vel.z)
		if face_vec.length_squared() > 0.01:
			var yaw: float = atan2(face_vec.x, face_vec.z)
			var roll: float = clampf(-vel.x * bank_k * 0.08, -0.6, 0.6)
			visual.rotation = Vector3(0.0, yaw, roll)

	# Wing flap — advance phase, snap each wing to its discrete pose.
	# Right wing trails left by one frame so the silhouette has
	# asymmetry mid-cycle (the OG sprite-flip trick).
	var flap_hz: float = float(cfg.get("flap_hz", 9.0))
	var flap_phase: float = c.get("flap_phase", 0.0)
	flap_phase += flap_hz * BAT_WING_POSES.size() * delta
	c["flap_phase"] = fmod(flap_phase, float(BAT_WING_POSES.size()))
	var pose_l: int = int(c["flap_phase"]) % BAT_WING_POSES.size()
	var pose_r: int = (pose_l + 2) % BAT_WING_POSES.size()  # trails by one (≡ +2 in mod-3)
	if pose_l != c.get("flap_pose_l", -1) or pose_r != c.get("flap_pose_r", -1):
		c["flap_pose_l"] = pose_l
		c["flap_pose_r"] = pose_r
		var wing_l: Node3D = node.get_node_or_null("bat_wing_L")
		var wing_r: Node3D = node.get_node_or_null("bat_wing_R")
		if wing_l != null:
			wing_l.rotation.x = BAT_WING_POSES[pose_l]
		if wing_r != null:
			wing_r.rotation.x = -BAT_WING_POSES[pose_r]  # mirror axis

	c["vel"] = vel


func _refresh_nearby_colliders(px: float, pz: float) -> void:
	# Spatial cull — rebuild nearby_colliders from collision_objects for
	# colliders within COLLIDER_CULL_RADIUS of (px, pz). Player push-out
	# iterates the culled list (~30 entries) instead of the full set
	# (800+). Refresh whenever the player strays more than
	# COLLIDER_CULL_REFRESH meters from the cached pos, or when the
	# underlying collision_objects set changes.
	nearby_colliders.clear()
	var r2: float = COLLIDER_CULL_RADIUS * COLLIDER_CULL_RADIUS
	for coll: Dictionary in collision_objects:
		var dx: float = float(coll.get("x", 0.0)) - px
		var dz: float = float(coll.get("z", 0.0)) - pz
		if dx * dx + dz * dz <= r2:
			nearby_colliders.append(coll)
	last_cull_pos = Vector2(px, pz)


func _push_out_of_collision(pos: Vector3, radius: float) -> Vector3:
	# Mirrors the player's push-out in _physics_process. Iterates scenery
	# collision_objects and ejects pos along the separating axis if the
	# creature overlaps a solid. XZ only — y is driven by hover/terrain.
	# Creatures use the full list (they scatter across the world and can
	# push-out anywhere); only the player uses nearby_colliders cull.
	for coll: Dictionary in collision_objects:
		var cdx: float = pos.x - coll["x"]
		var cdz: float = pos.z - coll["z"]
		var dist_sq: float = cdx * cdx + cdz * cdz
		var min_dist: float = coll["r"] + radius
		if dist_sq < min_dist * min_dist and dist_sq > 0.001:
			var cdist: float = sqrt(dist_sq)
			var push: float = min_dist - cdist
			pos.x += (cdx / cdist) * push
			pos.z += (cdz / cdist) * push
	return pos


# -- Telemetry tags ------------------------------------------------------------

var tag_count: int = 0
var tag_markers: Array[Node3D] = []

func _drop_tag_marker(num: int, pos: Vector3) -> void:
	var marker := Node3D.new()
	marker.position = Vector3(pos.x, 0.5, pos.z)  # ground level, slightly raised
	# Billboard label
	var label := Label3D.new()
	label.text = "#%d" % num
	label.font_size = 48
	label.modulate = Color(1.0, 0.85, 0.3, 0.9)
	label.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	label.no_depth_test = true
	label.position.y = 0.5
	marker.add_child(label)
	# Prime-mote doctrine: tag markers are motes dropped by the player by
	# hand. Same heptagonal test fixture — see design_heptagonal_mote.md.
	# You tag the world with the world's unit cell.
	var dot := MeshInstance3D.new()
	var hep: ArrayMesh = _build_heptagonal_mote_mesh(0.10)
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(1.0, 0.85, 0.3)
	mat.emission_enabled = true
	mat.emission = Color(1.0, 0.85, 0.3)
	mat.emission_energy_multiplier = 3.0
	mat.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	hep.surface_set_material(0, mat)
	dot.mesh = hep
	marker.add_child(dot)
	marker.name = "TagMarker_%d" % num
	add_child(marker)
	tag_markers.append(marker)

func _save_tag(reason: String = "neutral") -> void:
	tag_count += 1
	var img: Image = get_viewport().get_texture().get_image()
	var p: Vector3 = _player_pos()
	var cx: float = snapped(p.x, 0.1)
	var cy: float = snapped(p.z, 0.1)
	var ch: float = snapped(rad_to_deg(_player_yaw()), 0.1)
	var tension_st: String = manifest.get("tension_state", "?")
	var vis: int = manifest.get("entities", []).size()
	var fname: String = "sanctum_tag_%02d_x%s_y%s_h%s_%s_%s_%dvis.png" % [
		tag_count, str(cx), str(cy), str(ch), tension_st, reason, vis]

	# Save to absolute path — res:// is read-only at runtime
	var tag_dir: String = "/Users/themrburn/git/sanctum-terminal/godot/tags"
	DirAccess.make_dir_recursive_absolute(tag_dir)
	var path: String = tag_dir + "/" + fname
	var err: int = img.save_png(path)
	print("TAG #%d: %s (err=%d)" % [tag_count, path, err])
	# Sidecar JSON with full telemetry
	# Count per-kind entity breakdown for telemetry
	var kind_counts: Dictionary = {}
	var tile_variants_seen: Dictionary = {}
	var emissive_with_spectrum: int = 0
	for ent_t: Dictionary in manifest.get("entities", []):
		var k: String = ent_t.get("kind", "?")
		kind_counts[k] = kind_counts.get(k, 0) + 1
		var tv: String = ent_t.get("tile_variant", "")
		if tv != "":
			tile_variants_seen[tv] = tile_variants_seen.get(tv, 0) + 1
		if ent_t.has("spectrum_state"):
			emissive_with_spectrum += 1

	# Crosshair identification — find the entity nearest to camera forward.
	# Pure math (no physics raycast) so it works for every kind, including
	# those without collision shapes. Scores by angular alignment + visible
	# silhouette size, NOT raw distance — early version was distance-biased
	# and over-picked tiny floor scatter (cave_gravel) over the actual
	# subject of the screenshot. Returns the top 5 so the user / claude can
	# disambiguate when scoring is ambiguous.
	var fwd_v: Vector3 = -camera.global_transform.basis.z
	var cam_pos_v: Vector3 = camera.global_transform.origin
	var crosshair_candidates: Array = []
	for ent_xh: Dictionary in manifest.get("entities", []):
		var ent_pos := Vector3(
			ent_xh.get("x", 0.0),
			ent_xh.get("z", 0.0),  # manifest z → Godot y (up)
			ent_xh.get("y", 0.0)   # manifest y → Godot z (forward)
		)
		var to_ent: Vector3 = ent_pos - cam_pos_v
		var dist_xh: float = to_ent.length()
		if dist_xh < 0.3 or dist_xh > 40.0:
			continue
		var fwd_cos: float = to_ent.normalized().dot(fwd_v)
		if fwd_cos < 0.5:  # outside ~60° cone
			continue
		# Approximate visible silhouette: max axis of the rendered scale
		# divided by distance gives angular size. Bigger and centered =
		# clearly the subject. Tiny scatter at the same distance loses.
		var sx_xh: float = float(ent_xh.get("sx", 1.0))
		var sy_xh: float = float(ent_xh.get("sy", 1.0))
		var sz_xh: float = float(ent_xh.get("sz", 1.0))
		var max_axis: float = max(sx_xh, max(sy_xh, sz_xh))
		var angular_size: float = max_axis / dist_xh
		# Score (LOWER wins):
		#   - heavy penalty for angle off-center (×100, was ×30)
		#   - reward for angular size (negative term — bigger silhouette
		#     subtracts from score, so big-and-centered crushes tiny-and-close)
		#   - mild distance term so a far-but-huge thing doesn't auto-win
		var score: float = (1.0 - fwd_cos) * 100.0 - angular_size * 20.0 + dist_xh * 0.3
		crosshair_candidates.append({
			"kind": ent_xh.get("kind", "?"),
			"x": snapped(ent_xh.get("x", 0.0), 0.01),
			"y": snapped(ent_xh.get("y", 0.0), 0.01),
			"z": snapped(ent_xh.get("z", 0.0), 0.01),
			"distance": snapped(dist_xh, 0.01),
			"fwd_cos": snapped(fwd_cos, 0.001),
			"angular_size": snapped(angular_size, 0.001),
			"sx": ent_xh.get("sx", 1.0),
			"sy": ent_xh.get("sy", 1.0),
			"sz": ent_xh.get("sz", 1.0),
			"r": ent_xh.get("r", 0.0),
			"g": ent_xh.get("g", 0.0),
			"b": ent_xh.get("b", 0.0),
			"_score": snapped(score, 0.01),
		})
	crosshair_candidates.sort_custom(func(a, b): return a["_score"] < b["_score"])
	var crosshair_top: Array = crosshair_candidates.slice(0, 5)

	var _pt: Vector3 = _player_pos()
	var telemetry := {
		"tag": tag_count,
		"camera": {
			"x": snapped(_pt.x, 0.01),
			"y": snapped(_pt.z, 0.01),
			"z": snapped(_pt.y, 0.01),
			"heading": snapped(rad_to_deg(_player_yaw()), 0.1),
			"pitch": snapped(rad_to_deg(_player_pitch()), 0.1),
			"fov": camera.fov,
		},
		"tag_reason": reason,
		"crosshair": crosshair_top,
		"tension_state": manifest.get("tension_state", ""),
		"tension_budget": manifest.get("tension_budget", 0.0),
		"tension_envelope": manifest.get("tension_envelope", {}),  # includes dissociating, dwell_time, pressure
		"chronometer": manifest.get("chronometer", {}),
		"biome": manifest.get("biome", ""),
		"entities_visible": manifest.get("entities", []).size(),
		"kind_counts": kind_counts,
		"tile_variants": tile_variants_seen,
		"emissive_with_spectrum": emissive_with_spectrum,
		"tiles": manifest.get("stats", {}).get("tiles", 0),
		"outline_mode": OUTLINE_MODE_NAMES[outline_mode],
		"emissive_lights": light_pipes.size(),  # fixed pipe count
		"fog": manifest.get("fog", {}),
		"ambient": manifest.get("ambient", []),
		"connected": connected,
		"overlay": hud_label.text,
		"perf": _read_perf(),
	}
	var json_path: String = path.replace(".png", ".json")
	var jfile := FileAccess.open(json_path, FileAccess.WRITE)
	if jfile:
		jfile.store_string(JSON.stringify(telemetry, "  "))
		jfile.close()
	if expedition_active:
		_show_toast("TAG #%d [%s] — return to the column when ready" % [
			tag_count, reason.to_upper()])
	else:
		_show_toast("TAG #%d [%s] saved" % [tag_count, reason.to_upper()])
	# Drop 3D marker at tag position
	_drop_tag_marker(tag_count, _player_pos())

	# Expedition wire: send the full sidecar to brain so the engine
	# can score it and (on proximity) deposit it. The disk-saved PNG
	# + JSON remain the post-mortem artifacts; this is the in-game
	# loop's input channel.
	if connected:
		var tag_payload: Dictionary = telemetry.duplicate(true)
		tag_payload["tag_id"] = tag_count
		var msg_obj := {
			"cmd": "tag_event",
			"tag": tag_payload,
		}
		var msg_str: String = JSON.stringify(msg_obj) + "\n"
		tcp.put_data(msg_str.to_utf8_buffer())
		pending_tag_intents[tag_count] = tag_payload


# -- Stamp capture ---------------------------------------------------------
# Shift+Cmd+T captures the composition around the player as a drop-in stamp
# for biome_data.CAVERN_STAMPS. Output: godot/stamps/captured_<ts>.json with
# a ready-to-paste stamp dict (name, weight, members list). Positions are
# player-relative (dx/dy), so re-applying at any slot reproduces the scene.
# Author-interesting kinds only — ambient/creature/pure decor skipped so the
# captured stamp composes with procedural tissue scatter instead of fighting.

const STAMP_CAPTURE_RADIUS_M: float = 20.0
const STAMP_CAPTURE_SKIP_KINDS: Array = [
	"firefly", "leaf", "beetle", "rat", "rat_ice", "rat_fire", "rat_water",
	"spider", "bat", "orb", "clay_pot", "treasure_chest", "shadow_orb",
	"horizon_form", "horizon_mid", "horizon_near", "exit_lure",
]
# Kinds that get stamp_member.hard=true — anchor geometry that world_gen
# uses for composition clearance. Everything else defaults to hard=false
# (tissue scatter, soft companions) so the captured stamp's density plays
# nice with procedural companions layered on top.
const STAMP_CAPTURE_HARD_KINDS: Array = [
	"mega_column", "column", "stalagmite", "boulder", "buttress",
	"crystal_cluster", "giant_fungus", "dead_log", "monolith", "doorframe",
]


func _save_stamp_capture() -> void:
	var _pp: Vector3 = _player_pos()
	var cx: float = _pp.x
	var cy: float = _pp.z  # godot z axis = brain y axis
	var r2: float = STAMP_CAPTURE_RADIUS_M * STAMP_CAPTURE_RADIUS_M
	var skip := {}
	for k in STAMP_CAPTURE_SKIP_KINDS:
		skip[k] = true
	var hard_set := {}
	for k in STAMP_CAPTURE_HARD_KINDS:
		hard_set[k] = true

	var members: Array = []
	for ent: Dictionary in manifest.get("entities", []):
		var kind: String = ent.get("kind", "")
		if skip.has(kind):
			continue
		var ex: float = float(ent.get("x", 0.0))
		var ey: float = float(ent.get("y", 0.0))
		var dx: float = ex - cx
		var dy: float = ey - cy
		if dx * dx + dy * dy > r2:
			continue
		# scale_mult reversal — _make_entity emits sv = U(0.75,1.25) × 1.30 × scale_mult.
		# Approximate scale_mult as sv / 1.30 (dropping per-instance jitter is fine
		# because replay applies its own sv variance at re-spawn).
		var sv: float = float(ent.get("sv", 1.3))
		var member: Dictionary = {
			"kind": kind,
			"dx": snapped(dx, 0.1),
			"dy": snapped(dy, 0.1),
			"scale_mult": snapped(sv / 1.30, 0.01),
			"hard": hard_set.has(kind),
		}
		var ap: String = ent.get("attachment_plane", "")
		if ap != "":
			member["attachment_plane"] = ap
		members.append(member)

	var ts: int = int(Time.get_unix_time_from_system())
	var stamp := {
		"name": "captured_%d" % ts,
		# Footprint must match the capture radius so test_members_within_footprint
		# accepts the pasted stamp. Re-tune by hand if you want a tighter bound.
		"footprint": STAMP_CAPTURE_RADIUS_M,
		"weight": 1,
		"members": members,
	}

	var stamp_dir: String = "/Users/themrburn/git/sanctum-terminal/godot/stamps"
	DirAccess.make_dir_recursive_absolute(stamp_dir)
	var path: String = "%s/captured_%d.json" % [stamp_dir, ts]
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(stamp, "  "))
		file.close()
		print("STAMP CAPTURED: %s (%d members)" % [path, members.size()])
		_show_toast("Stamp captured: %d members" % members.size())
	else:
		print("STAMP CAPTURE FAILED: could not open %s" % path)
		_show_toast("Stamp capture failed")


# -- Cast input ------------------------------------------------------------
# CAST_TRIAL expedition class expects cast_event with element + origin +
# direction. Element drives accepts matching (same _tag_matches_accepts
# path as tag_reason). Proximity-to-deposit still flows through the
# existing deposit_intent channel — casts share tag_log.
var cast_count: int = 0

func _send_cast_event(element: String) -> void:
	if not connected:
		return
	cast_count += 1
	var fwd: Vector3 = -camera.global_transform.basis.z
	var _pp: Vector3 = _player_pos()
	var cast_payload: Dictionary = {
		# Use tag_id so _find_tag_by_id resolves it uniformly with tags.
		# Cast ids are namespaced by a negative sign to avoid collision
		# with real tag_ids (which start at 1 and count up).
		"tag_id": -cast_count,
		"element": element,
		"origin": [_pp.x, _pp.y, _pp.z],
		"direction": [fwd.x, fwd.y, fwd.z],
	}
	var msg_obj: Dictionary = {
		"cmd": "cast_event",
		"cast": cast_payload,
	}
	var msg_str: String = JSON.stringify(msg_obj) + "\n"
	tcp.put_data(msg_str.to_utf8_buffer())
	# Casts ride the same proximity → deposit_intent loop as tags. Shared
	# pending_tag_intents dict — negative keys keep namespaces separate.
	pending_tag_intents[-cast_count] = cast_payload
	_show_toast("CAST #%d [%s]" % [cast_count, element.to_upper()])


# -- Atmospheric layer state (future: light sheet, dust motes) ------------



# -- Expedition wire handlers ---------------------------------------------

func _on_expedition_manifest_field(enc: Dictionary) -> void:
	"""Called every frame after a manifest update. Caches the snapshot
	for proximity checks and fires a toast on last_message transitions."""
	if enc.is_empty():
		expedition_active = false
		expedition_cache = {}
		return
	expedition_cache = enc
	var state: String = enc.get("state", "dormant")
	expedition_active = (state == "active" or state == "resolution")

	# Toast on message transitions. Brain clears last_message after
	# each send via engine.consume_message(), so we only see a given
	# key once. Guard: JSON null → GDScript null, not String — must
	# coerce before assigning to typed String var.
	var msg_key_raw = enc.get("last_message")
	var msg_key: String = msg_key_raw if msg_key_raw is String else ""
	if msg_key != "" and msg_key != expedition_last_message:
		var msg_text_raw = enc.get("last_message_text")
		var msg_text: String = msg_text_raw if msg_text_raw is String else ""
		if msg_text != "":
			_show_toast(msg_text)
		expedition_last_message = msg_key


func _on_deposit_result(result: Dictionary) -> void:
	"""Brain acked a deposit_intent. On accept, clear the local
	pending tag so we don't re-send. On reject, keep it pending —
	it might match a different deposit point later."""
	if result.get("accepted", false):
		var dep: Dictionary = result.get("deposit", {})
		# We don't know which tag_id was deposited from the ack alone,
		# so we clear whichever pending tags are eligible by snapshot
		# comparison with the updated deposit_points (handled on next
		# manifest frame). For v1 we just let the brain's idempotence
		# guard catch duplicates — nothing to do here beyond toasting.
		var did: String = dep.get("id", "?")
		print("Expedition: deposit accepted at %s (%d/%d)" % [
			did, int(dep.get("current", 0)), int(dep.get("threshold", 0))
		])


func _on_expedition_resolution(data: Dictionary) -> void:
	"""Brain acked a walk_through. If resolution=complete and
	quit_godot=true, exit cleanly after a brief dwell so the last
	toast is readable."""
	var resolution: String = data.get("resolution", "")
	if resolution == "complete":
		var log_path: String = data.get("log_path", "")
		print("Expedition complete. Session log: %s" % log_path)
		if data.get("quit_godot", false):
			_show_toast("Session complete.")
			await get_tree().create_timer(0.6).timeout
			get_tree().quit()
	elif resolution == "exit_inactive":
		# Player walked through before exit activated — no-op.
		pass


# -- Expedition proximity + visuals --------------------------------------

# Visual nodes for expedition markers. Keyed by "<kind>:<id>" so we can
# update/remove them when the snapshot changes. Each entry is a Node3D
# with a heptagonal mote MeshInstance3D child — we reuse the tag marker
# primitive to keep the visual language consistent (design_heptagonal_mote).
var expedition_markers: Dictionary = {}
# Track walk-through dispatch so we only send once per activation.
var walk_through_sent: bool = false


func _check_expedition_proximity() -> void:
	"""Dispatch tag-intents when the camera enters a deposit point's
	radius, and a walk_through when it enters an active exit point's
	radius. Runs every frame; v1 has one deposit + one exit so cost
	is negligible."""
	if not expedition_active or expedition_cache.is_empty():
		return
	if not connected:
		return

	var cam_pos: Vector3 = camera.global_transform.origin

	# Deposit points ——————————————————————————————————————
	var dp_arr = expedition_cache.get("deposit_points")
	if dp_arr == null or not (dp_arr is Array):
		return
	for d_raw in dp_arr:
		if not (d_raw is Dictionary):
			continue
		var d: Dictionary = d_raw
		if d.get("satisfied", false):
			continue
		var pos_arr = d.get("pos")
		if pos_arr == null or not (pos_arr is Array) or pos_arr.size() < 2:
			continue
		# Manifest positions are (x, y, z) where x/y are world plane
		# and z is up. Godot is (x_plane, y_up, z_plane) so map
		# manifest x→Godot x, manifest y→Godot z, manifest z→Godot y.
		var dep_pos := Vector3(
			float(pos_arr[0]),
			cam_pos.y,
			float(pos_arr[1]))
		var dist: float = cam_pos.distance_to(dep_pos)
		if dist < EXPEDITION_DEPOSIT_RADIUS:
			# Attempt to deposit any still-pending tag at this point.
			var deposit_id: String = d.get("id", "")
			for tag_id in pending_tag_intents.keys().duplicate():
				var intent_msg := {
					"cmd": "deposit_intent",
					"deposit_id": deposit_id,
					"tag_id": tag_id,
				}
				var s: String = JSON.stringify(intent_msg) + "\n"
				tcp.put_data(s.to_utf8_buffer())
				# Optimistically clear — brain's idempotence guard
				# catches any false-positive clears on reject.
				pending_tag_intents.erase(tag_id)

	# Exit point ——————————————————————————————————————————
	var exit: Dictionary = expedition_cache.get("exit_point", {})
	if not exit.is_empty() and exit.get("active", false) and not walk_through_sent:
		var epos_arr: Array = exit.get("pos", [0.0, 0.0, 0.0])
		if epos_arr.size() >= 2:
			var exit_pos := Vector3(
				float(epos_arr[0]),
				cam_pos.y,
				float(epos_arr[1]))
			var radius: float = float(exit.get("trigger_radius", 2.0))
			if cam_pos.distance_to(exit_pos) < radius:
				walk_through_sent = true
				var msg := {"cmd": "walk_through"}
				var s: String = JSON.stringify(msg) + "\n"
				tcp.put_data(s.to_utf8_buffer())


func _update_expedition_visuals(_delta: float) -> void:
	"""Maintain per-deposit + exit marker Node3Ds from the snapshot."""
	if expedition_cache.is_empty() or not expedition_active:
		# Tear down any leftover markers when expedition ends or cache empty
		if not expedition_markers.is_empty():
			for key in expedition_markers.keys():
				expedition_markers[key].queue_free()
			expedition_markers.clear()
		return

	var seen: Dictionary = {}

	# Deposit markers — one mote per point
	for d_raw in expedition_cache.get("deposit_points", []):
		var d: Dictionary = d_raw
		var key: String = "deposit:" + d.get("id", "?")
		seen[key] = true
		var pos_arr: Array = d.get("pos", [0.0, 0.0, 0.0])
		if pos_arr.size() < 2:
			continue
		# Suspend mote above entity head — axis_mundi lives at ground
		# level in the manifest; raise the mote to hover where the
		# player will see it at walking height.
		var pos := Vector3(
			float(pos_arr[0]),
			4.0,
			float(pos_arr[1]))
		var visual: Dictionary = d.get("visual", {})
		var base_boost: float = 1.0
		if d.get("satisfied", false):
			base_boost = float(visual.get("emission_boost", 2.0))
		_ensure_expedition_marker(key, pos, base_boost)

	# Exit marker
	var exit: Dictionary = expedition_cache.get("exit_point", {})
	if not exit.is_empty():
		var key: String = "exit:" + exit.get("id", "?")
		seen[key] = true
		var epos_arr: Array = exit.get("pos", [0.0, 0.0, 0.0])
		if epos_arr.size() >= 2:
			var pos := Vector3(
				float(epos_arr[0]),
				5.0,
				float(epos_arr[1]))
			var visual: Dictionary = exit.get("visual", {})
			var base_boost: float = 0.3
			if exit.get("active", false):
				base_boost = float(visual.get("emission_boost", 1.5))
			_ensure_expedition_marker(key, pos, base_boost)

	# Tear down any markers no longer in the snapshot
	for key in expedition_markers.keys().duplicate():
		if not seen.has(key):
			expedition_markers[key].queue_free()
			expedition_markers.erase(key)


func _ensure_expedition_marker(
	key: String, pos: Vector3, emission_boost: float,
) -> void:
	"""Create or update a heptagonal mote marker at pos with the
	given emission multiplier. Reuses _build_heptagonal_mote_mesh —
	same primitive as tag markers, consistent visual language."""
	var node: Node3D
	if expedition_markers.has(key):
		node = expedition_markers[key]
	else:
		node = Node3D.new()
		node.name = "ExpeditionMarker_" + key.replace(":", "_")
		var mesh := MeshInstance3D.new()
		mesh.mesh = _build_heptagonal_mote_mesh(0.30)
		var mat := StandardMaterial3D.new()
		mat.albedo_color = Color(0.98, 0.86, 0.35)
		mat.emission_enabled = true
		mat.emission = Color(1.0, 0.85, 0.35)
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		mat.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED
		mat.no_depth_test = false
		mesh.set_surface_override_material(0, mat)
		node.add_child(mesh)
		add_child(node)
		expedition_markers[key] = node

	node.position = pos
	# Update emission energy based on boost (dormant=0.3, satisfied≈2.0)
	var mesh_child: MeshInstance3D = node.get_child(0) as MeshInstance3D
	if mesh_child:
		var mat: StandardMaterial3D = mesh_child.get_surface_override_material(0)
		if mat:
			mat.emission_energy_multiplier = clampf(emission_boost, 0.2, 4.0)


func _build_overlay_line(cfg: Dictionary,
		cx: float, cy: float, ch: float, tension_st: String, vis: int) -> String:
	"""Build the telemetry overlay string from config-driven field list."""
	var sep: String = cfg.get("separator", " | ")
	var fields: Array = cfg.get("fields", [])
	var parts: PackedStringArray = PackedStringArray()
	var chrono: Dictionary = manifest.get("chronometer", {})
	# Lazy-read perf only if any perf field is requested — avoids the
	# Performance.get_monitor calls every frame when no one asks.
	var perf: Dictionary = {}
	for f: String in fields:
		if f in ["fps", "frame_ms", "physics_ms", "draw_calls",
				 "render_objects", "render_tris", "static_mem"]:
			perf = _read_perf()
			break

	for f: String in fields:
		match f:
			"biome":
				parts.append(manifest.get("biome", "?"))
			"position":
				parts.append("x%.1f y%.1f" % [cx, cy])
			"heading":
				parts.append("h%.0f" % ch)
			"fov":
				parts.append("fov%.0f" % camera.fov)
			"entities_visible":
				parts.append("%dvis" % vis)
			"tension_state":
				parts.append(tension_st)
			"tension_budget":
				parts.append("t%.0f%%" % (manifest.get("tension_budget", 0.0) * 100))
			"day_phase":
				parts.append(chrono.get("day_phase", "?"))
			"tiles":
				parts.append("%dtiles" % manifest.get("stats", {}).get("tiles", 0))
			"outline_mode":
				parts.append(OUTLINE_MODE_NAMES[outline_mode])
			"kind_summary":
				var kc: Dictionary = {}
				for ent_t: Dictionary in manifest.get("entities", []):
					var k: String = ent_t.get("kind", "?")
					kc[k] = kc.get(k, 0) + 1
				var sorted_k: Array = kc.keys()
				sorted_k.sort_custom(func(a: String, b: String) -> bool:
					return kc[a] > kc[b])
				var top: PackedStringArray = PackedStringArray()
				for i: int in range(mini(3, sorted_k.size())):
					top.append("%s:%d" % [sorted_k[i], kc[sorted_k[i]]])
				parts.append(",".join(top) if top.size() > 0 else "empty")
			"timestamp":
				parts.append(Time.get_datetime_string_from_system(false, true))
			"fps":
				parts.append("%dfps" % perf.get("fps", 0))
			"frame_ms":
				parts.append("%.1fms" % perf.get("frame_ms", 0.0))
			"physics_ms":
				parts.append("p%.1fms" % perf.get("physics_ms", 0.0))
			"draw_calls":
				parts.append("%ddc" % perf.get("draw_calls", 0))
			"render_objects":
				parts.append("%dobj" % perf.get("objects", 0))
			"render_tris":
				var prims: int = perf.get("primitives", 0)
				if prims >= 1_000_000:
					parts.append("%.1fMtri" % (prims / 1_000_000.0))
				elif prims >= 1000:
					parts.append("%.0fKtri" % (prims / 1000.0))
				else:
					parts.append("%dtri" % prims)
			"static_mem":
				parts.append("%.0fMB" % perf.get("static_mem_mb", 0.0))
	return sep.join(parts)



# -- Lighting + Motes ----------------------------------------------------------
# Emissive entities get OmniLight3D (cast on surroundings) + particle motes

# Light configs derived from biome_data.py LIGHT_LAYERS
const CAUSTIC_COLORS := [
	Color(0.45, 0.35, 0.15),  # warm amber — mineral refraction
	Color(0.20, 0.35, 0.25),  # muted teal — wet stone scatter
	Color(0.25, 0.22, 0.40),  # desaturated violet — deep crystal
]

const LIGHT_KINDS := {
	"crystal_cluster": {
		"color": Color(0.35, 0.40, 0.70),
		"energy": 18.0,
		"range": 28.0,   # wider — visible as distant glow through fog
		"attenuation": 0.5,  # softer falloff — gradual arrival, no hard edge
		"prismatic": true,
		"caustic_intensity": 0.4,
		"caustic_radius": 3.5,
		"facet_spread": 2.5,
		"mote_color": Color(0.3, 0.35, 0.6),
		"mote_count": 40,
		"mote_radius": 5.0,
		"mote_height": 5.0,
		"mote_size": 1.0,
		"mote_arrangement": "lattice_7",
	},
	"giant_fungus": {
		"color": Color(0.18, 0.30, 0.10),
		"energy": 10.0,
		"range": 20.0,
		"attenuation": 0.6,
		"mote_color": Color(0.25, 0.08, 0.35),
		"mote_count": 32,
		"mote_radius": 5.0,
		"mote_height": 6.0,
		"mote_size": 0.75,
		"mote_arrangement": "scatter_7",
	},
	"moss_patch": {
		"color": Color(0.10, 0.40, 0.08),
		"energy": 8.0,
		"range": 16.0,
		"attenuation": 0.6,
		"mote_color": Color(0.1, 0.5, 0.08),
		"mote_count": 16,
		"mote_radius": 2.5,
		"mote_height": 3.0,
		"mote_size": 0.45,
		"mote_arrangement": "ground_hug_4",
	},
	"firefly": {
		"color": Color(0.95, 0.75, 0.30),
		"energy": 6.0,
		"range": 14.0,
		"attenuation": 0.5,
		"mote_color": Color(0.95, 0.8, 0.3),
		"mote_count": 4,
		"mote_radius": 1.5,
		"mote_height": 2.5,
		"mote_size": 0.40,
		"mote_arrangement": "solo",
	},
	"filament": {
		"color": Color(0.30, 0.40, 0.55),
		"energy": 14.0,
		"range": 26.0,
		"attenuation": 0.5,
		"mote_color": Color(0.35, 0.45, 0.6),
		"mote_count": 20,
		"mote_radius": 2.5,
		"mote_height": 4.0,
		"mote_size": 0.55,
		"mote_arrangement": "chain_5",
	},
	"ceiling_moss": {
		"color": Color(0.6, 0.40, 0.12),
		"energy": 16.0,
		"range": 26.0,
		"attenuation": 0.5,
		"mote_color": Color(0.8, 0.55, 0.15),
		"mote_count": 32,
		"mote_radius": 5.0,
		"mote_height": 8.0,
		"mote_size": 0.75,
		"mote_arrangement": "stream_vert_5",
	},
}

var emissive_lights: Array[Node3D] = []
var emissive_decals: Array[Decal] = []
var decal_texture_cache: Dictionary = {}  # color_key → GradientTexture2D
var mote_particles: Array[Node3D] = []  # mixed: GPUParticles3D (flow) + MeshInstance3D (structural atoms)

# Light pipe architecture — fixed number of OmniLights, always present.
# Each pipe covers a color family (warm/cool/organic). Pipes smoothly
# lerp to the best matching emissive cluster in the FOV. No creation,
# no destruction, no pop. 3 biome pipes + 1 reserved for player torch.
#
# Pipe config per biome: {name, color, kinds[], energy, range, attenuation}
# Initialized once at spawn, redistributed each manifest update.
const BIOME_LIGHT_PIPES := {
	"cavern": [
		{"name": "warm", "color": Color(0.50, 0.35, 0.12),
		 "kinds": ["giant_fungus", "ceiling_moss", "firefly"],
		 "energy": 9.0, "range": 28.0, "attenuation": 0.7},
		{"name": "cool", "color": Color(0.30, 0.35, 0.60),
		 "kinds": ["crystal_cluster", "filament", "exit_lure"],
		 "energy": 11.0, "range": 28.0, "attenuation": 0.7},
		{"name": "organic", "color": Color(0.15, 0.35, 0.10),
		 "kinds": ["moss_patch"],
		 "energy": 7.0, "range": 24.0, "attenuation": 0.7},
	],
	"outdoor": [
		{"name": "warm", "color": Color(0.55, 0.45, 0.18),
		 "kinds": ["firefly", "giant_fungus"],
		 "energy": 10.0, "range": 22.0, "attenuation": 0.5},
		{"name": "cool", "color": Color(0.25, 0.30, 0.45),
		 "kinds": ["crystal_cluster"],
		 "energy": 12.0, "range": 22.0, "attenuation": 0.5},
		{"name": "green", "color": Color(0.12, 0.30, 0.08),
		 "kinds": ["moss_patch"],
		 "energy": 8.0, "range": 18.0, "attenuation": 0.5},
	],
}

var light_pipes: Array[Dictionary] = []  # runtime pipe state: {node, fill_node, target_pos, cfg}

# Projection banner — 7 concentric cylinders faking mid-distance atmosphere.
# Created once at spawn, follow camera. Config from biome banner_layers.
var banner_cylinders: Array[MeshInstance3D] = []

# Mote dirty flag — only rebuild lights/decals/particles when the scene
# actually changes, not every manifest tick. Motes are ambient decoration;
# they loop in place. Rebuild triggers: new tile, tension state change,
# entity count change. Config hook for encounter-driven rebuilds.
var mote_dirty: bool = true
var last_entity_count: int = 0
var last_tension_state: String = ""


func _get_decal_texture(tint: Color) -> GradientTexture2D:
	"""Radial falloff texture for ground Decals, tinted per emissive kind.
	Uses RGB falloff (bright center → black edge) so emission naturally fades.
	Alpha channel provides the Decal shape mask."""
	var key: String = "%d_%d_%d" % [int(tint.r * 255), int(tint.g * 255), int(tint.b * 255)]
	if decal_texture_cache.has(key):
		return decal_texture_cache[key]

	var grad := Gradient.new()
	# Center: tinted color with full alpha → edge: black with zero alpha
	grad.set_color(0, Color(tint.r, tint.g, tint.b, 0.8))
	grad.add_point(0.3, Color(tint.r * 0.6, tint.g * 0.6, tint.b * 0.6, 0.5))
	grad.add_point(0.7, Color(tint.r * 0.15, tint.g * 0.15, tint.b * 0.15, 0.15))
	grad.set_color(grad.get_point_count() - 1, Color(0.0, 0.0, 0.0, 0.0))

	var tex := GradientTexture2D.new()
	tex.gradient = grad
	tex.fill = GradientTexture2D.FILL_RADIAL
	tex.fill_from = Vector2(0.5, 0.5)
	tex.fill_to = Vector2(0.5, 0.0)
	tex.width = 128
	tex.height = 128

	decal_texture_cache[key] = tex
	return tex

func _build_heptagonal_mote_mesh(radius: float) -> ArrayMesh:
	"""Build a flat 7-vertex heptagonal disc for use as a mote draw pass.

	Seven rim verts + one center vert = 7 triangles. Billboarded at the
	particle material level so the seven edges always face the camera. The
	canonical test fixture for the visual system — see
	design_heptagonal_mote.md. One ArrayMesh is built per mote emitter
	(not per particle) so the caller can set_surface_material with that
	emitter's color; cost is ~negligible (8 verts, 7 tris).
	"""
	var verts := PackedVector3Array()
	var normals := PackedVector3Array()
	var uvs := PackedVector2Array()
	var indices := PackedInt32Array()

	# Center vertex
	verts.append(Vector3.ZERO)
	normals.append(Vector3(0, 0, 1))
	uvs.append(Vector2(0.5, 0.5))

	# Seven rim vertices — one prime-rotation around Z.
	# Offset by -PI/2 so one vertex points straight up in mesh space,
	# giving the silhouette a canonical orientation when billboarded.
	var n: int = 7
	for i in range(n):
		var theta: float = -PI * 0.5 + TAU * float(i) / float(n)
		verts.append(Vector3(cos(theta) * radius, sin(theta) * radius, 0))
		normals.append(Vector3(0, 0, 1))
		uvs.append(Vector2(0.5 + cos(theta) * 0.5, 0.5 + sin(theta) * 0.5))

	# Seven triangles fanning out from center. Wind counter-clockwise so
	# the +Z face is the front face under default culling.
	for i in range(n):
		var a: int = 0
		var b: int = 1 + i
		var c: int = 1 + ((i + 1) % n)
		indices.append(a)
		indices.append(b)
		indices.append(c)

	var arrays: Array = []
	arrays.resize(Mesh.ARRAY_MAX)
	arrays[Mesh.ARRAY_VERTEX] = verts
	arrays[Mesh.ARRAY_NORMAL] = normals
	arrays[Mesh.ARRAY_TEX_UV] = uvs
	arrays[Mesh.ARRAY_INDEX] = indices

	var mesh := ArrayMesh.new()
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	return mesh


## Meta-pixel mote structure spawner — places heptagonal atom MeshInstance3Ds
## at each offset returned by the kind's arrangement template, centered on the
## entity's light position. Each atom uses the shared MoteMaterials factory
## (same BILLBOARD_PARTICLES invariant as the ambient particles, though these
## are static — billboarding still rotates each atom to face camera).
##
## Arrangements live in mote_arrangements.gd and are validated by
## tests/test_mote_arrangements.gd. Config lookup is
## LIGHT_KINDS[kind]["mote_arrangement"] defaulting to "solo".
##
## Static atoms + drift particle flow = structure + motion. The structure is
## the meta-pixel reading; the particles are the ambient life around it.
func _spawn_mote_structure(ent: Dictionary, cfg: Dictionary) -> void:
	var arrangement_name: String = cfg.get("mote_arrangement", "solo")
	var offsets: Array = MoteArrangements.get_offsets(arrangement_name)
	if offsets.is_empty():
		return

	var atom_radius: float = cfg.get("mote_size", 0.15)
	# Structure spawns at full mote_height above entity base — NOT half.
	# Half was burying the arrangement inside the host mesh (crystal clusters
	# etc. are several meters tall; a structure at 1.5m is inside the volume).
	var center: Vector3 = Vector3(
		ent.get("x", 0.0),
		ent.get("z", 0.0) + cfg.get("mote_height", 2.0),
		ent.get("y", 0.0)
	)

	for offset in offsets:
		var atom_mesh: ArrayMesh = _build_heptagonal_mote_mesh(atom_radius)
		var atom_mat: StandardMaterial3D = MoteMaterials.make_particle_mote_material(cfg["mote_color"])
		# Override billboard mode for static use. The factory returns
		# BILLBOARD_PARTICLES (correct for GPUParticles3D draw passes and
		# enforced by test_mote_materials.gd), but a plain MeshInstance3D
		# needs BILLBOARD_ENABLED — without it the flat disc stays locked
		# facing +Z in world space and disappears when viewed edge-on.
		atom_mat.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED
		# Boost emission energy slightly so the structural atoms read as
		# brighter than the ambient drift particles around them.
		atom_mat.emission_energy_multiplier = 28.0  # structural atoms must punch through fog haze
		atom_mesh.surface_set_material(0, atom_mat)

		var mi := MeshInstance3D.new()
		mi.mesh = atom_mesh
		mi.position = center + (offset as Vector3)
		# Force an oversized custom AABB so Godot's frustum culling doesn't
		# eat the atom when billboard rotates the flat disc at runtime.
		# The auto-computed AABB is ~(atom_radius)³ which is smaller than
		# the actual rendered pixel extent after billboard rotation.
		mi.custom_aabb = AABB(
			Vector3(-atom_radius * 2.0, -atom_radius * 2.0, -atom_radius * 2.0),
			Vector3(atom_radius * 4.0, atom_radius * 4.0, atom_radius * 4.0)
		)
		mi.name = "MoteAtom_%s_%s" % [ent.get("kind", "?"), arrangement_name]
		add_child(mi)
		mote_particles.append(mi as Node3D)  # reuse cleanup path


func _update_motes() -> void:
	# Atmospheric mode: rebuild emissive decals + particles + persistent
	# pipe lights from current entities each time the scene changes.
	# Decals and particles rebuild each update (cheap, position-dependent).
	# OmniLights are PERSISTENT — see persistent_lights dict. They stay alive
	# and get energy updates, never destroyed until env exit.
	for d: Decal in emissive_decals:
		if is_instance_valid(d):
			d.queue_free()
	emissive_decals.clear()
	for p: Node3D in mote_particles:
		if is_instance_valid(p):
			p.queue_free()
	mote_particles.clear()

	# Beacon hierarchy — brain tags emissives with render_tier:
	#   0 = beacon (full: 2 OmniLights + Decal + motes + shaft)
	#   1 = mid (Decal only, entity emission)
	#   2 = far (entity emission only, no external nodes)
	# Fallback: if no render_tier, use old distance sort for static manifests.
	var emissive_ents: Array[Dictionary] = []
	for ent: Dictionary in manifest.get("entities", []):
		if LIGHT_KINDS.has(ent.get("kind", "")):
			emissive_ents.append(ent)

	# If brain provides render_tier, use it. Otherwise fallback to distance sort.
	var has_tiers: bool = emissive_ents.size() > 0 and emissive_ents[0].has("render_tier")
	var _pwp: Vector3 = _player_pos()
	if not has_tiers:
		var cam_x: float = _pwp.x
		var cam_z: float = _pwp.z
		emissive_ents.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
			var da: float = (a["x"] - cam_x) ** 2 + (a["y"] - cam_z) ** 2
			var db: float = (b["x"] - cam_x) ** 2 + (b["y"] - cam_z) ** 2
			return da < db)

	# -- Light pipe redistribution --
	# Find the best target position for each pipe: nearest matching emissive
	# cluster center. Pipes smoothly lerp to targets. Always 3 lights total.
	for pipe: Dictionary in light_pipes:
		var pipe_kinds: Array = pipe["cfg"]["kinds"]
		# Lock rule: stay committed until you've walked far enough away.
		# Distance only — no view check. Backtracking keeps the same light.
		var current_valid: bool = false
		if pipe["active"]:
			current_valid = pipe["target_pos"].distance_squared_to(_pwp) < 40.0 * 40.0
		if not current_valid:
			# Find nearest matching emissive
			var best_dist: float = 9999.0
			var best_pos := Vector3.ZERO
			var found: bool = false
			for ent: Dictionary in emissive_ents:
				if not pipe_kinds.has(ent.get("kind", "")):
					continue
				var ex: float = ent.get("x", 0.0)
				var ey: float = ent.get("y", 0.0)
				var ez: float = ent.get("z", 0.0)
				var is_ceil: bool = ent.get("attachment_plane", "") == "ceiling"
				var ly: float = ez - 3.0 if is_ceil else ez + 5.0
				var candidate := Vector3(ex, ly, ey)
				var d: float = candidate.distance_squared_to(_pwp)
				if d < best_dist:
					best_dist = d
					best_pos = candidate
					found = true
			if found:
				var was_active: bool = pipe["active"]
				pipe["target_pos"] = best_pos
				pipe["active"] = true
				if not was_active:
					pipe["node"].position = best_pos
					pipe["fill_node"].position = best_pos + Vector3(0, -4.0, 0)
		# Slow lerp — pipe drifts like a living thing, never jumps
		var node: OmniLight3D = pipe["node"]
		var fill: OmniLight3D = pipe["fill_node"]
		node.position = node.position.lerp(pipe["target_pos"], 0.03)
		fill.position = fill.position.lerp(pipe["target_pos"] + Vector3(0, -4.0, 0), 0.03)
		# Dim if no matching emissive found (pipe has nothing to light)
		var target_e: float = pipe["cfg"]["energy"] if pipe["active"] else 0.0
		node.light_energy = lerpf(node.light_energy, target_e, 0.04)
		fill.light_energy = lerpf(fill.light_energy, target_e * 0.15, 0.04)

	# Sort emissives by distance — nearest get full treatment (motes + decals),
	# far ones get decals only. Budget: 12 mote slots max.
	var cam_pos_x: float = _pwp.x
	var cam_pos_z: float = _pwp.z
	emissive_ents.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		var da: float = (a.get("x", 0.0) - cam_pos_x) ** 2 + (a.get("y", 0.0) - cam_pos_z) ** 2
		var db: float = (b.get("x", 0.0) - cam_pos_x) ** 2 + (b.get("y", 0.0) - cam_pos_z) ** 2
		return da < db)
	var mote_budget: int = 12
	var motes_placed: int = 0

	for i in range(emissive_ents.size()):
		var ent: Dictionary = emissive_ents[i]
		var kind: String = ent.get("kind", "")
		if not LIGHT_KINDS.has(kind):
			continue
		var cfg: Dictionary = LIGHT_KINDS[kind]
		var base_y: float = ent.get("z", 0.0)
		var is_ceiling: bool = ent.get("attachment_plane", "") == "ceiling"
		var light_y: float = base_y - 3.0 if is_ceiling else base_y + 7.0
		var pos := Vector3(ent.get("x", 0.0), light_y, ent.get("y", 0.0))
		var hue_idx: int = ent.get("light_hue", 0)
		var hue_palettes: Dictionary = {
			"crystal_cluster": [Color(0.18, 0.20, 0.30), Color(0.22, 0.18, 0.28)],
			"giant_fungus": [Color(0.15, 0.25, 0.10), Color(0.20, 0.15, 0.22)],
			"moss_patch": [Color(0.10, 0.30, 0.08), Color(0.30, 0.22, 0.08),
						   Color(0.12, 0.18, 0.22), Color(0.20, 0.12, 0.18)],
			"ceiling_moss": [Color(0.35, 0.25, 0.10), Color(0.28, 0.30, 0.12)],
			"firefly": [Color(0.85, 0.65, 0.25), Color(0.70, 0.55, 0.20)],
			"filament": [Color(0.22, 0.28, 0.38), Color(0.28, 0.22, 0.35)],
		}
		var palette: Array = hue_palettes.get(kind, [cfg["color"]])
		var light_color: Color = palette[hue_idx % palette.size()]
		var spec: Array = ent.get("spectrum_state", [])
		if spec.size() == 3:
			light_color = Color(
				clampf(light_color.r + spec[0], 0.0, 1.0),
				clampf(light_color.g + spec[1], 0.0, 1.0),
				clampf(light_color.b + spec[2], 0.0, 1.0))
		var hue_seed: float = abs(sin(ent.get("x", 0.0) * 12.9898 + ent.get("y", 0.0) * 78.233))
		var e_var: float = 0.7 + hue_seed * 0.6

		# Ground Decal — only within 25m (beyond that, fog eats visibility anyway)
		var dx_decal: float = pos.x - cam_pos_x
		var dz_decal: float = pos.z - cam_pos_z
		if dx_decal * dx_decal + dz_decal * dz_decal > 625.0:  # 25m²
			continue
		var kind_entry: Dictionary = kind_config.get("kinds", {}).get(kind, {})
		var decal_cfg: Dictionary = kind_entry.get("decal", {})
		if decal_cfg.size() > 0:
			var decal := Decal.new()
			var d_radius: float = decal_cfg.get("emission_radius", 6.0) * ent.get("sv", 1.0)
			decal.size = Vector3(d_radius * 2.0, 4.0, d_radius * 2.0)
			var d_tint_blend: float = decal_cfg.get("tint_blend", 0.8)
			var d_tint := Color(
				light_color.r * d_tint_blend + (1.0 - d_tint_blend),
				light_color.g * d_tint_blend + (1.0 - d_tint_blend),
				light_color.b * d_tint_blend + (1.0 - d_tint_blend))
			var d_tex: GradientTexture2D = _get_decal_texture(d_tint)
			decal.texture_albedo = d_tex   # alpha channel = decal shape mask
			decal.texture_emission = d_tex  # RGB = emission glow
			decal.emission_energy = decal_cfg.get("emission_energy", 0.5) * e_var
			decal.albedo_mix = 0.12  # subtle ground tint + alpha mask
			decal.modulate = Color(1.0, 1.0, 1.0, 0.85)  # let texture do the tinting
			decal.normal_fade = 0.5
			if is_ceiling:
				# Ceiling decal — project UP onto ceiling plane, flipped fade
				decal.upper_fade = 0.8
				decal.lower_fade = 0.1
				decal.size = Vector3(d_radius * 2.0, 6.0, d_radius * 2.0)  # taller projection range
				decal.position = Vector3(pos.x, active_ceiling_y - 0.2, pos.z)
			else:
				decal.upper_fade = 0.1
				decal.lower_fade = 0.8
				decal.position = Vector3(pos.x, 0.2, pos.z)
			add_child(decal)
			emissive_decals.append(decal)

		# Prismatic caustics — small colored Decal patches refracted through crystal
		# Replaces 3 OmniLights with 3 tiny Decals — zero light draw calls
		if cfg.get("prismatic", false) and hue_seed > 0.4:  # ~60% of crystals
			var spread: float = cfg.get("facet_spread", 2.5)
			var c_energy: float = cfg.get("caustic_intensity", 0.4) * e_var * 0.5  # halved — subtle refractions
			var c_radius: float = cfg.get("caustic_radius", 3.5) * 0.6  # wider, softer patches
			for ci in range(CAUSTIC_COLORS.size()):
				var angle: float = (hue_seed * 360.0 + float(ci) * 120.0)
				var c_offset := Vector3(
					cos(deg_to_rad(angle)) * spread,
					0.0,
					sin(deg_to_rad(angle)) * spread)
				var caustic_decal := Decal.new()
				caustic_decal.size = Vector3(c_radius * 2.0, 3.0, c_radius * 2.0)
				var cc: Color = CAUSTIC_COLORS[ci]
				var c_tex: GradientTexture2D = _get_decal_texture(cc)
				caustic_decal.texture_albedo = c_tex    # alpha = shape mask
				caustic_decal.texture_emission = c_tex
				caustic_decal.emission_energy = c_energy * 1.2  # visible colored patches
				caustic_decal.albedo_mix = 0.08  # alpha mask + faint tint
				caustic_decal.modulate = Color(1.0, 1.0, 1.0, 0.7)
				caustic_decal.upper_fade = 0.1
				caustic_decal.lower_fade = 0.8
				caustic_decal.normal_fade = 0.5
				caustic_decal.position = Vector3(pos.x + c_offset.x, 0.15, pos.z + c_offset.z)
				add_child(caustic_decal)
				emissive_decals.append(caustic_decal)

		# Mote budget — nearest 12 emissives get full mote treatment.
		# Rest get decals only. Prevents particle system explosion.
		if motes_placed >= mote_budget:
			continue
		motes_placed += 1
		# See design_heptagonal_mote.md + design_meta_pixel_mote.md + the
		# arrangement library in mote_arrangements.gd + its regression test.
		# Runs alongside the ambient particle emitter below — this layer is
		# the visible STRUCTURE, the particles are the ambient FLOW.
		_spawn_mote_structure(ent, cfg)

		# Mote particles
		var particles := GPUParticles3D.new()
		particles.amount = cfg["mote_count"]
		particles.lifetime = 5.0
		particles.fixed_fps = 20
		particles.visibility_aabb = AABB(Vector3(-10, -4, -10), Vector3(20, 16, 20))

		var pmat := ParticleProcessMaterial.new()
		pmat.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
		pmat.emission_sphere_radius = cfg["mote_radius"]
		pmat.direction = Vector3(0, 1, 0)
		pmat.initial_velocity_min = 0.05
		pmat.initial_velocity_max = 0.15
		pmat.gravity = Vector3(0, -0.02, 0)
		# Natural ±20% variance so particles don't all look identical, but the
		# authored mesh size is respected. The previous 0.02–0.06 range was
		# shrinking the draw mesh to 2–6% of its authored size, which is why
		# motes were invisible regardless of mesh radius.
		pmat.scale_min = 0.8
		pmat.scale_max = 1.2
		particles.process_material = pmat

		# Seven-sided mote — the signature test fixture for the whole visual
		# system (design_heptagonal_mote.md). Every subsystem is validated
		# against this shape first; if it reads right on the mote, it scales.
		# Flat heptagonal disc, billboarded so all seven edges always face the
		# camera. Non-tiling shape + prime rotation count + Merkabah number.
		# Per-kind mesh radius — firefly butt (0.10) to Tron Bit (0.32).
		var mote_mesh_radius: float = cfg.get("mote_size", 0.15)
		var smesh: ArrayMesh = _build_heptagonal_mote_mesh(mote_mesh_radius)
		# Particle draw pass material via shared factory (mote_materials.gd).
		# BILLBOARD_PARTICLES is the load-bearing setting — see the regression
		# test at godot/tests/test_mote_materials.gd.
		var smat: StandardMaterial3D = MoteMaterials.make_particle_mote_material(cfg["mote_color"])
		smesh.surface_set_material(0, smat)
		particles.draw_pass_1 = smesh

		particles.position = Vector3(
			ent.get("x", 0.0),
			ent.get("z", 0.0) + cfg["mote_height"] * 0.5,
			ent.get("y", 0.0))
		add_child(particles)
		mote_particles.append(particles)

	# Light pipes handle all OmniLight redistribution above — no cleanup needed.

	# -- Ceiling light shafts (breaks in rock above, faint directional pools) --
	# Spawn a few SpotLights pointing down at random positions near emissives
	var shaft_count: int = 0
	for ent_s: Dictionary in emissive_ents:
		if shaft_count >= 6:
			break
		# Only some emissives get a shaft (40% chance)
		var shaft_seed: float = abs(sin(ent_s.get("x", 0.0) * 7.31 + ent_s.get("y", 0.0) * 13.37))
		if shaft_seed > 0.4:
			continue

		var spot := SpotLight3D.new()
		# Positioned high above the emissive, slightly offset
		spot.position = Vector3(
			ent_s.get("x", 0.0) + (shaft_seed - 0.2) * 4.0,
			12.0 + shaft_seed * 5.0,  # high up — ceiling break
			ent_s.get("y", 0.0) + (shaft_seed - 0.3) * 3.0
		)
		spot.rotation_degrees = Vector3(-80 - shaft_seed * 15.0, shaft_seed * 60.0, 0)
		# Dim warm light — not a spotlight, a shaft of ambient leaking in
		spot.light_color = Color(0.20, 0.18, 0.25)  # cool blue-gray, like indirect sky
		spot.light_energy = 3.0 + shaft_seed * 4.0
		spot.spot_range = 20.0
		spot.spot_angle = 15.0 + shaft_seed * 10.0  # narrow cone
		spot.spot_attenuation = 0.8
		spot.shadow_enabled = false  # perf: 6 shadow-casting spotlights was expensive
		add_child(spot)
		emissive_lights.append(spot)
		shaft_count += 1

	# -- Crystal SpotLights — max 3, nearest crystals only --
	var beam_count: int = 0
	for ent_c: Dictionary in emissive_ents:
		if beam_count >= 3:
			break
		if ent_c.get("kind", "") != "crystal_cluster":
			continue
		var cseed: float = abs(sin(ent_c.get("x", 0.0) * 5.17 + ent_c.get("y", 0.0) * 9.73))
		if cseed > 0.5:
			continue
		beam_count += 1
		var beam := SpotLight3D.new()
		beam.position = Vector3(ent_c.get("x", 0.0), 1.5, ent_c.get("y", 0.0))
		# Beam projects outward at a low angle — hits the floor/wall dramatically
		var beam_angle: float = cseed * 360.0
		beam.rotation_degrees = Vector3(-30 - cseed * 30.0, beam_angle, 0)
		var hue_idx: int = ent_c.get("light_hue", 0)
		var beam_colors: Array = [Color(0.15, 0.18, 0.40), Color(0.20, 0.10, 0.35)]
		beam.light_color = beam_colors[hue_idx % beam_colors.size()]
		beam.light_energy = 8.0 + cseed * 6.0
		beam.spot_range = 15.0
		beam.spot_angle = 20.0
		beam.spot_attenuation = 1.2
		beam.shadow_enabled = false
		add_child(beam)
		emissive_lights.append(beam)

	# -- Ceiling drip particles — max 6 nearest ceiling_moss --
	var drip_count: int = 0
	for ent: Dictionary in manifest.get("entities", []):
		if drip_count >= 6:
			break
		if ent.get("kind", "") != "ceiling_moss":
			continue
		drip_count += 1
		var drip := GPUParticles3D.new()
		drip.amount = 3
		drip.lifetime = 3.0
		drip.fixed_fps = 15
		drip.visibility_aabb = AABB(Vector3(-4, -10, -4), Vector3(8, 12, 8))
		var dmat := ParticleProcessMaterial.new()
		dmat.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
		dmat.emission_sphere_radius = 1.5
		dmat.direction = Vector3(0, -1, 0)
		dmat.initial_velocity_min = 0.5
		dmat.initial_velocity_max = 1.5
		dmat.gravity = Vector3(0, -2.0, 0)
		# Natural variance at authored size (same fix as ambient motes).
		dmat.scale_min = 0.8
		dmat.scale_max = 1.2
		drip.process_material = dmat
		# Prime-mote doctrine: ceiling drips are motes that happen to fall.
		# Same heptagonal test fixture — see design_heptagonal_mote.md.
		# Uses the same MoteMaterials factory so the BILLBOARD_PARTICLES
		# invariant is enforced by the same regression test.
		var dmesh: ArrayMesh = _build_heptagonal_mote_mesh(0.10)
		var dsmat: StandardMaterial3D = MoteMaterials.make_particle_mote_material(Color(0.5, 0.35, 0.10))
		dsmat.albedo_color = Color(0.6, 0.4, 0.12, 0.7)  # drips are slightly less transparent
		dsmat.emission_energy_multiplier = 3.0            # softer than ambient motes
		dmesh.surface_set_material(0, dsmat)
		drip.draw_pass_1 = dmesh
		drip.position = Vector3(ent.get("x", 0.0), ent.get("z", 0.0), ent.get("y", 0.0))
		add_child(drip)
		mote_particles.append(drip)

	# -- Creature scurry (rats/beetles/spiders dart away from camera) --
	_spawn_creatures()


# -- Input ---------------------------------------------------------------------

func _input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and mouse_captured:
		if USE_PHYSICS_RIG:
			# Yaw on the rig, pitch on the neck — mirrors fps_player.gd:60-62
			# so the capsule turns with the view rather than gliding sideways.
			player_rig.rotate_y(-event.relative.x * MOUSE_SENS)
			neck.rotate_x(-event.relative.y * MOUSE_SENS)
			neck.rotation.x = clampf(neck.rotation.x, deg_to_rad(-89), deg_to_rad(89))
		else:
			camera.rotation.y -= event.relative.x * MOUSE_SENS
			camera.rotation.x -= event.relative.y * MOUSE_SENS
			camera.rotation.x = clampf(camera.rotation.x, deg_to_rad(-89), deg_to_rad(89))

	if event.is_action_pressed("ui_cancel"):
		if mouse_captured:
			Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
			mouse_captured = false
		else:
			get_tree().quit()

	# Encounter HUD gets first shot at encounter-relevant input. Handles
	# kb + gamepad via action-based detection (menu_nav_*, menu_confirm,
	# portal). Only consumes when an encounter is active.
	if encounter_hud and encounter_hud.has_method("handle_input") \
			and encounter_hud.handle_input(event):
		return

	# Key bindings — use physical_keycode for layout-independent matching
	if event is InputEventKey and event.pressed and not event.echo:
		match event.physical_keycode:
			KEY_T, KEY_BRACKETLEFT, KEY_BRACKETRIGHT, KEY_BACKSLASH:  # telemetry tag
				# Shift+Cmd+T (chord) captures the current composition as a
				# stamp template — drop-in CAVERN_STAMPS entry. Check before
				# the single-modifier branches so the chord takes priority.
				if event.shift_pressed and event.meta_pressed:
					_save_stamp_capture()
				else:
					# Modifier-keyed semantic categories. Plain T = neutral
					# (legacy / unannotated). Modifiers tell the brain WHY:
					#   Shift+T  → interesting   (deliberate positive)
					#   Alt+T    → beautiful     (aesthetic)
					#   Ctrl+T   → dangerous     (warning)
					#   Cmd+T    → weird         (anomaly)
					var reason := "neutral"
					if event.shift_pressed:
						reason = "interesting"
					elif event.alt_pressed:
						reason = "beautiful"
					elif event.ctrl_pressed:
						reason = "dangerous"
					elif event.meta_pressed:
						reason = "weird"
					_save_tag(reason)
			KEY_L:  # cycle light state
				if connected:
					var msg := JSON.stringify({"cmd": "light_cycle"}) + "\n"
					tcp.put_data(msg.to_utf8_buffer())
			KEY_O:  # cycle outline mode (Moebius / Manga / Sable)
				_cycle_outline_mode()
			KEY_B:  # toggle tension cycle on/off
				if connected:
					var msg := JSON.stringify({"cmd": "tension_toggle"}) + "\n"
					tcp.put_data(msg.to_utf8_buffer())
			KEY_N:  # advance to next tension state (for live tuning)
				if connected:
					var msg := JSON.stringify({"cmd": "tension_advance"}) + "\n"
					tcp.put_data(msg.to_utf8_buffer())
			KEY_H:  # Home — teleport to hub spawn
				_teleport_player(Vector3(0.0, 0.0, -14.0), PI, deg_to_rad(-8.0))
				_show_toast("Returned to spawn")
			KEY_J:  # Jump to encounter_test slot (slot (0,2), world (0,32))
				_teleport_player(Vector3(0.0, 0.0, 32.0), 0.0, 0.0)
				_show_toast("Encounter test pocket")
			KEY_K:  # Jump to shadow_lab slot (slot (-2,0), world (-32,0))
				# Stand ~6m east of the orb looking west so the fixture
				# sits centered in frame with floor visible below it.
				_teleport_player(Vector3(-26.0, 0.0, 0.0), deg_to_rad(-90.0), deg_to_rad(-5.0))
				_show_toast("Shadow lab")
			KEY_I:  # Toggle iso dev camera (ortho 3/4 top-down)
				_toggle_iso_camera()
			KEY_1:
				_send_cast_event("fire")
			KEY_2:
				_send_cast_event("ice")
			KEY_3:
				_send_cast_event("electric")
			KEY_4:
				_send_cast_event("light")


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and not mouse_captured:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		mouse_captured = true


func _physics_process(delta: float) -> void:
	# HUD upkeep — typewriter, ceremony fade, vignette fade, camera shake.
	if encounter_hud:
		encounter_hud.tick(delta)
		# Hub arrival triggers consolidation; brain wipes staged XP into depth.
		var staged: float = 0.0
		var enc = manifest.get("encounter", null) if manifest else null
		if enc is Dictionary:
			var prog = enc.get("progression", null)
			if prog is Dictionary:
				staged = float(prog.get("staged_xp", 0.0))
		var _phub: Vector3 = _player_pos()
		encounter_hud.check_hub_arrival(_phub.x, _phub.z, staged)

	# Movement frozen during an encounter.
	if encounter_hud and encounter_hud.encounter_active:
		return

	# Crouch is shared between both paths (input state, not physics).
	var crouching := Input.is_action_pressed("crouch")

	if USE_PHYSICS_RIG:
		_physics_process_rig(delta, crouching)
	else:
		_physics_process_legacy(delta, crouching)

	# Lean — body yaw stays put; camera tilts + offsets via rotation.z. This
	# runs in both paths since the camera is a leaf in the rig hierarchy too,
	# so local rotation.z composes cleanly.
	var target_lean: float = 0.0
	if Input.is_action_pressed("lean_left"):
		target_lean = -1.0
	elif Input.is_action_pressed("lean_right"):
		target_lean = 1.0
	lean_state = lerpf(lean_state, target_lean, CAMERA_LERP_SMOOTHNESS * delta)
	camera.rotation.z = -lean_state * deg_to_rad(LEAN_TILT_DEG)

	# -- Shared post-movement tail (both paths) --
	# Creatures react to camera (flee, scatter on shatter, debris settle).
	_update_creatures(delta)
	# Shadow-lab orbs drift per config animation.drift.
	_update_shadow_orbs(delta)
	# Iso dev camera tracks player XZ when active. Cheap no-op otherwise.
	if iso_active:
		_update_iso_camera_position()
		_update_player_avatar()

	# Follow-camera planes track the player on their parallel axes.
	# Floor/ceiling: track X/Z, keep Y at configured offset.
	# Walls: track Y/Z (or Y/X), keep lateral offset fixed.
	var ppos: Vector3 = _player_pos()
	for tag in plane_nodes:
		var entry: Dictionary = plane_nodes[tag]
		if entry.get("follow", true):
			var node: MeshInstance3D = entry["node"]
			var pkind: String = entry.get("kind", "ground")
			if pkind == "wall":
				# Wall planes keep their lateral offset, track the other two axes
				# X-normal walls: keep X, track Y and Z
				# Z-normal walls (brain Y): keep Z, track X and Y
				if abs(node.rotation_degrees.z) > 45.0:
					# X-normal wall — rotated around Z
					node.position.y = ppos.y
					node.position.z = ppos.z
				else:
					# Z-normal wall — rotated around X
					node.position.x = ppos.x
					node.position.y = ppos.y
			else:
				# Floor/ceiling — track X/Z, Y follows terrain height
				node.position.x = ppos.x
				node.position.z = ppos.z
				if pkind == "ground":
					var t_z: float = manifest.get("camera", {}).get("terrain_z", 0.0)
					node.position.y = entry.get("offset", 0.0) + t_z
				elif pkind == "ceiling":
					var t_z: float = manifest.get("camera", {}).get("terrain_z", 0.0)
					node.position.y = entry.get("offset", CEILING_PLANE_Y_DEFAULT) + t_z

	# Banner cylinders follow player X/Z, keep their Y offset
	for bc: MeshInstance3D in banner_cylinders:
		bc.position.x = ppos.x
		bc.position.z = ppos.z


# --- Rig physics path (USE_PHYSICS_RIG) -----------------------------------
# Drives a CharacterBody3D via move_and_slide. Gravity + jump handled by
# is_on_floor(); XZ velocity set from input direction. Playable envelope
# applied after move_and_slide as a position fixup (soft pushback + clamp).
# Crouch is a neck-height lerp so the capsule shape doesn't need swapping.
var rig_neck_standing_y: float = EYE_HEIGHT


func _physics_process_rig(delta: float, crouching: bool) -> void:
	# Gamepad right-stick look — yaw on rig (so the capsule turns with view),
	# pitch on neck. Additive with mouse look (both write the same nodes).
	var look_vec := Input.get_vector("look_left", "look_right", "look_up", "look_down")
	if look_vec.length_squared() > 0.0001:
		player_rig.rotate_y(-look_vec.x * GAMEPAD_LOOK_SENS * delta)
		neck.rotate_x(-look_vec.y * GAMEPAD_LOOK_SENS * delta)
		neck.rotation.x = clampf(neck.rotation.x, PITCH_MIN, PITCH_MAX)

	# Horizontal input. Forward/right derived from the rig's basis (yaw-only),
	# so sprint direction doesn't tilt when pitching the view down.
	var input_vec := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var basis: Basis = player_rig.global_transform.basis
	var dir: Vector3 = basis.x * input_vec.x + basis.z * input_vec.y
	dir.y = 0.0
	if dir.length_squared() > 0.001:
		dir = dir.normalized()

	var speed := MOVE_SPEED
	if crouching:
		speed = MOVE_SPEED * 0.55
	elif Input.is_action_pressed("sprint"):
		speed = MOVE_SPEED * SPRINT_MULTIPLIER

	# Vertical — gravity + jump. is_on_floor() checks collision against the
	# ground-plane StaticBody3D + any entity/wall colliders below the capsule.
	if not player_rig.is_on_floor():
		player_rig.velocity.y -= GRAVITY * delta
	if Input.is_action_just_pressed("jump") and player_rig.is_on_floor() and not crouching:
		player_rig.velocity.y = JUMP_VELOCITY

	# Horizontal velocity set directly from input (no accel for now — matches
	# legacy path's instant response). Godot's slide handles wall collisions.
	player_rig.velocity.x = dir.x * speed
	player_rig.velocity.z = dir.z * speed
	player_rig.move_and_slide()

	# Playable envelope — soft pushback + hard clamp. Applied AFTER slide so
	# colliders do their work first and the envelope only reins in what escaped.
	var envelope: Dictionary = manifest.get("playable_envelope", {})
	var env_radius: float = float(envelope.get("radius", 0.0))
	if env_radius > 0.0:
		var env_softness: float = float(envelope.get("softness", 1.0))
		var rp: Vector3 = player_rig.position
		var dist_from_origin: float = sqrt(rp.x * rp.x + rp.z * rp.z)
		if dist_from_origin > env_radius:
			var overshoot: float = dist_from_origin - env_radius
			var pushback_mag: float = overshoot * env_softness * delta
			var inv_d: float = 1.0 / dist_from_origin
			rp.x -= rp.x * inv_d * pushback_mag
			rp.z -= rp.z * inv_d * pushback_mag
			var dist_after: float = sqrt(rp.x * rp.x + rp.z * rp.z)
			if dist_after > env_radius:
				var clamp_scale: float = env_radius / dist_after
				rp.x *= clamp_scale
				rp.z *= clamp_scale
			player_rig.position = rp

	# Crouch — lerp neck height instead of swapping capsule shape. Camera
	# rides the neck so the view dips smoothly. Matches fps_player.gd:113-128.
	var crouch_target_y: float = rig_neck_standing_y - CROUCH_HEIGHT_OFFSET if crouching else rig_neck_standing_y
	neck.position.y = lerpf(neck.position.y, crouch_target_y, CAMERA_LERP_SMOOTHNESS * delta)


# --- Legacy physics path (DEPRECATED — delete in commit 2 once UAT passes) -
# The hand-rolled Camera3D + manual sphere-distance push-out + terrain_z
# eye-height loop. Kept behind USE_PHYSICS_RIG = false for A/B regression.
func _physics_process_legacy(delta: float, crouching: bool) -> void:
	# Gamepad right-stick look — analog, deadzone applied by InputMap.
	# Additive to mouse look (both work simultaneously).
	var look_vec := Input.get_vector("look_left", "look_right", "look_up", "look_down")
	if look_vec.length_squared() > 0.0001:
		camera.rotation.y -= look_vec.x * GAMEPAD_LOOK_SENS * delta
		camera.rotation.x -= look_vec.y * GAMEPAD_LOOK_SENS * delta
		camera.rotation.x = clampf(camera.rotation.x, PITCH_MIN, PITCH_MAX)

	# Horizontal input with sprint modifier.
	var input_vec := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var dir := (camera.global_transform.basis.x * input_vec.x
		+ camera.global_transform.basis.z * input_vec.y)
	dir.y = 0.0
	if dir.length_squared() > 0.001:
		dir = dir.normalized()

	var speed := MOVE_SPEED
	if crouching:
		speed = MOVE_SPEED * 0.55
	elif Input.is_action_pressed("sprint"):
		speed = MOVE_SPEED * SPRINT_MULTIPLIER

	var new_pos: Vector3 = camera.position + dir * speed * delta

	# Spatial cull — refresh the nearby_colliders window when the player
	# drifts out of the cached zone. Push-out then iterates the culled
	# list (~30) instead of the full collision_objects (800+). Physics
	# hot path cost drops ~25× compared to iterating the full set.
	var _cull_dx: float = new_pos.x - last_cull_pos.x
	var _cull_dz: float = new_pos.z - last_cull_pos.y
	if _cull_dx * _cull_dx + _cull_dz * _cull_dz > COLLIDER_CULL_REFRESH * COLLIDER_CULL_REFRESH:
		_refresh_nearby_colliders(new_pos.x, new_pos.z)

	for coll: Dictionary in nearby_colliders:
		var dx: float = new_pos.x - coll["x"]
		var dz: float = new_pos.z - coll["z"]
		var dist_sq: float = dx * dx + dz * dz
		var min_dist: float = coll["r"] + 0.5
		if dist_sq < min_dist * min_dist and dist_sq > 0.001:
			var dist: float = sqrt(dist_sq)
			var push: float = min_dist - dist
			new_pos.x += (dx / dist) * push
			new_pos.z += (dz / dist) * push

	# Playable envelope — soft pushback + hard clamp.
	var envelope: Dictionary = manifest.get("playable_envelope", {})
	var env_radius: float = float(envelope.get("radius", 0.0))
	if env_radius > 0.0:
		var env_softness: float = float(envelope.get("softness", 1.0))
		var dist_from_origin: float = sqrt(new_pos.x * new_pos.x
			+ new_pos.z * new_pos.z)
		if dist_from_origin > env_radius:
			var overshoot: float = dist_from_origin - env_radius
			var pushback_mag: float = overshoot * env_softness * delta
			var inv_d: float = 1.0 / dist_from_origin
			new_pos.x -= new_pos.x * inv_d * pushback_mag
			new_pos.z -= new_pos.z * inv_d * pushback_mag
			var dist_after: float = sqrt(new_pos.x * new_pos.x
				+ new_pos.z * new_pos.z)
			if dist_after > env_radius:
				var clamp_scale: float = env_radius / dist_after
				new_pos.x *= clamp_scale
				new_pos.z *= clamp_scale

	# Terrain elevation — brain sends terrain_z, camera follows the field.
	var terrain_z: float = manifest.get("camera", {}).get("terrain_z", 0.0)
	var crouch_offset: float = CROUCH_HEIGHT_OFFSET if crouching else 0.0
	var terrain_ground_y: float = EYE_HEIGHT + terrain_z - crouch_offset

	var on_floor: bool = (camera.position.y <= terrain_ground_y + 0.05) and vertical_velocity <= 0.0
	if Input.is_action_just_pressed("jump") and on_floor and not crouching:
		vertical_velocity = JUMP_VELOCITY
		on_floor = false
	if not on_floor:
		vertical_velocity -= GRAVITY * delta
	var candidate_y: float = camera.position.y + vertical_velocity * delta
	if candidate_y <= terrain_ground_y:
		candidate_y = terrain_ground_y
		vertical_velocity = 0.0
	if vertical_velocity == 0.0:
		candidate_y = lerpf(camera.position.y, terrain_ground_y, 7.0 * delta)
	new_pos.y = candidate_y
	camera.position = new_pos
