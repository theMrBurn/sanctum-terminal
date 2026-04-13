extends SceneTree

const MoteArrangements = preload("res://mote_arrangements.gd")

## Regression test for the creature visibility baseline.
##
## Magic-show trick: when CREATURE_BASELINE_DEBUG is on (main.gd), every
## creature renders as ONE fat heptagonal mote at a known size. This
## guarantees a visible reference point regardless of per-kind config —
## so we can tune sizes/distances against a single number instead of
## fighting cascading multipliers.
##
## This test asserts the baseline contract:
##   - "solo" arrangement resolves to exactly one atom at origin
##     (the fallback shape the override uses).
##   - The baseline mote_size is a sane game-world size — large enough
##     to read at game distance, small enough to not clip the camera.
##
## When CREATURE_BASELINE_DEBUG flips off, this test stays valid because
## "solo" remains a real arrangement; the baseline constants only describe
## what the override will use.
##
## Run: cd godot && godot --headless --script tests/test_creature_baseline.gd
## Exits 0 on all-pass, 1 on any failure.

# Mirror constants from main.gd. Keeping them duplicated here keeps the test
# headless (no scene instantiation needed) and forces a deliberate update
# in two places if the baseline shifts — which is the point: baseline
# changes are load-bearing for visual scope.
const BASELINE_ARRANGEMENT: String = "solo"
const BASELINE_MOTE_SIZE: float = 0.5
const BASELINE_HOVER_M: float = 1.2

# Soft bounds — a baseline atom should be at least chest-readable from
# 3-5m and small enough to not eclipse player FOV at 1m. Keeps the
# magic-show trick honest: visible, not overwhelming.
const MIN_BASELINE_MOTE_SIZE: float = 0.20
const MAX_BASELINE_MOTE_SIZE: float = 1.50

# Hover bounds — clear typical floor variance (>= 0.5m), stay below cavern
# ceiling rooflines we've measured at remote tiles (<= 6m).
const MIN_BASELINE_HOVER_M: float = 0.5
const MAX_BASELINE_HOVER_M: float = 6.0


var _failures: Array[String] = []


func _init() -> void:
	_test_baseline_arrangement_resolves_to_single_atom()
	_test_baseline_mote_size_within_visible_range()
	_test_baseline_atom_at_origin()
	_test_baseline_hover_within_clearance_range()

	if _failures.is_empty():
		print("PASS: test_creature_baseline (4/4)")
		quit(0)
	else:
		print("FAIL: test_creature_baseline — %d failures" % _failures.size())
		for msg in _failures:
			print("  - " + msg)
		quit(1)


func _assert(cond: bool, label: String) -> void:
	if not cond:
		_failures.append(label)


func _test_baseline_arrangement_resolves_to_single_atom() -> void:
	var pts: Array = MoteArrangements.get_offsets(BASELINE_ARRANGEMENT)
	_assert(
		pts.size() == 1,
		"baseline arrangement '%s' must yield exactly 1 atom (got %d)" % [
			BASELINE_ARRANGEMENT, pts.size()]
	)


func _test_baseline_atom_at_origin() -> void:
	var pts: Array = MoteArrangements.get_offsets(BASELINE_ARRANGEMENT)
	if pts.is_empty():
		_failures.append("baseline atom-at-origin test skipped (no points)")
		return
	var p: Vector3 = pts[0]
	_assert(
		p.is_equal_approx(Vector3.ZERO),
		"baseline atom must be at world origin (got %s)" % str(p)
	)


func _test_baseline_hover_within_clearance_range() -> void:
	_assert(
		BASELINE_HOVER_M >= MIN_BASELINE_HOVER_M,
		"baseline hover %f below min %f (atoms would embed in elevated floors)" % [
			BASELINE_HOVER_M, MIN_BASELINE_HOVER_M]
	)
	_assert(
		BASELINE_HOVER_M <= MAX_BASELINE_HOVER_M,
		"baseline hover %f above max %f (atoms would clip cavern ceiling)" % [
			BASELINE_HOVER_M, MAX_BASELINE_HOVER_M]
	)


func _test_baseline_mote_size_within_visible_range() -> void:
	_assert(
		BASELINE_MOTE_SIZE >= MIN_BASELINE_MOTE_SIZE,
		"baseline mote_size %f below min %f (would be invisible at game distance)" % [
			BASELINE_MOTE_SIZE, MIN_BASELINE_MOTE_SIZE]
	)
	_assert(
		BASELINE_MOTE_SIZE <= MAX_BASELINE_MOTE_SIZE,
		"baseline mote_size %f above max %f (would eclipse player FOV)" % [
			BASELINE_MOTE_SIZE, MAX_BASELINE_MOTE_SIZE]
	)
