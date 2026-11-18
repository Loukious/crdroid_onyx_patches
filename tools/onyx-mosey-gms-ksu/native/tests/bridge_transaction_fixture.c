/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <android/binder_ibinder.h>
#include <android/log.h>
#include <errno.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct AStatus { int marker; };
struct AIBinder { int marker; };
struct AIBinder_Class { int marker; };
struct AParcel {
    uint8_t bytes[128];
    int32_t position;
    int32_t length;
    unsigned int_writes;
    unsigned get_positions;
    unsigned set_positions;
};

/* Restrict dlsym substitution to this source, avoiding sanitizer interception. */
static void *fixture_dlsym(void *handle, const char *symbol);
#define dlsym fixture_dlsym
#include "wonder-capability-bridge.c"
#undef dlsym

enum fault {
    FAIL_NONE,
    FAIL_NEW_OK,
    FAIL_HEADER,
    FAIL_NONNULL,
    FAIL_SIZE_PLACEHOLDER,
    FAIL_BYTES,
    FAIL_REWIND,
    FAIL_SIZE_BACKFILL,
    FAIL_FINAL_POSITION,
    FAIL_START_POSITION,
    FAIL_END_POSITION
};
static enum fault injected_fault;
static const binder_status_t injected_status = -701;
static unsigned checks;
static unsigned status_allocated;
static unsigned status_deleted;
static unsigned log_info;
static unsigned log_warn;
static char last_log[512];
static struct wonder_caps queued_caps[16];
static int queued_query_rc[16];
static unsigned queue_length;
static unsigned query_calls;
static bool resolver_present;
static unsigned resolve_calls;
static unsigned define_calls;
static const char *defined_descriptor;
static AIBinder_Class_onCreate defined_create;
static AIBinder_Class_onDestroy defined_destroy;
static AIBinder_Class_onTransact defined_transaction;
static struct AIBinder_Class fake_class;
static unsigned forwarded_calls;
static AIBinder *forwarded_binder;
static transaction_code_t forwarded_code;
static const AParcel *forwarded_in;
static AParcel *forwarded_out;
static const binder_status_t forwarded_status = -801;

#define CHECK(condition) do { \
    ++checks; \
    if (!(condition)) { \
        fprintf(stderr, "%s:%d: failed: %s\n", __FILE__, __LINE__, #condition); \
        exit(EXIT_FAILURE); \
    } \
} while (0)

static void reset(void)
{
    CHECK(status_allocated == status_deleted);
    injected_fault = FAIL_NONE;
    status_allocated = status_deleted = 0;
    log_info = log_warn = 0;
    last_log[0] = '\0';
    memset(queued_caps, 0, sizeof(queued_caps));
    memset(queued_query_rc, 0, sizeof(queued_query_rc));
    queue_length = query_calls = 0;
    resolver_present = true;
    resolve_calls = define_calls = 0;
    defined_descriptor = NULL;
    defined_create = NULL;
    defined_destroy = NULL;
    defined_transaction = NULL;
    forwarded_calls = 0;
    forwarded_binder = NULL;
    forwarded_code = 0;
    forwarded_in = NULL;
    forwarded_out = NULL;
    atomic_store_explicit(&original_transaction, NULL, memory_order_relaxed);
    CHECK(unsetenv("KONOHA_MOSEY_WONDER") == 0);
}

static void set_env(const char *key, const char *value)
{
    CHECK(value ? setenv(key, value, 1) == 0 : unsetenv(key) == 0);
}

static void queue_query(bool hopping, int rc)
{
    CHECK(queue_length < sizeof(queued_caps) / sizeof(queued_caps[0]));
    queued_caps[queue_length] = (struct wonder_caps){
        .hopping = hopping, .hbs = true, .nss = 2, .max_switch_us = 32000
    };
    queued_query_rc[queue_length++] = rc;
}

