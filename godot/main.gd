extends Node3D

## Sanctum Terminal — Godot viewer for Python brain manifests.
## Connects to brain_server.py via TCP for live streaming manifests.
## Falls back to static manifest.json if server isn't running.

const MOVE_SPEED := 8.0
const MOUSE_SENS := 0.002
const EYE_HEIGHT := 2.5
const SERVER_HOST := "127.0.0.1"
const SERVER_PORT := 9877

const MoteMaterials = preload("res://mote_materials.gd")
const MoteArrangements = preload("res://mote_arrangements.gd")

# Plane-attachment architecture (Design Law #14, Phase 3).
# Canonical ceiling height is now config-driven: resolved from the manifest's
# `planes` array at spawn time and cached in `active_ceiling_y`. The constant
# remains as the legacy fallback if the manifest omits planes entirely.
const CEILING_PLANE_Y_DEFAULT: float = 15.0
var active_ceiling_y: float = CEILING_PLANE_Y_DEFAULT

var camera: Camera3D
var env_node: WorldEnvironment
var godot_env: Environment
var manifest: Dictionary
var mouse_captured := true

# Collision
var collision_objects: Array[Dictionary] = []

# Mesh cache
var mesh_cache: Dictionary = {}
var mesh_bounds: Dictionary = {}

# Live connection
var tcp: StreamPeerTCP
var connected := false
var buf: String = ""
var update_timer: float = 0.0
const UPDATE_INTERVAL := 0.1  # send camera 10x/sec

# MultiMesh nodes per kind (for live rebuild)
var kind_nodes: Dictionary = {}

# Plane-attachment architecture: tag → {node, follow} dict, driven by
# manifest.planes. Ground/ceiling/future walls all live here.
var plane_nodes: Dictionary = {}

# HUD
var hud_label: Label


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
	_spawn_planes()
	_spawn_entities()
	_update_motes()
	_setup_hud()
	_aim_spawn_heading()  # Point camera at nearest natural landmark for spawn composition

	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED

	# Connect to brain server
	_connect_to_brain()


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
		var scene: PackedScene = load(glb_path)
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

	# Clean room: fog OFF — see everything at all distances
	godot_env.fog_enabled = false

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

	# Clean room: neutral grey ambient, no color bias
	godot_env.ambient_light_color = Color(1.0, 1.0, 1.0)
	godot_env.ambient_light_energy = 1.0  # full flat ambient — no shadows, no drama
	godot_env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR

	godot_env.tonemap_mode = 2
	godot_env.tonemap_white = 5.0

	# -- CLEAN ROOM MODE --
	# Everything off. Neutral ambient only. See shapes honestly.
	# Re-enable systems one at a time to build lighting intentionally.
	godot_env.glow_enabled = false
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

	# Clean room: sun/moon OFF — ambient only
	pass


func _setup_camera() -> void:
	camera = Camera3D.new()
	var cam_data: Dictionary = manifest.get("camera", {})
	camera.position = Vector3(cam_data.get("x", 0.0), EYE_HEIGHT, cam_data.get("y", 0.0))
	camera.rotation_degrees.y = cam_data.get("heading", 0.0)
	camera.rotation_degrees.x = 10.0  # upward tilt — catches stalactites + ceiling features naturally
	# Armor glow — warm omnidirectional bloom at waist height.
	# Not a flashlight — a lantern. Lights ground AND objects equally from
	# player's body, like bioluminescent armor plating. Soft dome of presence.
	var armor_glow := OmniLight3D.new()
	armor_glow.name = "ArmorGlow"
	armor_glow.light_color = Color(1.0, 1.0, 1.0)  # clean room — neutral white
	armor_glow.light_energy = 0.0  # OFF — ambient only, no point lights
	armor_glow.omni_range = 1.0
	armor_glow.omni_attenuation = 1.0
	armor_glow.shadow_enabled = false
	armor_glow.position = Vector3(0.0, -1.2, 0.0)  # waist height below camera
	camera.add_child(armor_glow)


