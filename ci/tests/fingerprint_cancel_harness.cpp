// Host models of the legacy HAL and AIDL callback boundaries. The runner inserts
// Session::cancel, VendorErrorFilter and the complete notify method unchanged.
#include <cerrno>
#include <cstdint>
#include <functional>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#define ALOGD(...) ((void)0)
#define ALOGE(...) ((void)0)
constexpr unsigned NUM_FINGERS = 5;
enum {
    FINGERPRINT_ERROR_HW_UNAVAILABLE = 1, FINGERPRINT_ERROR_UNABLE_TO_PROCESS,
    FINGERPRINT_ERROR_TIMEOUT, FINGERPRINT_ERROR_NO_SPACE, FINGERPRINT_ERROR_CANCELED,
    FINGERPRINT_ERROR_UNABLE_TO_REMOVE, FINGERPRINT_ERROR_LOCKOUT,
    FINGERPRINT_ERROR_VENDOR_BASE = 1000,
};
enum {
    FINGERPRINT_ERROR, FINGERPRINT_ACQUIRED, FINGERPRINT_TEMPLATE_ENROLLING,
    FINGERPRINT_TEMPLATE_REMOVED, FINGERPRINT_AUTHENTICATED,
    FINGERPRINT_TEMPLATE_ENUMERATING, FINGERPRINT_CHALLENGE_GENERATED,
    FINGERPRINT_CHALLENGE_REVOKED, FINGERPRINT_AUTHENTICATOR_ID_RETRIEVED,
    FINGERPRINT_AUTHENTICATOR_ID_INVALIDATED, FINGERPRINT_RESET_LOCKOUT,
};
enum class Error { HW_UNAVAILABLE, UNABLE_TO_PROCESS, TIMEOUT, NO_SPACE, CANCELED,
                   UNABLE_TO_REMOVE, VENDOR };
enum class AcquiredInfo { GOOD, VENDOR };
struct hw_auth_token_t { uint64_t value = 0; };
struct HardwareAuthToken { uint64_t value = 0; };
void translate(const hw_auth_token_t& in, HardwareAuthToken& out) { out.value = in.value; }
struct Finger { int32_t fid = 0, gid = 0; };
struct Templates {
    Finger finger, fingers[NUM_FINGERS];
    int remaining_templates = 0;
};
struct fingerprint_msg_t {
    int type = FINGERPRINT_ERROR;
    struct {
        int error = FINGERPRINT_ERROR_CANCELED;
        struct { int acquired_info = 0; } acquired;
        struct { Finger finger; int samples_remaining = 0; } enroll;
        Templates removed, enumerated;
        struct { Finger finger; hw_auth_token_t hat; } authenticated;
        struct { uint64_t value = 0; } challenge;
        struct { uint64_t id = 0; } authenticator;
    } data;
};
namespace ndk {
struct ScopedAStatus {
    int error;
    static ScopedAStatus ok() { return {0}; }
    static ScopedAStatus fromServiceSpecificError(int error) { return {error}; }
};
}
struct Event {
    std::string kind;
    Error error = Error::CANCELED;
    int vendor = 0, id = 0;
    uint64_t token = 0;
};
struct Callback {
    std::vector<Event> events;
    void onError(Error error, int vendor) { events.push_back({"error", error, vendor}); }
    void onAuthenticationSucceeded(int id, const HardwareAuthToken& token) {
        events.push_back({"authenticated", Error::CANCELED, 0, id, token.value});
    }
    void onAuthenticationFailed() { events.push_back({"authentication_failed"}); }
    void onEnrollmentProgress(int id, int) {
        events.push_back({"enrolled", Error::CANCELED, 0, id});
    }
    void onAcquired(AcquiredInfo, int) {}
    void onEnrollmentsRemoved(const std::vector<int32_t>&) {}
    void onEnrollmentsEnumerated(const std::vector<int32_t>&) {}
    void onChallengeGenerated(uint64_t) {}
    void onChallengeRevoked(uint64_t) {}
    void onAuthenticatorIdRetrieved(uint64_t) {}
    void onAuthenticatorIdInvalidated(uint64_t) {}
};
struct UdfpsHandler {
    std::vector<std::string>* order;
    void cancel() { order->push_back("overlay"); }
    void onAcquired(int32_t, int32_t) {}
    void onAuthenticationSucceeded() {}
    void onAuthenticationFailed() {}
};
struct fingerprint_device_t { std::function<int(fingerprint_device_t*)> cancel; };
struct LockoutTracker {
    int resets = 0, failures = 0;
    void reset(bool) { ++resets; }
    void addFailedAttempt() { ++failures; }
};
class Session {
public:
    fingerprint_device_t* mDevice;
    UdfpsHandler* mUdfpsHandler;
    std::shared_ptr<Callback> mCb;
    LockoutTracker mLockoutTracker;
    Session(fingerprint_device_t* device, UdfpsHandler* handler, std::shared_ptr<Callback> cb)
        : mDevice(device), mUdfpsHandler(handler), mCb(std::move(cb)) {}
    ndk::ScopedAStatus cancel();
    static Error VendorErrorFilter(int32_t error, int32_t* vendorCode);
    void notify(const fingerprint_msg_t* msg);
    static AcquiredInfo VendorAcquiredFilter(int32_t, int32_t*) { return AcquiredInfo::GOOD; }
    bool checkSensorLockout() { return false; }
    void clearLockout(bool) {}
};

