/* SPDX-License-Identifier: Apache-2.0 */
/* Bridge the newer APK query to the real Wonder capability command. */
#define _GNU_SOURCE
#include <android/binder_ibinder.h>
#include <android/binder_parcel.h>
#include <android/binder_status.h>
#include <android/log.h>
#include <dlfcn.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "wonder-cap-query.h"

typedef AIBinder_Class *(*define_fn)(const char *, AIBinder_Class_onCreate,
                                    AIBinder_Class_onDestroy, AIBinder_Class_onTransact);
static _Atomic(AIBinder_Class_onTransact) original_transaction;

static binder_status_t write_capability(AParcel *out, bool hopping)
{
    /* MoseyHardwareCapability carries a single protobuf bool field1. It does
     * not contain or change Android DBS, Wonder HBS, rate or aggregation bits.
     */
    const int8_t capability[] = {0x08, hopping ? 1 : 0};
    AStatus *ok = AStatus_newOk();
    if (!ok) return STATUS_NO_MEMORY;
    binder_status_t rc = AParcel_writeStatusHeader(out, ok);
    AStatus_delete(ok);
    if (rc != STATUS_OK) return rc;
    rc = AParcel_writeInt32(out, 1); /* Non-null typed object. */
    if (rc != STATUS_OK) return rc;
    int32_t start = AParcel_getDataPosition(out);
    if (start < 0) return STATUS_BAD_VALUE;
    rc = AParcel_writeInt32(out, 0); /* Stable parcelable size, filled below. */
    if (rc != STATUS_OK) return rc;
    rc = AParcel_writeByteArray(out, capability, sizeof(capability));
    if (rc != STATUS_OK) return rc;
    int32_t end = AParcel_getDataPosition(out);
    if (end < start) return STATUS_BAD_VALUE;
    rc = AParcel_setDataPosition(out, start);
    if (rc != STATUS_OK) return rc;
    rc = AParcel_writeInt32(out, end - start);
    if (rc != STATUS_OK) return rc;
    return AParcel_setDataPosition(out, end);
}

static binder_status_t transaction(AIBinder *binder, transaction_code_t code,
                                   const AParcel *in, AParcel *out)
{
    if (code == 4) {
        struct wonder_caps caps;
        int rc = query_wonder_caps(&caps);
        if (rc) {
            /* The APK already handles a failed query as unsupported. A query
             * failure must never become a successful capability assertion.
             */
            __android_log_print(ANDROID_LOG_WARN, "MoseyOnyx",
                                "Wonder capability query failed: %d", rc);
            return STATUS_FAILED_TRANSACTION;
        }
        /* This hook is restricted to the Onyx Wonder profile below. The
         * frozen driver supports shared traffic only on the STA home channel,
         * so do not advertise concurrent channel hopping to the controller.
         * It can use its normal Wi-Fi disconnect and restore policy. Native
         * config field5 separately enables software channel retuning and
         * remains unchanged in config.c.
         */
        __android_log_print(ANDROID_LOG_INFO, "MoseyOnyx",
                            "Wonder GET_CAP hopping=%d hbs=%d nss=%u max_switch_us=%u controller_hopping=0 (Onyx STA handoff profile)",
                            caps.hopping, caps.hbs, caps.nss, caps.max_switch_us);
        return write_capability(out, false);
    }
    AIBinder_Class_onTransact original =
        atomic_load_explicit(&original_transaction, memory_order_acquire);
    return original ? original(binder, code, in, out) : STATUS_UNKNOWN_TRANSACTION;
}

AIBinder_Class *AIBinder_Class_define(const char *descriptor,
    AIBinder_Class_onCreate create, AIBinder_Class_onDestroy destroy,
    AIBinder_Class_onTransact on_transact)
{
    define_fn real = (define_fn)dlsym(RTLD_NEXT, "AIBinder_Class_define");
    if (!real) return NULL;
    const char *enabled = getenv("KONOHA_MOSEY_WONDER");
    if (enabled && !strcmp(enabled, "1") && descriptor &&
        !strcmp(descriptor, "com.google.android.moseyservice.IMoseyService")) {
        AIBinder_Class_onTransact previous = NULL;
        if (!on_transact ||
            (!atomic_compare_exchange_strong_explicit(&original_transaction,
                &previous, on_transact, memory_order_release, memory_order_acquire) &&
             previous != on_transact)) return NULL;
        on_transact = transaction;
    }
    /* Interface version/hash and all existing calls retain the original
     * descriptor, lifetime handlers and transaction implementation.
     */
    return real(descriptor, create, destroy, on_transact);
}