func _aim_spawn_heading() -> void:
	"""Point camera at the nearest natural mega_column outside the spawn clearance.

	The foreground silhouette comes from the world's existing honeycomb, not from
	a staged blocking object. Camera is aimed with a 20° offset so the landmark
	falls in the right-forward peripheral instead of dead-center.
	"""
	const SPAWN_CLEARANCE: float = 18.0
	const IDEAL_MIN_DIST: float = 18.0
	const IDEAL_MAX_DIST: float = 32.0
	var cam_x: float = camera.position.x
	var cam_z: float = camera.position.z
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
	# Compute heading to face landmark, then offset 20° so it sits in right peripheral
	var dx: float = best_x - cam_x
	var dz: float = best_z - cam_z
	# Godot: -Z is forward. atan2(-dx, dz) gives heading where 0 = +Z forward
	var landmark_heading: float = atan2(dx, -dz)
	# Offset 35° LEFT so the landmark sits clearly in right-forward peripheral,
	# not center-blocking. FOV 52° means 20° was still near-center; 35° pushes
	# the landmark to the right edge of the frame so foreground is open.
	var peripheral_offset: float = deg_to_rad(-35.0)
	var final_heading: float = landmark_heading + peripheral_offset
	camera.rotation.y = final_heading
	print("Spawn aim: landmark at (%.1f, %.1f), dist %.1fm, heading %.1f°" % [
		best_x, best_z, sqrt(dx*dx + dz*dz), rad_to_deg(final_heading)])
	var fog_data: Dictionary = manifest.get("fog", {})
	camera.far = fog_data.get("far", 55.0) * 2.5  # extended for skeleton silhouettes
	camera.fov = 62.0  # wider peripheral — catches ceiling features + passive pull cues
	add_child(camera)

	# Initialize light pipes — 3 fixed OmniLights, created once, live forever.
	# Each pipe covers a color family. Positions lerp to nearest matching emissive.
	var biome_name: String = manifest.get("biome", "cavern")
	var pipe_cfgs: Array = BIOME_LIGHT_PIPES.get(biome_name, BIOME_LIGHT_PIPES["cavern"])
	for pipe_cfg: Dictionary in pipe_cfgs:
		var primary := OmniLight3D.new()
		primary.light_color = pipe_cfg["color"]
		primary.light_energy = pipe_cfg["energy"]
		primary.omni_range = pipe_cfg["range"]
		primary.omni_attenuation = pipe_cfg["attenuation"]
		primary.shadow_enabled = false
		primary.position = camera.position  # start at player, drift to nearest match
		add_child(primary)

		var fill := OmniLight3D.new()
		fill.light_color = pipe_cfg["color"]
		fill.light_energy = pipe_cfg["energy"] * 0.15
		fill.omni_range = pipe_cfg["range"] * 0.5
		fill.omni_attenuation = pipe_cfg["attenuation"] * 1.3
		fill.shadow_enabled = false
		fill.position = camera.position
		add_child(fill)

		light_pipes.append({
			"node": primary, "fill_node": fill, "cfg": pipe_cfg,
			"target_pos": camera.position, "active": false,
		})

	# CLEAN ROOM: banner cylinders OFF
	var banner_layers: Array = []  # manifest.get("banner_layers", [])
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
		mi.position = Vector3(camera.position.x, bl.get("height", 15.0) * 0.3, camera.position.z)
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

	if abs(nz) > 0.5:
		# Floor or ceiling — vertical plane
		if nz < 0.0:
			mi.rotation_degrees.x = 180.0
		mi.position.y = offset
	elif abs(nx) > 0.5:
		# Left/right wall — rotate around Z to face laterally
		mi.rotation_degrees.z = 90.0 if nx > 0.0 else -90.0
		mi.position.x = offset
	elif abs(ny) > 0.5:
		# Front/back wall — rotate around X (brain Y = godot Z)
		mi.rotation_degrees.x = 90.0 if ny > 0.0 else -90.0
		mi.position.z = offset
	add_child(mi)

	plane_nodes[tag] = {
		"node": mi,
		"follow": bool(p.get("follow_camera", true)),
		"kind": p.get("kind", "ground"),
		"offset": offset,
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
		# Wall planes: vertical UV projection + height darkening gradient
		var is_wall: bool = plane_kind == "wall"
		mat.set_shader_parameter("vertical_surface", is_wall)
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
		# Creature kinds get their own MeshInstance3D via _spawn_creatures().
		# Exclude from MultiMesh to prevent ghost duplicates at spawn point.
		if CREATURE_KINDS.has(kind):
			continue
		if not by_kind.has(kind):
			by_kind[kind] = []
		by_kind[kind].append(ent)

		var coll_r: float = ent.get("collision_radius", 0.0)
		if coll_r > 0.0:
			# Skip collision for ceiling-attached entities — they hang above head height.
			if ent.get("attachment_plane", "") != "ceiling":
				collision_objects.append({"x": ent.get("x", 0.0), "z": ent.get("y", 0.0), "r": coll_r})

	for kind: String in by_kind:
		_create_multimesh_for_kind(kind, by_kind[kind])
	_spawn_contact_shadows(by_kind)


# Kinds that get dark contact shadow Decals at their base.
# Radius multiplier scales with the kind's visual footprint.
const CONTACT_SHADOW_KINDS := {
	"mega_column": 5.0, "column": 3.5, "boulder": 2.5, "stalagmite": 1.5,
	"giant_fungus": 2.0, "crystal_cluster": 1.8, "dead_log": 1.5,
	"buttress": 2.5,
}

var contact_shadow_decals: Array[Decal] = []

func _spawn_contact_shadows(by_kind: Dictionary) -> void:
	# CLEAN ROOM: no contact shadows
	return
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
	mm.use_colors = true
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
			var base_s: float = orig_scale * sv
			var p_hash: float = abs(sin(ent.get("x", 0.0) * 3.17 + ent.get("y", 0.0) * 7.31))
			var p_hash2: float = abs(sin(ent.get("x", 0.0) * 11.9 + ent.get("y", 0.0) * 5.47))
			# Columns use stalagmite mesh via MESH_ALIAS (shared shape language).
			# Per-instance roll: 70% stay upright (standard column = wide-base stalagmite
			# shape = classical column), 30% become STALACTITE VARIANTS hanging from
			# the ceiling (inverted, narrow tip pointing down, wide base at ceiling).
			# Together these create the real eroded-cavern look: stalagmites rising
			# from the floor AND stalactites hanging from above.
			if kind == "mega_column" or kind == "column":
				# Brain owns the stalactite decision via attachment_plane field.
				# Fallback to hash for static manifests without the field.
				var is_stalactite: bool = ent.get("attachment_plane", "") == "ceiling"
				if not ent.has("attachment_plane"):
					var variant_hash: float = abs(sin(ent.get("x", 0.0) * 2.71 + ent.get("y", 0.0) * 5.43))
					is_stalactite = variant_hash < 0.40
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
			else:
				effective_y_height = base_s
				xform = xform.scaled(Vector3.ONE * base_s)
		else:
			var sx: float = ent.get("sx", 1.0)
			var sy: float = ent.get("sy", 1.0)
			var sz: float = ent.get("sz", 1.0)
			xform = xform.scaled(Vector3(sx, sz, sy))
		# Random rotation for geological kinds (break repeating mesh silhouettes)
		var final_heading: float = heading
		if kind == "mega_column" or kind == "column" or kind == "boulder" \
				or kind == "stalagmite" or kind == "rubble" or kind == "bone_pile":
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

	var mmi := MultiMeshInstance3D.new()
	mmi.multimesh = mm
	mmi.name = "Kind_%s_v%d" % [kind, variant]
	mmi.material_override = mat
	add_child(mmi)
	kind_nodes["Kind_%s_v%d" % [kind, variant]] = mmi

	# Hull outlines removed — created ground seam artifacts. Per-material facet
	# edges + rim light handle object definition. Outlines need proper solution later.


var toast_label: Label
var toast_timer: float = 0.0

func _show_toast(msg: String) -> void:
	if toast_label:
		toast_label.text = msg
		toast_label.modulate.a = 1.0
		toast_timer = 2.0

func _setup_hud() -> void:
	var overlay_cfg: Dictionary = kind_config.get("_global", {}).get("screenshot_overlay", {})
	var font_size: int = overlay_cfg.get("font_size", 14)
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
	var cx: float = snapped(camera.position.x, 0.1)
	var cy: float = snapped(camera.position.z, 0.1)
	var ch: float = snapped(camera.rotation_degrees.y, 0.1)
	var tension_st: String = manifest.get("tension_state", "?")
	var vis: int = manifest.get("entities", []).size()
	hud_label.text = _build_overlay_line(overlay_cfg, cx, cy, ch, tension_st, vis)


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


func _send_camera() -> void:
	if not connected:
		return
	# Camera position: Godot (x, y_up, z) → manifest (x, z_forward, y_up)
	var msg := {
		"cam_x": camera.position.x,
		"cam_y": camera.position.z,   # Godot Z → manifest Y
		"cam_z": camera.position.y,   # Godot Y → manifest Z
		"heading": camera.rotation_degrees.y,
		"pitch": camera.rotation_degrees.x,
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

		# Full manifest update — brain sent new data, rebuild entities.
		# The brain handles dirty detection via "unchanged" flag above.
		# If we got here, the scene HAS changed — always rebuild.
		manifest = data
		_rebuild_entities()
		_update_atmosphere()
		_update_hud()


func _rebuild_entities() -> void:
	# Incremental: only rebuild kinds whose entity lists changed
	var new_by_kind: Dictionary = {}
	collision_objects.clear()

	var silhouette_ents: Array = []  # render_mode silhouette/hint → banner projection
	for ent: Dictionary in manifest.get("entities", []):
		var kind: String = ent.get("kind", "unknown")
		# Creature kinds handled by _spawn_creatures() — skip MultiMesh
		if CREATURE_KINDS.has(kind):
			continue
		var render_mode: String = ent.get("render_mode", "geometry")

		# Non-geometry entities skip MultiMesh — they project onto banner cylinders
		if render_mode == "silhouette" or render_mode == "hint":
			silhouette_ents.append(ent)
			continue

		if not new_by_kind.has(kind):
			new_by_kind[kind] = []
		new_by_kind[kind].append(ent)
		var coll_r: float = ent.get("collision_radius", 0.0)
		if coll_r > 0.0:
			if ent.get("attachment_plane", "") != "ceiling":
				collision_objects.append({"x": ent.get("x", 0.0), "z": ent.get("y", 0.0), "r": coll_r})

	# Remove kinds no longer present
	var old_kinds := kind_nodes.keys()
	for kind: String in old_kinds:
		if not new_by_kind.has(kind):
			if is_instance_valid(kind_nodes[kind]):
				kind_nodes[kind].queue_free()
			kind_nodes.erase(kind)

	# Rebuild only kinds with different counts (fast heuristic)
	for kind: String in new_by_kind:
		var ents: Array = new_by_kind[kind]
		var needs_rebuild := true
		if kind_nodes.has(kind) and is_instance_valid(kind_nodes[kind]):
			var old_mm: MultiMesh = kind_nodes[kind].multimesh
			if old_mm and old_mm.instance_count == ents.size():
				needs_rebuild = false  # same count, skip rebuild

		if needs_rebuild:
			if kind_nodes.has(kind) and is_instance_valid(kind_nodes[kind]):
				kind_nodes[kind].queue_free()
			_create_multimesh_for_kind(kind, ents)

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
	if mote_dirty:
		_update_motes()
		mote_dirty = false
		last_entity_count = ent_count
		last_tension_state = t_state


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

const CREATURE_KINDS := {
	"rat": {"speed": 4.0, "flee_radius": 8.0, "color": Color(0.12, 0.09, 0.07), "size": 0.12},
	"beetle": {"speed": 2.0, "flee_radius": 5.0, "color": Color(0.08, 0.06, 0.05), "size": 0.05},
	"spider": {"speed": 3.0, "flee_radius": 6.0, "color": Color(0.06, 0.05, 0.04), "size": 0.06},
}

var creature_nodes: Array[Dictionary] = []  # {node, home_x, home_z, kind, fleeing}

func _spawn_creatures() -> void:
	# Remove old
	for c: Dictionary in creature_nodes:
		if is_instance_valid(c["node"]):
			c["node"].queue_free()
	creature_nodes.clear()

	for ent: Dictionary in manifest.get("entities", []):
		var kind: String = ent.get("kind", "")
		if not CREATURE_KINDS.has(kind):
			continue
		var cfg: Dictionary = CREATURE_KINDS[kind]
		# Simple dark sphere for the creature
		var mesh := SphereMesh.new()
		mesh.radius = cfg["size"]
		mesh.height = cfg["size"] * 1.5
		mesh.radial_segments = 6
		mesh.rings = 3
		var cmat := StandardMaterial3D.new()
		cmat.albedo_color = cfg["color"]
		cmat.roughness = 0.9
		mesh.material = cmat
		var mi := MeshInstance3D.new()
		mi.mesh = mesh
		mi.position = Vector3(ent.get("x", 0.0), cfg["size"] * 0.5, ent.get("y", 0.0))
		mi.name = "Creature_%s" % kind
		add_child(mi)
		creature_nodes.append({
			"node": mi,
			"home_x": ent.get("x", 0.0),
			"home_z": ent.get("y", 0.0),
			"kind": kind,
			"fleeing": false,
			"flee_dir_x": 0.0,
			"flee_dir_z": 0.0,
			"flee_timer": 0.0,
		})


func _update_creatures(delta: float) -> void:
	for c: Dictionary in creature_nodes:
		if not is_instance_valid(c["node"]):
			continue
		var cfg: Dictionary = CREATURE_KINDS[c["kind"]]
		var node: MeshInstance3D = c["node"]
		var dx: float = node.position.x - camera.position.x
		var dz: float = node.position.z - camera.position.z
		var dist: float = sqrt(dx * dx + dz * dz)

		if c["fleeing"]:
			# Dart away
			c["flee_timer"] -= delta
			node.position.x += c["flee_dir_x"] * cfg["speed"] * delta
			node.position.z += c["flee_dir_z"] * cfg["speed"] * delta
			if c["flee_timer"] <= 0.0:
				c["fleeing"] = false
		elif dist < cfg["flee_radius"]:
			# Start fleeing — dart away from camera
			c["fleeing"] = true
			c["flee_timer"] = 1.5  # dart for 1.5 seconds
			var flee_len: float = max(dist, 0.1)
			c["flee_dir_x"] = dx / flee_len
			c["flee_dir_z"] = dz / flee_len
		else:
			# Idle — slowly drift back toward home
			var hx: float = c["home_x"] - node.position.x
			var hz: float = c["home_z"] - node.position.z
			node.position.x += hx * 0.3 * delta
			node.position.z += hz * 0.3 * delta


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

func _save_tag() -> void:
	tag_count += 1
	var img: Image = get_viewport().get_texture().get_image()
	var cx: float = snapped(camera.position.x, 0.1)
	var cy: float = snapped(camera.position.z, 0.1)
	var ch: float = snapped(camera.rotation_degrees.y, 0.1)
	var tension_st: String = manifest.get("tension_state", "?")
	var vis: int = manifest.get("entities", []).size()
	var fname: String = "sanctum_tag_%02d_x%s_y%s_h%s_%s_%dvis.png" % [
		tag_count, str(cx), str(cy), str(ch), tension_st, vis]

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

	var telemetry := {
		"tag": tag_count,
		"camera": {
			"x": snapped(camera.position.x, 0.01),
			"y": snapped(camera.position.z, 0.01),
			"z": snapped(camera.position.y, 0.01),
			"heading": snapped(camera.rotation_degrees.y, 0.1),
			"pitch": snapped(camera.rotation_degrees.x, 0.1),
			"fov": camera.fov,
		},
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
	}
	var json_path: String = path.replace(".png", ".json")
	var jfile := FileAccess.open(json_path, FileAccess.WRITE)
	if jfile:
		jfile.store_string(JSON.stringify(telemetry, "  "))
		jfile.close()
	_show_toast("TAG #%d saved" % tag_count)
	# Drop 3D marker at tag position
	_drop_tag_marker(tag_count, camera.position)


func _build_overlay_line(cfg: Dictionary,
		cx: float, cy: float, ch: float, tension_st: String, vis: int) -> String:
	"""Build the telemetry overlay string from config-driven field list."""
	var sep: String = cfg.get("separator", " | ")
	var fields: Array = cfg.get("fields", [])
	var parts: PackedStringArray = PackedStringArray()
	var chrono: Dictionary = manifest.get("chronometer", {})

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
		 "energy": 0.0, "range": 30.0, "attenuation": 0.7},
		{"name": "cool", "color": Color(0.30, 0.35, 0.60),
		 "kinds": ["crystal_cluster", "filament", "exit_lure"],
		 "energy": 0.0, "range": 30.0, "attenuation": 0.7},
		{"name": "organic", "color": Color(0.15, 0.35, 0.10),
		 "kinds": ["moss_patch"],
		 "energy": 0.0, "range": 25.0, "attenuation": 0.7},
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
	# CLEAN ROOM: skip all mote/light/decal/particle spawning.
	# Re-enable when building lighting channels intentionally.
	return
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
	if not has_tiers:
		var cam_x: float = camera.position.x
		var cam_z: float = camera.position.z
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
			current_valid = pipe["target_pos"].distance_squared_to(camera.position) < 40.0 * 40.0
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
				var d: float = candidate.distance_squared_to(camera.position)
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
	var cam_pos_x: float = camera.position.x
	var cam_pos_z: float = camera.position.z
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
		camera.rotation.y -= event.relative.x * MOUSE_SENS
		camera.rotation.x -= event.relative.y * MOUSE_SENS
		camera.rotation.x = clampf(camera.rotation.x, deg_to_rad(-89), deg_to_rad(89))

	if event.is_action_pressed("ui_cancel"):
		if mouse_captured:
			Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
			mouse_captured = false
		else:
			get_tree().quit()

	# Key bindings — use physical_keycode for layout-independent matching
	if event is InputEventKey and event.pressed and not event.echo:
		match event.physical_keycode:
			KEY_T, KEY_BRACKETLEFT, KEY_BRACKETRIGHT, KEY_BACKSLASH:  # telemetry tag
				_save_tag()
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


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and not mouse_captured:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		mouse_captured = true


func _physics_process(delta: float) -> void:
	var dir := Vector3.ZERO
	if Input.is_action_pressed("move_forward"):
		dir -= camera.global_transform.basis.z
	if Input.is_action_pressed("move_back"):
		dir += camera.global_transform.basis.z
	if Input.is_action_pressed("move_left"):
		dir -= camera.global_transform.basis.x
	if Input.is_action_pressed("move_right"):
		dir += camera.global_transform.basis.x
	dir.y = 0.0
	if dir.length_squared() > 0.001:
		dir = dir.normalized()

	var new_pos: Vector3 = camera.position + dir * MOVE_SPEED * delta

	for coll: Dictionary in collision_objects:
		var dx: float = new_pos.x - coll["x"]
		var dz: float = new_pos.z - coll["z"]
		var dist_sq: float = dx * dx + dz * dz
		var min_dist: float = coll["r"] + 0.5
		if dist_sq < min_dist * min_dist and dist_sq > 0.001:
			var dist: float = sqrt(dist_sq)
			var push: float = min_dist - dist
			new_pos.x += (dx / dist) * push
			new_pos.z += (dz / dist) * push

	# Terrain elevation — brain sends terrain_z, camera follows the rolling field.
	# Smooth lerp prevents jarring pops when height changes between frames.
	var terrain_z: float = manifest.get("camera", {}).get("terrain_z", 0.0)
	var target_y: float = EYE_HEIGHT + terrain_z
	new_pos.y = lerpf(camera.position.y, target_y, 7.0 * delta)
	camera.position = new_pos

	# Creatures react to camera
	_update_creatures(delta)

	# Follow-camera planes track the player on their parallel axes.
	# Floor/ceiling: track X/Z, keep Y at configured offset.
	# Walls: track Y/Z (or Y/X), keep lateral offset fixed.
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
					node.position.y = new_pos.y
					node.position.z = new_pos.z
				else:
					# Z-normal wall — rotated around X
					node.position.x = new_pos.x
					node.position.y = new_pos.y
			else:
				# Floor/ceiling — track X/Z, Y follows terrain height
				node.position.x = new_pos.x
				node.position.z = new_pos.z
				if pkind == "ground":
					var t_z: float = manifest.get("camera", {}).get("terrain_z", 0.0)
					node.position.y = entry.get("offset", 0.0) + t_z
				elif pkind == "ceiling":
					var t_z: float = manifest.get("camera", {}).get("terrain_z", 0.0)
					node.position.y = entry.get("offset", CEILING_PLANE_Y_DEFAULT) + t_z

	# Banner cylinders follow camera X/Z, keep their Y offset
	for bc: MeshInstance3D in banner_cylinders:
		bc.position.x = new_pos.x
		bc.position.z = new_pos.z
