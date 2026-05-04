extends Node
class_name EncounterHUD

const TypedText = preload("res://ui/typed_text.gd")
# Encounter HUD — shared UI module for the Tartarus-style encounter system.
# Self-contained: builds its own CanvasLayer, renders the 4-panel layout
# (orb / monk / log / commands), manages roaming-orb rendering, handles
# input, and emits signals for brain commands.
#
# Hosts (main.gd, vector_viewer.gd):
#   var hud = preload("res://encounter_hud.gd").new()
#   add_child(hud); hud.setup(camera_ref)
#   hud.action_chosen.connect(func(n): send_cmd("encounter_action", {"action":n}))
#   hud.portal_requested.connect(func(): send_cmd("encounter_portal", {}))
#   hud.hub_arrival_needed.connect(func(): send_cmd("encounter_hub_arrival", {}))
#   in _process: hud.update_snapshot(manifest.get("encounter", {}));
#                hud.sync_orb_entities(manifest.get("entities", []));
#                hud.tick(delta)
#   in input handler: if hud.handle_key(ev.physical_keycode): return

signal action_chosen(action: String)
signal portal_requested
signal hub_arrival_needed

# -- Palette (Rucker/Carcosa register) ---------------------------------------
const PAL_BG        := Color(0.04, 0.035, 0.09, 0.95)
const PAL_BORDER    := Color(0.80, 0.72, 0.54, 0.95)
const PAL_TEXT      := Color(0.92, 0.89, 0.80, 1.0)
const PAL_TEXT_DIM  := Color(0.55, 0.52, 0.62, 0.95)
const PAL_ACCENT    := Color(0.72, 0.60, 0.28, 1.0)
const PAL_DANGER    := Color(0.82, 0.24, 0.20, 1.0)
const PAL_TITLE     := Color(0.88, 0.82, 0.70, 1.0)
const CORNER_GLYPH  := "◆"

const TYPE_SPEED: float = 48.0
# Fallback verb set used before the first active-encounter snapshot arrives.
# Real verb list comes from manifest.encounter.active.verbs each frame.
const FALLBACK_COMMANDS := ["PROBE", "PRESS", "YIELD", "RIDDLE", "LISTEN", "PORTAL"]
const COMMAND_COLS := 2
const HUB_ARRIVAL_RADIUS := 3.0

# -- Host-provided refs ------------------------------------------------------
var _camera: Camera3D = null              # for camera shake on HP loss

# -- Nodes -------------------------------------------------------------------
var canvas: CanvasLayer = null
var encounter_hud_root: Control = null
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
var command_labels: Array = []
var ceremony_label: TypedText = null
var vignette_rect: ColorRect = null
var crosshair_label: Label = null

# -- State -------------------------------------------------------------------
var encounter_snap: Dictionary = {}
var encounter_active: bool = false
var selected_cmd_index: int = 0
var current_commands: Array = []        # verbs currently rendered (incl. PORTAL)
var command_grid: GridContainer = null
var prev_player_hp: int = -1
var prev_ceremony_key: String = ""
var ceremony_t_remaining: float = 0.0
var vignette_t_remaining: float = 0.0
var camera_shake_t: float = 0.0
var camera_base_pos: Vector3 = Vector3.ZERO
var log_last_length: int = 0
var sent_hub_arrival: bool = false
var roaming_orb_nodes: Dictionary = {}
var _orb_texture: ImageTexture = null
var _bob_t: float = 0.0


func setup(cam: Camera3D) -> void:
	_camera = cam
	canvas = CanvasLayer.new()
	add_child(canvas)
	_build_hud()


# -- HUD construction --------------------------------------------------------

