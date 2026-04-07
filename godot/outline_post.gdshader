shader_type canvas_item;

// Screen-space outlines — minimal diagnostic version.
// Luminance Sobel only. Fixed 1px offsets. No depth/normal.

uniform sampler2D screen_texture : hint_screen_texture, filter_nearest;
uniform float edge_threshold : hint_range(0.0, 0.5) = 0.05;
uniform vec3 line_color : source_color = vec3(0.9, 0.85, 0.75);
uniform float line_opacity : hint_range(0.0, 1.0) = 0.9;

// keep uniforms so config doesn't error — just unused for now
uniform sampler2D depth_texture : hint_depth_texture, filter_nearest;
uniform sampler2D normal_texture : hint_normal_roughness_texture, filter_nearest;
uniform int outline_mode = 1;
uniform float outline_thickness = 2.0;
uniform float gap_frequency = 14.0;
uniform float gap_width = 0.35;
uniform float depth_weight = 1.0;
uniform float normal_weight = 1.0;
uniform float lum_weight = 0.3;

float lum(vec3 c) {
	return dot(c, vec3(0.299, 0.587, 0.114));
}

void fragment() {
	vec2 uv = SCREEN_UV;
	vec2 ps = SCREEN_PIXEL_SIZE * 1.5;  // fixed small offset

	// Sample luminance in 3x3 grid
	float tl = lum(texture(screen_texture, uv + vec2(-ps.x, -ps.y)).rgb);
	float tc = lum(texture(screen_texture, uv + vec2(0.0, -ps.y)).rgb);
	float tr = lum(texture(screen_texture, uv + vec2(ps.x, -ps.y)).rgb);
	float ml = lum(texture(screen_texture, uv + vec2(-ps.x, 0.0)).rgb);
	float mr = lum(texture(screen_texture, uv + vec2(ps.x, 0.0)).rgb);
	float bl = lum(texture(screen_texture, uv + vec2(-ps.x, ps.y)).rgb);
	float bc = lum(texture(screen_texture, uv + vec2(0.0, ps.y)).rgb);
	float br = lum(texture(screen_texture, uv + vec2(ps.x, ps.y)).rgb);

	// Sobel
	float gx = -tl - 2.0*ml - bl + tr + 2.0*mr + br;
	float gy = -tl - 2.0*tc - tr + bl + 2.0*bc + br;
	float edge = sqrt(gx*gx + gy*gy);

	// Binary edge
	float line = step(edge_threshold, edge);

	vec3 screen = texture(screen_texture, uv).rgb;
	COLOR = vec4(mix(screen, line_color, line * line_opacity), 1.0);
}
