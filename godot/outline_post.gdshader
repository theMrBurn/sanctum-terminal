shader_type canvas_item;

// Screen-space outlines — luminance Sobel edge detection.
// 0=Moebius, 1=Manga, 2=Sable

uniform sampler2D screen_texture : hint_screen_texture, filter_nearest;
uniform int outline_mode = 2;
uniform float outline_thickness : hint_range(0.5, 5.0) = 2.0;
uniform float edge_threshold : hint_range(0.0, 0.5) = 0.03;
uniform vec3 line_color : source_color = vec3(1.0, 1.0, 1.0);
uniform float line_opacity : hint_range(0.0, 1.0) = 0.9;
uniform float gap_frequency = 14.0;
uniform float gap_width : hint_range(0.0, 1.0) = 0.35;

float lum(vec3 c) {
	return dot(c, vec3(0.299, 0.587, 0.114));
}

void fragment() {
	vec2 ps = SCREEN_PIXEL_SIZE * outline_thickness;
	vec2 uv = SCREEN_UV;

	// 3x3 luminance samples
	float tl = lum(texture(screen_texture, uv + vec2(-ps.x, -ps.y)).rgb);
	float tc = lum(texture(screen_texture, uv + vec2(0, -ps.y)).rgb);
	float tr = lum(texture(screen_texture, uv + vec2(ps.x, -ps.y)).rgb);
	float ml = lum(texture(screen_texture, uv + vec2(-ps.x, 0)).rgb);
	float mr = lum(texture(screen_texture, uv + vec2(ps.x, 0)).rgb);
	float bl = lum(texture(screen_texture, uv + vec2(-ps.x, ps.y)).rgb);
	float bc = lum(texture(screen_texture, uv + vec2(0, ps.y)).rgb);
	float br = lum(texture(screen_texture, uv + vec2(ps.x, ps.y)).rgb);

	float gx = -tl - 2.0*ml - bl + tr + 2.0*mr + br;
	float gy = -tl - 2.0*tc - tr + bl + 2.0*bc + br;
	float sobel = sqrt(gx*gx + gy*gy);

	float edge = 0.0;
	vec3 screen = texture(screen_texture, uv).rgb;

	if (outline_mode == 0) {
		// MOEBIUS
		edge = smoothstep(edge_threshold * 0.5, edge_threshold * 1.5, sobel);
		float dir = abs(sin(atan(gy, gx) * 2.0));
		edge *= mix(0.5, 1.0, dir);
	} else if (outline_mode == 1) {
		// MANGA
		edge = step(edge_threshold, sobel);
	} else {
		// SABLE
		float raw = step(edge_threshold * 0.7, sobel);
		float line_p = (uv.x + uv.y * 0.618) / SCREEN_PIXEL_SIZE.x * 0.12;
		float gap = smoothstep(gap_width, gap_width + 0.15, abs(sin(line_p * gap_frequency)));
		edge = raw * gap;
		edge *= mix(0.6, 1.0, fract(sin(dot(floor(uv / SCREEN_PIXEL_SIZE * 0.5), vec2(12.9898, 78.233))) * 43758.5));
	}

	// WHITE lines on dark scene — high visibility for testing
	COLOR = vec4(mix(screen, line_color, edge * line_opacity), 1.0);
}