func _build_hud() -> void:
	encounter_hud_root = Control.new()
	encounter_hud_root.visible = false
	encounter_hud_root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	encounter_hud_root.anchor_right = 1.0
	encounter_hud_root.anchor_bottom = 1.0
	canvas.add_child(encounter_hud_root)

	# Orb window — top-left
	orb_panel = _make_window(Vector2(32, 32), Vector2(440, 170))
	encounter_hud_root.add_child(orb_panel)
	orb_name_lbl = _make_label(Vector2(28, 18), 28, PAL_TITLE)
	orb_hp_lbl = _make_label(Vector2(28, 64), 20, PAL_TEXT)
	orb_panel.add_child(orb_name_lbl)
	orb_panel.add_child(orb_hp_lbl)
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
	for i in range(1, 8):
		var notch := ColorRect.new()
		notch.color = Color(0.05, 0.03, 0.07, 1.0)
		notch.position = Vector2(28 + (384.0 / 8.0) * i - 1, 112)
		notch.size = Vector2(2, 22)
		orb_panel.add_child(notch)

	# Monk window — bottom-left
	monk_panel = _make_window(Vector2(32, -282), Vector2(380, 250))
	monk_panel.anchor_top = 1.0
	monk_panel.anchor_bottom = 1.0
	encounter_hud_root.add_child(monk_panel)
	var monk_title := _make_label(Vector2(28, 18), 28, PAL_TITLE)
	monk_title.text = "T H E   M O N K"
	monk_hp_lbl = _make_label(Vector2(28, 68), 24, PAL_DANGER)
	monk_saves_lbl = _make_label(Vector2(28, 118), 20, PAL_TEXT)
	monk_depth_lbl = _make_label(Vector2(28, 160), 18, PAL_TEXT_DIM)
	for l in [monk_title, monk_hp_lbl, monk_saves_lbl, monk_depth_lbl]:
		monk_panel.add_child(l)

	# Intent telegraph (center, no panel)
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
	encounter_hud_root.add_child(intent_lbl)

	# Log window — bottom stretch
	log_panel = Panel.new()
	log_panel.anchor_left = 0.0
	log_panel.anchor_right = 1.0
	log_panel.anchor_top = 1.0
	log_panel.anchor_bottom = 1.0
	log_panel.offset_left = 432
	log_panel.offset_right = -492
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
	encounter_hud_root.add_child(log_panel)
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
	# Corner glyphs for stretched log panel
	for c in [
		{"ax": 0.0, "ay": 0.0, "ox": 4.0, "oy": -2.0},
		{"ax": 1.0, "ay": 0.0, "ox": -18.0, "oy": -2.0},
		{"ax": 0.0, "ay": 1.0, "ox": 4.0, "oy": -22.0},
		{"ax": 1.0, "ay": 1.0, "ox": -18.0, "oy": -22.0},
	]:
		var g := Label.new()
		g.text = CORNER_GLYPH
		g.anchor_left = c["ax"]
		g.anchor_right = c["ax"]
		g.anchor_top = c["ay"]
		g.anchor_bottom = c["ay"]
		g.offset_left = c["ox"]
		g.offset_top = c["oy"]
		g.add_theme_font_size_override("font_size", 16)
		g.add_theme_color_override("font_color", PAL_BORDER)
		log_panel.add_child(g)

	# Command window — bottom-right. Labels are populated lazily from the
	# first encounter snapshot's `verbs` list so the HUD adapts to dialog
	# vs action verb sets without code changes.
	command_panel = _make_window(Vector2(-472, -282), Vector2(440, 250))
	command_panel.anchor_left = 1.0
	command_panel.anchor_right = 1.0
	command_panel.anchor_top = 1.0
	command_panel.anchor_bottom = 1.0
	encounter_hud_root.add_child(command_panel)
	command_grid = GridContainer.new()
	command_grid.columns = COMMAND_COLS
	command_grid.position = Vector2(24, 18)
	command_grid.size = Vector2(392, 214)
	command_grid.add_theme_constant_override("h_separation", 24)
	command_grid.add_theme_constant_override("v_separation", 14)
	command_panel.add_child(command_grid)
	_rebuild_command_labels(FALLBACK_COMMANDS)

	# Ceremony text (center, large, fades in/out)
	# Ceremony text uses the TypedText component (ported from godot-essentials,
	# see project_plugin_pile memory). BBCode-aware typewriter with per-
	# punctuation pacing — ceremony lines get DQ-style dramatic beats on
	# periods/commas automatically.
	ceremony_label = TypedText.new()
	ceremony_label.manual_start = true   # we drive reset_with() from _show_ceremony
	ceremony_label.content = ""
	ceremony_label.bbcode_enabled = true
	ceremony_label.fit_content = true
	ceremony_label.scroll_active = false
	ceremony_label.add_theme_font_size_override("normal_font_size", 60)
	ceremony_label.add_theme_color_override("default_color", PAL_ACCENT)
	ceremony_label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.9))
	ceremony_label.add_theme_constant_override("outline_size", 12)
	ceremony_label.anchor_left = 0.1
	ceremony_label.anchor_right = 0.9
	ceremony_label.anchor_top = 0.35
	ceremony_label.anchor_bottom = 0.55
	ceremony_label.visible = false
	canvas.add_child(ceremony_label)

	# Vignette — red full-screen tint for HP loss
	vignette_rect = ColorRect.new()
	vignette_rect.color = Color(0.8, 0.0, 0.0, 0.0)
	vignette_rect.anchor_right = 1.0
	vignette_rect.anchor_bottom = 1.0
	vignette_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	canvas.add_child(vignette_rect)

	# Crosshair — always visible, both FP and iso
	crosshair_label = Label.new()
	crosshair_label.text = "◆"
	crosshair_label.anchor_left = 0.5
	crosshair_label.anchor_right = 0.5
	crosshair_label.anchor_top = 0.5
	crosshair_label.anchor_bottom = 0.5
	crosshair_label.offset_left = -10
	crosshair_label.offset_right = 10
	crosshair_label.offset_top = -14
	crosshair_label.offset_bottom = 14
	crosshair_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	crosshair_label.add_theme_font_size_override("font_size", 18)
	crosshair_label.add_theme_color_override("font_color", Color(0.95, 0.9, 0.7, 0.6))
	crosshair_label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	crosshair_label.add_theme_constant_override("outline_size", 3)
	canvas.add_child(crosshair_label)


