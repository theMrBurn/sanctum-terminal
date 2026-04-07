shader_type spatial;
render_mode cull_disabled, unshaded;
// CLEAN ROOM: unshaded — no PBR, no lighting. ALBEDO = pixel color.
// See shapes and shader math honestly without lighting interference.

uniform vec3 palette_base : source_color = vec3(0.45, 0.43, 0.40);  // CLEAN ROOM — visible mid-grey
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

// Horizontal strata — Sable-style color banding on geological surfaces.
// Two band colors mix with base via world-space Y position.
uniform vec3 band_color_a : source_color = vec3(0.0);
uniform vec3 band_color_b : source_color = vec3(0.0);
uniform float band_scale : hint_range(0.0, 2.0) = 0.0;  // 0 = disabled

// Flat shading — recompute per-face normal from position derivatives
// 0 = smooth (vertex normals), 1 = flat (per-triangle facet normals)
uniform float flat_shading : hint_range(0.0, 1.0) = 0.0;

// Vertex displacement — noise-based surface erosion.
// Breaks smooth capsule silhouettes into craggy geological forms.
// 0 = disabled (crystalline, organic), 0.15-0.4 = geological/structural
uniform float vertex_displacement : hint_range(0.0, 1.0) = 0.0;

// Column taper — wider base, narrower top. Natural geological shape.
// 0 = uniform width, 0.3-0.5 = visible taper for columns/stalagmites
uniform float taper_strength : hint_range(0.0, 1.0) = 0.0;

// Axial twist — subtle rotation around Y as height increases.
// Creates organic geological character. Radians of total twist.
// 0 = straight, 0.15-0.4 = subtle natural twist
uniform float twist_amount : hint_range(0.0, 1.0) = 0.0;

// Rim light — fresnel edge glow for silhouette separation in dark scenes.
// Dark objects against dark backgrounds get a faint atmospheric edge.
// 0 = disabled, 0.1-0.2 = subtle separation
uniform float rim_strength : hint_range(0.0, 0.5) = 0.0;

// Wet base — height-based darkening + roughness reduction at ground contact.
// Objects look damp/seated where they meet the floor. The "Direct" composite.
// 0 = disabled, 0.3-0.5 = visible wet zone at bottom 30% of object
uniform float wet_base_strength : hint_range(0.0, 1.0) = 0.0;

// Phase 2 — Merkabah plane-attachment layer fade.
// fog_layer_color is the color entities fade toward as they migrate from
// near → mid → far → void layers. Usually matches scene fog color.
uniform vec3 fog_layer_color : source_color = vec3(0.08, 0.08, 0.13);

// Dithered dissolution — fragments discard at depth boundaries.
// The darkness eats the geometry. Blue-noise-style pattern from hash3d.
// 0 = disabled (emissive kinds stay solid), 1.0 = full dissolution at fog distance
uniform float dissolve_strength : hint_range(0.0, 1.0) = 0.0;

// 3D noise for vertex displacement — hash-based, no texture needed
float hash3d(vec3 p) {
	p = fract(p * vec3(443.897, 441.423, 437.195));
	p += dot(p, p.yzx + 19.19);
	return fract((p.x + p.y) * p.z);
}

float noise3d(vec3 p) {
	vec3 i = floor(p);
	vec3 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);  // smoothstep
	return mix(
		mix(mix(hash3d(i), hash3d(i + vec3(1,0,0)), f.x),
		    mix(hash3d(i + vec3(0,1,0)), hash3d(i + vec3(1,1,0)), f.x), f.y),
		mix(mix(hash3d(i + vec3(0,0,1)), hash3d(i + vec3(1,0,1)), f.x),
		    mix(hash3d(i + vec3(0,1,1)), hash3d(i + vec3(1,1,1)), f.x), f.y),
		f.z);
}

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
// Phase 2 — layer membership passed from vertex to fragment via INSTANCE_CUSTOM.
// Encoded as: .r = near weight, .g = mid weight, .b = far weight, .a = void weight
varying vec4 layer_mem;

void vertex() {
	// Column taper — scale X/Z based on normalized Y height.
	// Bottom (Y near 0) stays full width, top narrows.
	// Uses object-space Y so it works regardless of world position.
	if (taper_strength > 0.001) {
		// Normalize Y to 0-1 range using object bounds (assume mesh is 0..1 in Y)
		float height_t = clamp(VERTEX.y, 0.0, 1.0);
		float taper = 1.0 - height_t * taper_strength;  // 1.0 at base, narrower at top
		VERTEX.x *= taper;
		VERTEX.z *= taper;
	}

	// Axial twist — rotate X/Z around Y axis proportional to height.
	// Per-instance variation from INSTANCE_CUSTOM seed keeps each column unique.
	if (twist_amount > 0.001) {
		float height_t = clamp(VERTEX.y, 0.0, 1.0);
		// Twist direction varies per instance via INSTANCE_CUSTOM.r
		float twist_sign = INSTANCE_CUSTOM.r > 0.5 ? 1.0 : -1.0;
		float angle = height_t * twist_amount * twist_sign;
		float c = cos(angle);
		float s = sin(angle);
		float tx = VERTEX.x * c - VERTEX.z * s;
		float tz = VERTEX.x * s + VERTEX.z * c;
		VERTEX.x = tx;
		VERTEX.z = tz;
	}

	// Vertex displacement — broad undulations, not per-face cracks.
	// Low frequency noise preserves surface continuity on low-poly meshes.
	// The displacement should warp the SHAPE, not separate the FACES.
	if (vertex_displacement > 0.001) {
		vec3 wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
		float n1 = noise3d(wp * 0.5) - 0.5;   // very broad shape warping
		float n2 = noise3d(wp * 1.0) - 0.5;    // medium undulation
		float disp = (n1 * 0.8 + n2 * 0.2) * vertex_displacement;
		VERTEX += NORMAL * disp;
	}

	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	world_norm = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
	layer_mem = INSTANCE_CUSTOM;
}

void fragment() {
	// CLEAN ROOM — pure flat color. palette_base × kind_tint. Nothing else.
	// Add effects back ONE AT A TIME from here.
	vec3 col = palette_base * kind_tint;

	ALBEDO = col;
}
