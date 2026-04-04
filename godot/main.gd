extends Node3D

## Sanctum Terminal — Godot viewer for Python brain manifests.
## Connects to brain_server.py via TCP for live streaming manifests.
## Falls back to static manifest.json if server isn't running.

const MOVE_SPEED := 8.0
const MOUSE_SENS := 0.002
const EYE_HEIGHT := 2.5
const SERVER_HOST := "127.0.0.1"
const SERVER_PORT := 9877

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

# Ground
var ground_node: MeshInstance3D

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
	_spawn_ground()
	_spawn_entities()
	_update_motes()
	_setup_hud()

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


func _create_kind_material(kind: String) -> Material:
	"""Create a ShaderMaterial configured from kind_config for this kind."""
	var params: Dictionary = _get_kind_params(kind)
	var shader: Shader = load("res://kind_shader.gdshader")
	if not shader:
		var fallback := StandardMaterial3D.new()
		fallback.vertex_color_use_as_albedo = true
		fallback.roughness = 0.85
		fallback.cull_mode = BaseMaterial3D.CULL_DISABLED
		return fallback

	var mat := ShaderMaterial.new()
	mat.shader = shader

	# Roughness
	var rough: Dictionary = params.get("roughness", {})
	mat.set_shader_parameter("roughness_base", rough.get("base", 0.85))
	mat.set_shader_parameter("roughness_wet", rough.get("wet", 0.25))
	mat.set_shader_parameter("wet_height", rough.get("wet_height", 0.3))

	# Light response
	mat.set_shader_parameter("light_response", params.get("light_response", 0.35))

	# World grain — one pattern, all surfaces
	mat.set_shader_parameter("world_grain", 0.10)
	mat.set_shader_parameter("material_ratio", params.get("material_ratio", 1.0))
	var grain_albedo: Texture2D = load("res://world_grain.png")
	if grain_albedo:
		mat.set_shader_parameter("grain_tex", grain_albedo)
		mat.set_shader_parameter("grain_strength", 0.35)

	# Normal map (world grain normal by default)
	var nmap_name: String = str(params.get("normal_map", ""))
	if nmap_name != "" and nmap_name != "null":
		var nmap_path := "res://%s.png" % nmap_name
		var nmap: Texture2D = load(nmap_path)
		if nmap:
			mat.set_shader_parameter("normal_tex", nmap)
			mat.set_shader_parameter("normal_strength", params.get("normal_strength", 0.8))

	# Contact darkening
	var contact: Dictionary = params.get("contact", {})
	mat.set_shader_parameter("contact_darkness", contact.get("darkness", 0.4))
	mat.set_shader_parameter("contact_height", contact.get("radius", 3.0) * 0.05)

	# Surface effects
	var effects: Array = params.get("surface_effects", [])
	mat.set_shader_parameter("wet_base_enabled", "wet_base" in effects or "wet_all" in effects)
	mat.set_shader_parameter("moss_patches_enabled", "moss_patches" in effects or "moss_climb" in effects)

	# Inner glow (crystalline)
	mat.set_shader_parameter("inner_glow", params.get("inner_glow", 0.0))
	mat.set_shader_parameter("pulse_rate", params.get("pulse_rate", 0.0))

	# Subsurface (organic)
	mat.set_shader_parameter("subsurface", params.get("subsurface", 0.0))

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