func _make_window(pos: Vector2, size: Vector2) -> Panel:
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
	var corners := [
		Vector2(4, -2),
		Vector2(size.x - 18, -2),
		Vector2(4, size.y - 20),
		Vector2(size.x - 18, size.y - 20),
	]
	for p in corners:
		var g := Label.new()
		g.text = CORNER_GLYPH
		g.position = p
		g.add_theme_font_size_override("font_size", 16)
		g.add_theme_color_override("font_color", PAL_BORDER)
		panel.add_child(g)
	return panel


func _make_label(pos: Vector2, size: int, color: Color) -> Label:
	var l := Label.new()
	l.position = pos
	l.add_theme_font_size_override("font_size", size)
	l.add_theme_color_override("font_color", color)
	return l


# -- Public API --------------------------------------------------------------

func update_snapshot(enc_raw) -> void:
	var enc: Dictionary = enc_raw if enc_raw is Dictionary else {}
	encounter_snap = enc
	var active_raw = enc.get("active", null)
	var active: Dictionary = active_raw if active_raw is Dictionary else {}
	var is_active: bool = not active.is_empty()
	encounter_active = is_active
	if encounter_hud_root:
		encounter_hud_root.visible = is_active

	if is_active:
		_update_hud(enc)
	else:
		# Encounter ended — check for a last_outcome ceremony to display.
		var lo_raw = enc.get("last_outcome", null)
		if lo_raw is Dictionary and lo_raw.has("ceremony"):
			var key: String = str(lo_raw["ceremony"])
			if key != prev_ceremony_key:
				_show_ceremony(str(lo_raw.get("ceremony_text", key.to_upper())))
				prev_ceremony_key = key
		else:
			prev_ceremony_key = ""


