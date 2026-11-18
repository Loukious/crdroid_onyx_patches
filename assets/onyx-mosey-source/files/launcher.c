/* SPDX-License-Identifier: Apache-2.0 */
#include <android/log.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define MOSEY_SERVER "/system_ext/bin/mosey_server"
#define MOSEY_CONFIG "/system_ext/lib64/libmosey_onyx_config.so"

int main(int argc, char **argv)
{
    (void)argc;

    /* Init enters mosey_server through this executable with AT_SECURE set.
     * Install the process-local environment after that transition, then exec
     * the daemon in the same domain, UID and ambient capability set. Neither
     * executable has set-ID bits or file capabilities. The second exec does
     * not elevate privileges, so its linker can load our configuration library.
     */
    if (setenv("LD_PRELOAD", MOSEY_CONFIG, 1) ||
        setenv("KONOHA_MOSEY_WONDER", "1", 1)) {
        __android_log_print(ANDROID_LOG_ERROR, "MoseyOnyx",
                            "Cannot configure native Mosey: %s", strerror(errno));
        return 1;
    }

    argv[0] = MOSEY_SERVER;
    execv(MOSEY_SERVER, argv);
    __android_log_print(ANDROID_LOG_ERROR, "MoseyOnyx",
                        "Cannot start native Mosey: %s", strerror(errno));
    return 1;
}
