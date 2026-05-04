extends SceneTree

## Phase 4 parity test: kind_config behavior blocks must produce the same
## values that the legacy CREATURE_KINDS literal had. Headless: loads
## kind_config.json directly, asserts every expected creature has a behavior
## block with sane fields.
##
## Run: cd godot && godot --headless --script tests/test_creature_kinds_from_config.gd

var _failures: Array[String] = []


# Expected creature behavior values — mirror of pre-Phase-4 CREATURE_KINDS.
# When the literal is deleted in Phase 5, these become the ONLY source of
# truth for what creatures should look like at runtime; this test then
# becomes the canonical behavior contract.
const EXPECTED := {
	"rat":             {"speed": 4.0, "flee_radius": 8.0, "destructible": false,
						"mote_arrangement": "rat_15", "mote_size": 0.15},
	"rat_ice":         {"speed": 3.0, "flee_radius": 10.0, "destructible": false,
						"mote_arrangement": "rat_15", "mote_size": 0.15},
	"rat_fire":        {"speed": 5.0, "flee_radius": 6.0, "destructible": false,
						"mote_arrangement": "rat_15", "mote_size": 0.15},
	"treasure_chest":  {"speed": 0.0, "flee_radius": 0.0, "destructible": false,
						"mote_arrangement": "chest_8", "mote_size": 0.20},
	"clay_pot":        {"speed": 0.0, "flee_radius": 0.0, "destructible": true,
						"mote_arrangement": "pot_10", "mote_size": 0.15,
						"scatter_speed": 3.0, "scatter_gravity": 6.0},
	"beetle":          {"speed": 2.0, "flee_radius": 5.0, "destructible": false,
						"mote_arrangement": "solo", "mote_size": 0.03},
	"spider":          {"speed": 3.0, "flee_radius": 6.0, "destructible": false,
						"mote_arrangement": "solo", "mote_size": 0.04},
}


func _init() -> void:
	var cfg = _load_config()
	if cfg.is_empty():
		_failures.append("kind_config could not be loaded")
		_finish()
		return
	var kinds: Dictionary = cfg.get("kinds", {})
	for name: String in EXPECTED:
		_check_creature(kinds, name)
	_finish()


func _load_config() -> Dictionary:
	var f := FileAccess.open("res://kind_config.json", FileAccess.READ)
	if not f:
		return {}
	var jp := JSON.new()
	if jp.parse(f.get_as_text()) != OK:
		f.close()
		return {}
	var data = jp.data
	f.close()
	return data


func _check_creature(kinds: Dictionary, name: String) -> void:
	if not kinds.has(name):
		_failures.append("%s missing from kind_config" % name)
		return
	var k: Dictionary = kinds[name]
	if k.get("class", "") != "life":
		_failures.append("%s class is %s, expected 'life'" % [name, k.get("class")])
	var b: Dictionary = k.get("behavior", {})
	if b.is_empty():
		_failures.append("%s missing behavior block" % name)
		return
	var expected: Dictionary = EXPECTED[name]
	for field: String in expected:
		var have = b.get(field)
		var want = expected[field]
		if have != want:
			_failures.append("%s.behavior.%s = %s, expected %s" % [
				name, field, str(have), str(want)])


func _finish() -> void:
	var total: int = EXPECTED.size()
	if _failures.is_empty():
		print("PASS: test_creature_kinds_from_config (%d/%d)" % [total, total])
		quit(0)
	else:
		print("FAIL: test_creature_kinds_from_config — %d failures" % _failures.size())
		for msg in _failures:
			print("  - " + msg)
		quit(1)
