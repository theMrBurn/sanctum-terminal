/*
 * weather.h — deterministic atmospheric procgen layer.
 *
 * Sibling to the Pool (spec 50). Where the Pool drifts vocabulary/content
 * AS YOU WALK, weather drifts WITH TIME — derived from
 * (campaign_seed × chunk_xy × day-of-epoch). Same inputs → byte-equal
 * weather. The day advances; the weather pattern rolls forward.
 *
 * Biome-aware: outdoor chunks get the full effect; cavern chunks get an
 * attenuated version (distant rumble, dripping pools, cave fog). The
 * "you hear rain above" framing — even underground, weather exists.
 *
 * Pure module — integer math, no SDK deps, host-testable.
 *
 * Consumers (in sanctum_rpg.c, world.c):
 *   - draw_world_screen overlays rain/storm visual on lit cells
 *   - recompute_visibility caps FOV radius under fog/storm
 *   - do_transition emits chunk-enter status hint
 *   - advance_turn applies weather-modified fuel burn
 */

#pragma once

#include <stdint.h>

typedef enum {
    WEATHER_CLEAR      = 0, /* no effect, no overlay */
    WEATHER_FOG        = 1, /* FOV cap; no visual overlay (dimming IS the effect) */
    WEATHER_RAIN       = 2, /* visual overlay; mild fuel burn */
    WEATHER_STORM      = 3, /* heavy overlay + FOV cap + fuel burn */
    WEATHER_HEAT       = 4, /* fuel burn from heat; mirage = false-positive lit cells */
    WEATHER_DUST_STORM = 5, /* heavy FOV cap + dust overlay + fuel burn */
} WeatherKind;

/* Biome temperature gradient — biases the weather kind distribution.
 * COOL biomes (cavern) get rain/fog more; HOT biomes (future ARID) get
 * heat/dust storm more. Temperate (outdoor) gets a mix. */
typedef enum {
    BIOME_TEMP_COOL      = 0,
    BIOME_TEMP_TEMPERATE = 1,
    BIOME_TEMP_HOT       = 2,
} BiomeTemperature;

/* Map a biome ID (stamps.h's STAMP_BIOME_*) to temperature. Future biomes
 * declared in stamps.h get a row here. */
BiomeTemperature biome_temperature(uint8_t biome);

typedef struct {
    uint8_t  kind;                /* WeatherKind */
    uint8_t  intensity;           /* 0..100; biome-attenuated values are post-attenuation */
    uint8_t  indoor_attenuated;   /* 1 if biome is cavern; halves effects, changes copy */
    uint8_t  fov_cap_delta;       /* subtract this from base FOV radius (0..N) */
    uint8_t  fuel_burn_extra;     /* additional fuel per turn (0..3) */
    uint32_t pedigree;            /* hash-of-inputs identity */
} Weather;

/* Compute the weather at a chunk on a given day. Deterministic per
 * (campaign_seed × chunk_x × chunk_y × day) — same inputs → byte-equal Weather.
 * `day` is "days since epoch" (typically furi_hal_rtc / 86400; v1 uses the
 * same day across all calls within an in-game session).
 *
 * `biome` controls indoor attenuation — pass STAMP_BIOME_CAVERN for
 * indoor (dampened effects, "you hear rain above" copy), STAMP_BIOME_OUTDOOR
 * for full effects. */
void weather_at(uint32_t campaign_seed, int chunk_x, int chunk_y,
                uint32_t day, uint8_t biome, Weather* out);

/* Returns true if a tile (lit) should render a rain-overlay glyph this
 * turn. Deterministic per (turn × x × y × weather.pedigree). Used by
 * draw_world_screen during the lit pass.
 *
 * For RAIN: ~15% of tiles per frame.
 * For STORM: ~30% of tiles per frame.
 * For CLEAR/FOG: returns false. */
int weather_tile_has_overlay(const Weather* w, uint32_t turn, int x, int y);

/* The status-line hint emitted on chunk-enter under a given weather.
 * Returns NULL if the weather doesn't warrant a chunk-enter message. */
const char* weather_enter_hint(const Weather* w);

/* Convenience: weather effects collapsed into a single applied-FOV radius.
 * Pass the base radius; returns the weather-modified radius. */
int weather_apply_fov(const Weather* w, int base_radius);

/* Persistent 1-character HUD indicator for the current weather. Returns
 * '\0' if no indicator should be shown (CLEAR — silence reads as clear
 * by absence). Same glyph indoor and outdoor; biome context tells the
 * player whether they're hearing it from above or feeling it locally.
 *
 *   FOG  -> ~   RAIN -> '   STORM -> *   HEAT -> ^   DUST_STORM -> _ */
char weather_hud_glyph(const Weather* w);
