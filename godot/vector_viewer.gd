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
# UAT-1 mode: hide brain-streamed entities, render only the encounter
# arena (flat ground + tile pillars + orb). Flip to false to restore the
# full vector lens on the cavern.
const UAT_MODE := false

# Player avatar — pale-bone capsule, visible in iso view only (design_first_person).
const AVATAR_HEIGHT_M: float = 3.2
const AVATAR_RADIUS_M: float = 0.8
const AVATAR_COLOR := Color(0.85, 0.80, 0.65)

# Iso dev camera — orthographic 3/4 top-down, KEY_I toggles with first-person.
const ISO_SIZE: float = 22.0              # orthographic half-extent
const ISO_OFFSET := Vector3(0, 18.0, -12.0)   # relative to player XZ
const ISO_PITCH_DEG: float = -50.0

# Reuse the same mesh aliases as main.gd — buttress borrows boulder
# shape, mega_column/column borrow stalagmite. Keeps the vector viewer
# aligned with the canonical look without re-authoring.
const MESH_ALIAS := {
	"buttress": "boulder",
	"mega_column": "stalagmite",
	"column": "stalagmite",
}

var camera: Camera3D
var iso_camera: Camera3D
var player_avatar: MeshInstance3D
var is_iso_mode: bool = false
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

# --- Encounter state --------------------------------------------------------
# UAT-1 Watcher: brain owns HP/saves/depth/resolution. This viewer reads
# manifest['encounter'] each frame and paints the orb + HUD from it.

const ORB_DISTANCE := 4.5            # meters ahead of camera for front_fov
const ORB_HEIGHT_OFFSET := -0.4      # slightly below eye line
const HUB_ARRIVAL_RADIUS := 3.0      # post-encounter hub-reentry trigger
const ACTION_KEYS := {
	KEY_T: "THINK", KEY_A: "ACT", KEY_M: "MOVE", KEY_D: "DEFEND",
	KEY_O: "OBSERVE", KEY_C: "CRAFT", KEY_B: "TOOLS",
}

var encounter_snap: Dictionary = {}
var encounter_active: bool = false
var orb_node: MeshInstance3D = null
var encounter_hud: Control = null
var orb_base_color: Color = Color(1.0, 0.08, 0.08)
var orb_base_scale: float = 1.0
var toast_label: Label = null
var toast_t_remaining: float = 0.0
var sent_hub_arrival: bool = false     # one-shot per hub re-entry
var tile_marker_nodes: Array = []      # beacons over unconsumed tiles
var roaming_orb_nodes: Dictionary = {} # id -> MeshInstance3D for kind=orb entities

# Ceremony + feedback (Pass-3 primitive layer)
var ceremony_label: Label = null
var ceremony_t_remaining: float = 0.0
var vignette_rect: ColorRect = null
var vignette_t_remaining: float = 0.0
var camera_shake_t: float = 0.0
var camera_base_pos: Vector3 = Vector3.ZERO
var prev_player_hp: int = -1
var prev_ceremony_key: String = ""   # last seen ceremony (opening/victory/defeat)

# DQ-windowed HUD nodes (Pass 4)
const TYPE_SPEED: float = 48.0        # chars/sec typewriter reveal

# -- Palette (on-register: Rucker/Carcosa + Sable-reverse + monastic) --------
# Dark indigo-black instead of DQ navy; bone ochre edges instead of pure white;
# moth-gold for ceremony; heptagon-red for damage/cursor (matches orb color).
const PAL_BG        := Color(0.04, 0.035, 0.09, 0.95)   # deep indigo-black
const PAL_BORDER    := Color(0.80, 0.72, 0.54, 0.95)    # aged bone / parchment edge
const PAL_TEXT      := Color(0.92, 0.89, 0.80, 1.0)     # bone white
const PAL_TEXT_DIM  := Color(0.55, 0.52, 0.62, 0.95)    # muted indigo-gray
const PAL_ACCENT    := Color(0.72, 0.60, 0.28, 1.0)     # moth-gold
const PAL_DANGER    := Color(0.82, 0.24, 0.20, 1.0)     # heptagon red
const PAL_TITLE     := Color(0.88, 0.82, 0.70, 1.0)     # warm bone for titles
const CORNER_GLYPH  := "◆"                               # small diamond at each corner
# Command grid is 2 columns × 4 rows, index 0..7:
#   0 THINK    1 ACT
#   2 MOVE     3 DEFEND
#   4 OBSERVE  5 CRAFT
#   6 TOOLS    7 PORTAL
const COMMAND_NAMES := ["THINK", "ACT", "MOVE", "DEFEND",
						"OBSERVE", "CRAFT", "TOOLS", "PORTAL"]
const COMMAND_COLS := 2
var orb_panel: Panel = null
var orb_name_lbl: Label = null
var orb_hp_lbl: Label = null
var orb_hp_bar_fg: ColorRect = null
var orb_hp_bar_bg: ColorRect = null
var monk_panel: Panel = null
var monk_hp_lbl: Label = null
var monk_saves_lbl: Label = null
var monk_depth_lbl: Label = null
var intent_lbl: Label = null
var log_panel: Panel = null
var log_text_lbl: Label = null
var command_panel: Panel = null
var command_labels: Array = []         # 8 Labels
var selected_cmd_index: int = 0        # arrow-key cursor position
var log_last_length: int = 0


func _ready() -> void:
	_setup_environment()
	_load_mesh_bounds()
	_load_kind_config()
	_setup_camera()
	_setup_iso_camera()
	_setup_player_avatar()
	_setup_hub_ring()
	_setup_hud()
	if UAT_MODE:
		_setup_uat_ground()
	_connect_to_brain()


