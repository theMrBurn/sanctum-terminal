/* screens.h — the view port's draw callback: the current screen of the
 * game state `ctx` (an AppState*), drawn on `canvas`. */
#pragma once

#include <gui/canvas.h>

#include "game.h"

void screens_draw(Canvas* canvas, void* ctx);
