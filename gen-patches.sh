#!/usr/bin/env bash
#
# Generate the Evolution X onyx patch set from the working tree at $ROM.
#
# Splits the local modifications into per-project, per-feature patches.
# Untracked files are recorded with `git add -N` first so that the resulting
# patch *creates* them; the index is reset afterwards, so the working tree and
# the user's staging area are left exactly as they were found.
#
set -euo pipefail

ROM="${ROM:-/home/loukious/Android/custom-rom}"
OUT="${OUT:-/home/loukious/Android/crdroid_onyx_patches}"

die() { echo "FATAL: $*" >&2; exit 1; }

CTX=""       # per-patch diff context override, see emit()
FILTER=()    # per-patch hunk-filter.py args, see emit()
APPEND=0     # when 1, emit() appends instead of truncating
BASE=""      # when set, emit() diffs from this ref instead of the index
HEADEND=0    # with BASE set, diff BASE..HEAD instead of BASE..worktree
END=""       # optional explicit end ref used with BASE
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Exact source snapshots for the committed Secure Spaces feature. Updating the
# feature commits requires intentionally updating these ranges too; this prevents
# a later repo sync or unrelated local commit from silently changing generated
# security-sensitive patches.
FRAMEWORK_SECURE_BASE="${FRAMEWORK_SECURE_BASE:-4f5b74dd19f11e846536f5cda1004a54dba42a0a}"
FRAMEWORK_SECURE_END="${FRAMEWORK_SECURE_END:-7f7389d31fcc955c54df3286e33f1ad3a7df2650}"
SETTINGS_SECURE_BASE="${SETTINGS_SECURE_BASE:-36d32b115a6ce46e8b3098b62ccd1fe5a1f80fc0}"
SETTINGS_SECURE_END="${SETTINGS_SECURE_END:-5abf5fa3c5bfce68f3e04f372db51bf94b6724df}"
LINEAGE_SECURE_BASE="${LINEAGE_SECURE_BASE:-c3efc4ee11e2348a058f71b021e2ab4c403fdc64}"
LINEAGE_SECURE_END="${LINEAGE_SECURE_END:-2de7c6136ee057845ea7341e98f9ebfcd5370a75}"

[ -d "$ROM/.repo" ] || die "no .repo in $ROM"

mkdir -p "$OUT/patches"

# Untracked paths that must never enter a patch.
#   __pycache__        - build litter
EXCLUDE_RE='__pycache__'

# stage_intent <project> -- record intent-to-add for untracked, filtered files
stage_intent() {
    local proj="$1"
    local files
    files=$(git -C "$ROM/$proj" ls-files -o --exclude-standard | grep -Ev "$EXCLUDE_RE" || true)
    if [ -n "$files" ]; then
        # shellcheck disable=SC2086
        printf '%s\n' "$files" | tr '\n' '\0' | xargs -0 --no-run-if-empty \
            git -C "$ROM/$proj" add -N --
    fi
}

# emit <project> <patchname> <pathspec...>
emit() {
    local proj="$1" name="$2"; shift 2
    local dir="$OUT/patches/${proj//\//_}"
    mkdir -p "$dir"
    local target="$dir/$name"
    # CTX overrides the diff context width. Fewer context lines make a patch
    # survive unrelated churn near the hunk -- see the version.mk emit below.
    # FILTER selects individual hunks (hunk-filter.py) so that one file edited by
    # two unrelated features can be split between their patches -- see the
    # Settings.java emits below.
    # APPEND=1 concatenates onto an existing patch, which is how a patch made of
    # two differently-filtered diffs of the same project is assembled. `git apply`
    # is happy with multiple file sections in one file.
    [ "$APPEND" = 1 ] || : > "$target"
    # BASE makes emit() diff from a ref rather than from the index, which is the
    # only way to capture work that was *committed* locally. END pins the other
    # side of that range; HEADEND=1 remains available for non-pinned local work.
    local range=()
    if [ -n "$BASE" ]; then
        git -C "$ROM/$proj" rev-parse --verify -q "$BASE" >/dev/null \
            || die "$proj: base ref '$BASE' does not resolve"
        range=("$BASE")
        if [ -n "$END" ]; then
            git -C "$ROM/$proj" rev-parse --verify -q "$END" >/dev/null \
                || die "$proj: end ref '$END' does not resolve"
            git -C "$ROM/$proj" merge-base --is-ancestor "$BASE" "$END" \
                || die "$proj: '$BASE' is not an ancestor of '$END'"
            range+=("$END")
        elif [ "$HEADEND" = 1 ]; then
            range+=(HEAD)
        fi
    fi
    # shellcheck disable=SC2086  # deliberately unquoted: empty CTX must vanish
    if [ "${#FILTER[@]}" -gt 0 ]; then
        git -C "$ROM/$proj" diff --no-color --no-renames --binary \
            ${CTX:+-U$CTX} ${range[@]+"${range[@]}"} -- "$@" \
            | python3 "$HERE/hunk-filter.py" "${FILTER[@]}" >> "$target"
    else
        git -C "$ROM/$proj" diff --no-color --no-renames --binary \
            ${CTX:+-U$CTX} ${range[@]+"${range[@]}"} -- "$@" >> "$target"
    fi
    if [ ! -s "$target" ]; then
        rm -f "$target"
        die "$proj: patch $name came out EMPTY (pathspec: $*)"
    fi
    printf '  %-42s %6d lines\n' "${proj//\//_}/$name" "$(wc -l < "$target")"
}