func _get_mesh_for_kind(kind: String, variant: int = 0) -> Mesh:
	var cache_key: String = "%s_v%d" % [kind, variant]
	if mesh_cache.has(cache_key):
		return mesh_cache[cache_key]

	# Try variant file first, fall back to base name
	var glb_path := "res://meshes/%s_v%d.glb" % [kind, variant]
	if not ResourceLoader.exists(glb_path):
		glb_path = "res://meshes/%s.glb" % kind  # legacy fallback

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
	godot_env.fog_enabled = true
	var fc: Array = fog.get("color", [0.1, 0.1, 0.1])
	godot_env.fog_light_color = Color(fc[0], fc[1], fc[2])
	var fog_far: float = fog.get("far", 55.0)
	godot_env.fog_density = 1.5 / max(fog_far, 1.0)

	var bg: Array = manifest.get("bg_color", [0.12, 0.08, 0.12])
	godot_env.background_mode = Environment.BG_COLOR
	godot_env.background_color = Color(bg[0], bg[1], bg[2])

	var amb: Array = manifest.get("ambient", [0.3, 0.22, 0.15])
	godot_env.ambient_light_color = Color(amb[0], amb[1], amb[2])
	godot_env.ambient_light_energy = 0.5  # dim but visible — shapes everywhere, emissives pop as accent
	godot_env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR

	godot_env.tonemap_mode = 2
	godot_env.tonemap_white = 5.0

	# -- Post-process: Cavern register --
	# Bloom — crystals and moss GLOW and bleed into surroundings
	godot_env.glow_enabled = true
	godot_env.glow_enabled = true
	godot_env.glow_intensity = 0.8
	godot_env.glow_bloom = 0.25
	godot_env.glow_blend_mode = Environment.GLOW_BLEND_MODE_ADDITIVE
	godot_env.glow_hdr_threshold = 0.4  # aggressive bloom on any lit surface
	godot_env.glow_hdr_scale = 2.5

	# Adjustments — desaturate world, color lives only in light sources
	godot_env.adjustment_enabled = true
	godot_env.adjustment_brightness = 1.1
	godot_env.adjustment_contrast = 1.1
	godot_env.adjustment_saturation = 0.50

	# Volumetric fog — ground haze, light shafts from emissives
	godot_env.volumetric_fog_enabled = true
	godot_env.volumetric_fog_density = 0.04  # thicker for cave
	godot_env.volumetric_fog_albedo = Color(fc[0] * 0.5, fc[1] * 0.5, fc[2] * 0.5)
	godot_env.volumetric_fog_emission = Color(0.03, 0.02, 0.02)
	godot_env.volumetric_fog_emission_energy = 0.3
	godot_env.volumetric_fog_length = 35.0
	godot_env.volumetric_fog_gi_inject = 1.0  # pick up OmniLight color in fog

	# SSAO — contact shadows where objects meet ground
	godot_env.ssao_enabled = true
	godot_env.ssao_radius = 3.0
	godot_env.ssao_intensity = 2.0

	# SSIL — indirect light bounce from emissives onto nearby surfaces
	godot_env.ssil_enabled = true
	godot_env.ssil_radius = 5.0
	godot_env.ssil_intensity = 1.0

	env_node = WorldEnvironment.new()
	env_node.environment = godot_env
	add_child(env_node)

	# Sun
	var sun_data: Dictionary = manifest.get("sun", {})
	var sun_scale: float = sun_data.get("scale", 0.0)
	if sun_scale > 0.0:
		var sun := DirectionalLight3D.new()
		sun.name = "Sun"
		var sc: Array = sun_data.get("color", [1, 0.9, 0.65])
		sun.light_color = Color(sc[0], sc[1], sc[2])
		sun.light_energy = sun_scale * 0.25
		sun.rotation_degrees = Vector3(-45, -30, 0)
		sun.shadow_enabled = true
		add_child(sun)

	# Moon
	var moon_data: Dictionary = manifest.get("moon", {})
	var moon_scale: float = moon_data.get("scale", 0.0)
	if moon_scale > 0.0:
		var moon := DirectionalLight3D.new()
		moon.name = "Moon"
		var mc: Array = moon_data.get("color", [0.6, 0.65, 0.8])
		moon.light_color = Color(mc[0], mc[1], mc[2])
		moon.light_energy = moon_scale * 0.15
		moon.rotation_degrees = Vector3(-60, 45, 0)
		add_child(moon)


