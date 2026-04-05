extends SceneTree

const MoteMaterials = preload("res://mote_materials.gd")

## Regression test for MoteMaterials.make_particle_mote_material.
##
## Run headless:
##   cd godot && godot --headless --script tests/test_mote_materials.gd
##
## Exits 0 on all-pass, 1 on any failure. Designed to be runnable from CI
## alongside the Python pytest suite.
##
## The critical assertion is billboard_mode == BILLBOARD_PARTICLES. If that
## reverts to BILLBOARD_ENABLED (the static-mesh billboard mode), all
## particles collapse to the emitter origin and motes disappear from the
## scene. See commit 38c4657 for the bug this test prevents.


var _failures: Array[String] = []


func _init() -> void:
	_test_particle_billboard_mode()
	_test_emission_enabled_and_energy()
	_test_unshaded_and_transparent()
	_test_albedo_carries_color_with_half_alpha()
	_test_emission_matches_input_color()

	if _failures.is_empty():
		print("PASS: test_mote_materials (5/5)")
		quit(0)
	else:
		print("FAIL: test_mote_materials — %d failures" % _failures.size())
		for msg in _failures:
			print("  - " + msg)
		quit(1)


func _assert(cond: bool, label: String) -> void:
	if not cond:
		_failures.append(label)


func _test_particle_billboard_mode() -> void:
	var mat: StandardMaterial3D = MoteMaterials.make_particle_mote_material(Color(0.3, 0.4, 0.7))
	_assert(
		mat.billboard_mode == BaseMaterial3D.BILLBOARD_PARTICLES,
		"billboard_mode must be BILLBOARD_PARTICLES (got %d)" % int(mat.billboard_mode)
	)


func _test_emission_enabled_and_energy() -> void:
	var mat: StandardMaterial3D = MoteMaterials.make_particle_mote_material(Color(1, 1, 1))
	_assert(mat.emission_enabled, "emission_enabled must be true")
	_assert(
		mat.emission_energy_multiplier > 1.0,
		"emission_energy_multiplier must be > 1.0 for bloom contribution (got %f)" % mat.emission_energy_multiplier
	)


func _test_unshaded_and_transparent() -> void:
	var mat: StandardMaterial3D = MoteMaterials.make_particle_mote_material(Color(1, 1, 1))
	_assert(
		mat.shading_mode == BaseMaterial3D.SHADING_MODE_UNSHADED,
		"shading_mode must be UNSHADED (got %d)" % int(mat.shading_mode)
	)
	_assert(
		mat.transparency == BaseMaterial3D.TRANSPARENCY_ALPHA,
		"transparency must be TRANSPARENCY_ALPHA (got %d)" % int(mat.transparency)
	)


func _test_albedo_carries_color_with_half_alpha() -> void:
	var c := Color(0.25, 0.08, 0.35)
	var mat: StandardMaterial3D = MoteMaterials.make_particle_mote_material(c)
	_assert(is_equal_approx(mat.albedo_color.r, c.r), "albedo.r should match input")
	_assert(is_equal_approx(mat.albedo_color.g, c.g), "albedo.g should match input")
	_assert(is_equal_approx(mat.albedo_color.b, c.b), "albedo.b should match input")
	_assert(is_equal_approx(mat.albedo_color.a, 0.5), "albedo.a should be 0.5 (half-transparent dust)")


func _test_emission_matches_input_color() -> void:
	var c := Color(0.95, 0.80, 0.30)
	var mat: StandardMaterial3D = MoteMaterials.make_particle_mote_material(c)
	_assert(is_equal_approx(mat.emission.r, c.r), "emission.r should match input")
	_assert(is_equal_approx(mat.emission.g, c.g), "emission.g should match input")
	_assert(is_equal_approx(mat.emission.b, c.b), "emission.b should match input")
