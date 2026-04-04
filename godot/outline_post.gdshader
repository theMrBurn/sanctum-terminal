shader_type canvas_item;

// Screen-space outlines — depth + normal + luminance edge detection.
// Works in dark scenes where luminance-only Sobel fails.
// 0=Moebius (gapped, directional), 1=Manga (hard), 2=Sable (gapped + grain)

uniform sampler2D screen_texture : hint_screen_texture, filter_nearest;
uniform sampler2D depth_texture : hint_depth_texture, filter_nearest;
uniform sampler2D normal_texture : hint_normal_roughness_texture, filter_nearest;
uniform int outline_mode = 2;
uniform float outline_thickness : hint_range(0.5, 5.0) = 2.0;
uniform float edge_threshold : hint_range(0.0, 0.5) = 0.03;
uniform vec3 line_color : source_color = vec3(1.0, 1.0, 1.0);
uniform float line_opacity : hint_range(0.0, 1.0) = 0.9;
uniform float gap_frequency = 14.0;
uniform float gap_width : hint_range(0.0, 1.0) = 0.35;
uniform float depth_weight = 1.0;
uniform float normal_weight = 0.8;
uniform float lum_weight = 0.4;

float lum(vec3 c) {
	return dot(c, vec3(0.299, 0.587, 0.114));
}

float sample_depth(vec2 uv) {
	return texture(depth_texture, uv).r;
}

vec3 sample_normal(vec2 uv) {
	return texture(normal_texture, uv).rgb * 2.0 - 1.0;
}

void fragment() {
	vec2 ps = SCREEN_PIXEL_SIZE * outline_thickness;
	vec2 uv = SCREEN_UV;

	// 3x3 samples: luminance, depth, normal
	vec2 offsets[8] = {
		vec2(-ps.x, -ps.y), vec2(0, -ps.y), vec2(ps.x, -ps.y),
		vec2(-ps.x, 0),                      vec2(ps.x, 0),
		vec2(-ps.x, ps.y),  vec2(0, ps.y),   vec2(ps.x, ps.y)
	};

	// Center samples
	float center_depth = sample_depth(uv);
	vec3 center_normal = sample_normal(uv);
	float center_lum = lum(texture(screen_texture, uv).rgb);

	// Sobel on luminance
	float l[8];
	for (int i = 0; i < 8; i++) {
		l[i] = lum(texture(screen_texture, uv + offsets[i]).rgb);
	}
	float gx_l = -l[0] - 2.0*l[3] - l[5] + l[2] + 2.0*l[4] + l[7];
	float gy_l = -l[0] - 2.0*l[1] - l[2] + l[5] + 2.0*l[6] + l[7];
	float sobel_lum = sqrt(gx_l*gx_l + gy_l*gy_l);

	// Sobel on depth
	float d[8];
	for (int i = 0; i < 8; i++) {
		d[i] = sample_depth(uv + offsets[i]);
	}
	float gx_d = -d[0] - 2.0*d[3] - d[5] + d[2] + 2.0*d[4] + d[7];
	float gy_d = -d[0] - 2.0*d[1] - d[2] + d[5] + 2.0*d[6] + d[7];
	float sobel_depth = sqrt(gx_d*gx_d + gy_d*gy_d);
	// Scale depth edges — raw depth values are 0-1 nonlinear, amplify
	sobel_depth *= 50.0;

	// Normal discontinuity — dot product difference from center
	float normal_diff = 0.0;
	for (int i = 0; i < 8; i++) {
		vec3 n = sample_normal(uv + offsets[i]);
		normal_diff += 1.0 - max(dot(center_normal, n), 0.0);
	}
	normal_diff /= 8.0;
	// Amplify normal edges
	float sobel_normal = normal_diff * 4.0;

	// Combine all three edge sources
	float combined = sobel_lum * lum_weight + sobel_depth * depth_weight + sobel_normal * normal_weight;

	float edge = 0.0;
	vec3 screen = texture(screen_texture, uv).rgb;

	if (outline_mode == 0) {
		// MOEBIUS — directional gaps, pen-stroke feel
		edge = smoothstep(edge_threshold * 0.5, edge_threshold * 1.5, combined);
		float dir = abs(sin(atan(gy_l, gx_l) * 2.0));
		edge *= mix(0.5, 1.0, dir);
	} else if (outline_mode == 1) {
		// MANGA — hard binary edges
		edge = step(edge_threshold, combined);
	} else {
		// SABLE — gapped lines with grain noise
		float raw = step(edge_threshold * 0.7, combined);
		float line_p = (uv.x + uv.y * 0.618) / SCREEN_PIXEL_SIZE.x * 0.12;
		float gap = smoothstep(gap_width, gap_width + 0.15, abs(sin(line_p * gap_frequency)));
		edge = raw * gap;
		edge *= mix(0.6, 1.0, fract(sin(dot(floor(uv / SCREEN_PIXEL_SIZE * 0.5), vec2(12.9898, 78.233))) * 43758.5));
	}

	COLOR = vec4(mix(screen, line_color, edge * line_opacity), 1.0);
}
