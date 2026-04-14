extends Node3D
# vector_viewer — minimum-viable vector-3D Godot viewer.
#
# Connects to brain on :9877, consumes manifest.entities, renders each
# kind as a MultiMesh using the flat-3-color kind_shader. No decals,
# motes, lights, banners, outlines, avatar, envelope, iso — just the
# world you walk in, flat-shaded.
#
# WASD to move. Escape or window close to quit. Camera is first-person,
# slight downward tilt so the ground reads.
#
# The brain is authoritative: entity positions come from stamp_world,
# heading/scale from _make_entity. This viewer only paints.


const MOVE_SPEED := 8.0
const EYE_HEIGHT := 2.5
const MOUSE_SENS := 0.003
const BRAIN_HOST := "127.0.0.1"
const BRAIN_PORT := 9877
const CAMERA_SEND_HZ := 15.0
const NUM_VARIANTS := 4

# Reuse the same mesh aliases as main.gd — buttress borrows boulder
# shape, mega_column/column borrow stalagmite. Keeps the vector viewer
# aligned with the canonical look without re-authoring.
const MESH_ALIAS := {
	"buttress": "boulder",
	"mega_column": "stalagmite",
	"column": "stalagmite",
}

var camera: Camera3D
var mesh_cache: Dictionary = {}         # "<kind>_v<variant>" -> Mesh
var mesh_bounds: Dictionary = {}        # kind -> {scale,width,depth,height}
var kind_nodes: Dictionary = {}         # kind -> MultiMeshInstance3D
var kind_config_data: Dictionary = {}
var manifest: Dictionary = {}

var tcp: StreamPeerTCP
var connected: bool = false
var recv_buf: String = ""
var last_cam_send_t: float = 0.0
var mouse_captured: bool = false

var hud_label: Label


func _ready() -> void:
	_setup_environment()
	_load_mesh_bounds()
	_load_kind_config()
	_setup_camera()
	_setup_hud()
	_connect_to_brain()


# --- Environment ------------------------------------------------------------

func _setup_environment() -> void:
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.04, 0.04, 0.06)   # deep graphite
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.25, 0.25, 0.28)
	e.ambient_light_energy = 0.35
	e.fog_enabled = false                           # vector register: no atmospheric gradients
	e.ssao_enabled = false
	e.ssil_enabled = false
	e.glow_enabled = false
	e.tonemap_mode = Environment.TONE_MAPPER_LINEAR
	env.environment = e
	add_child(env)


func _setup_camera() -> void:
	camera = Camera3D.new()
	camera.position = Vector3(0.0, EYE_HEIGHT, -14.0)
	camera.rotation.y = PI                          # face +Z = brain's +Y (north)
	camera.rotation.x = deg_to_rad(-5.0)            # subtle downward tilt
	camera.fov = 62.0
	camera.far = 120.0
	camera.current = true
	add_child(camera)


func _setup_hud() -> void:
	var canvas := CanvasLayer.new()
	hud_label = Label.new()
	hud_label.position = Vector2(8, 4)
	hud_label.add_theme_color_override("font_color", Color(1, 1, 1, 0.85))
	canvas.add_child(hud_label)
	add_child(canvas)


# --- Mesh + kind_config helpers ---------------------------------------------

func _load_mesh_bounds() -> void:
	var f := FileAccess.open("res://meshes/bounds.json", FileAccess.READ)
	if f:
		var jp := JSON.new()
		if jp.parse(f.get_as_text()) == OK:
			mesh_bounds = jp.data
		f.close()


func _load_kind_config() -> void:
	var f := FileAccess.open("res://kind_config.json", FileAccess.READ)
	if f:
		var jp := JSON.new()
		if jp.parse(f.get_as_text()) == OK:
			kind_config_data = jp.data
		f.close()


func _find_mesh_instance(node: Node) -> MeshInstance3D:
	if node is MeshInstance3D:
		return node as MeshInstance3D
	for c in node.get_children():
		var found := _find_mesh_instance(c)
		if found:
			return found
	return null