func _update_hud(enc: Dictionary) -> void:
	var a_raw = enc.get("active", null)
	var active: Dictionary = a_raw if a_raw is Dictionary else {}
	var p_raw = enc.get("player", null)
	var p: Dictionary = p_raw if p_raw is Dictionary else {}
	var pr_raw = enc.get("progression", null)
	var prog: Dictionary = pr_raw if pr_raw is Dictionary else {}

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
		orb_hp_bar_fg.size.x = 384.0 * (float(o_hp) / float(o_max))

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

	# Intent telegraph
	var telegraph: String = str(active.get("intent_telegraph", ""))
	if intent_lbl:
		intent_lbl.text = telegraph if telegraph != "" else ""

	# Verb list — dialog vs action scouts ship different sets; rebuild if changed.
	var verbs_raw = active.get("verbs", null)
	var verbs: Array = verbs_raw if verbs_raw is Array else []
	if not verbs.is_empty():
		var expected: Array = []
		for v in verbs:
			expected.append(str(v))
		expected.append("PORTAL")   # host-side command, always last
		if expected != current_commands:
			_rebuild_command_labels(expected)

	# Opening ceremony on new encounter
	var cer_raw = active.get("ceremony", null)
	var cer: Dictionary = cer_raw if cer_raw is Dictionary else {}
	if prev_ceremony_key == "" and cer.has("opening"):
		_show_ceremony(str(cer["opening"]))
		prev_ceremony_key = "opening"
		selected_cmd_index = 0
		_refresh_command_cursor()

	# Log
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
			var old_len := log_text_lbl.visible_characters if log_text_lbl.visible_characters > 0 else 0
			log_text_lbl.text = log_txt
			if log_txt.length() < log_last_length:
				log_text_lbl.visible_characters = log_txt.length()
			else:
				log_text_lbl.visible_characters = min(old_len, log_txt.length())
			log_last_length = log_txt.length()

	_refresh_command_cursor()


func on_action_ack(result_raw) -> void:
	# Host calls this when brain returns an encounter_action result.
	var result: Dictionary = result_raw if result_raw is Dictionary else {}
	# Damage feedback is already triggered in _update_hud when HP drops,
	# so we don't need anything here for now. Reserved for future: orb
	# reaction animation, outcome toasts, etc.
	pass


func handle_input(event: InputEvent) -> bool:
	# Action-based routing so keyboard + gamepad drive the HUD uniformly.
	# Returns true if the event was consumed (host should not process further).
	if not encounter_active:
		return false
	if event.is_action_pressed("menu_nav_up"):
		_move_cursor(-COMMAND_COLS); return true
	if event.is_action_pressed("menu_nav_down"):
		_move_cursor(COMMAND_COLS); return true
	if event.is_action_pressed("menu_nav_left"):
		_move_cursor_h(-1); return true
	if event.is_action_pressed("menu_nav_right"):
		_move_cursor_h(1); return true
	if event.is_action_pressed("menu_confirm"):
		_confirm(); return true
	if event.is_action_pressed("portal"):
		portal_requested.emit(); return true
	return false


# Deprecated: kept as a no-op alias for any legacy caller. New hosts should
# call handle_input(event) with the raw InputEvent so action-based detection
# works for both keyboard and gamepad.
func handle_key(_key: int) -> bool:
	return false


func sync_orb_entities(entities: Array) -> void:
	# Spawn/move/free roaming orb nodes from manifest entity list.
	# Each entity carries a hue_shift (0..1) from the brain that procedurally
	# varies its color — one config, many orbs.
	var seen := {}
	for e in entities:
		if not (e is Dictionary) or e.get("kind") != "orb":
			continue
		var id: String = str(e.get("id", ""))
		if id == "":
			continue
		seen[id] = true
		var node: MeshInstance3D
		var is_new: bool = not roaming_orb_nodes.has(id) \
			or not is_instance_valid(roaming_orb_nodes.get(id))
		if is_new:
			node = _spawn_roaming_orb_node()
			roaming_orb_nodes[id] = node
			# Deterministic bob phase from id — no random var to track.
			node.set_meta("bob_phase", float(id.hash() % 1000) / 1000.0 * TAU)
			# Apply hue shift on first spawn (cheap; doesn't change after).
			var hue_shift: float = float(e.get("hue_shift", 0.0))
			_apply_orb_hue(node, hue_shift)
		else:
			node = roaming_orb_nodes[id]
		var base_y: float = float(e.get("z", 0.8))
		var phase: float = node.get_meta("bob_phase", 0.0)
		# Sine bob — 0.15m amplitude, 0.8 Hz, per-orb phase so they drift apart.
		var bob: float = sin(_bob_t * 1.6 + phase) * 0.15
		node.position = Vector3(
			float(e.get("x", 0.0)),
			base_y + bob,
			float(e.get("y", 0.0)))
	for id in roaming_orb_nodes.keys():
		if not seen.has(id):
			if is_instance_valid(roaming_orb_nodes[id]):
				roaming_orb_nodes[id].queue_free()
			roaming_orb_nodes.erase(id)