func _setup_iso_camera() -> void:
	iso_camera = Camera3D.new()
	iso_camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	iso_camera.size = ISO_SIZE
	iso_camera.rotation.x = deg_to_rad(ISO_PITCH_DEG)
	iso_camera.far = 200.0
	iso_camera.current = false   # FPS is default
	add_child(iso_camera)


func _setup_player_avatar() -> void:
	player_avatar = MeshInstance3D.new()
	var mesh := CapsuleMesh.new()
	mesh.radius = AVATAR_RADIUS_M
	mesh.height = AVATAR_HEIGHT_M
	player_avatar.mesh = mesh
	var mat := StandardMaterial3D.new()
	mat.albedo_color = AVATAR_COLOR
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	player_avatar.set_surface_override_material(0, mat)
	player_avatar.visible = false   # visible in iso mode only
	add_child(player_avatar)


func _setup_hub_ring() -> void:
	# Warm amber torus at the hub spawn point — respawn anchor + orientation.
	var hub := MeshInstance3D.new()
	var ring := TorusMesh.new()
	ring.inner_radius = 1.6
	ring.outer_radius = 2.0
	var hm := StandardMaterial3D.new()
	hm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	hm.albedo_color = Color(1.0, 0.7, 0.3)
	hm.emission_enabled = true
	hm.emission = Color(1.0, 0.6, 0.2)
	hm.emission_energy_multiplier = 1.5
	ring.material = hm
	hub.mesh = ring
	hub.position = Vector3(0.0, 0.05, -14.0)
	add_child(hub)


