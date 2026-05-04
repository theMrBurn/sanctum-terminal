shader_type spatial;
render_mode unshaded;
// CLEAN ROOM: unshaded ground — no PBR, flat color output.
//
// Procedural Voronoi tile pattern (added 2026-04-09):
// Each pixel computes the distance to the nearest two Voronoi seed points
// in world space. F2-F1 gives distance from cell boundary, used for mortar
// line darkening. The nearest cell ID seeds a per-cell brightness tint so
// adjacent tiles read as discrete cells, not a uniform field. Sub-cell
// grain texture remains for fine detail. Matches the Panda3D reference
// in test_artifacts (faceted polygon ground).

uniform vec3 color_base : source_color = vec3(0.06, 0.05, 0.04);
uniform vec3 fog_color : source_color = vec3(0.1, 0.1, 0.1);
uniform sampler2D grain_tex;
uniform sampler2D normal_tex : hint_normal;
uniform float grain_scale = 0.35;
uniform float grain_strength : hint_range(0.0, 1.0) = 0.12;
uniform float normal_strength : hint_range(0.0, 2.0) = 0.4;
uniform float roughness_val : hint_range(0.0, 1.0) = 0.95;
uniform float honeycomb_cell_size = 18.0;  // matches world_gen node spacing
uniform bool vertical_surface = false;  // walls use XY projection, floors use XZ
uniform bool is_floor = false;          // gate floor-only effects (Voronoi) — set by main.gd per plane kind
uniform float height_darken : hint_range(0.0, 1.0) = 0.0;  // vertical gradient (0=none, 1=full)

// Sparse hash-mark pattern — FLOOR ONLY. Sable-like surface design:
// plain dark base + discrete intentional-looking marks placed by position
// hashes. Same family as the kind_shader banding logic — three independent
// hashes per grid cell drive whether a mark exists, where it sits, what
// size, and whether it's lighter or darker than the base. The polarity
// (light vs dark) is biased by a slow-varying noise field, so light marks
// cluster in some regions ("rocky area / pebbles around stone") and dark
// marks cluster in others ("smooth dirt patches"). Total mark count is
// preserved — only the LIGHT/DARK distribution shifts spatially.
uniform bool sparse_marks_enabled = true;
uniform vec3 floor_base_color : source_color = vec3(0.09, 0.07, 0.05);   // plain dark earth
uniform float mark_grid_size : hint_range(0.5, 5.0) = 1.20;              // meters per grid cell
uniform float mark_chance : hint_range(0.0, 1.0) = 0.45;                 // probability a cell has any mark
uniform float mark_radius_base : hint_range(0.05, 0.50) = 0.18;          // base mark size in cell units
uniform float mark_strength : hint_range(0.0, 1.0) = 0.45;               // brightness shift amplitude
uniform float density_field_scale : hint_range(0.005, 0.10) = 0.038;     // (fallback) noise blob size when stone tex not bound
uniform float density_polarity_bias : hint_range(0.0, 2.0) = 1.30;       // how strongly density skews polarity

// Real stone density texture — supplied by main.gd._build_stone_density_texture.
// Each pixel is accumulated density from nearby stone-class entities. When
// stone_density_enabled is true, sample this instead of the value_noise
// fallback so light marks cluster around actual stone positions.
uniform bool stone_density_enabled = false;
uniform sampler2D stone_density_tex;
uniform vec2 stone_density_origin = vec2(0.0, 0.0);   // world center the texture covers
uniform float stone_density_radius = 100.0;            // half-extent in meters

varying vec2 world_uv;
varying float world_y;  // vertical position for height gradient

// Hash function for per-cell signature
float cell_hash(vec2 cell) {
	return fract(sin(dot(cell, vec2(127.1, 311.7))) * 43758.5453);
}

