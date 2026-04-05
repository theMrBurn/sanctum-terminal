extends RefCounted

## Mote arrangement library — meta-pixel compositions of the prime-mote.
##
## The heptagonal mote (design_heptagonal_mote.md) is the atom. This library
## is the set of *arrangements* of that atom into larger visible shapes. Each
## arrangement returns an Array[Vector3] of offset positions; each position
## hosts a heptagonal atom, and the cluster reads as a second-order shape.
##
## Light templates are config-as-code: adding a new light-emitting kind picks
## an arrangement name, not a new asset. Design Law #13 (primitive inversion)
## applied recursively at the rendering layer.
##
## Referenced by LIGHT_KINDS in main.gd via the `mote_arrangement` field.
## Covered by tests/test_mote_arrangements.gd.


## Resolve an arrangement name to a list of sub-mote offset positions.
##
## Unknown names fall back to "solo" (single origin point) so the caller
## never crashes on a config typo. Tested.
static func get_offsets(name: String) -> Array:
	match name:
		"solo":
			return _solo()
		"lattice_7":
			return _lattice_7()
		"scatter_7":
			return _scatter_7()
		"chain_5":
			return _chain_5()
		"ground_hug_4":
			return _ground_hug_4()
		"stream_vert_5":
			return _stream_vert_5()
		_:
			return _solo()  # safe fallback


# -- Individual arrangement templates ------------------------------------------

# solo: degenerate single-atom case. Firefly, exit_lure, any kind that wants
# the meta-pixel doctrine turned off for a "pure point of light" reading.
static func _solo() -> Array:
	return [Vector3.ZERO]


# lattice_7: one center atom + six atoms on a heptagonal horizontal rim.
# Crystal cluster's Tron Bit with internal structure. The rosette reads as
# a single glowing form at distance and a mineral lattice up close. Seven
# is the Merkabah count.
static func _lattice_7() -> Array:
	var offsets: Array = [Vector3.ZERO]
	var radius: float = 0.45  # ~45cm rim — tight enough to read as one object
	# Six rim atoms — 60° apart. (We use six not seven because 6+center=7,
	# preserving the Merkabah count without forcing an awkward 7-fold rim.)
	for i in range(6):
		var theta: float = -PI * 0.5 + TAU * float(i) / 6.0
		offsets.append(Vector3(cos(theta) * radius, 0.0, sin(theta) * radius))
	return offsets


# scatter_7: loose organic cloud, seven atoms scattered within a sphere.
# Giant fungus spore cloud. Positions are deterministic (no RNG) so tests
# and visual playback are reproducible.
static func _scatter_7() -> Array:
	# Hand-picked offsets inside a ~1.3m sphere. Irregular but non-colliding.
	return [
		Vector3( 0.00,  0.00,  0.00),
		Vector3( 0.85,  0.30, -0.15),
		Vector3(-0.60,  0.45,  0.55),
		Vector3( 0.25, -0.20,  0.80),
		Vector3(-0.75, -0.10, -0.35),
		Vector3( 0.40,  0.65, -0.70),
		Vector3(-0.10,  0.95,  0.05),
	]


# chain_5: vertical linear sequence along Y axis. Filament "current flowing
# through the structure." Atoms span ~1.2m vertically, zero horizontal drift.
static func _chain_5() -> Array:
	return [
		Vector3(0.0,  0.6, 0.0),
		Vector3(0.0,  0.3, 0.0),
		Vector3(0.0,  0.0, 0.0),
		Vector3(0.0, -0.3, 0.0),
		Vector3(0.0, -0.6, 0.0),
	]


# ground_hug_4: low arc of four atoms near ground. Moss patch spore dust
# skimming the floor. All atoms within 0.4m of Y=0.
static func _ground_hug_4() -> Array:
	return [
		Vector3(-0.35, 0.10,  0.20),
		Vector3( 0.00, 0.15, -0.25),
		Vector3( 0.40, 0.10,  0.15),
		Vector3(-0.10, 0.20,  0.40),
	]


# stream_vert_5: staggered vertical descent for ceiling_moss drip glyph.
# Y values strictly decreasing so the cluster reads as a sequence of drops
# frozen in mid-fall. Player perceives the drip as a glyph, not a point.
static func _stream_vert_5() -> Array:
	return [
		Vector3(0.00,  0.80, 0.00),
		Vector3(0.05,  0.40, 0.02),
		Vector3(-0.03, 0.00, 0.04),
		Vector3(0.02, -0.40, -0.01),
		Vector3(-0.02, -0.80, 0.03),
	]