func _setup_uat_ground() -> void:
	# Flat neutral plane for UAT-only testing. Hub ring is set up
	# separately (always visible as respawn anchor).
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(80, 80)
	var gm := StandardMaterial3D.new()
	gm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	gm.albedo_color = Color(0.16, 0.15, 0.14)
	plane.material = gm
	ground.mesh = plane
	ground.position = Vector3(0, 0, 0)
	add_child(ground)


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

	# Debug line top-left. Hidden during active encounter.
	hud_label = Label.new()
	hud_label.position = Vector2(8, 4)
	hud_label.add_theme_color_override("font_color", Color(1, 1, 1, 0.7))
	hud_label.add_theme_font_size_override("font_size", 12)
	canvas.add_child(hud_label)

	# Encounter HUD root — hidden until an encounter activates.
	encounter_hud = Control.new()
	encounter_hud.visible = false
	encounter_hud.mouse_filter = Control.MOUSE_FILTER_IGNORE
	encounter_hud.anchor_right = 1.0
	encounter_hud.anchor_bottom = 1.0
	canvas.add_child(encounter_hud)

	# -- Top-left: Orb status window ---------------------------------------
	orb_panel = _make_dq_window(Vector2(32, 32), Vector2(440, 170))
	encounter_hud.add_child(orb_panel)
	orb_name_lbl = _make_dq_label(Vector2(28, 18), 28, PAL_TITLE)
	orb_hp_lbl = _make_dq_label(Vector2(28, 64), 20, PAL_TEXT)
	orb_panel.add_child(orb_name_lbl)
	orb_panel.add_child(orb_hp_lbl)
	# Orb HP bar — segmented into notches (analog feel).
	orb_hp_bar_bg = ColorRect.new()
	orb_hp_bar_bg.color = Color(0.10, 0.05, 0.08, 0.85)
	orb_hp_bar_bg.position = Vector2(28, 112)
	orb_hp_bar_bg.size = Vector2(384, 22)
	orb_panel.add_child(orb_hp_bar_bg)
	orb_hp_bar_fg = ColorRect.new()
	orb_hp_bar_fg.color = PAL_DANGER
	orb_hp_bar_fg.position = Vector2(28, 112)
	orb_hp_bar_fg.size = Vector2(384, 22)
	orb_panel.add_child(orb_hp_bar_fg)
	# Notch dividers — 7 thin dark stripes split the bar into 8 segments.
	# Seven is the signature number (heptagon primitive), gaps carve it live.
	for i in range(1, 8):
		var notch := ColorRect.new()
		notch.color = Color(0.05, 0.03, 0.07, 1.0)
		notch.position = Vector2(28 + (384.0 / 8.0) * i - 1, 112)
		notch.size = Vector2(2, 22)
		orb_panel.add_child(notch)

	# -- Bottom-left: Monk status window (moved down from top-right
	# to match the classic DQ battle layout — three panels across the bottom).
	monk_panel = _make_dq_window(Vector2(32, -282), Vector2(380, 250))
	monk_panel.anchor_top = 1.0
	monk_panel.anchor_bottom = 1.0
	encounter_hud.add_child(monk_panel)
	var monk_title := _make_dq_label(Vector2(28, 18), 28, PAL_TITLE)
	monk_title.text = "T H E   M O N K"
	monk_hp_lbl = _make_dq_label(Vector2(28, 68), 24, PAL_DANGER)
	monk_saves_lbl = _make_dq_label(Vector2(28, 118), 20, PAL_TEXT)
	monk_depth_lbl = _make_dq_label(Vector2(28, 160), 18, PAL_TEXT_DIM)
	for l in [monk_title, monk_hp_lbl, monk_saves_lbl, monk_depth_lbl]:
		monk_panel.add_child(l)

	# -- Mid-screen: Intent telegraph (unboxed, under the orb) -------------
	intent_lbl = Label.new()
	intent_lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	intent_lbl.anchor_left = 0.15
	intent_lbl.anchor_right = 0.85
	intent_lbl.anchor_top = 0.60
	intent_lbl.anchor_bottom = 0.68
	intent_lbl.add_theme_font_size_override("font_size", 26)
	intent_lbl.add_theme_color_override("font_color", PAL_ACCENT)
	intent_lbl.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	intent_lbl.add_theme_constant_override("outline_size", 6)
	encounter_hud.add_child(intent_lbl)

	# -- Bottom-center: Log window (stretches between monk and command) ---
	log_panel = Panel.new()
	log_panel.anchor_left = 0.0
	log_panel.anchor_right = 1.0
	log_panel.anchor_top = 1.0
	log_panel.anchor_bottom = 1.0
	log_panel.offset_left = 432            # right of monk panel + gap
	log_panel.offset_right = -492          # left of command panel + gap
	log_panel.offset_top = -282
	log_panel.offset_bottom = -32
	var log_sb := StyleBoxFlat.new()
	log_sb.bg_color = PAL_BG
	log_sb.border_color = PAL_BORDER
	log_sb.border_width_left = 3
	log_sb.border_width_right = 3
	log_sb.border_width_top = 3
	log_sb.border_width_bottom = 3
	log_sb.content_margin_left = 14
	log_sb.content_margin_right = 14
	log_sb.content_margin_top = 10
	log_sb.content_margin_bottom = 10
	log_panel.add_theme_stylebox_override("panel", log_sb)
	encounter_hud.add_child(log_panel)

	log_text_lbl = Label.new()
	log_text_lbl.anchor_left = 0.0
	log_text_lbl.anchor_right = 1.0
	log_text_lbl.anchor_top = 0.0
	log_text_lbl.anchor_bottom = 1.0
	log_text_lbl.offset_left = 28
	log_text_lbl.offset_right = -28
	log_text_lbl.offset_top = 22
	log_text_lbl.offset_bottom = -22
	log_text_lbl.add_theme_font_size_override("font_size", 20)
	log_text_lbl.add_theme_color_override("font_color", PAL_TEXT)
	log_text_lbl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	log_text_lbl.vertical_alignment = VERTICAL_ALIGNMENT_TOP
	log_panel.add_child(log_text_lbl)

	# Corner glyphs for the stretched log panel — anchor-based since size is dynamic.
	for corner in [
		{"anchor": Vector2(0, 0), "offset": Vector2(4, -2)},
		{"anchor": Vector2(1, 0), "offset": Vector2(-18, -2)},
		{"anchor": Vector2(0, 1), "offset": Vector2(4, -22)},
		{"anchor": Vector2(1, 1), "offset": Vector2(-18, -22)},
	]:
		var g := Label.new()
		g.text = CORNER_GLYPH
		g.anchor_left = corner["anchor"].x
		g.anchor_right = corner["anchor"].x
		g.anchor_top = corner["anchor"].y
		g.anchor_bottom = corner["anchor"].y
		g.offset_left = corner["offset"].x
		g.offset_top = corner["offset"].y
		g.add_theme_font_size_override("font_size", 16)
		g.add_theme_color_override("font_color", PAL_BORDER)
		log_panel.add_child(g)

	# -- Bottom-right: Command window (2×4 grid) ---------------------------
	command_panel = _make_dq_window(Vector2(-472, -282), Vector2(440, 250))
	command_panel.anchor_left = 1.0
	command_panel.anchor_right = 1.0
	command_panel.anchor_top = 1.0
	command_panel.anchor_bottom = 1.0
	encounter_hud.add_child(command_panel)

	var grid := GridContainer.new()
	grid.columns = COMMAND_COLS
	grid.position = Vector2(24, 18)
	grid.size = Vector2(392, 214)
	grid.add_theme_constant_override("h_separation", 24)
	grid.add_theme_constant_override("v_separation", 14)
	command_panel.add_child(grid)
	for n in COMMAND_NAMES:
		var l := Label.new()
		l.text = "  " + n
		l.add_theme_font_size_override("font_size", 24)
		l.add_theme_color_override("font_color", PAL_TEXT)
		grid.add_child(l)
		command_labels.append(l)

	# -- Ceremony (center, unchanged) --------------------------------------
	ceremony_label = Label.new()
	ceremony_label.add_theme_font_size_override("font_size", 60)
	ceremony_label.add_theme_color_override("font_color", PAL_ACCENT)
	ceremony_label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.9))
	ceremony_label.add_theme_constant_override("outline_size", 12)
	ceremony_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	ceremony_label.anchor_left = 0.1
	ceremony_label.anchor_right = 0.9
	ceremony_label.anchor_top = 0.35
	ceremony_label.anchor_bottom = 0.55
	ceremony_label.offset_left = 0
	ceremony_label.offset_right = 0
	ceremony_label.visible = false
	canvas.add_child(ceremony_label)

	# -- Vignette ----------------------------------------------------------
	vignette_rect = ColorRect.new()
	vignette_rect.color = Color(0.8, 0.0, 0.0, 0.0)
	vignette_rect.anchor_right = 1.0
	vignette_rect.anchor_bottom = 1.0
	vignette_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	canvas.add_child(vignette_rect)

	# Legacy toast (kept but unused — Pass 2 artifact)
	toast_label = Label.new()
	toast_label.visible = false
	canvas.add_child(toast_label)

	# Crosshair — center of screen, both FPS and iso. Shows player facing.
	var crosshair := Label.new()
	crosshair.text = "◆"
	crosshair.anchor_left = 0.5
	crosshair.anchor_right = 0.5
	crosshair.anchor_top = 0.5
	crosshair.anchor_bottom = 0.5
	crosshair.offset_left = -10
	crosshair.offset_right = 10
	crosshair.offset_top = -14
	crosshair.offset_bottom = 14
	crosshair.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	crosshair.add_theme_font_size_override("font_size", 18)
	crosshair.add_theme_color_override("font_color", Color(0.95, 0.9, 0.7, 0.6))
	crosshair.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	crosshair.add_theme_constant_override("outline_size", 3)
	canvas.add_child(crosshair)

	add_child(canvas)


