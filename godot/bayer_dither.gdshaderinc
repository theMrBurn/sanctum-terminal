// bayer_dither.gdshaderinc
//
// Fixed 4x4 Bayer matrix, screen-space alpha threshold. Cheaper than alpha
// blending — produces the "checkerboard" transparency look of 90s hardware,
// which fits the terminal aesthetic. Reusable across any transparent
// material (flow, haze, future smoke/spore primitives).
//
// Usage:
//   #include "res://bayer_dither.gdshaderinc"
//   ...
//   ALPHA = bayer_dither_alpha(FRAGCOORD.xy, raw_alpha);
//
// Discards the fragment when raw_alpha falls below the threshold. The 16
// thresholds are spaced so smooth gradients dither cleanly without banding.

const float BAYER_4x4[16] = float[16](
	 0.0 / 16.0,  8.0 / 16.0,  2.0 / 16.0, 10.0 / 16.0,
	12.0 / 16.0,  4.0 / 16.0, 14.0 / 16.0,  6.0 / 16.0,
	 3.0 / 16.0, 11.0 / 16.0,  1.0 / 16.0,  9.0 / 16.0,
	15.0 / 16.0,  7.0 / 16.0, 13.0 / 16.0,  5.0 / 16.0
);


float bayer_threshold(vec2 frag_coord) {
	int x = int(mod(frag_coord.x, 4.0));
	int y = int(mod(frag_coord.y, 4.0));
	return BAYER_4x4[y * 4 + x];
}


// Returns 1.0 if the fragment passes, 0.0 otherwise. Pair with
// render_mode blend_mix + a discard or with ALPHA_SCISSOR_THRESHOLD.
float bayer_dither_alpha(vec2 frag_coord, float alpha) {
	return alpha > bayer_threshold(frag_coord) ? 1.0 : 0.0;
}
