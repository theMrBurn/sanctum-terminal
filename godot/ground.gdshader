shader_type spatial;

// Ground shader — uses the SAME world_grain texture as all objects.
// One visual DNA. Ground is just another surface in the cave.

uniform vec3 color_base : source_color = vec3(0.06, 0.05, 0.04);
uniform vec3 fog_color : source_color = vec3(0.1, 0.1, 0.1);
uniform sampler2D grain_tex;
uniform sampler2D normal_tex : hint_normal;
uniform float grain_scale = 0.35;  // SAME as kind_shader
uniform float grain_strength : hint_range(0.0, 1.0) = 0.12;
uniform float normal_strength : hint_range(0.0, 2.0) = 0.4;
uniform float roughness_val : hint_range(0.0, 1.0) = 0.95;

varying vec2 world_uv;

void vertex() {
	world_uv = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xz;
}

void fragment() {
	// Sample world_grain at the same scale as everything else
	vec2 uv = world_uv * grain_scale;
	float grain = texture(grain_tex, uv).r;

	// Ground color: dark base, subtle grain variation
	vec3 col = color_base * mix(0.9, 1.1, grain * grain_strength + (1.0 - grain_strength));

	// Fade to fog at edges
	float edge_dist = length(VERTEX.xz) / 800.0;
	float fade = smoothstep(0.5, 0.95, edge_dist);
	col = mix(col, fog_color, fade);

	ALBEDO = col;
	ROUGHNESS = roughness_val;

	// Normal from same grain texture
	if (normal_strength > 0.01) {
		vec3 n = texture(normal_tex, uv).rgb;
		NORMAL_MAP = n;
		NORMAL_MAP_DEPTH = normal_strength;
	}
}