func _make_dq_window(pos: Vector2, size: Vector2) -> Panel:
	var panel := Panel.new()
	panel.position = pos
	panel.size = size
	var sb := StyleBoxFlat.new()
	sb.bg_color = PAL_BG
	sb.border_color = PAL_BORDER
	sb.border_width_left = 3
	sb.border_width_right = 3
	sb.border_width_top = 3
	sb.border_width_bottom = 3
	sb.content_margin_left = 14
	sb.content_margin_right = 14
	sb.content_margin_top = 10
	sb.content_margin_bottom = 10
	panel.add_theme_stylebox_override("panel", sb)
	_add_corner_glyphs(panel, size)
	return panel


func _add_corner_glyphs(panel: Panel, size: Vector2) -> void:
	# Four small marks, one per corner — signature motif that repeats the
	# primitive's heptagon-mote lineage (stylized as diamond for type-safe rendering).
	var positions := [
		Vector2(4, -2),                    # top-left
		Vector2(size.x - 18, -2),          # top-right
		Vector2(4, size.y - 20),           # bottom-left
		Vector2(size.x - 18, size.y - 20), # bottom-right
	]
	for p in positions:
		var g := Label.new()
		g.text = CORNER_GLYPH
		g.position = p
		g.add_theme_font_size_override("font_size", 16)
		g.add_theme_color_override("font_color", PAL_BORDER)
		panel.add_child(g)


func _make_dq_label(pos: Vector2, size: int, color: Color) -> Label:
	var l := Label.new()
	l.position = pos
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	return l


func _make_hud_label(pos: Vector2, size: int, color: Color) -> Label:
	var l := Label.new()
	l.position = pos
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	return l


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
		# Encounter acks are single-key dicts, not full manifests
		if data.has("encounter_action"):
			_on_action_ack(data["encounter_action"])
			continue
		if data.has("encounter_portal"):
			_flash_outcome("PORTAL")
			continue
		if data.has("encounter_consolidate"):
			var cons_raw = data.get("encounter_consolidate", null)
			var cons: Dictionary = cons_raw if cons_raw is Dictionary else {}
			var shift: float = float(cons.get("depth_shift", 0.0))
			if shift > 0.0:
				_flash_outcome("DEPTH +%.2f" % shift)
			continue
		if data.has("encounter_error"):
			print("encounter_error: ", data["encounter_error"])
			continue
		if data.get("unchanged", false):
			continue
		manifest = data
		_rebuild_entities()
		_refresh_encounter(manifest.get("encounter", {}))


func _maybe_send_camera(delta: float) -> void:
	last_cam_send_t += delta
	if last_cam_send_t < 1.0 / CAMERA_SEND_HZ:
		return
	last_cam_send_t = 0.0
	# Brain reads cam_x/cam_y/cam_z (see brain_server.py:913). Earlier
	# x/y/z naming silently defaulted to 0,0 server-side.
	var msg := JSON.stringify({
		"cam_x": camera.position.x,
		"cam_y": camera.position.z,   # brain's Y = Godot's Z
		"cam_z": camera.position.y,
		"heading": rad_to_deg(camera.rotation.y),
		"pitch": rad_to_deg(camera.rotation.x),
		"dt": 1.0 / CAMERA_SEND_HZ,
	}) + "\n"
	tcp.put_data(msg.to_utf8_buffer())


# --- Rendering --------------------------------------------------------------

func _rebuild_entities() -> void:
	var ents: Array = manifest.get("entities", [])

	# Roaming orbs — rendered per-entity as emissive spheres (kind_shader's
	# MultiMesh path doesn't match our unshaded emissive aesthetic). Pull
	# them out of the kind-grouping step.
	var orb_ents: Array = []
	var non_orb: Array = []
	for e in ents:
		if e is Dictionary and e.get("kind") == "orb":
			orb_ents.append(e)
		else:
			non_orb.append(e)
	_sync_roaming_orbs(orb_ents)
	ents = non_orb

	if UAT_MODE:
		# Drop any kinds we spawned previously (e.g. after toggling the flag
		# at runtime). Encounter rendering handles its own nodes.
		for k in kind_nodes.keys():
			if is_instance_valid(kind_nodes[k]):
				kind_nodes[k].queue_free()
		kind_nodes.clear()
		if hud_label:
			if encounter_active:
				hud_label.text = ""
			else:
				var cx := camera.position.x
				var cz := camera.position.z
				hud_label.text = "vector · UAT · (%5.1f, %5.1f)%s" % [
					cx, cz, _nearest_tile_hint(cx, cz)]
		return

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
		var nearest: String = _nearest_tile_hint(cam_x, cam_z)
		hud_label.text = "vector · (%5.1f, %5.1f) · ents %d%s" % [
			cam_x, cam_z, ents.size(), nearest]


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
	# Encounter controls — arrow keys navigate grid, Enter confirms.
	# P is a global portal shortcut (works mid-encounter).
	if event is InputEventKey and event.pressed and not event.echo:
		var key: int = event.physical_keycode
		# KEY_I toggles iso/fp camera — always available
		if key == KEY_I:
			_toggle_iso()
			return
		if key == KEY_P and encounter_active:
			_send_encounter_cmd({"cmd": "encounter_portal"})
			return
		if encounter_active:
			if key == KEY_UP:
				_move_cursor(-COMMAND_COLS)
			elif key == KEY_DOWN:
				_move_cursor(COMMAND_COLS)
			elif key == KEY_LEFT:
				_move_cursor_horizontal(-1)
			elif key == KEY_RIGHT:
				_move_cursor_horizontal(1)
			elif key == KEY_ENTER or key == KEY_KP_ENTER or key == KEY_SPACE:
				_confirm_selected_command()