func _get_mesh(kind: String, variant: int = 0) -> Mesh:
	var mesh_kind: String = MESH_ALIAS.get(kind, kind)
	var key: String = "%s_v%d" % [mesh_kind, variant]
	if mesh_cache.has(key):
		return mesh_cache[key]
	var path := "res://meshes/%s_v%d.glb" % [mesh_kind, variant]
	if not ResourceLoader.exists(path):
		path = "res://meshes/%s.glb" % mesh_kind
	if ResourceLoader.exists(path):
		var scene: PackedScene = ResourceLoader.load(path)
		if scene:
			var instance := scene.instantiate()
			var mi := _find_mesh_instance(instance)
			if mi:
				mesh_cache[key] = mi.mesh
				return mi.mesh
	# Fallback — tiny cube so the kind still shows up.
	var box := BoxMesh.new()
	box.size = Vector3(0.4, 0.4, 0.4)
	mesh_cache[key] = box
	return box


func _make_kind_material(kind: String) -> ShaderMaterial:
	var shader: Shader = load("res://kind_shader.gdshader")
	var mat := ShaderMaterial.new()
	mat.shader = shader

	var kinds: Dictionary = kind_config_data.get("kinds", {})
	var entry: Dictionary = kinds.get(kind, {})
	var class_name_: String = entry.get("class", "geological")
	var defaults: Dictionary = kind_config_data.get("_class_defaults", {}) \
		.get(class_name_, {})
	# Per-kind palette overrides class defaults overrides hardcoded fallback.
	var cb: Array = entry.get("color_base", defaults.get("color_base", [0.30, 0.27, 0.23]))
	var cs: Array = entry.get("color_shadow", defaults.get("color_shadow", [0.26, 0.23, 0.19]))
	var ca: Array = entry.get("color_accent", defaults.get("color_accent", [0.34, 0.30, 0.25]))
	mat.set_shader_parameter("color_base",   Color(cb[0], cb[1], cb[2]))
	mat.set_shader_parameter("color_shadow", Color(cs[0], cs[1], cs[2]))
	mat.set_shader_parameter("color_accent", Color(ca[0], ca[1], ca[2]))
	mat.set_shader_parameter("light_reactive", 0.0)
	mat.set_shader_parameter("taper_strength", 0.0)
	mat.set_shader_parameter("twist_amount", 0.0)
	mat.set_shader_parameter("band_strength", 0.0)
	mat.set_shader_parameter("wind_strength", 0.0)
	mat.set_shader_parameter("ghost_chance", 0.0)
	mat.set_shader_parameter("use_vertex_colors",
		1.0 if entry.get("use_vertex_colors", false) else 0.0)
	return mat


# --- Brain wire -------------------------------------------------------------

func _connect_to_brain() -> void:
	tcp = StreamPeerTCP.new()
	var err := tcp.connect_to_host(BRAIN_HOST, BRAIN_PORT)
	if err == OK:
		print("vector_viewer: connecting to brain at %s:%d" % [BRAIN_HOST, BRAIN_PORT])
	else:
		push_error("vector_viewer: TCP connect error %s" % err)


func _process(delta: float) -> void:
	if tcp == null:
		return
	tcp.poll()
	var status := tcp.get_status()
	if status == StreamPeerTCP.STATUS_CONNECTED:
		if not connected:
			print("vector_viewer: connected")
			connected = true
		_receive()
		_maybe_send_camera(delta)
	elif status == StreamPeerTCP.STATUS_ERROR:
		if connected:
			print("vector_viewer: brain disconnected")
		connected = false


func _receive() -> void:
	var available := tcp.get_available_bytes()
	if available > 0:
		var bytes := tcp.get_data(available)
		if bytes[0] == OK:
			recv_buf += bytes[1].get_string_from_utf8()
	while true:
		var nl := recv_buf.find("\n")
		if nl < 0:
			break
		var line := recv_buf.substr(0, nl)
		recv_buf = recv_buf.substr(nl + 1)
		if line.is_empty():
			continue
		var jp := JSON.new()
		if jp.parse(line) != OK:
			continue
		var data: Dictionary = jp.data
		if data.get("unchanged", false):
			continue
		manifest = data
		_rebuild_entities()


func _maybe_send_camera(delta: float) -> void:
	last_cam_send_t += delta
	if last_cam_send_t < 1.0 / CAMERA_SEND_HZ:
		return
	last_cam_send_t = 0.0
	var msg := JSON.stringify({
		"x": camera.position.x,
		"y": camera.position.z,   # brain's Y = Godot's Z
		"z": camera.position.y,
		"heading": rad_to_deg(camera.rotation.y),
		"pitch": rad_to_deg(camera.rotation.x),
	}) + "\n"
	tcp.put_data(msg.to_utf8_buffer())