# emit_committed <project> <patchname> <pathspec...>
#
# Secure Spaces is intentionally committed in the source repos so it can also be
# preserved in the user's GitHub forks. A plain worktree diff cannot see those
# commits. Use exact audited base/end snapshots so unrelated future commits or
# dirty worktree changes cannot enter these patches.
emit_committed() {
    local proj="$1"
    local saved_base="$BASE" saved_end="$END" saved_headend="$HEADEND"
    case "$proj" in
        frameworks/base)
            BASE="$FRAMEWORK_SECURE_BASE"
            END="$FRAMEWORK_SECURE_END"
            ;;
        packages/apps/Settings)
            BASE="$SETTINGS_SECURE_BASE"
            END="$SETTINGS_SECURE_END"
            ;;
        lineage-sdk)
            BASE="$LINEAGE_SECURE_BASE"
            END="$LINEAGE_SECURE_END"
            ;;
        *)
            die "$proj: no pinned committed feature range configured"
            ;;
    esac
    HEADEND=0
    emit "$@"
    BASE="$saved_base"
    END="$saved_end"
    HEADEND="$saved_headend"
}

# emit_selected_hunks <project> <patchname> <keep-regex> <pathspec...>
#
# Some general features share a file with an unrelated dirty feature. Filtering
# the normal -U3 diff is not enough when the edits are close enough for git to
# merge them into one hunk. Build a zero-context diff so the edits split, keep
# only the requested hunks, apply those hunks to an isolated temporary index,
# then re-diff that synthetic index with normal context. The resulting patch is
# deterministic and robust, without staging or modifying the real worktree.
emit_selected_hunks() {
    local proj="$1" name="$2" keep_re="$3"; shift 3
    local dir="$OUT/patches/${proj//\//_}"
    local target="$dir/$name"
    local selected index

    mkdir -p "$dir"
    selected="$(mktemp)"
    index="$(mktemp)"
    rm -f "$index"

    (
        trap 'rm -f "$selected" "$index"' EXIT

        git -C "$ROM/$proj" diff --no-color --no-renames --binary -U0 -- "$@" \
            | python3 "$HERE/hunk-filter.py" --keep "$keep_re" > "$selected"
        [ -s "$selected" ] \
            || die "$proj: selected patch $name came out EMPTY (pathspec: $*)"

        GIT_INDEX_FILE="$index" git -C "$ROM/$proj" read-tree HEAD
        GIT_INDEX_FILE="$index" git -C "$ROM/$proj" apply \
            --cached --unidiff-zero "$selected"
        GIT_INDEX_FILE="$index" git -C "$ROM/$proj" diff --cached \
            --no-color --no-renames --binary HEAD -- "$@" > "$target"
        [ -s "$target" ] \
            || die "$proj: canonical selected patch $name came out EMPTY"
    )

    printf '  %-42s %6d lines\n' "${proj//\//_}/$name" "$(wc -l < "$target")"
}