func _apply_orb_hue(node: MeshInstance3D, hue_shift: float) -> void:
	# hue_shift ∈ [0, 1]. 0 = Watcher red. Shifts the emission toward amber,
	# green, blue, violet, back to red as it climbs. Keeps saturation bright.
	var base := Color(1.0, 0.1, 0.1)
	var hsv := Color.from_hsv(
		fmod(base.h + hue_shift, 1.0),
		0.9,
		1.0)
	var mat: StandardMaterial3D = node.material_override
	if mat:
		mat.albedo_color = hsv
		mat.emission = hsv


func _spawn_roaming_orb_node() -> MeshInstance3D:
	# Billboard quad with a procedural soft-circle alpha. Auto-faces camera,
	# ~1 poly per orb, reads as a glowing sphere without real geometry.
	# Old-dev cheat: one texture, instanced cheaply.
	if _orb_texture == null:
		_orb_texture = _make_orb_texture()

	var node := MeshInstance3D.new()
	var quad := QuadMesh.new()
	quad.size = Vector2(1.4, 1.4)
	node.mesh = quad
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.albedo_color = Color(1.0, 0.1, 0.1)
	mat.albedo_texture = _orb_texture
	mat.emission_enabled = true
	mat.emission = Color(1.0, 0.1, 0.1)
	mat.emission_energy_multiplier = 2.2
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.billboard_mode = BaseMaterial3D.BILLBOARD_ENABLED
	mat.billboard_keep_scale = true
	mat.no_depth_test = false
	node.material_override = mat
	get_parent().add_child(node)
	return node


func _make_orb_texture() -> ImageTexture:
	# 64x64 radial-gradient alpha, soft falloff. One-shot, shared by all orbs.
	var img := Image.create(64, 64, false, Image.FORMAT_RGBA8)
	var center := Vector2(32, 32)
	for y in 64:
		for x in 64:
			var d: float = Vector2(x, y).distance_to(center) / 32.0
			var alpha: float = clampf(1.0 - d, 0.0, 1.0)
			alpha = pow(alpha, 1.5)
			img.set_pixel(x, y, Color(1, 1, 1, alpha))
	return ImageTexture.create_from_image(img)


func tick(delta: float) -> void:
	_bob_t += delta   # orb bob animation clock

	# Ceremony fade-out
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
	# Camera shake
	if camera_shake_t > 0.0 and _camera:
		camera_shake_t -= delta
		var mag: float = max(0.0, camera_shake_t / 0.25) * 0.08
		_camera.position = camera_base_pos + Vector3(
			randf_range(-mag, mag), randf_range(-mag, mag), randf_range(-mag, mag))
		if camera_shake_t <= 0.0:
			_camera.position = camera_base_pos
	# Typewriter tick
	if log_text_lbl:
		var total: int = log_text_lbl.text.length()
		if log_text_lbl.visible_characters < total:
			var step: int = max(1, int(TYPE_SPEED * delta))
			log_text_lbl.visible_characters = min(total,
				log_text_lbl.visible_characters + step)