# --- Rendering --------------------------------------------------------------

func _rebuild_entities() -> void:
	var ents: Array = manifest.get("entities", [])

	# Group by kind.
	var by_kind: Dictionary = {}
	for ent in ents:
		var k: String = ent.get("kind", "unknown")
		if not by_kind.has(k):
			by_kind[k] = []
		by_kind[k].append(ent)

	# Free departed kinds.
	for k in kind_nodes.keys():
		if not by_kind.has(k):
			if is_instance_valid(kind_nodes[k]):
				kind_nodes[k].queue_free()
			kind_nodes.erase(k)

	# Rebuild present kinds.
	for k in by_kind.keys():
		if kind_nodes.has(k) and is_instance_valid(kind_nodes[k]):
			kind_nodes[k].queue_free()
		_spawn_kind_multimesh(k, by_kind[k])

	if hud_label:
		var cam_x := camera.position.x
		var cam_z := camera.position.z
		hud_label.text = "vector · (%5.1f, %5.1f) · ents %d" % [cam_x, cam_z, ents.size()]


func _spawn_kind_multimesh(kind: String, ents: Array) -> void:
	var mesh := _get_mesh(kind, 0)
	var mm := MultiMesh.new()
	mm.transform_format = MultiMesh.TRANSFORM_3D
	mm.use_colors = false
	mm.mesh = mesh
	mm.instance_count = ents.size()

	var bounds_key: String = kind if mesh_bounds.has(kind) else MESH_ALIAS.get(kind, kind)
	var bounds: Dictionary = mesh_bounds.get(bounds_key, {})
	var orig_scale: float = bounds.get("scale", 1.0)

	for i in range(ents.size()):
		var ent: Dictionary = ents[i]
		var sx: float = float(ent.get("sx", 1.0))
		var sy: float = float(ent.get("sy", 1.0))
		var sz: float = float(ent.get("sz", 1.0))
		var heading: float = deg_to_rad(float(ent.get("heading", 0.0)))
		var xform := Transform3D()
		# Default pathway (no per-axis Godot variance) — use the
		# entity's sx/sy/sz directly times bounds scale. Matches the
		# non-variance else-branch in main.gd so kinds without per-axis
		# formulas render consistently.
		xform = xform.scaled(Vector3(sx * orig_scale, sz * orig_scale, sy * orig_scale))
		xform = xform.rotated(Vector3.UP, heading)
		xform.origin = Vector3(
			float(ent.get("x", 0.0)),
			float(ent.get("z", 0.0)),
			float(ent.get("y", 0.0)))
		mm.set_instance_transform(i, xform)

	var mi := MultiMeshInstance3D.new()
	mi.multimesh = mm
	mi.material_override = _make_kind_material(kind)
	mi.name = "Kind_%s" % kind
	add_child(mi)
	kind_nodes[kind] = mi


# --- Input / movement -------------------------------------------------------

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and not mouse_captured:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
		mouse_captured = true
	if event is InputEventKey and event.pressed and event.physical_keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
		mouse_captured = false
	if event is InputEventMouseMotion and mouse_captured:
		camera.rotation.y -= event.relative.x * MOUSE_SENS
		camera.rotation.x = clamp(
			camera.rotation.x - event.relative.y * MOUSE_SENS,
			-PI / 2.0 + 0.01, PI / 2.0 - 0.01)


func _physics_process(delta: float) -> void:
	var dir := Vector3.ZERO
	if Input.is_key_pressed(KEY_W):
		dir -= camera.global_transform.basis.z
	if Input.is_key_pressed(KEY_S):
		dir += camera.global_transform.basis.z
	if Input.is_key_pressed(KEY_A):
		dir -= camera.global_transform.basis.x
	if Input.is_key_pressed(KEY_D):
		dir += camera.global_transform.basis.x
	dir.y = 0.0
	if dir.length_squared() > 0.001:
		dir = dir.normalized()
	camera.position += dir * MOVE_SPEED * delta
	# Keep eye at configured height; brain-side terrain could modulate later.
	camera.position.y = EYE_HEIGHT
