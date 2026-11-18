/* Minimal API surface used by the actual capability bridge. */
#ifndef FIXTURE_ANDROID_BINDER_PARCEL_H
#define FIXTURE_ANDROID_BINDER_PARCEL_H
#include <android/binder_status.h>
#include <stdint.h>
typedef struct AParcel AParcel;
binder_status_t AParcel_writeStatusHeader(AParcel *parcel, const AStatus *status);
binder_status_t AParcel_writeInt32(AParcel *parcel, int32_t value);
binder_status_t AParcel_writeByteArray(AParcel *parcel, const int8_t *array, int32_t length);
int32_t AParcel_getDataPosition(const AParcel *parcel);
binder_status_t AParcel_setDataPosition(const AParcel *parcel, int32_t position);
#endif