int query_wonder_caps(struct wonder_caps *caps)
{
    CHECK(query_calls < queue_length);
    unsigned slot = query_calls++;
    /* Poison even error outputs: the bridge must respect the query status. */
    *caps = queued_caps[slot];
    return queued_query_rc[slot];
}

int __android_log_print(int priority, const char *tag, const char *format, ...)
{
    CHECK(strcmp(tag, "MoseyOnyx") == 0);
    if (priority == ANDROID_LOG_INFO) ++log_info;
    else if (priority == ANDROID_LOG_WARN) ++log_warn;
    else CHECK(false);
    va_list args;
    va_start(args, format);
    int rc = vsnprintf(last_log, sizeof(last_log), format, args);
    va_end(args);
    CHECK(rc >= 0 && (size_t)rc < sizeof(last_log));
    return rc;
}

AStatus *AStatus_newOk(void)
{
    if (injected_fault == FAIL_NEW_OK) return NULL;
    AStatus *status = malloc(sizeof(*status));
    CHECK(status != NULL);
    status->marker = 0;
    ++status_allocated;
    return status;
}

void AStatus_delete(AStatus *status)
{
    CHECK(status != NULL && status->marker == 0);
    ++status_deleted;
    free(status);
}

static void parcel_int(AParcel *parcel, int32_t value)
{
    CHECK(parcel->position >= 0);
    CHECK((size_t)parcel->position + 4 <= sizeof(parcel->bytes));
    uint32_t bits = (uint32_t)value;
    for (unsigned i = 0; i < 4; ++i)
        parcel->bytes[parcel->position++] = (uint8_t)(bits >> (i * 8));
    if (parcel->position > parcel->length) parcel->length = parcel->position;
}

binder_status_t AParcel_writeStatusHeader(AParcel *parcel, const AStatus *status)
{
    CHECK(status != NULL && status->marker == 0);
    if (injected_fault == FAIL_HEADER) return injected_status;
    parcel_int(parcel, 0);
    return STATUS_OK;
}

binder_status_t AParcel_writeInt32(AParcel *parcel, int32_t value)
{
    unsigned call = ++parcel->int_writes;
    if ((call == 1 && injected_fault == FAIL_NONNULL) ||
        (call == 2 && injected_fault == FAIL_SIZE_PLACEHOLDER) ||
        (call == 3 && injected_fault == FAIL_SIZE_BACKFILL)) return injected_status;
    parcel_int(parcel, value);
    return STATUS_OK;
}

binder_status_t AParcel_writeByteArray(AParcel *parcel, const int8_t *array,
                                      int32_t length)
{
    CHECK(array != NULL && length == 2);
    if (injected_fault == FAIL_BYTES) return injected_status;
    parcel_int(parcel, length);
    int32_t padded = (length + 3) & ~3;
    CHECK(parcel->position >= 0 && padded >= length);
    CHECK((size_t)parcel->position + (size_t)padded <= sizeof(parcel->bytes));
    memcpy(&parcel->bytes[parcel->position], array, (size_t)length);
    memset(&parcel->bytes[parcel->position + length], 0, (size_t)(padded - length));
    parcel->position += padded;
    if (parcel->position > parcel->length) parcel->length = parcel->position;
    return STATUS_OK;
}

int32_t AParcel_getDataPosition(const AParcel *parcel)
{
    AParcel *mutable = (AParcel *)parcel;
    unsigned call = ++mutable->get_positions;
    if (call == 1 && injected_fault == FAIL_START_POSITION) return -1;
    if (call == 2 && injected_fault == FAIL_END_POSITION) return 7;
    return parcel->position;
}

binder_status_t AParcel_setDataPosition(const AParcel *parcel, int32_t position)
{
    AParcel *mutable = (AParcel *)parcel;
    unsigned call = ++mutable->set_positions;
    if ((call == 1 && injected_fault == FAIL_REWIND) ||
        (call == 2 && injected_fault == FAIL_FINAL_POSITION)) return injected_status;
    CHECK(position >= 0 && position <= parcel->length);
    mutable->position = position;
    return STATUS_OK;
}

