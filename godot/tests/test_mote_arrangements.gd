extends SceneTree

const MoteArrangements = preload("res://mote_arrangements.gd")

## Regression test for the meta-pixel mote arrangement library.
##
## Option B of the mote scaling decision (2026-04-05 session close): the
## prime-mote doctrine extends fractally. Each light-emitting kind picks an
## arrangement template from this library; each template is a set of sub-mote
## offsets forming a larger visible shape. The atom is always the seven-sided
## heptagonal mote; only the arrangement varies per kind.
##
## Run: cd godot && godot --headless --script tests/test_mote_arrangements.gd
## Exits 0 on all-pass, 1 on any failure.


var _failures: Array[String] = []


func _init() -> void:
	_test_solo_is_single_origin_point()
	_test_lattice_7_has_seven_points()
	_test_lattice_7_has_center_and_six_rim()
	_test_scatter_7_count_and_bounds()
	_test_chain_5_is_vertical_axis()
	_test_ground_hug_4_stays_low()
	_test_stream_vert_5_is_staggered_descent()
	_test_all_templates_resolvable()
	_test_unknown_template_falls_back_to_solo()

	if _failures.is_empty():
		print("PASS: test_mote_arrangements (9/9)")
		quit(0)
	else:
		print("FAIL: test_mote_arrangements — %d failures" % _failures.size())
		for msg in _failures:
			print("  - " + msg)
		quit(1)


func _assert(cond: bool, label: String) -> void:
	if not cond:
		_failures.append(label)


# -- Individual template shape tests -------------------------------------------

func _test_solo_is_single_origin_point() -> void:
	var pts: Array = MoteArrangements.get_offsets("solo")
	_assert(pts.size() == 1, "solo must have exactly 1 point (got %d)" % pts.size())
	if pts.size() >= 1:
		var p: Vector3 = pts[0]
		_assert(
			p.is_equal_approx(Vector3.ZERO),
			"solo's single point must be at origin (got %s)" % str(p)
		)


func _test_lattice_7_has_seven_points() -> void:
	var pts: Array = MoteArrangements.get_offsets("lattice_7")
	_assert(
		pts.size() == 7,
		"lattice_7 must have exactly 7 points — Merkabah number (got %d)" % pts.size()
	)


func _test_lattice_7_has_center_and_six_rim() -> void:
	# The lattice is one center atom + six atoms on a heptagonal-rim arc.
	# Center at origin, six rim atoms at equal radial distance.
	var pts: Array = MoteArrangements.get_offsets("lattice_7")
	if pts.size() != 7:
		_failures.append("lattice_7 shape test skipped (wrong point count)")
		return

	var center_count: int = 0
	var rim_count: int = 0
	var rim_radius: float = -1.0
	for p in pts:
		var r: float = Vector2(p.x, p.z).length()  # horizontal radial distance
		if r < 0.01:
			center_count += 1
		else:
			rim_count += 1
			if rim_radius < 0.0:
				rim_radius = r
			else:
				_assert(
					abs(r - rim_radius) < 0.01,
					"lattice_7 rim radii must be equal (expected %f, got %f)" % [rim_radius, r]
				)
	_assert(center_count == 1, "lattice_7 must have exactly 1 center point (got %d)" % center_count)
	_assert(rim_count == 6, "lattice_7 must have exactly 6 rim points (got %d)" % rim_count)
	_assert(
		rim_radius > 0.1 and rim_radius < 2.0,
		"lattice_7 rim radius must be in [0.1, 2.0] (got %f)" % rim_radius
	)


func _test_scatter_7_count_and_bounds() -> void:
	var pts: Array = MoteArrangements.get_offsets("scatter_7")
	_assert(
		pts.size() == 7,
		"scatter_7 must have 7 points — prime atom count (got %d)" % pts.size()
	)
	# Every point must fall within a 2m bounding sphere — spore cloud, not galaxy
	for p in pts:
		_assert(
			(p as Vector3).length() < 2.0,
			"scatter_7 point %s exceeds 2m bound" % str(p)
		)


func _test_chain_5_is_vertical_axis() -> void:
	var pts: Array = MoteArrangements.get_offsets("chain_5")
	_assert(pts.size() == 5, "chain_5 must have 5 points (got %d)" % pts.size())
	# All x/z components must be near-zero — chain runs along Y
	for p in pts:
		var pv: Vector3 = p
		_assert(
			abs(pv.x) < 0.15 and abs(pv.z) < 0.15,
			"chain_5 point drifted off vertical axis: %s" % str(pv)
		)
	# Y values must span a reasonable range (at least 0.8m tall)
	if pts.size() >= 2:
		var y_min: float = 9999.0
		var y_max: float = -9999.0
		for p in pts:
			y_min = min(y_min, (p as Vector3).y)
			y_max = max(y_max, (p as Vector3).y)
		_assert(
			y_max - y_min >= 0.8,
			"chain_5 Y span must be ≥ 0.8m (got %f)" % (y_max - y_min)
		)


func _test_ground_hug_4_stays_low() -> void:
	var pts: Array = MoteArrangements.get_offsets("ground_hug_4")
	_assert(pts.size() == 4, "ground_hug_4 must have 4 points (got %d)" % pts.size())
	# All points must be within 0.5m of ground (low arc)
	for p in pts:
		_assert(
			abs((p as Vector3).y) < 0.5,
			"ground_hug_4 point too high: %s" % str(p)
		)


func _test_stream_vert_5_is_staggered_descent() -> void:
	var pts: Array = MoteArrangements.get_offsets("stream_vert_5")
	_assert(pts.size() == 5, "stream_vert_5 must have 5 points (got %d)" % pts.size())
	# Y values should be strictly decreasing (staggered descent)
	for i in range(pts.size() - 1):
		var pa: Vector3 = pts[i]
		var pb: Vector3 = pts[i + 1]
		_assert(
			pa.y > pb.y,
			"stream_vert_5 must descend monotonically (index %d: %f → %f)" % [i, pa.y, pb.y]
		)


# -- Library-level tests -------------------------------------------------------

func _test_all_templates_resolvable() -> void:
	# Every name referenced by LIGHT_KINDS in main.gd should resolve.
	# Single source of truth lives in the library itself.
	var expected: Array[String] = [
		"solo", "lattice_7", "scatter_7", "chain_5", "ground_hug_4", "stream_vert_5"
	]
	for name in expected:
		var pts: Array = MoteArrangements.get_offsets(name)
		_assert(
			pts.size() > 0,
			"template '%s' returned empty array" % name
		)


func _test_unknown_template_falls_back_to_solo() -> void:
	# Unknown template names must not crash — they fall back to "solo".
	var pts: Array = MoteArrangements.get_offsets("definitely_not_a_real_template")
	_assert(pts.size() == 1, "unknown template must fall back to solo (got %d points)" % pts.size())
	if pts.size() >= 1:
		var p: Vector3 = pts[0]
		_assert(
			p.is_equal_approx(Vector3.ZERO),
			"unknown template fallback must be origin solo"
		)
