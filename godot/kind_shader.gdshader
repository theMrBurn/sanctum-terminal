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

// Vertex shape (kept from clean room — these earn their pixels)
uniform float taper_strength : hint_range(0.0, 1.0) = 0.0;
uniform float twist_amount : hint_range(0.0, 1.0) = 0.0;

varying vec3 world_pos;

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
}

void fragment() {
	// Per-face normal from screen-space derivatives — flat shading
	vec3 face_normal = normalize(cross(dFdx(world_pos), dFdy(world_pos)));

	// Facing ratio: how much this facet points toward camera
	// 1.0 = facing camera directly, 0.0 = perpendicular/away
	float facing = max(dot(face_normal, VIEW), 0.0);

	// 3-color selection:
	//   accent  — facets facing camera most directly (top 30%)
	//   base    — mid-range facets (middle band)
	//   shadow  — facets angled away from camera (bottom 40%)
	vec3 col = color_base;
	col = mix(color_shadow, col, smoothstep(0.25, 0.45, facing));
	col = mix(col, color_accent, smoothstep(0.70, 0.90, facing));

	// Light reactive kinds: blend toward white when eventually lit.
	// For now, placeholder — light_reactive kinds get a subtle self-brightness
	// that distinguishes them from deaf objects. When light pipes come back,
	// this uniform gets modulated by the pipe channel color + intensity.
	if (light_reactive > 0.5) {
		col = mix(col, color_accent, 0.15);
	}

	ALBEDO = col;
}