# Same idea as emit_selected_hunks, but keep ordinary unified-diff context.
# Use this when the wanted/unwanted edits are already separate -U3 hunks: the
# context pins the hunk to its exact semantic location and avoids relocation
# around repeated lines such as nested Makefile `endif`s.
emit_context_hunks() {
    local proj="$1" name="$2" keep_re="$3"; shift 3
    local dir="$OUT/patches/${proj//\//_}"
    local target="$dir/$name"
    local selected index

    mkdir -p "$dir"
    selected="$(mktemp)"
    index="$(mktemp)"
    rm -f "$index"

    (
        trap 'rm -f "$selected" "$index"' EXIT

        git -C "$ROM/$proj" diff --no-color --no-renames --binary -- "$@" \
            | python3 "$HERE/hunk-filter.py" --keep "$keep_re" > "$selected"
        [ -s "$selected" ] \
            || die "$proj: selected patch $name came out EMPTY (pathspec: $*)"

        GIT_INDEX_FILE="$index" git -C "$ROM/$proj" read-tree HEAD
        GIT_INDEX_FILE="$index" git -C "$ROM/$proj" apply --cached "$selected"
        GIT_INDEX_FILE="$index" git -C "$ROM/$proj" diff --cached \
            --no-color --no-renames --binary HEAD -- "$@" > "$target"
        [ -s "$target" ] \
            || die "$proj: canonical selected patch $name came out EMPTY"
    )

    printf '  %-42s %6d lines\n' "${proj//\//_}/$name" "$(wc -l < "$target")"
}

PROJECTS="build/release device/xiaomi/onyx frameworks/base hardware/nxp/nfc lineage-sdk system/vold system/security
packages/apps/Settings packages/apps/Updater packages/apps/Evolver
packages/modules/Bluetooth
vendor/gms vendor/lineage vendor/qcom/opensource/interfaces
vendor/xiaomi/onyx"

cleanup() {
    for p in $PROJECTS; do
        git -C "$ROM/$p" reset -q || true
    done
}

# stage_intent() temporarily touches the index. Refuse to run if any managed
# project already has staged work, so cleanup can never unstage user changes.
for p in $PROJECTS; do
    git -C "$ROM/$p" diff --cached --quiet \
        || die "$p: staged changes present; commit or unstage them before generating patches"
done

trap cleanup EXIT

for p in $PROJECTS; do
    stage_intent "$p"
done

echo "Generating patches into $OUT/patches"

# ---------------------------------------------------------------- frameworks/base
# Settings.java carries only GESTURE_NAVBAR_SPACE_MODE now, so no hunk filter.
emit frameworks/base 0001-gesture-navbar-space.patch \
    core/java/android/provider/Settings.java \
    services/core/java/com/android/server/wm/DisplayPolicy.java

if [ -f "$ROM/packages/apps/Settings/src/com/android/settings/security/securespaces/SecureSpaceRepository.java" ]; then
    emit_committed frameworks/base 0003-secure-spaces-full-user-type.patch \
        core/java/android/os/UserManager.java \
        services/core/java/com/android/server/pm/UserTypeFactory.java \
        services/tests/servicestests/src/com/android/server/pm/UserManagerServiceUserTypeTest.java

    emit_committed packages/apps/Settings 0002-secure-spaces-management.patch \
        src/com/android/settings/security/securespaces \
        src/com/android/settings/users/UserSettings.java \
        src/com/android/settings/users/UserCapabilities.java \
        src/com/android/settings/users/MultiUserPreferenceController.java \
        src/com/android/settings/deviceinfo/storage/NonCurrentUserController.java \
        src/com/android/settings/deviceinfo/StorageWizardMoveConfirm.java \
        src/com/android/settings/deviceinfo/StorageWizardMigrateConfirm.java \
        src/com/android/settings/core/gateway/SettingsGateway.java \
        src/com/android/settings/password/ChooseLockPassword.java \
        src/com/android/settings/Utils.java \
        src/com/android/settings/applications/appinfo/AppButtonsPreferenceController.java \
        src/com/android/settings/applications/appinfo/AppInfoDashboardFragment.java \
        src/com/android/settings/biometrics/BiometricEnrollIntroduction.java \
        src/com/android/settings/deviceinfo/storage/UserIconLoader.java \
        src/com/android/settings/network/VpnPreferenceController.java \
        res/values/secure_spaces_strings.xml \
        res/xml/security_dashboard_settings.xml \
        res/xml/security_advanced_settings.xml \
        res/xml/more_security_privacy_settings.xml \
        tests/robotests/Android.bp \
        tests/robotests/src/com/android/settings/security/securespaces
fi

