shader_type spatial;
render_mode cull_disabled;

// Simplified kind shader — palette first, one grain, clean.
// Get cohesion before adding effects.

uniform vec3 palette_base : source_color = vec3(0.12, 0.11, 0.10);
uniform vec3 kind_tint : source_color = vec3(1.0, 1.0, 1.0);
uniform float vertex_color_blend : hint_range(0.0, 1.0) = 0.15;
uniform float roughness_base : hint_range(0.0, 1.0) = 0.85;
uniform float light_response : hint_range(0.0, 1.0) = 0.35;

// World grain — one texture, all surfaces
uniform sampler2D grain_tex;
uniform sampler2D normal_tex : hint_normal;
uniform float grain_scale = 0.08;
uniform float grain_strength : hint_range(0.0, 1.0) = 0.15;
uniform float normal_strength : hint_range(0.0, 2.0) = 0.5;

// Emissive
uniform float inner_glow : hint_range(0.0, 1.0) = 0.0;
uniform float pulse_rate : hint_range(0.0, 0.2) = 0.0;

// Triplanar sampling
vec4 triplanar(sampler2D tex, vec3 pos, vec3 norm, float scale) {
	vec3 blend = pow(abs(norm), vec3(1.5));
	blend /= (blend.x + blend.y + blend.z);
	return texture(tex, pos.yz * scale) * blend.x
	     + texture(tex, pos.xz * scale) * blend.y
	     + texture(tex, pos.xy * scale) * blend.z;
}

varying vec3 world_pos;
varying vec3 world_norm;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	world_norm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

void fragment() {
	// 1. Start from palette base
	vec3 col = palette_base;

	// 2. Blend in vertex color (subtle — just for per-instance variation)
	col = mix(col, COLOR.rgb * palette_base * 2.0, vertex_color_blend);

	// 3. Apply kind tint
	col *= kind_tint;

	// 4. World grain — subtle multiply for surface texture
	float grain = triplanar(grain_tex, world_pos, world_norm, grain_scale).r;
	col *= mix(1.0, grain * 1.5 + 0.25, grain_strength);

	// 5. Normal map — subtle surface detail
	if (normal_strength > 0.01) {
		vec3 n = triplanar(normal_tex, world_pos, world_norm, grain_scale).rgb;
		NORMAL_MAP = n;
		NORMAL_MAP_DEPTH = normal_strength;
	}

	ALBEDO = col;
	ROUGHNESS = roughness_base;
	METALLIC = light_response * 0.05;

	// Emissive glow (crystals, moss, fungus)
	if (inner_glow > 0.01) {
		float pulse = 1.0 + sin(TIME * pulse_rate * 6.28) * 0.15;
		EMISSION = col * inner_glow * pulse * 2.0;
	}
}