func _setup_camera() -> void:
	camera = Camera3D.new()
	var cam_data: Dictionary = manifest.get("camera", {})
	camera.position = Vector3(cam_data.get("x", 0.0), EYE_HEIGHT, cam_data.get("y", 0.0))
	camera.rotation_degrees.y = cam_data.get("heading", 0.0)
	var fog_data: Dictionary = manifest.get("fog", {})
	camera.far = fog_data.get("far", 55.0) * 2.5  # extended for skeleton silhouettes
	camera.fov = 52.0  # very tight — columns ARE walls, forced through corridors
	add_child(camera)


func _setup_outline() -> void:
	# Screen-space outline post-process — thin dark lines at silhouettes
	var outline_shader: Shader = load("res://outline_post.gdshader")
	if not outline_shader:
		return

	var mat := ShaderMaterial.new()
	mat.shader = outline_shader
	mat.set_shader_parameter("outline_thickness", 1.0)
	mat.set_shader_parameter("depth_threshold", 0.002)
	mat.set_shader_parameter("normal_threshold", 0.4)
	mat.set_shader_parameter("outline_color", Color(0.0, 0.0, 0.0, 0.5))

	# Full-screen quad attached to camera
	var quad := MeshInstance3D.new()
	var qm := QuadMesh.new()
	qm.size = Vector2(2.0, 2.0)
	quad.mesh = qm
	quad.material_override = mat
	quad.position = Vector3(0, 0, -0.1)  # just in front of camera near plane
	quad.extra_cull_margin = 10000.0
	camera.add_child(quad)


func _spawn_ground() -> void:
	var mesh := PlaneMesh.new()
	mesh.size = Vector2(2000, 2000)
	mesh.subdivide_width = 4
	mesh.subdivide_depth = 4

	# Procedural ground shader
	var shader := load("res://ground.gdshader")
	if shader:
		var mat := ShaderMaterial.new()
		mat.shader = shader
		# Tint ground colors from biome palette
		var palette: Array = manifest.get("ambient", [0.12, 0.10, 0.06])
		var dark := Color(palette[0] * 0.12, palette[1] * 0.10, palette[2] * 0.08)
		var mid := Color(palette[0] * 0.25, palette[1] * 0.22, palette[2] * 0.18)
		var light := Color(palette[0] * 0.38, palette[1] * 0.35, palette[2] * 0.28)
		mat.set_shader_parameter("color_dark", dark)
		mat.set_shader_parameter("color_mid", mid)
		mat.set_shader_parameter("color_light", light)
		var fc_arr: Array = manifest.get("fog", {}).get("color", [0.1, 0.1, 0.1])
		mat.set_shader_parameter("fog_color", Color(fc_arr[0], fc_arr[1], fc_arr[2]))
		mesh.material = mat
	else:
		# Fallback flat color
		var mat := StandardMaterial3D.new()
		var palette: Array = manifest.get("ambient", [0.12, 0.10, 0.06])
		mat.albedo_color = Color(palette[0] * 0.4, palette[1] * 0.4, palette[2] * 0.4)
		mat.roughness = 0.95
		mesh.material = mat

	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.name = "Ground"
	add_child(mi)
	ground_node = mi