if [ -f "$ROM/frameworks/base/packages/SystemUI/src/com/android/systemui/authentication/shared/model/AuthenticationResultModel.kt" ] &&
        rg -q 'checkedUserId' "$ROM/frameworks/base/packages/SystemUI/src/com/android/systemui/authentication/shared/model/AuthenticationResultModel.kt"; then
    emit_committed frameworks/base 0004-authentication-user-identity.patch \
        packages/SystemUI/src/com/android/keyguard/KeyguardAbsKeyInputViewController.java \
        packages/SystemUI/multivalentTests/src/com/android/keyguard/KeyguardAbsKeyInputViewControllerTest.java \
        packages/SystemUI/Android.bp \
        packages/SystemUI/src/com/android/systemui/authentication/shared/model/AuthenticationResultModel.kt \
        packages/SystemUI/src/com/android/systemui/authentication/shared/model/AuthenticationResult.kt \
        packages/SystemUI/src/com/android/systemui/authentication/data/repository/AuthenticationRepository.kt \
        packages/SystemUI/src/com/android/systemui/authentication/domain/interactor/AuthenticationInteractor.kt \
        packages/SystemUI/tests/utils/src/com/android/systemui/authentication/data/repository/FakeAuthenticationRepository.kt \
        packages/SystemUI/multivalentTests/src/com/android/systemui/authentication/data/repository/AuthenticationRepositoryTest.kt \
        packages/SystemUI/multivalentTests/src/com/android/systemui/authentication/domain/interactor/AuthenticationInteractorTest.kt \
        packages/SystemUI/multivalentTests/src/com/android/systemui/bouncer/ui/viewmodel/PasswordBouncerViewModelTest.kt \
        packages/SystemUI/multivalentTests/src/com/android/systemui/bouncer/ui/viewmodel/BouncerMessageViewModelTest.kt \
        packages/SystemUI/multivalentTests/src/com/android/systemui/deviceentry/domain/interactor/DeviceUnlockedInteractorTest.kt \
        packages/SystemUI/tests/robolectric/src/com/android/systemui/authentication/SecureSpaceAuthenticationIdentityTest.kt \
        packages/SystemUI/SecureSpacesAuthenticationRoboManifest.xml
fi


if [ -f "$ROM/frameworks/base/services/core/java/com/android/server/locksettings/SecureSpaceCredentialRouter.java" ]; then
    emit_committed frameworks/base 0005-secure-space-credential-router.patch \
        core/java/com/android/internal/widget/LockscreenCredential.java \
        core/tests/coretests/src/com/android/internal/widget/LockscreenCredentialTest.java \
        core/java/com/android/internal/widget/ILockSettings.aidl \
        core/java/com/android/internal/widget/ISecureSpaceCredentialAttempt.aidl \
        core/java/com/android/internal/widget/LockPatternUtils.java \
        core/java/com/android/internal/widget/SecureSpaceCredentialResponse.aidl \
        core/java/com/android/internal/widget/SecureSpaceCredentialResponse.java \
        services/core/Android.bp \
        services/core/java/com/android/server/locksettings/LockSettingsService.java \
        services/core/java/com/android/server/locksettings/SecureSpaceCredentialRouter.java \
        services/core/java/com/android/server/locksettings/SecureSpaceCredentialHandoff.java \
        services/core/java/com/android/server/locksettings/LockSettingsStrongAuth.java \
        services/tests/servicestests/Android.bp \
        services/tests/servicestests/src/com/android/server/locksettings/SecureSpaceCredentialRouterTest.java \
        services/tests/servicestests/src/com/android/server/locksettings/SecureSpaceCredentialHandoffTest.java \
        services/tests/servicestests/SecureSpaceCredentialRouterTests.xml
fi

if [ -f "$ROM/frameworks/base/packages/SystemUI/src/com/android/systemui/securespaces/SecureSpaceEntryCoordinator.java" ]; then
    emit_committed frameworks/base 0006-secure-space-public-switcher-privacy.patch \
        core/java/android/content/pm/UserInfo.java \
        core/tests/mockingcoretests/src/android/content/pm/UserInfoTest.java \
        services/core/java/com/android/server/am/UserController.java \
        services/core/java/com/android/server/am/UserSwitchingDialog.java \
        services/core/java/com/android/server/pm/UserManagerService.java \
        services/tests/servicestests/src/com/android/server/am/UserControllerTest.java \
        packages/SystemUI/src/com/android/systemui/user/domain/interactor/UserSwitcherInteractor.kt \
        packages/SystemUI/src/com/android/systemui/globalactions/GlobalActionsDialogLite.java \
        packages/SystemUI/src/com/android/systemui/statusbar/policy/UserInfoControllerImpl.java \
        packages/SystemUI/multivalentTests/src/com/android/systemui/user/domain/interactor/UserSwitcherInteractorTest.kt
