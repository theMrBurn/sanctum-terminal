shader_type spatial;

// Config-driven kind shader. Reads per-kind parameters from uniforms.
// Applied via triplanar mapping — no UVs needed.

// Base rendering
uniform bool use_vertex_color = true;
uniform float roughness_base : hint_range(0.0, 1.0) = 0.85;
uniform float roughness_wet : hint_range(0.0, 1.0) = 0.25;
uniform float wet_height : hint_range(0.0, 1.0) = 0.3;
uniform float light_response : hint_range(0.0, 1.0) = 0.35;

// Normal map (triplanar) — world_grain sampled at WORLD_GRAIN × material_ratio
uniform sampler2D normal_tex : hint_normal;
uniform float normal_strength : hint_range(0.0, 2.0) = 0.8;
uniform float material_ratio = 0.80;  // from MATERIAL_RATIOS: stone_heavy=0.80, organic=1.20
uniform float world_grain = 0.10;     // base frequency — same for everything
uniform float triplanar_sharpness = 1.5;

// Albedo grain texture (same base pattern, multiplied into vertex color)
uniform sampler2D grain_tex;
uniform float grain_strength : hint_range(0.0, 1.0) = 0.3;

// Surface effects
uniform bool wet_base_enabled = true;
uniform vec3 wet_tint : source_color = vec3(0.06, 0.08, 0.07);
uniform bool moss_patches_enabled = false;
uniform vec3 moss_color : source_color = vec3(0.08, 0.20, 0.06);
uniform float moss_threshold : hint_range(0.0, 1.0) = 0.6;
uniform float moss_height : hint_range(0.0, 1.0) = 0.5;

// Contact darkening
uniform float contact_darkness : hint_range(0.0, 1.0) = 0.4;
uniform float contact_height : hint_range(0.0, 1.0) = 0.15;

// Inner glow (crystalline)
uniform float inner_glow : hint_range(0.0, 1.0) = 0.0;
uniform float pulse_rate : hint_range(0.0, 0.2) = 0.0;

// Subsurface hint (organic)
uniform float subsurface : hint_range(0.0, 1.0) = 0.0;

// Hash noise for moss/mold distribution
float hash(vec2 p) {
	vec3 p3 = fract(vec3(p.xyx) * 0.1031);
	p3 += dot(p3, p3.yzx + 33.33);
	return fract((p3.x + p3.y) * p3.z);
}

float noise(vec2 p) {
	vec2 i = floor(p);
	vec2 f = fract(p);
	f = f * f * (3.0 - 2.0 * f);
	return mix(mix(hash(i), hash(i + vec2(1,0)), f.x),
	           mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), f.x), f.y);
}

// Triplanar sampling
vec4 triplanar_sample(sampler2D tex, vec3 world_pos, vec3 world_normal, float scale, float sharpness) {
	vec3 blend = pow(abs(world_normal), vec3(sharpness));
	blend /= (blend.x + blend.y + blend.z);
	vec4 x = texture(tex, world_pos.yz * scale);
	vec4 y = texture(tex, world_pos.xz * scale);
	vec4 z = texture(tex, world_pos.xy * scale);
	return x * blend.x + y * blend.y + z * blend.z;
}

varying vec3 world_pos;
varying vec3 world_normal_v;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	world_normal_v = (MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz;
}

void fragment() {
	// Base color from vertex colors or white
	vec3 base_col = use_vertex_color ? COLOR.rgb : vec3(0.5);

	// Normalized height (0 = ground, 1 = top of object) from world Y
	float norm_height = clamp(world_pos.y / 5.0, 0.0, 1.0);

	// Contact darkening at base
	float contact = 1.0 - contact_darkness * (1.0 - smoothstep(0.0, contact_height * 5.0, world_pos.y));
	base_col *= contact;

	// Wet base effect — darken + lower roughness near ground
	float wet_factor = 0.0;
	if (wet_base_enabled) {
		wet_factor = 1.0 - smoothstep(0.0, wet_height * 5.0, world_pos.y);
		base_col = mix(base_col, base_col * (vec3(1.0) + wet_tint), wet_factor * 0.5);
	}

	// Moss patches — noise-driven green patches on lower surfaces
	if (moss_patches_enabled && norm_height < moss_height) {
		float moss_noise = noise(world_pos.xz * 1.5);
		if (moss_noise > moss_threshold) {
			float moss_blend = (moss_noise - moss_threshold) / (1.0 - moss_threshold);
			moss_blend *= (1.0 - norm_height / moss_height); // fades with height
			base_col = mix(base_col, moss_color, moss_blend * 0.6);
		}
	}

	// World grain texture — same pattern on everything, scaled by material ratio
	float grain_scale = world_grain * material_ratio;
	vec4 grain_sample = triplanar_sample(grain_tex, world_pos, world_normal_v, grain_scale, triplanar_sharpness);
	// Multiply grain into albedo (darken mortar lines, lighten cell faces)
	base_col *= mix(vec3(1.0), grain_sample.rgb * 1.8, grain_strength);

	ALBEDO = base_col;

	// Roughness: interpolate between wet and dry based on height
	ROUGHNESS = mix(roughness_wet, roughness_base, smoothstep(0.0, wet_height * 5.0, world_pos.y));

	// Metallic from light response
	METALLIC = light_response * 0.1;

	// Normal map (triplanar) — same world_grain scale
	if (normal_strength > 0.01) {
		vec3 norm_sample = triplanar_sample(normal_tex, world_pos, world_normal_v, grain_scale, triplanar_sharpness).rgb;
		norm_sample = norm_sample * 2.0 - 1.0;
		NORMAL_MAP = vec3(norm_sample.xy * normal_strength, norm_sample.z);
		NORMAL_MAP_DEPTH = normal_strength;
	}

	// Inner glow (crystalline kinds)
	if (inner_glow > 0.01) {
		float pulse = 1.0 + sin(TIME * pulse_rate * 6.28) * 0.15;
		EMISSION = base_col * inner_glow * pulse;
	}

	// Subsurface hint (organic kinds) — fake via emission on back-facing
	if (subsurface > 0.01) {
		EMISSION += base_col * subsurface * 0.15;
	}
}
