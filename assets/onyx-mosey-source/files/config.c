/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <android/log.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "wonder-cap-query.h"

typedef void *(*dlsym_fn)(void *, const char *);
typedef void *(*start5_fn)(const void *, size_t, uint32_t, const void *,
                         uint32_t, const uint8_t *, size_t);
/* Shipped FFI v5: country is a nullable, NUL-terminated C string. Stop
 * consumes the handle and returns bool, including on failed shutdown; update
 * returns void and takes the unchanged protobuf bytes/count after country. */
typedef bool (*stop_fn)(void *, const char *);
typedef void (*update_fn)(void *, const char *, const uint8_t *, size_t);

static _Atomic(dlsym_fn) original_dlsym;
static _Atomic(start5_fn) original_start;
static _Atomic(stop_fn) original_stop;
static _Atomic(update_fn) original_update;

struct wonder_session {
    void *handle;
    struct wonder_session *next;
};

static pthread_mutex_t sessions_mutex = PTHREAD_MUTEX_INITIALIZER;
static struct wonder_session *sessions;

static bool find_wonder_session(void *handle, bool consume)
{
    struct wonder_session **entry, *matched = NULL;
    bool found;

    pthread_mutex_lock(&sessions_mutex);
    for (entry = &sessions; *entry; entry = &(*entry)->next) {
        if ((*entry)->handle == handle) {
            matched = *entry;
            if (consume)
                *entry = matched->next;
            break;
        }
    }
    pthread_mutex_unlock(&sessions_mutex);
    found = matched != NULL;
    if (consume)
        free(matched);
    return found;
}

static const char *cleanup_country(struct wonder_regulatory *regulatory)
{
    int rc = query_wlan_regulatory(regulatory);

    if (rc) {
        /* The FFI's NULL-country path requests no country. Never replay a
         * cached country after a failed read: it may no longer match firmware.
         * Continue native cleanup/config handling and preserve its status. */
        __android_log_print(ANDROID_LOG_ERROR, "MoseyOnyx",
                            "Cannot verify wlan0 regulatory country for cleanup: %d; using no country request",
                            rc);
        return NULL;
    }
    __android_log_print(ANDROID_LOG_INFO, "MoseyOnyx",
                        "Using wlan0 regulatory country %.2s for cleanup (ifindex=%u, wiphy=%u)",
                        regulatory->alpha2, regulatory->ifindex, regulatory->wiphy);
    return regulatory->alpha2;
}

static bool stop_wonder(void *handle, const char *country)
{
    stop_fn stop = atomic_load_explicit(&original_stop, memory_order_acquire);
    struct wonder_regulatory regulatory;

    if (!stop)
        return false;
    if (find_wonder_session(handle, true))
        country = cleanup_country(&regulatory);
    return stop(handle, country);
}

static void update_wonder(void *handle, const char *country,
                          const uint8_t *config, size_t length)
{
    update_fn update = atomic_load_explicit(&original_update, memory_order_acquire);
    struct wonder_regulatory regulatory;

    if (!update)
        return;
    if (find_wonder_session(handle, false))
        country = cleanup_country(&regulatory);
    update(handle, country, config, length);
}

static void *start_wonder(const void *channels, size_t channel_count,
                          uint32_t max_mdns, const void *country,
                          uint32_t radio, const uint8_t *config, size_t length)
{
    start5_fn start = atomic_load_explicit(&original_start, memory_order_acquire);
    uint8_t *extended;
    struct wonder_session *session;
    void *result;
    struct wonder_regulatory regulatory;

    (void)radio;
    if (!start || (length && !config) || length > SIZE_MAX - 2)
        return NULL;

    int rc = query_wlan_regulatory(&regulatory);
    if (rc) {
        __android_log_print(ANDROID_LOG_ERROR, "MoseyOnyx",
                            "Cannot verify wlan0 regulatory country: %d", rc);
        return NULL;
    }
    (void)country;

    extended = malloc(length + 2);
    if (!extended)
        return NULL;
    session = malloc(sizeof(*session));
    if (!session) {
        free(extended);
        return NULL;
    }
    if (length)
        memcpy(extended, config, length);

    /* Current FFI v5: radio 2 selects wonder0/wonder. Protobuf field 5
     * enables channel hopping; the final scalar occurrence takes precedence.
     * Keep the app's channels, aggregation and rate configuration. Wonder's
     * monitor backend requires the actual vendor wiphy regulatory country;
     * reading and passing it preserves the existing firmware regulatory state.
     */
    extended[length] = 0x28;
    extended[length + 1] = 1;
    __android_log_print(ANDROID_LOG_INFO, "MoseyOnyx",
                        "Using wlan0 regulatory country %.2s (ifindex=%u, wiphy=%u)",
                        regulatory.alpha2, regulatory.ifindex, regulatory.wiphy);
    result = start(channels, channel_count, max_mdns, regulatory.alpha2, 2,
                   extended, length + 2);
    free(extended);
    if (result) {
        session->handle = result;
        pthread_mutex_lock(&sessions_mutex);
        session->next = sessions;
        sessions = session;
        pthread_mutex_unlock(&sessions_mutex);
    } else {
        free(session);
    }
    return result;
}

void *dlsym(void *handle, const char *symbol)
{
    dlsym_fn resolve = atomic_load_explicit(&original_dlsym, memory_order_acquire);
    void *result;
    const char *enabled;

    if (!resolve) {
        resolve = (dlsym_fn)dlvsym(RTLD_NEXT, "dlsym", "LIBC");
        if (!resolve)
            return NULL;
        atomic_store_explicit(&original_dlsym, resolve, memory_order_release);
    }
    result = resolve(handle, symbol);
    enabled = getenv("KONOHA_MOSEY_WONDER");
    if (result && enabled && !strcmp(enabled, "1")) {
        if (!strcmp(symbol, "mosey_start_5")) {
            atomic_store_explicit(&original_start, (start5_fn)result, memory_order_release);
            __android_log_print(ANDROID_LOG_INFO, "MoseyOnyx",
                                "Using Wonder radio with channel hopping");
            return (void *)start_wonder;
        }
        if (!strcmp(symbol, "mosey_stop")) {
            atomic_store_explicit(&original_stop, (stop_fn)result, memory_order_release);
            return (void *)stop_wonder;
        }
        if (!strcmp(symbol, "mosey_update")) {
            atomic_store_explicit(&original_update, (update_fn)result, memory_order_release);
            return (void *)update_wonder;
        }
    }
    return result;
}