// PRODUCTION_METHODS

void expect(bool condition, const char* reason) {
    if (!condition) throw std::runtime_error(reason);
}
struct Fixture {
    std::vector<std::string> order;
    std::shared_ptr<Callback> callback = std::make_shared<Callback>();
    UdfpsHandler handler{&order};
    fingerprint_device_t device;
    Session session;
    std::function<int()> vendorAction = [] { return 0; };
    explicit Fixture(bool withHandler = true)
        : session(&device, withHandler ? &handler : nullptr, callback) {
        device.cancel = [this](fingerprint_device_t*) {
            order.push_back("vendor");
            return vendorAction();
        };
    }
    void error(int value = FINGERPRINT_ERROR_CANCELED) {
        fingerprint_msg_t message;
        message.type = FINGERPRINT_ERROR;
        message.data.error = value;
        session.notify(&message);
    }
    void authenticated(int id = 7) {
        fingerprint_msg_t message;
        message.type = FINGERPRINT_AUTHENTICATED;
        message.data.authenticated.finger.fid = id;
        message.data.authenticated.hat.value = 42;
        session.notify(&message);
    }
    void oneCancellation() {
        expect(callback->events.size() == 1, "expected exactly one terminal callback");
        expect(callback->events[0].kind == "error" &&
               callback->events[0].error == Error::CANCELED &&
               callback->events[0].vendor == 0, "wrong cancellation event");
    }
};

int main() {
    const std::vector<std::pair<std::string, std::function<void()>>> cases = {
        {"synchronous vendor completion occurs once", [] {
            Fixture f;
            f.vendorAction = [&f] { f.error(); return 0; };
            expect(f.session.cancel().error == 0, "cancel acknowledgement failed");
            f.oneCancellation();
            expect(f.order == std::vector<std::string>({"overlay", "vendor"}),
                   "overlay cleanup must precede the vendor request");
        }},
        {"asynchronous completion waits for vendor", [] {
            Fixture f;
            expect(f.session.cancel().error == 0, "cancel acknowledgement failed");
            expect(f.callback->events.empty(), "request acknowledgement fabricated completion");
            f.error();
            f.oneCancellation();
        }},
        {"cancellation without an overlay handler", [] {
            Fixture f(false);
            expect(f.session.cancel().error == 0, "cancel acknowledgement failed");
            expect(f.callback->events.empty(), "premature completion without an overlay");
            f.error();
            f.oneCancellation();
            expect(f.order == std::vector<std::string>({"vendor"}), "wrong vendor call count");
        }},
        {"vendor failure preserves errno and emits no completion", [] {
            Fixture f;
            f.vendorAction = [] { return -EIO; };
            expect(f.session.cancel().error == -EIO, "vendor failure status was lost");
            expect(f.callback->events.empty(), "failed request fabricated completion");
            expect(f.order == std::vector<std::string>({"overlay", "vendor"}),
                   "cleanup order changed on failure");
        }},
        {"actual vendor error is the only terminal event", [] {
            Fixture f;
            f.vendorAction = [&f] { f.error(FINGERPRINT_ERROR_HW_UNAVAILABLE); return 0; };
            expect(f.session.cancel().error == 0, "cancel acknowledgement failed");
            expect(f.callback->events.size() == 1 &&
                   f.callback->events[0].error == Error::HW_UNAVAILABLE,
                   "real vendor error gained a synthetic cancellation");
        }},
        {"a result racing cancellation is forwarded once", [] {
            Fixture f;
            f.vendorAction = [&f] { f.authenticated(); return 0; };
            expect(f.session.cancel().error == 0, "cancel acknowledgement failed");
            expect(f.callback->events.size() == 1 &&
                   f.callback->events[0].kind == "authenticated" &&
                   f.callback->events[0].id == 7 && f.callback->events[0].token == 42,
                   "terminal result gained another completion");
        }},
        {"next operation notifications remain independent", [] {
            Fixture f;
            expect(f.session.cancel().error == 0, "cancel acknowledgement failed");
            f.error();
            f.oneCancellation();
            f.authenticated(9);
            expect(f.callback->events.size() == 2 &&
                   f.callback->events[1].kind == "authenticated" &&
                   f.callback->events[1].id == 9 && f.session.mLockoutTracker.resets == 1,
                   "the next result was dropped or cancellation completed twice");
        }},
    };
    int passed = 0, failed = 0;
    for (const auto& [name, test] : cases) {
        try {
            test();
            ++passed;
            std::cout << "PASS " << name << '\n';
        } catch (const std::exception& error) {
            ++failed;
            std::cout << "FAIL " << name << ": " << error.what() << '\n';
        }
    }
    std::cout << "passed=" << passed << " failed=" << failed << '\n';
    return failed ? 1 : 0;
}
