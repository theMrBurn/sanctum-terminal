shader_type spatial;
render_mode unshaded;

// Screen-space edge detection outline.
// Reads depth + normal buffers, draws thin dark lines at silhouettes and creases.
// Apply to a full-screen quad via a MeshInstance3D in front of camera.
//
// Dark Souls / Okami restraint: thin lines, not thick comic borders.

uniform sampler2D depth_texture : hint_depth_texture;
uniform sampler2D normal_roughness_texture : hint_normal_roughness_texture;
uniform float outline_thickness : hint_range(0.5, 3.0) = 1.0;
uniform float depth_threshold : hint_range(0.0, 0.1) = 0.002;
uniform float normal_threshold : hint_range(0.0, 2.0) = 0.4;
uniform vec4 outline_color : source_color = vec4(0.0, 0.0, 0.0, 0.6);

void fragment() {
	vec2 pixel_size = vec2(1.0) / VIEWPORT_SIZE;
	vec2 uv = SCREEN_UV;

	// Sample depth at center and 4 neighbors
	float d_c = texture(depth_texture, uv).r;
	float d_l = texture(depth_texture, uv + vec2(-pixel_size.x, 0.0) * outline_thickness).r;
	float d_r = texture(depth_texture, uv + vec2(pixel_size.x, 0.0) * outline_thickness).r;
	float d_u = texture(depth_texture, uv + vec2(0.0, -pixel_size.y) * outline_thickness).r;
	float d_d = texture(depth_texture, uv + vec2(0.0, pixel_size.y) * outline_thickness).r;

	// Depth edge: Sobel-like
	float depth_diff = abs(d_l - d_r) + abs(d_u - d_d);
	float depth_edge = step(depth_threshold, depth_diff);

	// Sample normals at center and neighbors
	vec3 n_c = texture(normal_roughness_texture, uv).rgb * 2.0 - 1.0;
	vec3 n_l = texture(normal_roughness_texture, uv + vec2(-pixel_size.x, 0.0) * outline_thickness).rgb * 2.0 - 1.0;
	vec3 n_r = texture(normal_roughness_texture, uv + vec2(pixel_size.x, 0.0) * outline_thickness).rgb * 2.0 - 1.0;
	vec3 n_u = texture(normal_roughness_texture, uv + vec2(0.0, -pixel_size.y) * outline_thickness).rgb * 2.0 - 1.0;
	vec3 n_d = texture(normal_roughness_texture, uv + vec2(0.0, pixel_size.y) * outline_thickness).rgb * 2.0 - 1.0;

	// Normal edge: difference in normal directions
	float normal_diff = length(n_l - n_r) + length(n_u - n_d);
	float normal_edge = step(normal_threshold, normal_diff);

	// Combined edge
	float edge = max(depth_edge, normal_edge);

	// Output: transparent where no edge, dark where edge
	ALBEDO = outline_color.rgb;
	ALPHA = edge * outline_color.a;
}
