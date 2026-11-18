/* Minimal API surface used by the actual capability bridge. */
#ifndef FIXTURE_ANDROID_BINDER_IBINDER_H
#define FIXTURE_ANDROID_BINDER_IBINDER_H
#include <android/binder_parcel.h>
typedef struct AIBinder AIBinder;
typedef struct AIBinder_Class AIBinder_Class;
typedef uint32_t transaction_code_t;
typedef void *(*AIBinder_Class_onCreate)(void *args);
typedef void (*AIBinder_Class_onDestroy)(void *user_data);
typedef binder_status_t (*AIBinder_Class_onTransact)(AIBinder *binder,
    transaction_code_t code, const AParcel *in, AParcel *out);
AIBinder_Class *AIBinder_Class_define(const char *descriptor,
    AIBinder_Class_onCreate create, AIBinder_Class_onDestroy destroy,
    AIBinder_Class_onTransact on_transact);
#endif
