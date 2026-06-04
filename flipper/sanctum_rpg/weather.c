/*
 * weather.c — see weather.h. Atmospheric procgen layer.
 */

#include "weather.h"

#include <stddef.h>

/* The biome ids are stamp-side constants, repeated here so weather.c
 * stays free of the stamps.h include — only the integer comparison
 * matters for indoor attenuation. */
#define WEATHER_BIOME_CAVERN  0u
#define WEATHER_BIOME_OUTDOOR 1u
#define WEATHER_BIOME_ARID    2u /* future biome (Thread A.1); declared here so the
                                  * temperature gradient is ready when it ships */

BiomeTemperature biome_temperature(uint8_t biome) {
    switch(biome) {
    case WEATHER_BIOME_CAVERN:  return BIOME_TEMP_COOL;
    case WEATHER_BIOME_ARID:    return BIOME_TEMP_HOT;
    case WEATHER_BIOME_OUTDOOR:
    default:                    return BIOME_TEMP_TEMPERATE;
    }
}

/* ─── Integer hash (FNV-1a-flavored). Byte-equal port target. ───────── */

static uint32_t weather_hash32(uint32_t a, uint32_t b, uint32_t c, uint32_t d) {
    uint32_t h = 0x811C9DC5u;
    /* Mix four 32-bit inputs as 16 bytes. */
    uint32_t vs[4] = {a, b, c, d};
    for(int i = 0; i < 4; i++) {
        uint32_t v = vs[i];
        h ^= (v >>  0) & 0xFFu; h *= 16777619u;
        h ^= (v >>  8) & 0xFFu; h *= 16777619u;
        h ^= (v >> 16) & 0xFFu; h *= 16777619u;
        h ^= (v >> 24) & 0xFFu; h *= 16777619u;
    }
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    return h;
}

void weather_at(uint32_t campaign_seed, int chunk_x, int chunk_y,
                uint32_t day, uint8_t biome, Weather* out) {
    if(!out) return;

    uint32_t h = weather_hash32(
        campaign_seed, (uint32_t)chunk_x, (uint32_t)chunk_y, day);

    /* Temperature-aware kind distribution. Each temperature band has its
     * own cumulative thresholds over [0, 100). Hot biomes shift heavily
     * toward HEAT + DUST_STORM; cool/temperate keep the rain/fog mix.
     *
     * Outdoor (temperate) still gets HEAT occasionally (summer days) and
     * very rarely DUST_STORM. This is enough atmosphere ahead of a hot
     * biome arriving — when ARID lands, its thresholds amplify. */
    BiomeTemperature temp = biome_temperature(biome);
    uint32_t kind_roll = h % 100u;
    uint8_t kind;
    switch(temp) {
    case BIOME_TEMP_HOT:
        /* CLEAR 30 | HEAT 35 | DUST_STORM 15 | FOG 10 | RAIN 8 | STORM 2 */
        if(kind_roll <  30u)       kind = WEATHER_CLEAR;
        else if(kind_roll <  65u)  kind = WEATHER_HEAT;
        else if(kind_roll <  80u)  kind = WEATHER_DUST_STORM;
        else if(kind_roll <  90u)  kind = WEATHER_FOG;
        else if(kind_roll <  98u)  kind = WEATHER_RAIN;
        else                        kind = WEATHER_STORM;
        break;
    case BIOME_TEMP_COOL:
        /* CLEAR 45 | FOG 30 | RAIN 15 | STORM 10 | (no heat/dust) */
        if(kind_roll <  45u)       kind = WEATHER_CLEAR;
        else if(kind_roll <  75u)  kind = WEATHER_FOG;
        else if(kind_roll <  90u)  kind = WEATHER_RAIN;
        else                        kind = WEATHER_STORM;
        break;
    case BIOME_TEMP_TEMPERATE:
    default:
        /* CLEAR 45 | FOG 20 | RAIN 18 | STORM 8 | HEAT 7 | DUST_STORM 2 */
        if(kind_roll <  45u)       kind = WEATHER_CLEAR;
        else if(kind_roll <  65u)  kind = WEATHER_FOG;
        else if(kind_roll <  83u)  kind = WEATHER_RAIN;
        else if(kind_roll <  91u)  kind = WEATHER_STORM;
        else if(kind_roll <  98u)  kind = WEATHER_HEAT;
        else                        kind = WEATHER_DUST_STORM;
        break;
    }

    /* Intensity drawn from the upper bits — uncorrelated with kind. */
    uint8_t intensity = (uint8_t)((h >> 16) % 100u);

    /* Indoor attenuation — cavern dampens. The dampening preserves the
     * KIND so the player still hears the "rain above" framing, but the
     * mechanical effect is halved. CLEAR stays CLEAR (cavern weather is
     * just "still air"). */
    uint8_t indoor = (biome == WEATHER_BIOME_CAVERN) ? 1u : 0u;
    if(indoor) intensity = (uint8_t)(intensity / 2u);

    /* Derived effects. */
    uint8_t fov_cap_delta = 0;
    uint8_t fuel_burn_extra = 0;
    switch(kind) {
    case WEATHER_FOG:
        fov_cap_delta = (uint8_t)(intensity / 35u); /* ~0..2 cells */
        break;
    case WEATHER_RAIN:
        fuel_burn_extra = (intensity > 50u) ? 1u : 0u; /* heavy rain only */
        break;
    case WEATHER_STORM:
        fov_cap_delta = (uint8_t)((intensity / 30u) + 1u); /* ~1..4 cells */
        fuel_burn_extra = (intensity > 60u) ? 2u : 1u;
        break;
    case WEATHER_HEAT:
        /* The heat wastes the torch — flame fights the dry air. No FOV cap
         * (you can see fine in heat); the mirage is a separate visual gag
         * applied per-tile in the renderer. */
        fuel_burn_extra = (intensity > 40u) ? 1u : 0u;
        if(intensity > 80u) fuel_burn_extra = 2u; /* searing day */
        break;
    case WEATHER_DUST_STORM:
        /* Heavier than a rain storm — sand cuts vision dramatically. */
        fov_cap_delta = (uint8_t)((intensity / 25u) + 1u); /* ~1..5 cells */
        fuel_burn_extra = (intensity > 50u) ? 2u : 1u;
        break;
    case WEATHER_CLEAR:
    default:
        break;
    }

    out->kind = kind;
    out->intensity = intensity;
    out->indoor_attenuated = indoor;
    out->fov_cap_delta = fov_cap_delta;
    out->fuel_burn_extra = fuel_burn_extra;
    out->pedigree = h;
}

