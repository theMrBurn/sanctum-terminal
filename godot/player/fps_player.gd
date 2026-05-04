class_name FPSPlayer extends CharacterBody3D
#
# FarCry/Skyrim-style first-person player controller.
# Adapted from LuisOtv/ImmersiveSimGodotController (MIT, Godot 4.1) — see
# godot/studies/immersive_sim/ and project_plugin_pile memory for origin.
# Simplified for our prototype: no PlayerStats singleton, no ladder state,
# minimum-viable scene requirements (Neck + Camera3D + CollisionShape3D).
#
# Controls (see project.godot InputMap for full gamepad + keyboard bindings):
#   Move     — left stick / WASD
#   Look     — right stick / mouse
#   Jump     — A / Space
#   Crouch   — B / C (hold)
#   Sprint   — L3 / Shift (hold)
#   Lean     — Q / E (keyboard only for now)
#   Interact — X / E
#
# Expected scene structure (see fps_player.tscn):
#   FPSPlayer (CharacterBody3D)
#     Neck (Node3D)
#       Camera3D
#     CollisionShape3D (capsule)

# -- Tuning knobs ------------------------------------------------------------

@export var walking_speed: float       = 4.0
@export var running_speed: float       = 6.5
@export var crouching_speed: float     = 2.2
@export var jump_velocity: float       = 5.0
@export var mouse_sensitivity: float   = 0.002
@export var gamepad_look_sensitivity: float = 2.5   # radians/sec at full stick
@export var crouch_height_offset: float = 0.55
@export var lean_distance: float       = 0.35
@export var lean_tilt_deg: float       = 8.0
@export var lerp_smoothness: float     = 10.0

# Pitch clamp — can't look further than ±80° vertical.
const PITCH_MIN := -80.0 * PI / 180.0
const PITCH_MAX :=  80.0 * PI / 180.0

# -- Scene refs --------------------------------------------------------------

@onready var neck: Node3D       = $Neck
@onready var camera: Camera3D   = $Neck/Camera3D
@onready var standing_y: float  = neck.position.y

# -- State -------------------------------------------------------------------

var current_speed: float = 0.0
var look_input: Vector2  = Vector2.ZERO   # accumulated per frame


func _ready() -> void:
	Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.get_mouse_mode() == Input.MOUSE_MODE_CAPTURED:
		# Yaw on body, pitch on neck.
		rotate_y(-event.relative.x * mouse_sensitivity)
		neck.rotate_x(-event.relative.y * mouse_sensitivity)
		neck.rotation.x = clamp(neck.rotation.x, PITCH_MIN, PITCH_MAX)

	if event.is_action_pressed("ui_cancel"):
		# Esc releases mouse (keep existing main.gd behavior consistent).
		if Input.get_mouse_mode() == Input.MOUSE_MODE_CAPTURED:
			Input.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)
		else:
			Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)


func _process(delta: float) -> void:
	_apply_gamepad_look(delta)
	_apply_stance(delta)
	_apply_lean(delta)


func _physics_process(delta: float) -> void:
	# Gravity.
	if not is_on_floor():
		velocity += get_gravity() * delta

	# Jump.
	if Input.is_action_just_pressed("jump") and is_on_floor():
		velocity.y = jump_velocity

	# Horizontal movement — get_vector handles analog stick + digital keys.
	var input_dir := Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var movement := (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()

	if movement.length_squared() > 0.0:
		velocity.x = movement.x * current_speed
		velocity.z = movement.z * current_speed
	else:
		velocity.x = move_toward(velocity.x, 0, current_speed * 2.0 * delta)
		velocity.z = move_toward(velocity.z, 0, current_speed * 2.0 * delta)

	move_and_slide()


# -- Helpers -----------------------------------------------------------------

func _apply_gamepad_look(delta: float) -> void:
	# Right-stick as a yaw/pitch axis. Analog, deadzone already applied by InputMap.
	var look := Input.get_vector("look_left", "look_right", "look_up", "look_down")
	if look.length_squared() < 0.0001:
		return
	rotate_y(-look.x * gamepad_look_sensitivity * delta)
	neck.rotate_x(-look.y * gamepad_look_sensitivity * delta)
	neck.rotation.x = clamp(neck.rotation.x, PITCH_MIN, PITCH_MAX)


func _apply_stance(delta: float) -> void:
	# Crouch lerp — no collision swap yet (kept minimal). Full immersive-sim
	# has separate standing/crouching CollisionShape3D; add when prototype
	# proves the feel.
	var crouching := Input.is_action_pressed("crouch")
	var target_y := standing_y - crouch_height_offset if crouching else standing_y
	neck.position.y = lerp(neck.position.y, target_y, lerp_smoothness * delta)

	# Sprint (only meaningful when not crouching).
	if crouching:
		current_speed = crouching_speed
	elif Input.is_action_pressed("sprint"):
		current_speed = running_speed
	else:
		current_speed = walking_speed


func _apply_lean(delta: float) -> void:
	# Lean left/right — body doesn't move, camera tilts + offsets.
	var target_x := 0.0
	var target_roll := 0.0
	if Input.is_action_pressed("lean_left"):
		target_x = -lean_distance
		target_roll = deg_to_rad(lean_tilt_deg)
	elif Input.is_action_pressed("lean_right"):
		target_x = lean_distance
		target_roll = -deg_to_rad(lean_tilt_deg)
	camera.position.x = lerp(camera.position.x, target_x, lerp_smoothness * delta)
	camera.rotation.z = lerp(camera.rotation.z, target_roll, lerp_smoothness * delta)
