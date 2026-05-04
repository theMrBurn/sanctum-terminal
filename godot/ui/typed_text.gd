class_name TypedText extends RichTextLabel
#
# Typewriter RichTextLabel with BBCode-aware reveal + per-punctuation pacing.
#
# Absorbed from godot-essentials 2026-04-16 — see project_plugin_pile memory.
# Original by Banana Holograma (MIT), GitLab godot-tools/godot-essentials.
# Modifications in this port:
#   - Removed InputWizard dependency (uses native Input directly)
#   - Fixed lookahead bounds bug at end-of-content
#   - Kept API surface identical to original for drop-in compatibility
#
# Usage:
#   var tt := TypedText.new("Hello world.")
#   add_child(tt)            # starts typing on _ready (auto)
#   await tt.finished_display
#
# BBCode tags flow through unchanged — useful for [shake]/[wave]/[rainbow]
# and for color/font overrides. The typewriter preserves the tag as a
# whole unit rather than revealing char-by-char.

signal finished_display

const BBCODE_START_FLAG: StringName = "["
const BBCODE_END_FLAG: StringName = "]"

@export var content: String
@export var manual_start := false
@export var input_action_to_start := "ui_accept"
@export var can_be_skipped := true
@export var input_action_to_skip := "ui_accept"
@export var letter_time := 0.03
@export var space_time := 0.06
@export var punctuation_time := 0.2

var letter_index := 0
var typing_timer: Timer

var current_bbcode := ""
var bbcode_flag := false

var is_typing := false
var typing_finished := false


func _init(content_to_display: String = content):
	content = content_to_display


func _unhandled_input(_event: InputEvent) -> void:
	if typing_finished:
		return
	if not is_typing and manual_start and \
			InputMap.has_action(input_action_to_start) and \
			Input.is_action_just_pressed(input_action_to_start):
		display_letters()
	elif is_typing and can_be_skipped and \
			InputMap.has_action(input_action_to_skip) and \
			Input.is_action_just_pressed(input_action_to_skip):
		skip()


func _ready() -> void:
	if content.is_empty():
		push_warning("TypedText node %s has no content; freeing" % name)
		queue_free()
		return

	bbcode_enabled = true
	fit_content = true

	_create_typing_timer()
	finished_display.connect(on_finished_display)

	if not manual_start:
		display_letters()


func display_letters() -> void:
	if typing_finished:
		return

	if letter_index >= content.length():
		finished_display.emit()
		if is_instance_valid(typing_timer):
			typing_timer.stop()
		return

	is_typing = true

	var next_character: String = content[letter_index]
	letter_index += 1

	if not bbcode_flag and next_character == BBCODE_START_FLAG:
		bbcode_flag = true

	if bbcode_flag:
		current_bbcode += next_character
		bbcode_flag = next_character != BBCODE_END_FLAG
		display_letters()
		return
	else:
		if not current_bbcode.is_empty():
			text += current_bbcode + next_character
			current_bbcode = ""
			display_letters()
			return

	text += next_character

	# Lookahead pacing — bounds-guarded (original crashed on last char).
	if letter_index >= content.length():
		typing_timer.start(letter_time)
		return

	match content[letter_index]:
		".", ",", ":", ";", "!", "¡", "?", "¿":
			typing_timer.start(punctuation_time)
		" ":
			typing_timer.start(space_time)
		_:
			typing_timer.start(letter_time)


func skip() -> void:
	if is_typing:
		text = ""
		append_text(content)
		finished_display.emit()


func _create_typing_timer() -> void:
	if typing_timer:
		return

	typing_timer = Timer.new()
	typing_timer.name = "TypingTimer"
	typing_timer.process_callback = Timer.TIMER_PROCESS_IDLE
	typing_timer.one_shot = true
	typing_timer.autostart = false

	add_child(typing_timer)
	typing_timer.timeout.connect(on_typing_timer_timeout)


func on_typing_timer_timeout() -> void:
	display_letters()


func on_finished_display() -> void:
	letter_index = 0
	content = ""
	is_typing = false
	typing_finished = true
	set_process_unhandled_input(false)

	if is_instance_valid(typing_timer):
		typing_timer.stop()


# Restart the typewriter with new content. Allows a single TypedText node
# to be reused across multiple reveals (e.g. per-encounter ceremony text)
# without re-instancing. Not in the original — added for in-place reuse.
func reset_with(new_content: String, auto_start: bool = true) -> void:
	if is_instance_valid(typing_timer):
		typing_timer.stop()
	text = ""
	content = new_content
	letter_index = 0
	current_bbcode = ""
	bbcode_flag = false
	is_typing = false
	typing_finished = false
	set_process_unhandled_input(true)
	if auto_start:
		display_letters()
