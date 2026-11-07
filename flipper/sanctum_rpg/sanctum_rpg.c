
/* sanctum_rpg.c — the Flipper shell: the app entry, the button queue, the
 * view port, the records, and the device side of platform.h. The rules are
 * game.c; the screens, screens.c. */

#include <stdarg.h>
#include <string.h>
#include <furi.h>
#include <furi_hal_random.h>
#include <furi_hal_rtc.h>
#include <datetime/datetime.h>
#include <gui/gui.h>
#include <input/input.h>
#include <notification/notification_messages.h>
#include <storage/storage.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>

#include "game.h"
#include "screens.h"

/* ─── the Flipper shell's side of platform.h ─────────────────────── */

static NotificationApp* shell_notif;  /* haptic/LED/sound feedback (v0.3.5d) */
static ViewPort* shell_view_port;     /* the Forge's mid-press frames */

uint64_t platform_now_unix(void) {
    DateTime now;
    furi_hal_rtc_get_datetime(&now);
    return datetime_datetime_to_timestamp(&now);
}

uint32_t platform_random(void) {
    return furi_hal_random_get();
}

void platform_note(GameNote note) {
    if(!shell_notif) return;
    const NotificationSequence* seq = note == GameNoteSuccess ? &sequence_success
                                    : note == GameNoteVibro   ? &sequence_single_vibro
                                                              : &sequence_error;
    notification_message(shell_notif, seq);
}

void platform_present_frame(uint32_t hold_ms) {
    if(shell_view_port) view_port_update(shell_view_port);
    furi_delay_ms(hold_ms);
}

#define INPUT_QUEUE_DEPTH     8

/* ─── input plumbing ──────────────────────────────────────────────── */

static void title_input(InputEvent* event, void* ctx) {
    FuriMessageQueue* queue = ctx;
    furi_message_queue_put(queue, event, FuriWaitForever);
}

/* The Flipper's buttons as the game's keys. */
static void shell_map_event(const InputEvent* e, GameKey* key, GamePress* type) {
    switch(e->key) {
    case InputKeyUp:    *key = GameKeyUp; break;
    case InputKeyDown:  *key = GameKeyDown; break;
    case InputKeyRight: *key = GameKeyRight; break;
    case InputKeyLeft:  *key = GameKeyLeft; break;
    case InputKeyOk:    *key = GameKeyOk; break;
    case InputKeyBack:  *key = GameKeyBack; break;
    default:            *key = GameKeyNone; break;
    }
    *type = e->type == InputTypeShort    ? GamePressShort
          : e->type == InputTypeLong     ? GamePressLong
          : e->type == InputTypeRepeat   ? GamePressRepeat
                                         : GamePressOther;
}

int32_t sanctum_rpg_app(void* p) {
    UNUSED(p);

    AppState state;
    game_open(&state);

    FuriMessageQueue* input_queue =
        furi_message_queue_alloc(INPUT_QUEUE_DEPTH, sizeof(InputEvent));
    if(!input_queue) {
        return -1;
    }

    ViewPort* view_port = view_port_alloc();
    view_port_draw_callback_set(view_port, screens_draw, &state);
    view_port_input_callback_set(view_port, title_input, input_queue);

    Gui* gui = furi_record_open(RECORD_GUI);
    gui_add_view_port(gui, view_port, GuiLayerFullscreen);
    shell_view_port = view_port; /* Thread B — for in-handler animation */
    shell_notif = furi_record_open(RECORD_NOTIFICATION);

    bool running = true;
    InputEvent event;
    while(running) {
        FuriStatus s =
            furi_message_queue_get(input_queue, &event, FuriWaitForever);
        if(s != FuriStatusOk) continue;
        GameKey key;
        GamePress type;
        shell_map_event(&event, &key, &type);
        GameStep step = game_input(&state, key, type);
        if(step == GameIgnored) continue;
        view_port_update(view_port);
        if(step == GameQuit) running = false;
    }

    shell_view_port = NULL;
    shell_notif = NULL;
    gui_remove_view_port(gui, view_port);
    furi_record_close(RECORD_GUI);
    furi_record_close(RECORD_NOTIFICATION);
    view_port_free(view_port);
    furi_message_queue_free(input_queue);

    return 0;
}