func _physics_process(delta: float) -> void:
	# Tick toast timer regardless of freeze
	if toast_t_remaining > 0.0:
		toast_t_remaining -= delta
		if toast_t_remaining <= 0.0 and toast_label:
			toast_label.visible = false

	# Ceremony fade-out after its hold window
	if ceremony_t_remaining > 0.0:
		ceremony_t_remaining -= delta
		if ceremony_t_remaining <= 0.0 and ceremony_label:
			var tw := create_tween()
			tw.tween_property(ceremony_label, "modulate:a", 0.0, 0.5)
			tw.tween_callback(func(): ceremony_label.visible = false)

	# Vignette fade
	if vignette_t_remaining > 0.0:
		vignette_t_remaining -= delta
		if vignette_rect:
			var alpha: float = max(0.0, vignette_t_remaining / 0.4) * 0.5
			vignette_rect.color = Color(0.8, 0.0, 0.0, alpha)

	# Typewriter tick
	_tick_typewriter(delta)

	# Player avatar follows camera XZ; iso camera follows player.
	if player_avatar:
		player_avatar.position = Vector3(
			camera.position.x,
			AVATAR_HEIGHT_M * 0.5,
			camera.position.z)
	if iso_camera:
		iso_camera.position = Vector3(
			camera.position.x + ISO_OFFSET.x,
			ISO_OFFSET.y,
			camera.position.z + ISO_OFFSET.z)

	# Camera shake — random offsets for the shake window
	if camera_shake_t > 0.0 and camera:
		camera_shake_t -= delta
		var mag: float = max(0.0, camera_shake_t / 0.25) * 0.08
		camera.position = camera_base_pos + Vector3(
			randf_range(-mag, mag), randf_range(-mag, mag), randf_range(-mag, mag))
		if camera_shake_t <= 0.0:
			camera.position = camera_base_pos

	# Movement frozen during encounter; environment continues breathing.
	if encounter_active:
		return

	# FP camera's heading = the player's facing vector. Iso view is just a
	# different lens to watch from; it never drives input. WASD and mouse-look
	# always operate on the FP camera, so controls stay stable across toggles.
	var fwd: Vector3 = -camera.global_transform.basis.z
	var right: Vector3 = camera.global_transform.basis.x
	fwd.y = 0.0
	right.y = 0.0
	if fwd.length_squared() > 0.001:
		fwd = fwd.normalized()
	if right.length_squared() > 0.001:
		right = right.normalized()

	var dir := Vector3.ZERO
	if Input.is_key_pressed(KEY_W):
		dir += fwd
	if Input.is_key_pressed(KEY_S):
		dir -= fwd
	if Input.is_key_pressed(KEY_A):
		dir -= right
	if Input.is_key_pressed(KEY_D):
		dir += right
	dir.y = 0.0
	if dir.length_squared() > 0.001:
		dir = dir.normalized()
	camera.position += dir * MOVE_SPEED * delta
	camera.position.y = EYE_HEIGHT

	# Rotate the avatar to match the player's facing — only matters in iso
	# view but it's cheap; drives the pill's visual orientation so the user
	# can see which way they're pointing.
	if player_avatar:
		player_avatar.rotation.y = camera.rotation.y

	# Hub-arrival detection — one-shot per re-entry. Sends consolidate cmd
	# when camera crosses back into the hub ring after leaving it.
	var hub_raw = encounter_snap.get("hub_spawn", null) if encounter_snap else null
	var hub: Array = hub_raw if hub_raw is Array else [0.0, -14.0]
	var dxh: float = camera.position.x - float(hub[0])
	var dzh: float = camera.position.z - float(hub[1])
	var in_hub: bool = (dxh * dxh + dzh * dzh) <= (HUB_ARRIVAL_RADIUS * HUB_ARRIVAL_RADIUS)
	if in_hub and not sent_hub_arrival:
		var prog_raw = encounter_snap.get("progression", null) if encounter_snap else null
		var prog: Dictionary = prog_raw if prog_raw is Dictionary else {}
		var staged: float = float(prog.get("staged_xp", 0.0))
		if staged > 0.0 and connected:
			_send_encounter_cmd({"cmd": "encounter_hub_arrival"})
		sent_hub_arrival = true
	elif not in_hub:
		sent_hub_arrival = false


# --- Encounter rendering ----------------------------------------------------

