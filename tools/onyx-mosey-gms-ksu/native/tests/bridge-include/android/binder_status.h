/* Offline Binder fixture declarations; production uses Android NDK headers. */
#ifndef FIXTURE_ANDROID_BINDER_STATUS_H
#define FIXTURE_ANDROID_BINDER_STATUS_H
#include <stdint.h>
typedef int32_t binder_status_t;
typedef struct AStatus AStatus;
enum {
    STATUS_OK = 0,
    STATUS_NO_MEMORY = -12,
    STATUS_BAD_VALUE = -22,
    STATUS_UNKNOWN_TRANSACTION = -74,
    STATUS_FAILED_TRANSACTION = (-2147483647 - 1) + 2
};
AStatus *AStatus_newOk(void);
void AStatus_delete(AStatus *status);
#endif