static void *original_create(void *args) { return args; }
static void original_destroy(void *args) { (void)args; }

static binder_status_t original_callback(AIBinder *binder, transaction_code_t code,
                                         const AParcel *in, AParcel *out)
{
    ++forwarded_calls;
    forwarded_binder = binder;
    forwarded_code = code;
    forwarded_in = in;
    forwarded_out = out;
    return forwarded_status;
}

static binder_status_t different_callback(AIBinder *binder, transaction_code_t code,
                                          const AParcel *in, AParcel *out)
{
    (void)binder; (void)code; (void)in; (void)out;
    return 123;
}

static AIBinder_Class *real_define(const char *descriptor,
    AIBinder_Class_onCreate create, AIBinder_Class_onDestroy destroy,
    AIBinder_Class_onTransact on_transact)
{
    ++define_calls;
    defined_descriptor = descriptor;
    defined_create = create;
    defined_destroy = destroy;
    defined_transaction = on_transact;
    return &fake_class;
}

static void *fixture_dlsym(void *handle, const char *symbol)
{
    CHECK(handle == RTLD_NEXT);
    CHECK(strcmp(symbol, "AIBinder_Class_define") == 0);
    ++resolve_calls;
    return resolver_present ? (void *)real_define : NULL;
}

static void assert_parcel(const AParcel *parcel, bool hopping)
{
    const uint8_t expected[] = {
        0, 0, 0, 0, 1, 0, 0, 0, 12, 0, 0, 0,
        2, 0, 0, 0, 8, hopping ? 1 : 0, 0, 0
    };
    CHECK(parcel->length == 20);
    CHECK(parcel->position == 20);
    CHECK(parcel->int_writes == 3);
    CHECK(parcel->get_positions == 2);
    CHECK(parcel->set_positions == 2);
    CHECK(memcmp(parcel->bytes, expected, sizeof(expected)) == 0);
    CHECK(status_allocated == status_deleted);
}

static void test_raw_capabilities(void)
{
    for (unsigned raw = 0; raw < 2; ++raw) {
        reset();
        queue_query(raw != 0, 0);
        AParcel out = {0};
        CHECK(transaction(NULL, 4, NULL, &out) == STATUS_OK);
        assert_parcel(&out, false);
        CHECK(query_calls == 1 && log_info == 1 && log_warn == 0);
        CHECK(strstr(last_log, raw ? "GET_CAP hopping=1" : "GET_CAP hopping=0") != NULL);
        CHECK(strstr(last_log, "controller_hopping=0") != NULL);
    }
}

static void test_fresh_queries(void)
{
    reset();
    queue_query(true, 0);
    queue_query(false, 0);
    queue_query(true, -EIO);
    queue_query(true, 0);
    queue_query(true, 0);
    queue_query(true, 0);
    AParcel out[6] = {0};
    CHECK(transaction(NULL, 4, NULL, &out[0]) == STATUS_OK);
    assert_parcel(&out[0], false);
    CHECK(transaction(NULL, 4, NULL, &out[1]) == STATUS_OK);
    assert_parcel(&out[1], false);
    CHECK(transaction(NULL, 4, NULL, &out[2]) == STATUS_FAILED_TRANSACTION);
    CHECK(out[2].position == 0 && out[2].length == 0);
    CHECK(transaction(NULL, 4, NULL, &out[3]) == STATUS_OK);
    assert_parcel(&out[3], false);
    CHECK(transaction(NULL, 4, NULL, &out[4]) == STATUS_OK);
    assert_parcel(&out[4], false);
    CHECK(transaction(NULL, 4, NULL, &out[5]) == STATUS_OK);
    assert_parcel(&out[5], false);
    CHECK(query_calls == 6 && log_info == 5 && log_warn == 1);
}

