shader_type spatial;
render_mode cull_disabled, unshaded;
// 3-color flat shader. Facet orientation picks base/shadow/accent.
// light_reactive kinds can respond to light channels. Everything else is deaf.

// 3-color palette — config-driven per kind
uniform vec3 color_base : source_color = vec3(0.30, 0.27, 0.23);
uniform vec3 color_shadow : source_color = vec3(0.26, 0.23, 0.19);
uniform vec3 color_accent : source_color = vec3(0.34, 0.30, 0.25);

// Light reactivity — 0 = deaf (flat output), 1 = listens to light channel
uniform float light_reactive : hint_range(0.0, 1.0) = 0.0;

// Per-instance horizontal banding — each object gets 1 or 2 bands max,
// spanning its own local height. Uniqueness comes from a per-instance
// hash of MODEL_MATRIX origin: different objects get different band
// counts, different phases, so the world doesn't look gridded.
uniform float band_strength : hint_range(0.0, 0.3) = 0.10;  // brightness shift

// Vertex shape (kept from clean room — these earn their pixels)
uniform float taper_strength : hint_range(0.0, 1.0) = 0.0;
uniform float twist_amount : hint_range(0.0, 1.0) = 0.0;

varying vec3 world_pos;
varying float local_y;

void vertex() {
	// Column taper
	if (taper_strength > 0.001) {
		float height_t = clamp(VERTEX.y, 0.0, 1.0);
		float taper = 1.0 - height_t * taper_strength;
		VERTEX.x *= taper;
		VERTEX.z *= taper;
	}

	// Axial twist
	if (twist_amount > 0.001) {
		float height_t = clamp(VERTEX.y, 0.0, 1.0);
		float twist_sign = INSTANCE_CUSTOM.r > 0.5 ? 1.0 : -1.0;
		float angle = height_t * twist_amount * twist_sign;
		float c = cos(angle);
		float s = sin(angle);
		float tx = VERTEX.x * c - VERTEX.z * s;
		float tz = VERTEX.x * s + VERTEX.z * c;
		VERTEX.x = tx;
		VERTEX.z = tz;
	}

	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	local_y = VERTEX.y;
}

void fragment() {
	// Per-face normal from screen-space derivatives — flat shading
	vec3 face_normal = normalize(cross(dFdx(world_pos), dFdy(world_pos)));

	// Facing ratio: how much this facet points toward camera
	// 1.0 = facing camera directly, 0.0 = perpendicular/away
	float facing = max(dot(face_normal, VIEW), 0.0);

	// 3-color selection — hard snap, not gradient.
	// Each facet is ONE color. The hard edge between planes IS the shape.
	vec3 col = color_base;
	col = mix(color_shadow, col, step(0.35, facing));
	col = mix(col, color_accent, step(0.75, facing));

	// Light reactive kinds: blend toward white when eventually lit.
	// For now, placeholder — light_reactive kinds get a subtle self-brightness
	// that distinguishes them from deaf objects. When light pipes come back,
	// this uniform gets modulated by the pipe channel color + intensity.
	if (light_reactive > 0.5) {
		col = mix(col, color_accent, 0.15);
	}

	// Per-instance horizontal banding — three independent hashes drive band
	// count, phase, and width so no two instances share a layout. The world
	// reads as individually-stratified objects, not a grid.
	vec3 instance_origin = MODEL_MATRIX[3].xyz;
	float h1 = fract(sin(dot(instance_origin.xz, vec2(12.9898, 78.233))) * 43758.5453);
	float h2 = fract(sin(dot(instance_origin.xz, vec2(31.7777, 19.3791))) * 28765.1234);
	float h3 = fract(sin(dot(instance_origin.xz, vec2(54.2517, 91.0833))) * 17483.9012);
	float band_count = 1.0 + floor(h1 * 3.0);          // 1, 2, or 3 bands per object
	float phase = h2;                                   // full 0..1 vertical offset
	float band_width = mix(0.30, 0.70, h3);             // dark portion of period
	float band = mod(local_y * band_count + phase, 1.0);
	float band_t = step(band_width, band);              // hard step at variable width
	float stripe = band_t * 2.0 - 1.0;                  // -1 dark, +1 light
	col *= 1.0 + stripe * band_strength;

	ALBEDO = col;
}
