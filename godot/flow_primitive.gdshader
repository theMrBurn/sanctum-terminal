// flow_primitive.gdshader
//
// P_06 (The Flow) — planar fluid via UV-scrolled greyscale noise.
// Same shader serves puddles, slime trails, lava trickles, oil slicks. The
// primitive is colorless capability; tint, velocity, and opacity arrive from
// kind_config per design_kind_config_single_source.
//
// Applied to a PlaneMesh in main.gd's _build_flow_mesh() when a subpart
// references family "flow".

shader_type spatial;
render_mode unshaded, cull_disabled, depth_draw_opaque, blend_mix;

#include "res://bayer_dither.gdshaderinc"

uniform sampler2D noise_tex : source_color, filter_linear, repeat_enable;
uniform vec2 flow_velocity = vec2(0.05, 0.0);
uniform float noise_scale = 1.0;
uniform vec3 tint : source_color = vec3(0.5, 0.5, 0.5);
uniform float opacity = 0.7;
uniform float emission_strength = 0.0;


void fragment() {
	// Two-octave UV scroll. Second octave moves at a different rate so
	// patterns don't tile obviously. Same noise texture, two reads.
	vec2 uv_a = UV * noise_scale + flow_velocity * TIME;
	vec2 uv_b = UV * noise_scale * 1.7 - flow_velocity * TIME * 0.6;
	float n = (texture(noise_tex, uv_a).r + texture(noise_tex, uv_b).r) * 0.5;

	// Soft contrast so flow has bands rather than uniform fog.
	float v = smoothstep(0.25, 0.85, n);

	ALBEDO = tint * (0.6 + 0.4 * v);
	if (emission_strength > 0.0) {
		EMISSION = tint * v * emission_strength;
	}

	float a = opacity * v;
	ALPHA = bayer_dither_alpha(FRAGCOORD.xy, a);
}
