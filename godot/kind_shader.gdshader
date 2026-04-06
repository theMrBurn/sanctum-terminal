shader_type spatial;
// Backface culling enabled by default (no cull_disabled) — prevents
// the "solid wall from inside the mesh" artifact when camera clips
// a mesh edge. Interior surfaces no longer render as opaque walls.

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
	// 1. Start from palette base
	vec3 col = palette_base;

	// 2. Blend in vertex color (subtle — just for per-instance variation)
	col = mix(col, COLOR.rgb * palette_base * 2.0, vertex_color_blend);

	// 3. Apply kind tint
	col *= kind_tint;

	// 3.5 Horizontal strata — world-space Y banding for geological surface variety.
	// Creates readable layered-rock detail without texture resolution.
	if (band_scale > 0.01) {
		float band_y = world_pos.y * band_scale;
		// Two overlapping sine waves at different frequencies = organic strata
		float band_a = smoothstep(0.3, 0.7, sin(band_y * 3.14) * 0.5 + 0.5);
		float band_b = smoothstep(0.2, 0.8, sin(band_y * 1.57 + 1.0) * 0.5 + 0.5);
		vec3 banded = mix(col, band_color_a, band_a * 0.25);
		banded = mix(banded, band_color_b, band_b * 0.15);
		col = banded;
	}

	// 3.7 Wet base — bottom of object darkens and gets glossy.
	// Uses object-space Y (via world_pos relative to instance base).
	// The darkening + roughness shift makes objects look damp where they
	// meet the ground — the "Direct" composite from the boulder sketch.
	float wet_factor = 0.0;
	if (wet_base_strength > 0.001) {
		// world_pos.y relative to ground (0) — bottom 2m of object gets wet
		float wet_height = clamp(1.0 - world_pos.y / 2.0, 0.0, 1.0);
		wet_factor = wet_height * wet_base_strength;
		col *= 1.0 - wet_factor * 0.4;  // darken by up to 40% at base
	}

	// 4. World grain — subtle multiply for surface texture
	float grain = triplanar(grain_tex, world_pos, world_norm, grain_scale).r;
	col *= mix(1.0, grain * 1.5 + 0.25, grain_strength);

	// 5. Normal map — subtle surface detail
	if (normal_strength > 0.01) {
		vec3 n = triplanar(normal_tex, world_pos, world_norm, grain_scale).rgb;
		NORMAL_MAP = n;
		NORMAL_MAP_DEPTH = normal_strength;
	}

	// 6. Flat shading — blend per-face normal with vertex normal.
	// 70% face + 30% vertex softens the hardest silhouette edges in dark
	// frames while preserving the low-poly rock facet look.
	if (flat_shading > 0.5) {
		vec3 face_normal = normalize(cross(dFdx(VERTEX), dFdy(VERTEX)));
		NORMAL = normalize(mix(NORMAL, face_normal, 0.7));
	}

	// Phase 2 — Merkabah layer fade. Entities in deeper layers mix toward
	// the fog color (atmospheric perspective) and reduce visibility.
	// Defaults are safe: if INSTANCE_CUSTOM is zero (legacy path), treat as
	// fully near-layer (near_w=1) so nothing changes for old behavior.
	float near_w = layer_mem.r;
	float mid_w  = layer_mem.g;
	float far_w  = layer_mem.b;
	float void_w = layer_mem.a;
	float layer_total = near_w + mid_w + far_w + void_w;
	if (layer_total < 0.001) {
		near_w = 1.0;  // legacy default — no layer data → fully near
		layer_total = 1.0;
	}
	// Atmospheric perspective: entities in deeper layers blend toward fog
	float fog_blend = mid_w * 0.25 + far_w * 0.65 + void_w * 0.95;
	col = mix(col, fog_layer_color, fog_blend);
	// Visibility falls off with depth but never to zero (asymptotic)
	float visibility = near_w + mid_w * 0.85 + far_w * 0.55 + void_w * 0.15;
	col *= visibility;

	ALBEDO = col;
	// Wet base reduces roughness — glossy damp surface catches light at ground contact
	ROUGHNESS = roughness_base - wet_factor * 0.35;
	METALLIC = light_response * 0.05;

	// Emissive glow (crystals, moss, fungus)
	float emit_base = 0.0;
	if (inner_glow > 0.01) {
		float pulse = 1.0 + sin(TIME * pulse_rate * 6.28) * 0.15;
		emit_base = inner_glow * pulse * 2.0;
	}

	// Rim light — fresnel edge glow for silhouette separation.
	// Dark objects against dark backgrounds get a faint atmospheric edge.
	// The rim color matches fog_layer_color so it reads as the environment
	// wrapping around the object, not a glowing outline.
	float rim = 0.0;
	if (rim_strength > 0.001) {
		rim = 1.0 - max(dot(VIEW, NORMAL), 0.0);
		rim = pow(rim, 3.0) * rim_strength;
	}

	EMISSION = col * emit_base + fog_layer_color * rim * 1.5;
}