func _refresh_encounter(enc_raw) -> void:
	# Manifest may carry null or an absent key; coerce to empty dict.
	var enc: Dictionary = enc_raw if enc_raw is Dictionary else {}
	encounter_snap = enc
	var active_raw = enc.get("active", null)
	var active: Dictionary = active_raw if active_raw is Dictionary else {}
	var is_active: bool = not active.is_empty()
	encounter_active = is_active
	encounter_hud.visible = is_active

	if is_active:
		_ensure_orb(active)
		_update_hud(enc)
	else:
		_despawn_orb()
		# Encounter ended — check for a last_outcome ceremony to display.
		var lo_raw = enc.get("last_outcome", null)
		if lo_raw is Dictionary and lo_raw.has("ceremony"):
			var key: String = str(lo_raw["ceremony"])
			if key != prev_ceremony_key:
				_show_ceremony(str(lo_raw.get("ceremony_text", key.to_upper())))
				prev_ceremony_key = key
		else:
			# Fully cleared — ready for next encounter
			prev_ceremony_key = ""

	_refresh_tile_markers(enc)


func _ensure_orb(active: Dictionary) -> void:
	if orb_node and is_instance_valid(orb_node):
		return
	orb_node = MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 0.6
	sphere.height = 1.2
	# Primitive shape: snapshot.active.orb.visual carries base_color/emission/pulse
	var orb_raw = active.get("orb", null)
	var orb_data: Dictionary = orb_raw if orb_raw is Dictionary else {}
	var vis_raw = orb_data.get("visual", null)
	var visual: Dictionary = vis_raw if vis_raw is Dictionary else {}
	var col_raw = visual.get("base_color", null)
	var col_arr: Array = col_raw if col_raw is Array else [1.0, 0.08, 0.08]
	var col := Color(
		float(col_arr[0]) if col_arr.size() > 0 else 1.0,
		float(col_arr[1]) if col_arr.size() > 1 else 0.08,
		float(col_arr[2]) if col_arr.size() > 2 else 0.08)
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = col
	mat.emission_enabled = true
	mat.emission = col
	mat.emission_energy_multiplier = float(visual.get("emission", 2.5))
	mat.no_depth_test = true   # red_orb_fixture pattern: always visible
	sphere.material = mat
	orb_node.mesh = sphere
	# Place ORB_DISTANCE ahead of camera, regardless of facing.
	var fwd := -camera.global_transform.basis.z
	fwd.y = 0.0
	if fwd.length_squared() > 0.001:
		fwd = fwd.normalized()
	orb_node.position = camera.position + fwd * ORB_DISTANCE + Vector3(0, ORB_HEIGHT_OFFSET, 0)
	add_child(orb_node)


func _despawn_orb() -> void:
	if orb_node and is_instance_valid(orb_node):
		orb_node.queue_free()
	orb_node = null


func _refresh_tile_markers(enc: Dictionary) -> void:
	# UAT-1 artifact — fixed-tile cyan pillars. Tartarus mode uses roaming
	# orb entities from the brain pool, not tiles, so this is a no-op here.
	# Left in place so UAT_MODE=true still paints the arena if someone flips it.
	for n in tile_marker_nodes:
		if is_instance_valid(n):
			n.queue_free()
	tile_marker_nodes.clear()
	if not UAT_MODE:
		return
	if encounter_active:
		return

	var tiles_raw = enc.get("tiles", null)
	if not (tiles_raw is Array):
		return
	for t in tiles_raw:
		if not (t is Dictionary):
			continue
		if t.get("consumed", false):
			continue
		var tx: float = float(t.get("x", 0.0))
		var ty: float = float(t.get("y", 0.0))
		var pillar := MeshInstance3D.new()
		var mesh := CylinderMesh.new()
		mesh.top_radius = 0.15
		mesh.bottom_radius = 0.15
		mesh.height = 6.0
		var mat := StandardMaterial3D.new()
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		mat.albedo_color = Color(0.3, 0.9, 1.0, 0.7)
		mat.emission_enabled = true
		mat.emission = Color(0.3, 0.9, 1.0)
		mat.emission_energy_multiplier = 2.0
		mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		mesh.material = mat
		pillar.mesh = mesh
		# Godot y = brain z (height); brain's (x, y) is ground plane → Godot (x, ?, z)
		pillar.position = Vector3(tx, 3.0, ty)
		add_child(pillar)
		tile_marker_nodes.append(pillar)


