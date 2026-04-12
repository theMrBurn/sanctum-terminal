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

// Per-instance wind sway — TIME-driven vertex displacement scaled by
// local_y so the top bends and the base stays planted. Phase and direction
// hash from MODEL_MATRIX origin so no two instances sway together.
uniform float wind_strength : hint_range(0.0, 0.1) = 0.0;

// Per-instance ghost fade — a hash-selected fraction of instances render
// as "ghosts" (half-opaque at distance, lerp to full as camera approaches).
// Same hash pattern as banding/wind for consistency. Uses Bayer dither
// discard so no transparency config is needed and Metal stays stable.
uniform float ghost_chance : hint_range(0.0, 1.0) = 0.0;

// Vertex color path — when true, fragment reads baked per-vertex COLOR
// from the mesh instead of computing the 3-color palette from facet
// normals. Used for "designed" kinds authored via tools/gen_kind_mesh.py
// where color regions are painted into the mesh (toadstool cap/spots/
// stem/base). Stone kinds keep the facet-normal path for stratification.
uniform float use_vertex_colors : hint_range(0.0, 1.0) = 0.0;

// Vertex shape (kept from clean room — these earn their pixels)
uniform float taper_strength : hint_range(0.0, 1.0) = 0.0;
uniform float twist_amount : hint_range(0.0, 1.0) = 0.0;

varying vec3 world_pos;
varying float local_y;
varying flat vec4 vertex_col;  // flat = no interpolation across faces (Sable look)

void vertex() {
	// Capture the mesh's baked vertex color for designed kinds.
	// Unused when use_vertex_colors == 0, cheap either way.
	vertex_col = COLOR;

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

	// Gusting breeze — a wave that travels across the ground rather than
	// every instance twitching independently. Most of the time motion is
	// effectively zero; every ~15s a gust ripples through, briefly bending
	// whichever tufts it's crossing. Much more breeze-like than constant
	// desynced oscillation.
	//
	//   wind_dir     — constant unit vector (x, z plane)
	//   omega        — temporal angular frequency, 2π/period
	//   k            — spatial angular frequency, 2π/wavelength
	//   wave speed   = omega / k   (≈ 3 m/s with current constants)
	//   pow(sin, 8)  — sharpens the sine into a brief peak; ~1 s active
	//                  out of each 15 s cycle, near-zero the rest.
	if (wind_strength > 0.001) {
		vec3 wi_origin = MODEL_MATRIX[3].xyz;
		vec2 wind_dir = vec2(0.7071, 0.7071);    // 45° from X, normalized
		float pos_along = dot(wi_origin.xz, wind_dir);
		float omega = 0.42;                      // rad/s → 15 s period
		float k     = 0.14;                      // rad/m → 45 m wavelength
		float gust_raw = sin(TIME * omega - pos_along * k);
		float gust = pow(max(gust_raw, 0.0), 8.0);  // brief sharp peak
		// Tiny per-instance fine phase so tufts on the same wave crest
		// don't all hit peak in the same frame (kills residual "in sync"
		// feel when two neighbors happen to be on the same isocline).
		float fine_phase = fract(sin(dot(wi_origin.xz, vec2(22.1, 31.7))) * 13.41);
		gust *= 0.80 + fine_phase * 0.40;        // 0.80-1.20 amplitude jitter
		float height_w = clamp(VERTEX.y, 0.0, 2.0);
		float sway = gust * wind_strength * height_w;
		// Direction jitter: neighbors don't bend exactly parallel.
		float dir_jitter = (fract(sin(dot(wi_origin.xz, vec2(41.9, 17.3))) * 19.73) - 0.5) * 0.35;
		VERTEX.x += (wind_dir.x + dir_jitter) * sway;
		VERTEX.z += (wind_dir.y + dir_jitter) * sway;
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

	// Designed kinds (toadstool, shrubs, fauna composites) bake per-
	// region colors into mesh vertex data. When use_vertex_colors is
	// set, skip the facet-normal palette entirely and use the baked
	// colors directly. Stone kinds keep the facet-normal path so
	// banding and shadow selection still work for them.
	vec3 col;
	if (use_vertex_colors > 0.5) {
		// sRGB → linear correction. gen_kind_mesh.py stores per-vertex
		// colors as sRGB byte values, but glTF spec says vertex colors
		// are linear. Godot interprets them as linear and applies gamma
		// at display, double-brightening the palette. This pow(2.2)
		// converts the sRGB-in-disguise values to actual linear so the
		// display pipeline produces the intended perceptual colors.
		col = pow(vertex_col.rgb, vec3(2.2));
	} else {
		// 3-color selection — hard snap, not gradient.
		// Each facet is ONE color. The hard edge between planes IS the shape.
		col = color_base;
		col = mix(color_shadow, col, step(0.35, facing));
		col = mix(col, color_accent, step(0.75, facing));

		// Light reactive kinds: blend toward white when eventually lit.
		// For now, placeholder — light_reactive kinds get a subtle self-brightness
		// that distinguishes them from deaf objects. When light pipes come back,
		// this uniform gets modulated by the pipe channel color + intensity.
		if (light_reactive > 0.5) {
			col = mix(col, color_accent, 0.15);
		}
	}

	// Per-instance horizontal banding — three independent hashes drive band
	// count, phase, and width so no two instances share a layout. The world
	// reads as individually-stratified objects, not a grid.
	// Skipped when use_vertex_colors is set — banding is rock stratification
	// and would paint horizontal dark stripes across a toadstool cap.
	vec3 instance_origin = MODEL_MATRIX[3].xyz;
	if (use_vertex_colors < 0.5 && band_strength > 0.001) {
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
	}

	// Per-instance ghost silhouette — hash-selected fraction of instances
	// darken progressively toward the far visibility edge. Stones stay
	// fully bright inside 20m, drop to 55% brightness by 45m. No alpha,
	// no discard — purely a multiplicative darkening on col. Reads as
	// atmospheric perspective / receding into shadow at distance.
	if (ghost_chance > 0.001) {
		float gh_hash = fract(sin(dot(instance_origin.xz, vec2(37.1, 59.3))) * 23.47);
		if (gh_hash < ghost_chance) {
			float cam_dist = distance(CAMERA_POSITION_WORLD, world_pos);
			float fade_t = smoothstep(20.0, 45.0, cam_dist);
			col *= mix(1.0, 0.55, fade_t);
		}
	}

	ALBEDO = col;
}