func _spawn_entities() -> void:
	var by_kind: Dictionary = {}
	collision_objects.clear()

	for ent: Dictionary in manifest.get("entities", []):
		var kind: String = ent.get("kind", "unknown")
		if not by_kind.has(kind):
			by_kind[kind] = []
		by_kind[kind].append(ent)

		var coll_r: float = ent.get("collision_radius", 0.0)
		if coll_r > 0.0:
			collision_objects.append({"x": ent.get("x", 0.0), "z": ent.get("y", 0.0), "r": coll_r})

	for kind: String in by_kind:
		_create_multimesh_for_kind(kind, by_kind[kind])


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
	var bounds: Dictionary = mesh_bounds.get(kind, {})
	var has_real_mesh: bool = bounds.size() > 0 and not (base_mesh is BoxMesh)

	# Real mesh: normalized to max_dim=1.0. To restore original builder size,
	# multiply uniformly by orig_scale. Then per-instance variation from manifest
	# is a small multiplier around 1.0 (the 0.75-1.25 seed variation).
	var orig_scale: float = bounds.get("scale", 1.0)

	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = true
	mm.mesh = base_mesh
	mm.instance_count = ents.size()

	for i in range(ents.size()):
		var ent: Dictionary = ents[i]
		var heading: float = deg_to_rad(ent.get("heading", 0.0))
		var emissive: float = ent.get("emissive", 0.0)
		# Per-instance scale variation (from manifest seed rng, ~0.75-1.25)
		var sv: float = ent.get("sv", 1.0)

		var xform := Transform3D()
		if has_real_mesh:
			var base_s: float = orig_scale * sv
			# Columns: widen X and Z to feel like walls, not pillars
			if kind == "mega_column" or kind == "column":
				xform = xform.scaled(Vector3(base_s * 2.2, base_s, base_s * 2.2))
			else:
				xform = xform.scaled(Vector3.ONE * base_s)
		else:
			var sx: float = ent.get("sx", 1.0)
			var sy: float = ent.get("sy", 1.0)
			var sz: float = ent.get("sz", 1.0)
			xform = xform.scaled(Vector3(sx, sz, sy))
		xform = xform.rotated(Vector3.UP, heading)

		# Position: manifest (x, y, z) → Godot (x, z_up, y_forward)
		# Sink objects slightly into ground so they grow FROM it
		var y_offset: float = 0.0 if has_real_mesh else ent.get("sz", 1.0) * 0.5
		var sink: float = 0.0
		if has_real_mesh:
			if kind == "moss_patch" or kind == "leaf_pile" or kind == "twig_scatter" or kind == "cave_gravel":
				sink = -0.05  # ground cover sinks into floor
			elif kind == "boulder" or kind == "rubble" or kind == "bone_pile":
				sink = -0.15  # partially buried
			elif kind == "mega_column" or kind == "column" or kind == "stalagmite":
				sink = -0.3  # grows from the ground
		var pos := Vector3(
			ent.get("x", 0.0),
			ent.get("z", 0.0) + y_offset + sink,
			ent.get("y", 0.0)
		)
		xform.origin = pos
		mm.set_instance_transform(i, xform)

		var r: float = ent.get("r", 0.5)
		var g: float = ent.get("g", 0.5)
		var b: float = ent.get("b", 0.5)
		if emissive > 0.0:
			# Emissive objects: hold their COLOR, don't blow to white
			# The OmniLight does the brightness, the object stays tinted
			var boost: float = 1.0 + emissive * 0.5  # subtle, not blinding
			mm.set_instance_color(i, Color(r * boost, g * boost, b * boost))
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


func _setup_hud() -> void:
	hud_label = Label.new()
	hud_label.name = "HUD"
	hud_label.position = Vector2(12, 8)
	hud_label.add_theme_font_size_override("font_size", 14)
	hud_label.add_theme_color_override("font_color", Color(0.7, 0.65, 0.55))
	var canvas := CanvasLayer.new()
	canvas.add_child(hud_label)
	add_child(canvas)
	_update_hud()


func _update_hud() -> void:
	var biome: String = manifest.get("biome", "?")
	var ent_count: int = manifest.get("entities", []).size()
	var tension: String = manifest.get("tension_state", "")
	var budget: float = manifest.get("tension_budget", 0.0)
	var tiles: int = manifest.get("stats", {}).get("tiles", 1)
	var conn_str := " [LIVE]" if connected else " [static]"
	hud_label.text = "Sanctum — %s | %d visible | tension: %s (%.0f%%) | %d tiles%s | ESC quit / L light / B tension" % [
		biome, ent_count, tension, budget * 100, tiles, conn_str]


# -- Brain server connection ---------------------------------------------------

func _connect_to_brain() -> void:
	tcp = StreamPeerTCP.new()
	tcp.connect_to_host(SERVER_HOST, SERVER_PORT)
	print("Connecting to brain server %s:%d..." % [SERVER_HOST, SERVER_PORT])