func _update_hud(enc: Dictionary) -> void:
	var a_raw = enc.get("active", null)
	var active: Dictionary = a_raw if a_raw is Dictionary else {}
	var p_raw = enc.get("player", null)
	var p: Dictionary = p_raw if p_raw is Dictionary else {}
	var pr_raw = enc.get("progression", null)
	var prog: Dictionary = pr_raw if pr_raw is Dictionary else {}

	# Player-hit feedback: detect HP drop frame-over-frame.
	var cur_hp: int = int(p.get("hp", -1))
	if prev_player_hp > 0 and cur_hp < prev_player_hp:
		_trigger_damage_feedback()
	prev_player_hp = cur_hp

	# Orb window
	var orb_raw = active.get("orb", null)
	var orb_data: Dictionary = orb_raw if orb_raw is Dictionary else {}
	var orb_name: String = str(orb_data.get("name", "watcher")).to_upper()
	var o_hp: int = int(orb_data.get("hp", 0))
	var o_max: int = int(orb_data.get("max_hp", 1))
	if orb_name_lbl:
		orb_name_lbl.text = orb_name
	if orb_hp_lbl:
		orb_hp_lbl.text = "HP  %d / %d" % [o_hp, o_max]
	if orb_hp_bar_fg and o_max > 0:
		orb_hp_bar_fg.size.x = 244.0 * (float(o_hp) / float(o_max))

	# Monk window
	if monk_hp_lbl:
		monk_hp_lbl.text = "HP  %d / %d" % [
			int(p.get("hp", 0)), int(p.get("max_hp", 0))]
	if monk_saves_lbl:
		monk_saves_lbl.text = "STR %d   DEX %d   WIL %d" % [
			int(p.get("str_save", 0)),
			int(p.get("dex_save", 0)),
			int(p.get("wil_save", 0))]
	if monk_depth_lbl:
		monk_depth_lbl.text = "DEPTH  %.2f     STAGED  %.2f" % [
			float(prog.get("depth", 0.0)),
			float(prog.get("staged_xp", 0.0))]

	# Intent telegraph (screen-center below orb, no panel)
	var telegraph: String = str(active.get("intent_telegraph", ""))
	if intent_lbl:
		intent_lbl.text = telegraph if telegraph != "" else ""

	# Opening ceremony — first time we see an active encounter this trigger.
	var cer_raw = active.get("ceremony", null)
	var cer: Dictionary = cer_raw if cer_raw is Dictionary else {}
	if prev_ceremony_key == "" and cer.has("opening"):
		_show_ceremony(str(cer["opening"]))
		prev_ceremony_key = "opening"
		# Fresh encounter — reset the command cursor to the top.
		selected_cmd_index = 0
		_refresh_command_cursor()

	# Log — build full text, typewriter-reveal via visible_characters
	var log_raw = active.get("log", null)
	var log_lines: Array = log_raw if log_raw is Array else []
	var log_txt := ""
	for entry in log_lines:
		if entry is Dictionary:
			var role: String = str(entry.get("action", ""))
			var text: String = str(entry.get("text", ""))
			var prefix: String = "> " if role != "—" and not role.begins_with("[") else "  "
			log_txt += "%s%s\n" % [prefix, text]
	if log_text_lbl:
		if log_txt != log_text_lbl.text:
			# New content arrived — rewind typewriter to just before the new tail.
			var old_len := log_text_lbl.visible_characters if log_text_lbl.visible_characters > 0 else 0
			log_text_lbl.text = log_txt
			# If log shrank (new encounter started), snap to full reveal
			if log_txt.length() < log_last_length:
				log_text_lbl.visible_characters = log_txt.length()
			else:
				log_text_lbl.visible_characters = min(old_len, log_txt.length())
			log_last_length = log_txt.length()

	# Command menu cursor — ▸ prefix on last-pressed action
	_refresh_command_cursor()


func _on_action_ack(result_raw) -> void:
	var result: Dictionary = result_raw if result_raw is Dictionary else {}
	var res: String = str(result.get("resolution", "pending"))
	var save: String = str(result.get("save", ""))

	# Orb reactivity — four behaviors keyed off outcome state.
	if res == "resolved":
		_orb_react("resolved")
		_flash_outcome("RESOLVED +%.2f xp" % float(result.get("xp_staged", 0.0)))
	elif res == "defeated":
		_orb_react("defeated")
		_flash_outcome("DEFEATED — respawn")
	elif save == "pass":
		_orb_react("pass")
	elif save == "fail":
		_orb_react("fail")
	else:
		_orb_react("brace")   # DEFEND / no-roll


func _orb_react(state: String) -> void:
	if orb_node == null or not is_instance_valid(orb_node):
		return
	var mat: StandardMaterial3D = orb_node.mesh.material
	if mat == null:
		return
	# Kill any in-flight tweens so overlapping actions don't stack.
	var tw := create_tween()
	tw.set_parallel(true)
	match state:
		"pass":
			# soft ripple: scale ×1.25 → 1.0 over 0.3s
			tw.tween_property(orb_node, "scale", Vector3.ONE * 1.25, 0.12)
			tw.chain().tween_property(orb_node, "scale", Vector3.ONE, 0.18)
		"fail":
			# sharp white flash + scale jab
			tw.tween_property(mat, "emission", Color(1, 1, 1), 0.05)
			tw.tween_property(orb_node, "scale", Vector3.ONE * 1.35, 0.05)
			tw.chain().tween_property(mat, "emission", orb_base_color, 0.15)
			tw.parallel().tween_property(orb_node, "scale", Vector3.ONE, 0.15)
		"brace":
			# steady gold pulse — player is tanking, orb acknowledges
			tw.tween_property(mat, "emission_energy_multiplier", 4.0, 0.1)
			tw.chain().tween_property(mat, "emission_energy_multiplier", 2.5, 0.3)
		"resolved":
			# bloom + despawn: scale ×2.5, emission ×3, fade to transparent
			tw.tween_property(orb_node, "scale", Vector3.ONE * 2.5, 0.8)
			tw.parallel().tween_property(mat, "emission_energy_multiplier", 8.0, 0.6)
			tw.parallel().tween_property(mat, "albedo_color",
				Color(orb_base_color.r, orb_base_color.g, orb_base_color.b, 0.0), 0.8)
			tw.chain().tween_callback(_despawn_orb)
		"defeated":
			# violent shake + emission fade
			var base_pos: Vector3 = orb_node.position
			for i in 6:
				var jit := Vector3(
					randf_range(-0.25, 0.25), 0.0, randf_range(-0.25, 0.25))
				tw.tween_property(orb_node, "position", base_pos + jit, 0.05)
				tw.chain()
			tw.tween_property(orb_node, "position", base_pos, 0.1)
			tw.parallel().tween_property(
				mat, "emission_energy_multiplier", 0.3, 0.4)


