shader_type sky;

// Cavern sky — vertical gradient simulating trapped atmosphere.
// Dark ceiling, dark floor, faint luminous band at eye level.
// The cavern has no sky — this IS the void, shaped.

uniform vec3 horizon_color : source_color = vec3(0.08, 0.07, 0.09);
uniform vec3 void_color : source_color = vec3(0.02, 0.02, 0.03);
uniform float band_width : hint_range(0.01, 1.0) = 0.25;
uniform float band_sharpness : hint_range(1.0, 10.0) = 3.0;

void sky() {
	// EYEDIR.y: +1 = straight up (ceiling), -1 = straight down (floor), 0 = horizon
	float horizon_dist = abs(EYEDIR.y);

	// Smooth falloff from horizon toward ceiling/floor
	// band_width controls how wide the luminous band is
	// band_sharpness controls how quickly it falls off
	float band = 1.0 - pow(smoothstep(0.0, band_width, horizon_dist), 1.0 / band_sharpness);

	COLOR = mix(void_color, horizon_color, band);
}