static void test_query_errors(void)
{
    const int errors[] = {-EIO, -EOPNOTSUPP, -EINVAL, 1};
    for (unsigned i = 0; i < sizeof(errors) / sizeof(errors[0]); ++i) {
        reset();
        queue_query(true, errors[i]);
        AParcel out = {0};
        CHECK(transaction(NULL, 4, NULL, &out) == STATUS_FAILED_TRANSACTION);
        CHECK(query_calls == 1 && log_info == 0 && log_warn == 1);
        CHECK(out.position == 0 && out.length == 0);
        CHECK(status_allocated == 0 && status_deleted == 0);
    }
}

static void test_parcel_errors(void)
{
    for (enum fault fault = FAIL_NEW_OK; fault <= FAIL_END_POSITION; ++fault) {
        reset();
        injected_fault = fault;
        queue_query(true, 0);
        AParcel out = {0};
        binder_status_t expected = fault == FAIL_NEW_OK ? STATUS_NO_MEMORY :
            (fault == FAIL_START_POSITION || fault == FAIL_END_POSITION) ?
            STATUS_BAD_VALUE : injected_status;
        CHECK(transaction(NULL, 4, NULL, &out) == expected);
        CHECK(query_calls == 1);
        CHECK(status_allocated == status_deleted);
        CHECK(status_allocated == (fault == FAIL_NEW_OK ? 0u : 1u));
    }
}

static void test_forwarding(void)
{
    reset();
    AIBinder binder = {0};
    AParcel in = {0}, out = {0};
    const transaction_code_t codes[] = {0, 1, 3, 5, 16777214, 16777215};
    for (unsigned i = 0; i < sizeof(codes) / sizeof(codes[0]); ++i)
        CHECK(transaction(&binder, codes[i], &in, &out) == STATUS_UNKNOWN_TRANSACTION);
    CHECK(forwarded_calls == 0 && query_calls == 0);
    atomic_store_explicit(&original_transaction, original_callback, memory_order_relaxed);
    for (unsigned i = 0; i < sizeof(codes) / sizeof(codes[0]); ++i) {
        CHECK(transaction(&binder, codes[i], &in, &out) == forwarded_status);
        CHECK(forwarded_calls == i + 1);
        CHECK(forwarded_binder == &binder && forwarded_code == codes[i]);
        CHECK(forwarded_in == &in && forwarded_out == &out);
    }
    CHECK(query_calls == 0 && log_info == 0 && log_warn == 0);
}

static void test_hook_boundaries(void)
{
    const char *target = "com.google.android.moseyservice.IMoseyService";
    const char *profiles[] = {NULL, "0", "true", "01", "1 ", "", "2", "1"};
    const char *descriptors[] = {NULL, "other", "com.google.android.moseyservice.IMoseyServiceX", target};
    for (unsigned p = 0; p < sizeof(profiles) / sizeof(profiles[0]); ++p) {
        for (unsigned d = 0; d < sizeof(descriptors) / sizeof(descriptors[0]); ++d) {
            for (unsigned raw = 0; raw < 2; ++raw) {
                reset();
                set_env("KONOHA_MOSEY_WONDER", profiles[p]);
                CHECK(AIBinder_Class_define(descriptors[d], original_create,
                    original_destroy, original_callback) == &fake_class);
                bool active = profiles[p] && strcmp(profiles[p], "1") == 0 &&
                    descriptors[d] && strcmp(descriptors[d], target) == 0;
                CHECK(define_calls == 1 && resolve_calls == 1);
                CHECK(defined_descriptor == descriptors[d]);
                CHECK(defined_create == original_create && defined_destroy == original_destroy);
                CHECK(defined_transaction == (active ? transaction : original_callback));
                CHECK(atomic_load_explicit(&original_transaction, memory_order_relaxed) ==
                    (active ? original_callback : NULL));
                queue_query(raw != 0, 0);
                AIBinder binder = {0};
                AParcel in = {0}, out = {0};
                CHECK(defined_transaction(&binder, 4, &in, &out) ==
                    (active ? STATUS_OK : forwarded_status));
                if (active) {
                    assert_parcel(&out, false);
                    CHECK(query_calls == 1 && forwarded_calls == 0);
                } else {
                    CHECK(query_calls == 0 && forwarded_calls == 1);
                    CHECK(out.position == 0 && out.length == 0);
                    CHECK(forwarded_binder == &binder && forwarded_code == 4);
                    CHECK(forwarded_in == &in && forwarded_out == &out);
                }
                CHECK(defined_transaction(&binder, 16777215, &in, &out) == forwarded_status);
                CHECK(query_calls == (active ? 1u : 0u));
                CHECK(forwarded_calls == (active ? 1u : 2u));
                CHECK(forwarded_binder == &binder && forwarded_code == 16777215);
                CHECK(forwarded_in == &in && forwarded_out == &out);
            }
        }
    }
}