func _process(delta: float) -> void:
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

		# Full manifest update — rebuild scene
		manifest = data
		_rebuild_entities()
		_update_atmosphere()
		_update_hud()


func _rebuild_entities() -> void:
	# Incremental: only rebuild kinds whose entity lists changed
	var new_by_kind: Dictionary = {}
	collision_objects.clear()

	for ent: Dictionary in manifest.get("entities", []):
		var kind: String = ent.get("kind", "unknown")
		if not new_by_kind.has(kind):
			new_by_kind[kind] = []
		new_by_kind[kind].append(ent)
		var coll_r: float = ent.get("collision_radius", 0.0)
		if coll_r > 0.0:
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

	# Update mote particles
	_update_motes()


func _update_atmosphere() -> void:
	if not godot_env:
		return

	var fog: Dictionary = manifest.get("fog", {})
	var fc: Array = fog.get("color", [0.1, 0.1, 0.1])
	godot_env.fog_light_color = Color(fc[0], fc[1], fc[2])
	var fog_far: float = fog.get("far", 55.0)
	godot_env.fog_density = 1.0 / max(fog_far, 1.0)

	var amb: Array = manifest.get("ambient", [0.3, 0.22, 0.15])
	godot_env.ambient_light_color = Color(amb[0], amb[1], amb[2])

	var bg: Array = manifest.get("bg_color", [0.12, 0.08, 0.12])
	godot_env.background_color = Color(bg[0], bg[1], bg[2])

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
	# Save to project directory (godot/tags/) — accessible by Claude
	var dir_path: String = "res://tags"
	DirAccess.make_dir_recursive_absolute(dir_path)
	var path: String = dir_path + "/" + fname
	var err: int = img.save_png(path)
	if err == OK:
		print("TAG #%d: %s" % [tag_count, fname])
	else:
		# Fallback: try absolute path
		var abs_path: String = "/Users/themrburn/git/sanctum-terminal/godot/tags/" + fname
		DirAccess.make_dir_recursive_absolute("/Users/themrburn/git/sanctum-terminal/godot/tags")
		err = img.save_png(abs_path)
		print("TAG #%d: %s (err=%d)" % [tag_count, abs_path, err])


# -- Lighting + Motes ----------------------------------------------------------
# Emissive entities get OmniLight3D (cast on surroundings) + particle motes

# Light configs derived from biome_data.py LIGHT_LAYERS
const CAUSTIC_COLORS := [
	Color(0.85, 0.20, 0.10),  # warm red edge
	Color(0.15, 0.75, 0.25),  # green refract
	Color(0.10, 0.20, 0.90),  # cool blue edge
]

const LIGHT_KINDS := {
	"crystal_cluster": {
		"color": Color(0.35, 0.40, 0.70),
		"energy": 16.0,
		"range": 18.0,
		"attenuation": 1.0,
		"prismatic": true,
		"caustic_intensity": 0.4,
		"caustic_radius": 3.5,
		"facet_spread": 2.5,
		"mote_color": Color(0.3, 0.35, 0.6),
		"mote_count": 10,
		"mote_radius": 3.0,
		"mote_height": 3.0,
	},
	"giant_fungus": {
		"color": Color(0.18, 0.30, 0.10),  # warm green-amber, organic not crystal
		"energy": 8.0,
		"range": 10.0,
		"attenuation": 1.4,
		"mote_color": Color(0.25, 0.08, 0.35),
		"mote_count": 8,
		"mote_radius": 3.0,
		"mote_height": 4.0,
	},
	"moss_patch": {
		"color": Color(0.10, 0.40, 0.08),  # green glow
		"energy": 6.0,
		"range": 8.0,
		"attenuation": 1.3,
		"mote_color": Color(0.1, 0.5, 0.08),
		"mote_count": 4,
		"mote_radius": 1.5,
		"mote_height": 1.0,
	},
	"firefly": {
		"color": Color(0.95, 0.75, 0.30),  # warm amber
		"energy": 1.0,
		"range": 3.0,
		"attenuation": 2.0,
		"mote_color": Color(0.95, 0.8, 0.3),
		"mote_count": 1,
		"mote_radius": 0.5,
		"mote_height": 1.5,
	},
	"filament": {
		"color": Color(0.30, 0.40, 0.55),  # cool blue thread
		"energy": 1.5,
		"range": 4.0,
		"attenuation": 1.8,
		"mote_color": Color(0.35, 0.45, 0.6),
		"mote_count": 5,
		"mote_radius": 1.0,
		"mote_height": 2.5,
	},
	"ceiling_moss": {
		"color": Color(0.6, 0.40, 0.12),  # amber drip glow
		"energy": 6.0,
		"range": 12.0,
		"attenuation": 1.3,
		"mote_color": Color(0.8, 0.55, 0.15),
		"mote_count": 8,
		"mote_radius": 3.0,
		"mote_height": 5.0,
	},
}

