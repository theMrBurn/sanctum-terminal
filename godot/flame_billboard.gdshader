// flame_billboard.gdshader
//
// Procedural fire primitive — camera-facing billboard, additive blend, no
// texture. Parameterized by inner/outer color, intensity (emission energy),
// and flicker speed. Per-instance time offset (INSTANCE_ID) decorrelates
// flicker between adjacent flames so a row of torches doesn't pulse in sync.
//
// Designed for MultiMesh batching: same QuadMesh + ShaderMaterial drawn N
// times, each instance billboards to camera independently and reads its own
// flicker phase.
//
// Usage: applied to a QuadMesh in main.gd's _build_flame_mesh() when a
// subpart references family "flame". See design_render_reuse_mandate for
// the registry promotion rationale.

shader_type spatial;
render_mode unshaded, blend_add, cull_disabled;

uniform vec3 inner_color : source_color = vec3(1.0, 1.0, 0.85);
uniform vec3 outer_color : source_color = vec3(1.0, 0.4, 0.1);
uniform float intensity = 2.0;
uniform float flicker_speed = 1.5;

varying flat float v_instance_offset;


void vertex() {
	// Per-instance flicker phase — INSTANCE_ID is the MultiMesh slot index.
	// Multiplier picked to be irrationally-spaced so neighboring flames
	// don't fall into rhythm.
	v_instance_offset = float(INSTANCE_ID) * 0.73;

	// Camera-facing billboard. Strip the model rotation by reconstructing
	// MODELVIEW from VIEW + INV_VIEW, then re-apply only the world-space
	// scale (extracted via length of each model basis vector). This is the
	// standard Godot 4 spatial-billboard formulation.
	MODELVIEW_MATRIX = VIEW_MATRIX * mat4(
		INV_VIEW_MATRIX[0],
		INV_VIEW_MATRIX[1],
		INV_VIEW_MATRIX[2],
		MODEL_MATRIX[3]
	);
	MODELVIEW_MATRIX = MODELVIEW_MATRIX * mat4(
		vec4(length(MODEL_MATRIX[0].xyz), 0.0, 0.0, 0.0),
		vec4(0.0, length(MODEL_MATRIX[1].xyz), 0.0, 0.0),
		vec4(0.0, 0.0, length(MODEL_MATRIX[2].xyz), 0.0),
		vec4(0.0, 0.0, 0.0, 1.0)
	);
}


// Computes the flame mask: 1.0 inside the flame teardrop, 0.0 outside,
// soft falloff at edges. Animated wobble adds flicker. UV is (0,0) bottom-
// left to (1,1) top-right (Godot QuadMesh default).
float flame_shape(vec2 uv, float t) {
	// Recenter to (-1, +1) and flip y so y=+1 is the tip (top of flame).
	vec2 c = uv * 2.0 - 1.0;
	c.y = -c.y;

	// Two-octave sine wobble, dampened at base + tip so they stay steady.
	float wobble = sin(c.y * 6.0 + t * 4.0) * 0.12;
	wobble += sin(c.y * 3.5 + t * 2.7) * 0.08;
	wobble *= (1.0 - abs(c.y));
	c.x += wobble;

	// Width tapers from base (full) to tip (zero). t_along is 0 at base, 1 at tip.
	float t_along = (c.y + 1.0) * 0.5;
	float width = 1.0 - smoothstep(0.0, 1.0, t_along);
	width = max(width, 0.05);

	// Inside the teardrop: distance from centerline normalized by local width.
	float r = abs(c.x) / width;
	float inside = 1.0 - r;

	// Soft falloff at base + sharp falloff at tip. Tip cutoff at +0.6 to +1.0
	// keeps the visible flame within the quad while leaving headroom for
	// wobble to push the edge upward without clipping.
	float base_falloff = smoothstep(-1.0, -0.85, c.y);
	float tip_falloff = 1.0 - smoothstep(0.6, 1.0, c.y);

	return clamp(inside * base_falloff * tip_falloff, 0.0, 1.0);
}


void fragment() {
	float t = TIME * flicker_speed + v_instance_offset;
	float shape = flame_shape(UV, t);

	// Hot-core to cool-edge gradient. pow() steepens the falloff so the
	// brightest core is small and concentrated, with the orange ring
	// dominating most of the flame.
	float core = pow(shape, 2.0);
	vec3 col = mix(outer_color, inner_color, core);

	ALBEDO = col;
	EMISSION = col * intensity;
	// blend_add uses ALPHA as additive contribution. Soft edges = soft glow.
	ALPHA = shape;
}
