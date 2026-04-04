shader_type spatial;

// Procedural forest floor — noise-based soil with color variation.
// Matches the Panda3D Voronoi sediment texture feel.

uniform vec3 color_dark : source_color = vec3(0.04, 0.03, 0.02);
uniform vec3 color_mid : source_color = vec3(0.08, 0.06, 0.04);
uniform vec3 color_light : source_color = vec3(0.14, 0.10, 0.06);
uniform float noise_scale : hint_range(0.01, 1.0) = 0.25;
uniform float detail_scale : hint_range(0.1, 5.0) = 1.5;
uniform float roughness_val : hint_range(0.0, 1.0) = 0.95;
uniform vec3 fog_color : source_color = vec3(0.1, 0.1, 0.1);

// Simple hash-based noise (no texture dependency)
float hash(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}

float noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	f = f * f * (3.0 - 2.0 * f); // smoothstep
	float a = hash(i);
	float b = hash(i + vec2(1.0, 0.0));
	float c = hash(i + vec2(0.0, 1.0));
	float d = hash(i + vec2(1.0, 1.0));
	return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
	float v = 0.0;
	float amp = 0.5;
	for (int i = 0; i < 4; i++) {
		v += amp * noise(p);
		p *= 2.1;
		amp *= 0.45;
	}
	return v;
}

// Voronoi-ish cell pattern for organic ground breakup
float voronoi(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	float min_dist = 1.0;
	for (int y = -1; y <= 1; y++) {
		for (int x = -1; x <= 1; x++) {
			vec2 neighbor = vec2(float(x), float(y));
			vec2 point = vec2(hash(i + neighbor), hash(i + neighbor + 17.0));
			vec2 diff = neighbor + point - f;
			min_dist = min(min_dist, dot(diff, diff));
		}
	}
	return sqrt(min_dist);
}

void vertex() {
	// Pass world position to fragment shader
	UV = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xz;
}

void fragment() {
	vec2 world_uv = UV;

	// Large-scale terrain variation
	float large = fbm(world_uv * noise_scale);

	// Medium detail — soil patches
	float medium = fbm(world_uv * noise_scale * 3.0 + 42.0);

	// Fine detail — gravel/pebble breakup
	float fine = voronoi(world_uv * detail_scale);

	// Combine: large drives dark↔light, medium adds patches, fine adds texture
	float t = large * 0.5 + medium * 0.3 + fine * 0.2;

	// Map to color ramp
	vec3 col;
	if (t < 0.4) {
		col = mix(color_dark, color_mid, t / 0.4);
	} else {
		col = mix(color_mid, color_light, (t - 0.4) / 0.6);
	}

	// Slight normal perturbation for surface relief
	float dx = fbm(world_uv * noise_scale * 2.0 + vec2(0.1, 0.0)) -
	           fbm(world_uv * noise_scale * 2.0 - vec2(0.1, 0.0));
	float dz = fbm(world_uv * noise_scale * 2.0 + vec2(0.0, 0.1)) -
	           fbm(world_uv * noise_scale * 2.0 - vec2(0.0, 0.1));
	NORMAL_MAP = vec3(dx * 2.0 + 0.5, dz * 2.0 + 0.5, 1.0);

	// Fade ground to fog color at edges — no hard cliff
	float edge_dist = length(world_uv) / 800.0;
	float fade = smoothstep(0.5, 0.95, edge_dist);
	col = mix(col, fog_color, fade);

	ALBEDO = col;
	ROUGHNESS = roughness_val;
}