int weather_tile_has_overlay(const Weather* w, uint32_t turn, int x, int y) {
    if(!w) return 0;
    if(w->kind == WEATHER_CLEAR || w->kind == WEATHER_FOG) return 0;
    /* Density: rain ~15% / storm ~30% / heat ~8% (light shimmer) /
     * dust storm ~35% (dense). Halved indoors. */
    uint32_t density_threshold;
    switch(w->kind) {
    case WEATHER_RAIN:        density_threshold = 15u; break;
    case WEATHER_STORM:       density_threshold = 30u; break;
    case WEATHER_HEAT:        density_threshold =  8u; break;
    case WEATHER_DUST_STORM:  density_threshold = 35u; break;
    default:                  return 0;
    }
    if(w->indoor_attenuated) density_threshold /= 2u;
    uint32_t h = weather_hash32(
        w->pedigree, turn, (uint32_t)x, (uint32_t)y);
    return (h % 100u) < density_threshold;
}

const char* weather_enter_hint(const Weather* w) {
    if(!w) return NULL;
    if(w->kind == WEATHER_CLEAR) return NULL;
    if(w->indoor_attenuated) {
        switch(w->kind) {
        case WEATHER_FOG:        return "cave-fog hangs low";
        case WEATHER_RAIN:       return "rain murmurs above";
        case WEATHER_STORM:      return "the storm reaches you here";
        case WEATHER_HEAT:       return "the stone holds the day's heat";
        case WEATHER_DUST_STORM: return "dust drifts in from outside";
        default: return NULL;
        }
    } else {
        switch(w->kind) {
        case WEATHER_FOG:        return "fog rolls in";
        case WEATHER_RAIN:       return "the rain begins";
        case WEATHER_STORM:      return "wind kicks up";
        case WEATHER_HEAT:       return "the air shimmers";
        case WEATHER_DUST_STORM: return "the dust comes";
        default: return NULL;
        }
    }
}

int weather_apply_fov(const Weather* w, int base_radius) {
    if(!w) return base_radius;
    int r = base_radius - (int)w->fov_cap_delta;
    if(r < 1) r = 1; /* never blind the player completely */
    return r;
}