var emissive_lights: Array[Node3D] = []
var mote_particles: Array[GPUParticles3D] = []

func _update_motes() -> void:
	# Remove old
	for l: Node3D in emissive_lights:
		if is_instance_valid(l):
			l.queue_free()
	emissive_lights.clear()
	for p: GPUParticles3D in mote_particles:
		if is_instance_valid(p):
			p.queue_free()
	mote_particles.clear()

	# Cap lights to avoid GPU overload — nearest emissives only
	var emissive_ents: Array[Dictionary] = []
	for ent: Dictionary in manifest.get("entities", []):
		if LIGHT_KINDS.has(ent.get("kind", "")):
			emissive_ents.append(ent)

	# Sort by distance to camera, take nearest 24
	var cam_x: float = camera.position.x
	var cam_z: float = camera.position.z
	emissive_ents.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		var da: float = (a["x"] - cam_x) ** 2 + (a["y"] - cam_z) ** 2
		var db: float = (b["x"] - cam_x) ** 2 + (b["y"] - cam_z) ** 2
		return da < db)
	var max_lights: int = mini(emissive_ents.size(), 24)

	for i in range(max_lights):
		var ent: Dictionary = emissive_ents[i]
		var kind: String = ent.get("kind", "")
		var cfg: Dictionary = LIGHT_KINDS[kind]

		var pos := Vector3(ent.get("x", 0.0), ent.get("z", 0.0) + 1.0, ent.get("y", 0.0))

		# OmniLight — casts color on nearby surfaces
		var light := OmniLight3D.new()
		var hue_seed: float = abs(sin(ent.get("x", 0.0) * 12.9898 + ent.get("y", 0.0) * 78.233))
		var hue_shift: float = (hue_seed - 0.5) * 0.15
		var base_c: Color = cfg["color"]
		var shifted := Color(
			clampf(base_c.r + hue_shift * 0.3, 0.0, 1.0),
			clampf(base_c.g + hue_shift * 0.1, 0.0, 1.0),
			clampf(base_c.b - hue_shift * 0.2, 0.0, 1.0))
		light.light_color = shifted
		var e_var: float = 0.7 + hue_seed * 0.6
		light.light_energy = cfg["energy"] * e_var
		light.omni_range = cfg["range"]
		light.omni_attenuation = cfg["attenuation"]
		light.shadow_enabled = false
		light.position = pos
		add_child(light)
		emissive_lights.append(light)

		# Prismatic caustics — colored light patches refracted through crystal
		if cfg.get("prismatic", false) and hue_seed > 0.4:  # ~60% of crystals
			var spread: float = cfg.get("facet_spread", 2.5)
			var c_energy: float = cfg.get("caustic_intensity", 0.4) * e_var
			var c_range: float = cfg.get("caustic_radius", 3.5)
			for ci in range(CAUSTIC_COLORS.size()):
				var angle: float = (hue_seed * 360.0 + float(ci) * 120.0)
				var c_offset := Vector3(
					cos(deg_to_rad(angle)) * spread,
					0.2,  # near ground
					sin(deg_to_rad(angle)) * spread)
				var caustic := OmniLight3D.new()
				caustic.light_color = CAUSTIC_COLORS[ci]
				caustic.light_energy = c_energy * cfg["energy"] * 0.15
				caustic.omni_range = c_range
				caustic.omni_attenuation = 1.5
				caustic.shadow_enabled = false
				caustic.position = pos + c_offset
				add_child(caustic)
				emissive_lights.append(caustic)

		# Mote particles
		var particles := GPUParticles3D.new()
		particles.amount = cfg["mote_count"]
		particles.lifetime = 5.0
		particles.fixed_fps = 20
		particles.visibility_aabb = AABB(Vector3(-6, -2, -6), Vector3(12, 12, 12))

		var pmat := ParticleProcessMaterial.new()
		pmat.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
		pmat.emission_sphere_radius = cfg["mote_radius"]
		pmat.direction = Vector3(0, 1, 0)
		pmat.initial_velocity_min = 0.05
		pmat.initial_velocity_max = 0.15
		pmat.gravity = Vector3(0, -0.02, 0)
		pmat.scale_min = 0.02
		pmat.scale_max = 0.06
		particles.process_material = pmat

		var smesh := SphereMesh.new()
		smesh.radius = 0.04
		smesh.height = 0.08
		smesh.radial_segments = 4
		smesh.rings = 2
		var smat := StandardMaterial3D.new()
		smat.albedo_color = Color(cfg["mote_color"].r, cfg["mote_color"].g, cfg["mote_color"].b, 0.5)
		smat.emission_enabled = true
		smat.emission = cfg["mote_color"]
		smat.emission_energy_multiplier = 8.0
		smat.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED
		smat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		smat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		smesh.material = smat
		particles.draw_pass_1 = smesh

		particles.position = Vector3(
			ent.get("x", 0.0),
			ent.get("z", 0.0) + cfg["mote_height"] * 0.5,
			ent.get("y", 0.0))
		add_child(particles)
		mote_particles.append(particles)

	# -- Ceiling drip particles (amber drops falling from ceiling_moss) --
	for ent: Dictionary in manifest.get("entities", []):
		if ent.get("kind", "") != "ceiling_moss":
			continue
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
		dmat.scale_min = 0.02
		dmat.scale_max = 0.04
		drip.process_material = dmat
		var dmesh := SphereMesh.new()
		dmesh.radius = 0.03
		dmesh.height = 0.06
		dmesh.radial_segments = 4
		dmesh.rings = 2
		var dsmat := StandardMaterial3D.new()
		dsmat.albedo_color = Color(0.6, 0.4, 0.12, 0.7)
		dsmat.emission_enabled = true
		dsmat.emission = Color(0.5, 0.35, 0.10)
		dsmat.emission_energy_multiplier = 3.0
		dsmat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		dsmat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		dmesh.material = dsmat
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

	# T key — telemetry tag (screenshot + position)
	if event is InputEventKey and event.pressed and event.keycode == KEY_T:
		_save_tag()

	# L key — cycle light state
	if event is InputEventKey and event.pressed and event.keycode == KEY_L:
		if connected:
			var msg := JSON.stringify({"cmd": "light_cycle"}) + "\n"
			tcp.put_data(msg.to_utf8_buffer())

	# B key — toggle tension cycle
	if event is InputEventKey and event.pressed and event.keycode == KEY_B:
		if connected:
			var msg := JSON.stringify({"cmd": "tension_toggle"}) + "\n"
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

	new_pos.y = EYE_HEIGHT
	camera.position = new_pos

	# Creatures react to camera
	_update_creatures(delta)

	# Ground follows camera so it never ends
	if ground_node:
		ground_node.position.x = new_pos.x
		ground_node.position.z = new_pos.z
