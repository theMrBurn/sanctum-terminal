#pragma once
#include "host.h"
#include <gui/canvas.h>
#include <input/input.h>

typedef struct ViewPort ViewPort;
typedef struct Gui Gui;
typedef enum { GuiLayerDesktop, GuiLayerWindow, GuiLayerStatusBarLeft, GuiLayerStatusBarRight,
               GuiLayerFullscreen, GuiLayerMAX } GuiLayer;
typedef void (*ViewPortDrawCallback)(Canvas* canvas, void* context);
typedef void (*ViewPortInputCallback)(InputEvent* event, void* context);

ViewPort* view_port_alloc(void);
void view_port_free(ViewPort* vp);
void view_port_draw_callback_set(ViewPort* vp, ViewPortDrawCallback cb, void* ctx);
void view_port_input_callback_set(ViewPort* vp, ViewPortInputCallback cb, void* ctx);
void view_port_update(ViewPort* vp);   /* host: draws now, then the trace step */
void gui_add_view_port(Gui* gui, ViewPort* vp, GuiLayer layer);
void gui_remove_view_port(Gui* gui, ViewPort* vp);