static void test_hook_registration(void)
{
    const char *target = "com.google.android.moseyservice.IMoseyService";
    reset();
    set_env("KONOHA_MOSEY_WONDER", "1");
    CHECK(AIBinder_Class_define(target, original_create, original_destroy, NULL) == NULL);
    CHECK(define_calls == 0);
    CHECK(atomic_load_explicit(&original_transaction, memory_order_relaxed) == NULL);
    CHECK(AIBinder_Class_define(target, original_create, original_destroy, original_callback) == &fake_class);
    CHECK(defined_transaction == transaction && define_calls == 1);
    CHECK(AIBinder_Class_define(target, original_create, original_destroy, original_callback) == &fake_class);
    CHECK(defined_transaction == transaction && define_calls == 2);
    CHECK(AIBinder_Class_define(target, original_create, original_destroy, different_callback) == NULL);
    CHECK(define_calls == 2);
    CHECK(AIBinder_Class_define(target, original_create, original_destroy, NULL) == NULL);
    CHECK(define_calls == 2);
    CHECK(atomic_load_explicit(&original_transaction, memory_order_relaxed) == original_callback);
    resolver_present = false;
    CHECK(AIBinder_Class_define(target, original_create, original_destroy, original_callback) == NULL);
    CHECK(define_calls == 2);
    CHECK(atomic_load_explicit(&original_transaction, memory_order_relaxed) == original_callback);
    reset();
    resolver_present = false;
    set_env("KONOHA_MOSEY_WONDER", "1");
    CHECK(AIBinder_Class_define(target, original_create, original_destroy, original_callback) == NULL);
    CHECK(define_calls == 0 && resolve_calls == 1);
    CHECK(atomic_load_explicit(&original_transaction, memory_order_relaxed) == NULL);
    reset();
    CHECK(AIBinder_Class_define(target, NULL, NULL, NULL) == &fake_class);
    CHECK(defined_create == NULL && defined_destroy == NULL && defined_transaction == NULL);
}

int main(int argc, char **argv)
{
    const struct {
        const char *name;
        void (*run)(void);
    } cases[] = {
        {"raw-capabilities", test_raw_capabilities},
        {"fresh-queries", test_fresh_queries},
        {"query-errors", test_query_errors},
        {"parcel-errors", test_parcel_errors},
        {"forwarding", test_forwarding},
        {"hook-boundaries", test_hook_boundaries},
        {"hook-registration", test_hook_registration}
    };
    if (argc != 2) return 2;
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        if (strcmp(argv[1], cases[i].name)) continue;
        cases[i].run();
        CHECK(status_allocated == status_deleted);
        printf("{\"case\":\"%s\",\"assertions\":%u}\n", cases[i].name, checks);
        return EXIT_SUCCESS;
    }
    fprintf(stderr, "Unknown offline bridge case: %s\n", argv[1]);
    return 2;
}