fi

if [ -f "$ROM/frameworks/base/services/core/java/com/android/server/recoverysystem/SecureAuthDuressWipe.java" ]; then
    emit_committed frameworks/base 0007-secure-auth-key-erasure.patch \
        services/core/java/com/android/server/pm/UserManagerInternal.java \
        services/core/java/com/android/server/recoverysystem/Android.bp \
        services/core/java/com/android/server/recoverysystem/SecureAuthKeyErasure.java \
        services/core/java/com/android/server/recoverysystem/SecureAuthDuressWipe.java \
        services/tests/secureauth
    emit system/vold 0001-secure-auth-key-erasure.patch \
        binder/android/os/IVold.aidl \
        FsCrypt.cpp FsCrypt.h MetadataCrypt.cpp MetadataCrypt.h \
        VoldNativeService.cpp VoldNativeService.h
fi

if [ -f "$ROM/frameworks/base/services/core/java/com/android/server/locksettings/SecureAuthDuressCredentialStore.java" ]; then
    emit_committed frameworks/base 0008-secure-auth-duress-verifier.patch \
        services/core/java/com/android/server/locksettings/Android.bp \
        services/core/java/com/android/server/locksettings/SecureAuthDuressCodec.java \
        services/core/java/com/android/server/locksettings/SecureAuthDuressReservation.java \
        services/core/java/com/android/server/locksettings/SecureAuthDuressCredentialStore.java \
        services/tests/secureauthduress
fi

if [ -f "$ROM/frameworks/base/packages/SystemUI/src/com/android/systemui/securespaces/SecureSpaceEntryCoordinator.java" ]; then
    emit_committed frameworks/base 0009-secure-space-entry-coordinator.patch \
        Android.bp \
        packages/SystemUI/tests/robolectric/src/com/android/systemui/securespaces \
        packages/SystemUI/src/com/android/systemui/securespaces \
        packages/SystemUI/src/com/android/keyguard/KeyguardSecurityContainerController.java \
        packages/SystemUI/src/com/android/keyguard/KeyguardInputViewController.java \
        packages/SystemUI/src/com/android/keyguard/KeyguardSecurityModel.java \
        packages/SystemUI/src/com/android/keyguard/KeyguardUpdateMonitor.java \
        packages/SystemUI/src/com/android/keyguard/AdminSecondaryLockScreenController.java \
        packages/SystemUI/tests/src/com/android/keyguard/KeyguardUpdateMonitorTest.java \
        packages/SystemUI/tests/src/com/android/keyguard/AdminSecondaryLockScreenControllerTest.java \
        packages/SystemUI/src/com/android/systemui/deviceentry/domain/interactor/DeviceUnlockedInteractor.kt \
        packages/SystemUI/src/com/android/systemui/bouncer/data/repository/KeyguardBouncerRepository.kt \
        packages/SystemUI/src/com/android/systemui/bouncer/domain/interactor/PrimaryBouncerInteractor.kt \
        packages/SystemUI/src/com/android/systemui/keyguard/domain/interactor/KeyguardDismissInteractor.kt \
        packages/SystemUI/src/com/android/systemui/keyguard/domain/interactor/FromLockscreenTransitionInteractor.kt \
        packages/SystemUI/src/com/android/systemui/statusbar/phone/StatusBarKeyguardViewManager.java \
        packages/SystemUI/src/com/android/systemui/bouncer/domain/interactor/BouncerInteractor.kt \
        packages/SystemUI/src/com/android/systemui/bouncer/ui/viewmodel/AuthMethodBouncerViewModel.kt \
        packages/SystemUI/src/com/android/systemui/bouncer/ui/viewmodel/BouncerOverlayContentViewModel.kt \
        packages/SystemUI/compose/features/src/com/android/systemui/bouncer/ui/composable/BouncerOverlay.kt \
        packages/SystemUI/tests/utils/src/com/android/systemui/keyguard/domain/interactor/FromLockscreenTransitionInteractorKosmos.kt
fi

