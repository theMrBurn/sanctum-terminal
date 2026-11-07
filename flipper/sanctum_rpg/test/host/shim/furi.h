#pragma once
#include "host.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <input/input.h>

#define UNUSED(x) (void)(x)
#define RECORD_STORAGE "storage"
#define RECORD_GUI "gui"
#define RECORD_NOTIFICATION "notification"
#define FuriWaitForever 0xFFFFFFFFu

typedef enum { FuriStatusOk = 0, FuriStatusError = -1 } FuriStatus;
typedef struct FuriMessageQueue FuriMessageQueue;

void* furi_record_open(const char* name);
void furi_record_close(const char* name);
FuriMessageQueue* furi_message_queue_alloc(uint32_t count, uint32_t size);
void furi_message_queue_free(FuriMessageQueue* q);
FuriStatus furi_message_queue_put(FuriMessageQueue* q, const void* msg, uint32_t timeout);
FuriStatus furi_message_queue_get(FuriMessageQueue* q, void* msg, uint32_t timeout);
void furi_delay_ms(uint32_t ms);
