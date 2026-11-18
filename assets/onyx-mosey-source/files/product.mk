# SPDX-License-Identifier: Apache-2.0

TARGET_INCLUDE_MOSEY := true
TARGET_USES_MOSEY_NOPAUTH := false

# Product inheritance is evaluated as a graph. Include the native package
# directly instead of relying on common.mk observing our deferred variable.
$(call inherit-product, vendor/gms-mosey/mosey/mosey-vendor.mk)

PRODUCT_SOONG_NAMESPACES += vendor/extra/mosey
PRODUCT_PACKAGES += libmosey_onyx_config onyx_mosey_launcher
PRODUCT_COPY_FILES += \
    vendor/extra/mosey/onyx-mosey.rc:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/init/onyx-mosey.rc
