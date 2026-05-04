// haze_primitive.gdshader
//
// P_07 (The Haze) — volumetric box approximation via radial density falloff
// + procedural turbulence + Bayer dither. Cheaper than Godot FogVolume (no
// volumetric fog environment cost) and stays in the MultiMesh pipeline like
// every other primitive.
//
// The "volume" is a unit BoxMesh (vertices in [-0.5, +0.5]); local-space
// distance from center drives density falloff. Turbulence uses TIME + a
// per-instance seed to keep adjacent haze from pulsing in sync.
//
// Applied to a BoxMesh in main.gd's _build_haze_mesh() when a subpart
// references family "haze".

shader_type spatial;
render_mode unshaded, cull_disabled, depth_draw_opaque, blend_mix;

#include "res://bayer_dither.gdshaderinc"

uniform vec3 tint : source_color = vec3(0.5, 0.5, 0.5);
uniform float density = 0.4;
uniform float turbulence_seed = 0.0;
uniform vec3 drift = vec3(0.0, 0.05, 0.0);
uniform float emission_strength = 0.0;

varying vec3 v_local;


void vertex() {
	// VERTEX is in mesh-local space; BoxMesh size 1.0 puts vertices at ±0.5.
	// Scale to ±1.0 for cleaner falloff math in the fragment.
	v_local = VERTEX * 2.0;
}


void fragment() {
	// Radial falloff: full density at center, zero at the unit-sphere edge.
	float d = length(v_local);
	float falloff = 1.0 - smoothstep(0.4, 1.0, d);

	// Cheap procedural turbulence — three sine products with phase drift.
	// Per-instance turbulence_seed offsets the field so adjacent haze
	// volumes don't share the same swirl pattern.
	vec3 p = v_local * 2.5 + drift * TIME + vec3(turbulence_seed);
	float t = sin(p.x) * sin(p.y) * sin(p.z);
	float modulation = 0.7 + 0.3 * t;

	float a = density * falloff * modulation;

	ALBEDO = tint;
	if (emission_strength > 0.0) {
		EMISSION = tint * emission_strength * falloff;
	}
	ALPHA = bayer_dither_alpha(FRAGCOORD.xy, a);
}
