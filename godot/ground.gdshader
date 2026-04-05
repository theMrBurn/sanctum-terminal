shader_type spatial;

// Ground shader — uses the SAME world_grain texture as all objects.
// One visual DNA. Ground is just another surface in the cave.

uniform vec3 color_base : source_color = vec3(0.06, 0.05, 0.04);
uniform vec3 fog_color : source_color = vec3(0.1, 0.1, 0.1);
uniform sampler2D grain_tex;
uniform sampler2D normal_tex : hint_normal;
uniform float grain_scale = 0.35;
uniform float grain_strength : hint_range(0.0, 1.0) = 0.12;
uniform float normal_strength : hint_range(0.0, 2.0) = 0.4;
uniform float roughness_val : hint_range(0.0, 1.0) = 0.95;
uniform float honeycomb_cell_size = 18.0;  // matches world_gen node spacing

varying vec2 world_uv;

// Hash function for per-cell signature
float cell_hash(vec2 cell) {
	return fract(sin(dot(cell, vec2(127.1, 311.7))) * 43758.5453);
}

void vertex() {
	world_uv = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xz;
}

void fragment() {
	// Per-cell offset — each honeycomb cell gets a unique texture phase shift
	// so adjacent cells read as slightly different "zones" of cave floor.
	vec2 cell = floor(world_uv / honeycomb_cell_size);
	float cell_sig = cell_hash(cell);
	vec2 cell_offset = vec2(cell_sig, cell_hash(cell + vec2(1.0, 0.0))) * 2.0;

	// Sample world_grain at cell-offset UV
	vec2 uv = world_uv * grain_scale + cell_offset;
	float grain = texture(grain_tex, uv).r;

	// Distance-based amplitude — closer ground has more grain contrast,
	// far ground fades asymptotically toward fog color. Asymptotic falloff
	// (1/(1+d²)) instead of hard cutoff — distant grain never fully vanishes.
	float cam_dist = length(VERTEX.xz);
	float amplitude = 1.0 / (1.0 + cam_dist * cam_dist * 0.0008);

	// Ground color: dark base, strong grain variation with distance falloff
	float grain_effect = mix(0.9, 1.4, grain);
	vec3 col = color_base * mix(1.0, grain_effect, grain_strength * amplitude);

	// Fade to fog at far edges (still asymptotic, never fully replaces)
	float edge_dist = cam_dist / 800.0;
	float fade = smoothstep(0.4, 0.9, edge_dist);
	col = mix(col, fog_color, fade * 0.85);

	ALBEDO = col;
	ROUGHNESS = roughness_val;

	// Normal map with distance amplitude — relief fades with distance
	if (normal_strength > 0.01) {
		vec3 n = texture(normal_tex, uv).rgb;
		NORMAL_MAP = n;
		NORMAL_MAP_DEPTH = normal_strength * amplitude;
	}
}