if [ -f "$ROM/frameworks/base/services/core/java/com/android/server/biometrics/sensors/fingerprint/SecureSpaceFingerprintPool.java" ]; then
    emit_committed frameworks/base 0010-secure-space-fingerprint-routing.patch \
        core/java/android/hardware/fingerprint/FingerprintCallback.java \
        core/java/android/hardware/fingerprint/FingerprintManager.java \
        core/java/android/hardware/fingerprint/FingerprintServiceReceiver.java \
        core/java/android/hardware/fingerprint/IFingerprintService.aidl \
        core/java/android/hardware/fingerprint/IFingerprintServiceReceiver.aidl \
        keystore/java/android/security/KeyStoreAuthorization.java \
        services/core/java/com/android/server/biometrics/AuthService.java \
        services/core/java/com/android/server/biometrics/AuthSession.java \
        services/core/java/com/android/server/biometrics/BiometricService.java \
        services/core/java/com/android/server/biometrics/BiometricUserScope.java \
        services/core/java/com/android/server/biometrics/sensors/AuthenticationClient.java \
        services/core/java/com/android/server/biometrics/sensors/ClientMonitorCallbackConverter.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/FingerprintService.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/SecureSpaceFingerprintPolicy.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/SecureSpaceFingerprintPool.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/AidlSession.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/BiometricTestSessionImpl.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/FingerprintAuthenticationClient.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/FingerprintEnrollClient.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/FingerprintGetAuthenticatorIdClient.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/FingerprintInternalCleanupClient.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/FingerprintInternalEnumerateClient.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/FingerprintInvalidationClient.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/FingerprintRemovalClient.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/FingerprintStartUserClient.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/aidl/SharedFingerprintCleanupUtils.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/hidl/FingerprintUpdateActiveUserClient.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/hidl/HidlToAidlSensorAdapter.java \
        services/core/java/com/android/server/biometrics/sensors/fingerprint/hidl/LockoutFrameworkImpl.java \
        services/core/java/com/android/server/locksettings/LockSettingsInternal.java \
        packages/SystemUI/src/com/android/systemui/deviceentry/domain/interactor/DeviceEntryHapticsInteractor.kt \
        packages/SystemUI/multivalentTests/src/com/android/systemui/deviceentry/domain/interactor/DeviceEntryHapticsInteractorTest.kt \
        services/tests/secureauthfingerprint/Android.bp \
        services/tests/secureauthfingerprint/SecureSpaceFingerprintPolicyTest.java
fi

if [ -f "$ROM/lineage-sdk/lineage/lib/main/java/org/lineageos/platform/internal/common/UserContentObserver.java" ] &&
        rg -q 'reply.sendResult' "$ROM/lineage-sdk/lineage/lib/main/java/org/lineageos/platform/internal/common/UserContentObserver.java"; then
    emit_committed lineage-sdk 0001-secure-space-user-switch-observer-acks.patch \
        lineage/lib/main/java/org/lineageos/platform/internal/common/UserContentObserver.java
fi

if [ -f "$ROM/system/security/keystore2/src/biometric_user_scope.rs" ]; then
    emit system/security 0001-secure-auth-biometric-user-scope.patch \
        keystore2/aidl/android/security/authorization/IKeystoreAuthorization.aidl \
        keystore2/src/authorization.rs \
        keystore2/src/biometric_user_scope.rs \
        keystore2/src/database.rs \
        keystore2/src/enforcements.rs \
        keystore2/src/lib.rs
fi

# --------------------------------------------------------------- hardware/nxp/nfc
# Keep the timer-visible client ID zeroing from the 2026 UAF fix, while giving
# the legacy client thread a stable queue handle until it is joined. This avoids
# the teardown race where the thread spins forever on msgrcv(0) after NFC closes.
emit hardware/nxp/nfc 0001-fix-client-thread-teardown-race.patch \
    snxxx/halimpl/hal/phNxpNciHal.cc \
    snxxx/halimpl/hal/phNxpNciHal.h \
    snxxx/halimpl/recovery/phNxpNciHal_Recovery.cc \
    snxxx/halimpl/tml/phDal4Nfc_messageQueueLib.cc \
    snxxx/halimpl/tml/phDal4Nfc_messageQueueLib.h

# ------------------------------------------------------------------------- LHDC
emit packages/modules/Bluetooth 0001-lhdc-v5-qti-offload.patch .

emit vendor/qcom/opensource/interfaces 0001-lhdc-aidl.patch .

