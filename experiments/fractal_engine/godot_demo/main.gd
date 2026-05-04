# Fractal Engine demo consumer.
#
# Reads frame.jsonl (produced by ../runner.py) and draws each line
# segment with draw_line(). Maps NDC [-1, 1] x [-1, 1] to the
# viewport.
#
# Generate a frame from the project root:
#   python3 experiments/fractal_engine/runner.py --depth 2 --seed 1337 \
#       > experiments/fractal_engine/godot_demo/frame.jsonl
#
# Then run this scene in Godot 4.

extends Node2D

const FRAME_PATH := "res://frame.jsonl"

var _lines: Array = []  # each entry: {a: Vector2, b: Vector2, color: Color}


func _ready() -> void:
	_load_frame()
	queue_redraw()


func _load_frame() -> void:
	_lines.clear()
	var f := FileAccess.open(FRAME_PATH, FileAccess.READ)
	if f == null:
		push_warning("frame.jsonl missing — run ../runner.py to generate it")
		return
	while not f.eof_reached():
		var raw := f.get_line()
		if raw.is_empty():
			continue
		var data: Variant = JSON.parse_string(raw)
		if typeof(data) != TYPE_DICTIONARY:
			continue
		var a: Array = data.get("a", [0, 0])
		var b: Array = data.get("b", [0, 0])
		var c: Array = data.get("color", [1, 1, 1, 1])
		_lines.append({
			"a": Vector2(a[0], a[1]),
			"b": Vector2(b[0], b[1]),
			"color": Color(c[0], c[1], c[2], c[3]),
		})


func _draw() -> void:
	var size := get_viewport_rect().size
	var cx := size.x * 0.5
	var cy := size.y * 0.5
	var sx := size.x * 0.5
	var sy := size.y * 0.5
	for line in _lines:
		# NDC y is up, screen y is down — flip.
		var a := Vector2(cx + line.a.x * sx, cy - line.a.y * sy)
		var b := Vector2(cx + line.b.x * sx, cy - line.b.y * sy)
		draw_line(a, b, line.color, 1.5, true)


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and event.keycode == KEY_R:
		_load_frame()
		queue_redraw()