// 2D value noise — bilinearly interpolated hash grid. Smooth output in
// [0, 1]. Used to create a slow-varying "density field" that biases mark
// polarity so light marks cluster in regions instead of being uniformly
// random. Same hash family as kind_shader banding for consistency.
float value_noise2d(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	float a = fract(sin(dot(i + vec2(0.0, 0.0), vec2(127.1, 311.7))) * 43758.5453);
	float b = fract(sin(dot(i + vec2(1.0, 0.0), vec2(127.1, 311.7))) * 43758.5453);
	float c = fract(sin(dot(i + vec2(0.0, 1.0), vec2(127.1, 311.7))) * 43758.5453);
	float d = fract(sin(dot(i + vec2(1.0, 1.0), vec2(127.1, 311.7))) * 43758.5453);
	vec2 u = f * f * (3.0 - 2.0 * f);  // smoothstep ease
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

// 2D Voronoi — returns vec3(F1, F2, cell_id_hash) given a position p.
//   F1 = distance to nearest seed point
//   F2 = distance to second-nearest seed point
//   cell_id_hash = stable per-cell hash in [0, 1]
//
// (F2 - F1) gives distance from the Voronoi boundary edge, used to draw
// mortar lines. Loop is fixed 3x3 neighborhood — cheap, no branching cost
// on modern hardware.
vec3 voronoi2d(vec2 p) {
	vec2 cell = floor(p);
	vec2 frac = fract(p);
	float f1 = 8.0;
	float f2 = 8.0;
	float closest_id = 0.0;
	for (int y = -1; y <= 1; y++) {
		for (int x = -1; x <= 1; x++) {
			vec2 neighbor = vec2(float(x), float(y));
			vec2 cell_pos = cell + neighbor;
			// Pseudorandom seed point inside the neighbor cell.
			vec2 seed_offset = vec2(
				fract(sin(dot(cell_pos, vec2(127.1, 311.7))) * 43758.5453),
				fract(sin(dot(cell_pos, vec2(269.5, 183.3))) * 43758.5453)
			);
			vec2 seed = neighbor + seed_offset;
			float d = length(seed - frac);
			if (d < f1) {
				f2 = f1;
				f1 = d;
				closest_id = fract(sin(dot(cell_pos, vec2(91.7, 233.1))) * 14.5);
			} else if (d < f2) {
				f2 = d;
			}
		}
	}
	return vec3(f1, f2, closest_id);
}

void vertex() {
	vec3 world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	// Walls: project on XY (vertical surface). Floors: project on XZ (horizontal).
	world_uv = vertical_surface ? world_pos.xy : world_pos.xz;
	world_y = world_pos.y;
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

	// Ground pattern: mostly dark negative space, bright pixels cluster into
	// piles/stacks like rubble in dirt. Steep power curve = vast dark areas
	// with occasional bright mortar/gravel deposits. Light reveals the texture;
	// unlit ground reads as featureless dark earth.
	float grain_shaped = pow(grain, 3.5);  // steeper — more dark, sharper peaks
	float grain_effect = mix(0.25, 2.4, grain_shaped);  // wider range: darker lows, brighter highs
	vec3 col = color_base * mix(1.0, grain_effect, grain_strength * amplitude);

	// Sparse hash-mark pattern — FLOOR ONLY. Same design family as the
	// kind_shader banding: per-grid-cell, roll three independent hashes
	// from world position, derive (has_mark, position, size, polarity)
	// from them. Most cells render as plain dark earth; cells whose first
	// hash crosses mark_chance get a discrete mark of varied size and
	// random lighter-or-darker polarity. Reads as "intentional sparse
	// detail," not "algorithmic pattern."
	if (sparse_marks_enabled && is_floor) {
		// Plain dark base — replaces manifest color_base entirely.
		vec3 base = floor_base_color;

		// Grid index + local coordinate within the cell (0..1).
		vec2 mark_grid = floor(world_uv / mark_grid_size);
		vec2 mark_frac = fract(world_uv / mark_grid_size);

		// Three independent hashes per grid cell — same family as
		// kind_shader.gdshader band hashes (different multipliers).
		float h1 = fract(sin(dot(mark_grid, vec2(12.9898, 78.233))) * 43758.5453);
		float h2 = fract(sin(dot(mark_grid, vec2(31.7777, 19.3791))) * 28765.1234);
		float h3 = fract(sin(dot(mark_grid, vec2(54.2517, 91.0833))) * 17483.9012);

		// Does this cell get a mark?
		float has_mark = step(1.0 - mark_chance, h1);
		if (has_mark > 0.5) {
			// Mark center inside cell, kept away from edges (0.2..0.8).
			vec2 mark_center = vec2(0.20 + h2 * 0.60, 0.20 + h3 * 0.60);
			// Anisotropic distance — squash one axis per-mark so each mark
			// gets its own aspect ratio. Combined with the soft falloff this
			// turns "dots" into rounded ovals stretched horizontally, like
			// natural soil variation rather than discrete pinpoints.
			vec2 delta = mark_frac - mark_center;
			float aspect_y = 1.0 + h2 * 0.85;          // 1.0..1.85 — squash on Y
			delta.y *= aspect_y;
			float dist = length(delta);
			// Per-mark size variation: 0.85x to 1.55x base radius.
			float radius = mark_radius_base * (0.85 + h2 * 0.70);
			// Smooth falloff from center to edge with NO hard inner core.
			// pow() squares the falloff so the bright peak stays contained
			// while the soft halo extends out — marks read as patches, not dots.
			float falloff = 1.0 - smoothstep(0.0, radius, dist);
			float mark_alpha = falloff * falloff;
			// Density field — defines "rocky areas" (high density, want light
			// marks) vs "smooth dirt" (low density, want dark marks). When
			// stone_density_enabled, sample the texture built per-frame from
			// real entity positions so light marks cluster around actual
			// stones. Otherwise fall back to value_noise2d (independent of
			// stones) so the visual still works on first frame / when texture
			// isn't bound yet.
			vec2 mark_world_pos = (mark_grid + mark_center) * mark_grid_size;
			float density;
			if (stone_density_enabled) {
				vec2 dens_uv = (mark_world_pos - stone_density_origin)
					/ (stone_density_radius * 2.0) + 0.5;
				if (dens_uv.x < 0.0 || dens_uv.x > 1.0 || dens_uv.y < 0.0 || dens_uv.y > 1.0) {
					density = 0.0;  // outside texture extent → treat as low density
				} else {
					density = texture(stone_density_tex, dens_uv).r;
				}
			} else {
				density = value_noise2d(mark_world_pos * density_field_scale);
			}
			// Combine: hash-driven random polarity blended with density bias.
			// At density 0.5 (neutral), polarity is purely random from h3.
			// At density >> 0.5, polarity skews positive (lighter marks).
			// At density << 0.5, polarity skews negative (darker marks).
			float random_polarity = (h3 - 0.5) * 2.0;
			float density_polarity = (density - 0.5) * 2.0 * density_polarity_bias;
			float polarity = clamp(random_polarity + density_polarity, -1.0, 1.0);
			float shift = polarity * mark_strength;
			base *= 1.0 + shift * mark_alpha;
		}

		// Multiply existing grain factor on top for fine tactile texture.
		float grain_mod = mix(1.0, grain_effect, grain_strength * amplitude * 0.4);
		col = base * grain_mod;
	}

	// Distance fade disabled — ground/ceiling stay their color at all distances

	// Height gradient — walls darken toward ceiling, lighter near floor
	// where light pools reflect. Creates vertical depth variation.
	if (height_darken > 0.01) {
		float h_factor = clamp(world_y / 15.0, 0.0, 1.0);  // 0 at floor, 1 at ceiling
		col *= mix(1.0, 0.3, h_factor * height_darken);
	}

	ALBEDO = col;
	ROUGHNESS = roughness_val;

	// Normal map with distance amplitude — relief fades with distance
	if (normal_strength > 0.01) {
		vec3 n = texture(normal_tex, uv).rgb;
		NORMAL_MAP = n;
		NORMAL_MAP_DEPTH = normal_strength * amplitude;
	}
}
