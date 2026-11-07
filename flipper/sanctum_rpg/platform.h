/* platform.h — what the game asks of the machine it runs on.
 *
 * The game's rules (the turn loop, combat, the screens' state) call only
 * these, never the Flipper SDK, so the same code runs on the device and on
 * the Mac. Each shell implements them: sanctum_rpg.c for the Flipper (the
 * RTC, furi_hal_random, the notification record, the view port).
 */
#pragma once

#include <stdint.h>

/* A feedback cue: haptic, LED or sound, as the platform can. */
typedef enum {
    GameNoteSuccess, /* a find, a sale, a kill */
    GameNoteVibro,   /* a warning: a dimmed torch, a hit taken */
    GameNoteError,   /* a failure: torch out, can't afford */
} GameNote;

/* The local wall clock, in Unix seconds. The sky, the weather and the
 * day streak read it; it is an input, like a key. */
uint64_t platform_now_unix(void);

/* A fresh random word (the new campaign's seed). */
uint32_t platform_random(void);

/* Play a cue. The game has already applied the player's mute setting. */
void platform_note(GameNote note);

/* Show the current state now, mid-handler, and hold it for `hold_ms`
 * (the Forge's reel animation draws frames inside one key press). */
void platform_present_frame(uint32_t hold_ms);
