extends RefCounted

## MoteMaterials factory. Reference via preload rather than class_name so
## headless test runners pick it up without the editor's class indexer.

## Factory for mote particle materials.
##
## Extracted from main.gd so the material construction is independently
## testable. See design_heptagonal_mote.md for the prime-mote doctrine.
##
## Critical invariant: particle draw-pass materials MUST use
## BILLBOARD_PARTICLES, not BILLBOARD_ENABLED. The latter collapses all
## particles to the emitter origin. See test_mote_materials.gd for the
## regression guard.


## Build a StandardMaterial3D for a mote particle draw pass.
##
## color: base emission + albedo tint for this mote kind.
## Returns a fully configured material ready for ArrayMesh.surface_set_material.
static func make_particle_mote_material(color: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = Color(color.r, color.g, color.b, 0.5)
	m.emission_enabled = true
	m.emission = color
	m.emission_energy_multiplier = 8.0
	# BILLBOARD_PARTICLES respects per-particle transforms. BILLBOARD_ENABLED
	# would collapse every particle to the emitter origin — see commit 38c4657
	# and test_mote_materials.gd for the regression guard.
	m.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	m.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	return m
