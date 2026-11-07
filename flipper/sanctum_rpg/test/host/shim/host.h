/* Host stand-in for the Flipper SDK, for the app itself (test/host/):
 * sanctum_rpg.c, save_io.c and deltas.c build on the Mac against these
 * headers, unchanged, and run from a script (host_main.c). Everything the
 * device gets from outside is an input here: the clock, the random source,
 * the buttons, and the SD card (a folder). */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

extern uint64_t host_clock_unix;          /* local time the RTC reports */
extern uint32_t host_random_state;
extern const char* host_root;             /* the folder standing in for /ext */
void host_note(const char* what);         /* a notification, a draw: into the trace */