func set_crosshair_visible(v: bool) -> void:
	# Host calls this on iso/fps toggle. In iso view the screen-center
	# crosshair is misleading (doesn't represent player facing), so hide it;
	# the avatar's forward-arrow carries direction in iso.
	if crosshair_label:
		crosshair_label.visible = v


func check_hub_arrival(cam_x: float, cam_z: float, staged_xp: float) -> void:
	var hub_raw = encounter_snap.get("hub_spawn", null) if encounter_snap else null
	var hub: Array = hub_raw if hub_raw is Array else [0.0, -14.0]
	var dxh: float = cam_x - float(hub[0])
	var dzh: float = cam_z - float(hub[1])
	var in_hub: bool = (dxh * dxh + dzh * dzh) <= (HUB_ARRIVAL_RADIUS * HUB_ARRIVAL_RADIUS)
	if in_hub and not sent_hub_arrival:
		if staged_xp > 0.0:
			hub_arrival_needed.emit()
		sent_hub_arrival = true
	elif not in_hub:
		sent_hub_arrival = false


# -- Internal helpers --------------------------------------------------------

func _rebuild_command_labels(names: Array) -> void:
	# Drop existing labels + rebuild against the new verb list. Called on
	# first build and whenever the brain ships a different set (e.g. the
	# next encounter is action-mode instead of dialog).
	if command_grid == null:
		return
	for child in command_grid.get_children():
		command_grid.remove_child(child)
		child.queue_free()
	command_labels.clear()
	for n in names:
		var l := Label.new()
		l.text = "  " + str(n)
		l.add_theme_font_size_override("font_size", 24)
		l.add_theme_color_override("font_color", PAL_TEXT)
		command_grid.add_child(l)
		command_labels.append(l)
	current_commands = names.duplicate()
	if selected_cmd_index >= current_commands.size():
		selected_cmd_index = 0
	_refresh_command_cursor()


func _refresh_command_cursor() -> void:
	for i in range(command_labels.size()):
		var lbl: Label = command_labels[i]
		var n: String = str(current_commands[i]) if i < current_commands.size() else ""
		if i == selected_cmd_index:
			lbl.text = "◆ " + n
			lbl.add_theme_color_override("font_color", PAL_ACCENT)
		else:
			lbl.text = "  " + n
			lbl.add_theme_color_override("font_color", PAL_TEXT_DIM)


func _move_cursor(delta: int) -> void:
	var next: int = selected_cmd_index + delta
	if next < 0 or next >= current_commands.size():
		return
	selected_cmd_index = next
	_refresh_command_cursor()


func _move_cursor_h(delta: int) -> void:
	var col: int = selected_cmd_index % COMMAND_COLS
	var row: int = selected_cmd_index / COMMAND_COLS
	var next_col: int = col + delta
	if next_col < 0 or next_col >= COMMAND_COLS:
		return
	var new_idx: int = row * COMMAND_COLS + next_col
	if new_idx >= current_commands.size():
		return
	selected_cmd_index = new_idx
	_refresh_command_cursor()


func _confirm() -> void:
	if selected_cmd_index >= current_commands.size():
		return
	var chosen: String = str(current_commands[selected_cmd_index])
	if chosen == "PORTAL":
		portal_requested.emit()
	else:
		action_chosen.emit(chosen)


func _show_ceremony(text: String) -> void:
	if ceremony_label == null:
		return
	# Wrap in BBCode [center] so RichTextLabel centers per-line the way
	# the old Label's horizontal_alignment did. Preserves multi-line breaks.
	ceremony_label.modulate = Color(1, 1, 1, 0)
	ceremony_label.visible = true
	ceremony_label.reset_with("[center]" + text + "[/center]", true)
	ceremony_t_remaining = 3.5
	var tw := create_tween()
	tw.tween_property(ceremony_label, "modulate:a", 1.0, 1.0)


func _trigger_damage_feedback() -> void:
	camera_shake_t = 0.25
	if _camera:
		camera_base_pos = _camera.position
	vignette_t_remaining = 0.4
	if vignette_rect:
		vignette_rect.color = Color(0.8, 0.0, 0.0, 0.5)