# Only the new flag file. The modified a2dp_lhdc_api_flag_values.textproto is a
# whitespace-only reindent (verified with `git diff -w`) and is dropped.
emit build/release 0001-lhdc-aconfig-flag.patch \
    aconfig/bp4a/com.android.bluetooth.flags/lhdc_codec_support_flag_values.textproto

# --------------------------------------------------------------- device/xiaomi/onyx
emit device/xiaomi/onyx 0001-vendor-extra-kernel-hook.patch BoardConfig.mk

# device.mk also carries the separately curated NXP/libperfmgr namespace patch
# (0002). Keep only the release-config hunk here so regeneration can never fold
# 0002 into this patch or overwrite its established numbering.
emit_context_hunks device/xiaomi/onyx 0003-release-config-bp4a.patch \
    'PRODUCT_RELEASE_CONFIG_MAPS' device.mk
APPEND=1 emit device/xiaomi/onyx 0003-release-config-bp4a.patch configs/release
APPEND=0

emit device/xiaomi/onyx 0004-lhdc-aptx-props-and-blob-fixups.patch \
    properties/product.prop extract-files.py

emit device/xiaomi/onyx 0005-firmware-os3.0.302.0.patch proprietary-firmware.txt

# Keep CFR enabled in the WCN7750 vendor configuration.
emit device/xiaomi/onyx 0015-enable-wifi-cfr.patch configs/wifi/WCNSS_qcom_cfg.ini

# ------------------------------------------------------------------- vendor/lineage
# kernel.mk also contains 0006's target-files/module ordering dependency. Keep
# the kernel-binary override isolated so both patches remain independently
# reproducible and apply in their documented order.
emit_context_hunks vendor/lineage 0001-kernel-bin-override.patch \
    'TARGET_OVERRIDE_KERNEL_BIN|KERNEL_BIN :=' build/tasks/kernel.mk

# ------------------------------------------------------- packages/apps/Settings
# The UI half of gesture-navbar-space: one ListPreference in the gesture-nav
# screen. Under Evolution X this is XML only -- Evo's
# org.evolution.settings.preferences.SystemSettingListPreference persists the
# value to Settings.System itself, so the 43 lines of Java the crDroid version
# needed (initGestureNavbarSpacePreference + constants + listener) are gone.
# Do not add them back; a preference class doing the write is what Evo does for
# every other system setting, and it is one less thing to rebase.
emit packages/apps/Settings 0001-gesture-navbar-space-ui.patch \
    res/xml/gesture_navigation_settings.xml

emit packages/apps/Updater 0001-self-hosted-ota-url.patch \
    app/src/main/res/values/strings.xml

# ----------------------------------------------------------------- Evolver
# Strings and arrays for the gesture-navbar-space preference. They have to live
# here, not in packages/apps/Settings: Evo builds Evolver *into* the Settings
# APK (Settings/Android.bp: "Evolver/res" in resource_dirs, --extra-packages
# org.evolution.settings), which is why an @string reference from
# res/xml/gesture_navigation_settings.xml resolves against Evolver's resources.
# Evo splits strings and arrays across two files, so both are listed.
emit_selected_hunks packages/apps/Evolver 0001-gesture-navbar-space-ui.patch \
    'gesture_navbar_space' \
    res/values/evolution_strings.xml \
    res/values/evolution_arrays.xml

# --------------------------------------------------------------------- vendor/gms
# Keep AOSP/Lineage Dialer as the only dialer. GoogleDialer's prebuilt declares
# LOCAL_OVERRIDES_PACKAGES := Dialer, so simply omitting GoogleDialer from the
# product package list lets the platform Dialer remain installed.
emit vendor/gms 0001-keep-aosp-dialer.patch gms_full.mk

# --------------------------------------------------------------- vendor/xiaomi/onyx
# Only Android.mk. The 351MB of rebuilt radio/ images and the 2 byte-patched
# LHDC blobs ship as a separate overlay project (onyx-firmware) that apply.sh
# copies in -- they are binaries and have no business in a patch. Android.mk is
# text, so it stays a patch: if crDroid regenerates it upstream this conflicts
# loudly instead of being silently clobbered.
emit vendor/xiaomi/onyx 0001-firmware-sha1s-os3.0.302.0.patch Android.mk

echo
echo "Done. Totals:"
find "$OUT/patches" -name '*.patch' | wc -l | xargs echo "  patch files:"
du -sh "$OUT/patches" | awk '{print "  size:        "$1}'
