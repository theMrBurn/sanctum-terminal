#pragma once
typedef struct NotificationApp NotificationApp;
typedef struct { const char* name; } NotificationSequence;
extern const NotificationSequence sequence_success, sequence_single_vibro, sequence_error;
void notification_message(NotificationApp* app, const NotificationSequence* seq);