func _flash_outcome(text: String) -> void:
	if toast_label == null:
		return
	toast_label.text = text
	toast_label.visible = true
	toast_t_remaining = 2.5


func _nearest_tile_hint(cx: float, cz: float) -> String:
	var tiles_raw = encounter_snap.get("tiles", null) if encounter_snap else null
	if not (tiles_raw is Array):
		return ""
	var best := -1.0
	var best_pos := Vector2.ZERO
	for t in tiles_raw:
		if not (t is Dictionary):
			continue
		if t.get("consumed", false):
			continue
		var tx: float = float(t.get("x", 0.0))
		var ty: float = float(t.get("y", 0.0))
		var d := sqrt((cx - tx) * (cx - tx) + (cz - ty) * (cz - ty))
		if best < 0.0 or d < best:
			best = d
			best_pos = Vector2(tx, ty)
	if best < 0.0:
		return " · tiles clear"
	return " · tile @ (%.1f, %.1f) dist %.1fm" % [best_pos.x, best_pos.y, best]


func _sync_roaming_orbs(orb_ents: Array) -> void:
	# Diff current nodes against the new orb list: spawn new, move existing, free missing.
	var seen_ids := {}
	for e in orb_ents:
		var id: String = str(e.get("id", ""))
		if id == "":
			continue
		seen_ids[id] = true
		var node: MeshInstance3D
		if roaming_orb_nodes.has(id) and is_instance_valid(roaming_orb_nodes[id]):
			node = roaming_orb_nodes[id]
		else:
			node = _spawn_roaming_orb_node()
			roaming_orb_nodes[id] = node
		node.position = Vector3(
			float(e.get("x", 0.0)),
			float(e.get("z", 0.8)),      # altitude lifted (float over ground)
			float(e.get("y", 0.0)))

	# Free orbs that are no longer in the manifest (consumed or despawned).
	for id in roaming_orb_nodes.keys():
		if not seen_ids.has(id):
			if is_instance_valid(roaming_orb_nodes[id]):
				roaming_orb_nodes[id].queue_free()
			roaming_orb_nodes.erase(id)


func _spawn_roaming_orb_node() -> MeshInstance3D:
	var node := MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 0.55
	sphere.height = 1.1
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color(1.0, 0.1, 0.1)
	mat.emission_enabled = true
	mat.emission = Color(1.0, 0.1, 0.1)
	mat.emission_energy_multiplier = 2.2
	sphere.material = mat
	node.mesh = sphere
	add_child(node)
	return node


func _toggle_iso() -> void:
	is_iso_mode = not is_iso_mode
	if is_iso_mode:
		iso_camera.current = true
		camera.current = false
		player_avatar.visible = true
	else:
		camera.current = true
		iso_camera.current = false
		player_avatar.visible = false


func _refresh_command_cursor() -> void:
	for i in range(command_labels.size()):
		var lbl: Label = command_labels[i]
		var n: String = COMMAND_NAMES[i]
		if i == selected_cmd_index:
			lbl.text = "◆ " + n
			lbl.add_theme_color_override("font_color", PAL_ACCENT)
		else:
			lbl.text = "  " + n
			lbl.add_theme_color_override("font_color", PAL_TEXT_DIM)


func _move_cursor(delta: int) -> void:
	var total: int = COMMAND_NAMES.size()
	var next: int = selected_cmd_index + delta
	# Clamp vertically (DQ doesn't wrap up/down)
	if next < 0 or next >= total:
		return
	selected_cmd_index = next
	_refresh_command_cursor()


func _move_cursor_horizontal(delta: int) -> void:
	# Left/Right flips the column bit in a 2-col grid.
	var col: int = selected_cmd_index % COMMAND_COLS
	var row: int = selected_cmd_index / COMMAND_COLS
	var next_col: int = col + delta
	if next_col < 0 or next_col >= COMMAND_COLS:
		return
	selected_cmd_index = row * COMMAND_COLS + next_col
	_refresh_command_cursor()


func _confirm_selected_command() -> void:
	var chosen: String = COMMAND_NAMES[selected_cmd_index]
	if chosen == "PORTAL":
		_send_encounter_cmd({"cmd": "encounter_portal"})
	else:
		_send_encounter_cmd({
			"cmd": "encounter_action",
			"action": chosen,
		})


func _tick_typewriter(delta: float) -> void:
	if log_text_lbl == null:
		return
	var total: int = log_text_lbl.text.length()
	if log_text_lbl.visible_characters >= total:
		return
	var step: int = max(1, int(TYPE_SPEED * delta))
	log_text_lbl.visible_characters = min(
		total, log_text_lbl.visible_characters + step)


func _show_ceremony(text: String) -> void:
	if ceremony_label == null:
		return
	ceremony_label.text = text
	ceremony_label.modulate = Color(1, 1, 1, 0)
	ceremony_label.visible = true
	ceremony_t_remaining = 3.5
	var tw := create_tween()
	tw.tween_property(ceremony_label, "modulate:a", 1.0, 1.0)


func _trigger_damage_feedback() -> void:
	# Camera shake — 0.25s of jitter on camera.position offsets
	camera_shake_t = 0.25
	if camera:
		camera_base_pos = camera.position
	# Red vignette flash
	vignette_t_remaining = 0.4
	if vignette_rect:
		vignette_rect.color = Color(0.8, 0.0, 0.0, 0.5)


func _send_encounter_cmd(payload: Dictionary) -> void:
	if not connected or tcp == null:
		return
	var s := JSON.stringify(payload) + "\n"
	tcp.put_data(s.to_utf8_buffer())
