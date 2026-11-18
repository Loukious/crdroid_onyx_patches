// SPDX-License-Identifier: Apache-2.0
// Preserve the live policy and grant only Mosey's link and neighbor messages.
// KernelSU's current allowxperm writer incorrectly encodes nlmsg as ioctl.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>
#include <sepol/policydb/avtab.h>
#include <sepol/policydb/ebitmap.h>
#include <sepol/policydb/hashtab.h>
#include <sepol/policydb/polcaps.h>
#include <sepol/policydb/policydb.h>

#define POLICY_PATH "/sys/fs/selinux/policy"
#define LOAD_PATH "/sys/fs/selinux/load"
#define MAX_POLICY_SIZE (64U * 1024U * 1024U)
#define GETLINK_BIT (UINT32_C(1) << 18)
#define SETLINK_BIT (UINT32_C(1) << 19)
#define NEWNEIGH_BIT (UINT32_C(1) << 28)
#define DELNEIGH_BIT (UINT32_C(1) << 29)
#define GETNEIGH_BIT (UINT32_C(1) << 30)
#define REQUIRED_NLMSG_BITS (GETLINK_BIT | SETLINK_BIT | NEWNEIGH_BIT | DELNEIGH_BIT | GETNEIGH_BIT)

static void die(const char *message) {
    fprintf(stderr, "onyx-mosey-nlmsg: %s\n", message);
    exit(1);
}

static void die_errno(const char *message) {
    fprintf(stderr, "onyx-mosey-nlmsg: %s: %s\n", message, strerror(errno));
    exit(1);
}

static void *read_image(const char *path, size_t *length) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) die_errno("open policy");
    size_t capacity = 4U * 1024U * 1024U;
    size_t used = 0;
    unsigned char *data = malloc(capacity);
    if (!data) die("out of memory");
    for (;;) {
        if (used == capacity) {
            if (capacity >= MAX_POLICY_SIZE) die("policy exceeds size limit");
            capacity *= 2;
            unsigned char *larger = realloc(data, capacity);
            if (!larger) die("out of memory");
            data = larger;
        }
        ssize_t n = read(fd, data + used, capacity - used);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) die_errno("read policy");
        if (!n) break;
        used += (size_t)n;
    }
    if (close(fd)) die_errno("close policy");
    if (!used) die("empty policy");
    *length = used;
    return data;
}

static int enforcing(void) {
    char value;
    int fd = open("/sys/fs/selinux/enforce", O_RDONLY | O_CLOEXEC);
    if (fd < 0) die_errno("open enforcing state");
    ssize_t n = read(fd, &value, 1);
    close(fd);
    return n == 1 && value == '1';
}

static int exact_setlink(const avtab_extended_perms_t *x) {
    if (!x || x->driver != 0 || x->perms[0] != SETLINK_BIT) return 0;
    for (size_t i = 1; i < 8; ++i) if (x->perms[i]) return 0;
    return 1;
}

static avtab_key_t target_key(policydb_t *p, uint16_t specified,
                              uint32_t *nlmsg_mask) {
    type_datum_t *type = hashtab_search(p->p_types.table, "mosey_server");
    class_datum_t *cls = hashtab_search(p->p_classes.table, "netlink_route_socket");
    if (!type || type->flavor != TYPE_TYPE || !cls)
        die("expected Mosey domain or route socket class is absent");
    perm_datum_t *perm = hashtab_search(cls->permissions.table, "nlmsg");
    if (!perm && cls->comdatum)
        perm = hashtab_search(cls->comdatum->permissions.table, "nlmsg");
    if (!perm || perm->s.value < 1 || perm->s.value > 32)
        die("nlmsg permission is absent or invalid");
    if (!ebitmap_get_bit(&p->policycaps, POLICYDB_CAP_NETLINK_XPERM))
        die("policy does not enable netlink_xperm");
    if (p->policy_type != POLICY_KERN || p->policyvers < POLICYDB_VERSION_XPERMS_IOCTL)
        die("unsupported policy format");
    *nlmsg_mask = UINT32_C(1) << (perm->s.value - 1);
    avtab_key_t key = {type->s.value, type->s.value, cls->s.value, specified};
    return key;
}

static int patch_policy(policydb_t *p) {
    uint32_t mask;
    avtab_key_t key = target_key(p, AVTAB_ALLOWED, &mask);
    avtab_datum_t *base = avtab_search(&p->te_avtab, &key);
    int changed = 0;
    if (!base) {
        avtab_datum_t datum = {.data = mask, .xperms = NULL};
        if (avtab_insert(&p->te_avtab, &key, &datum)) die("insert base permission failed");
        changed = 1;
    } else if (!(base->data & mask)) {
        base->data |= mask;
        changed = 1;
    }
    key.specified = AVTAB_XPERMS_ALLOWED;
    avtab_ptr_t nlmsg = NULL, mistaken_ioctl = NULL;
    uint32_t permitted = 0;
    for (avtab_ptr_t n = avtab_search_node(&p->te_avtab, &key); n;
         n = avtab_search_node_next(n, AVTAB_XPERMS_ALLOWED)) {
        avtab_extended_perms_t *x = n->datum.xperms;
        if (x && x->specified == AVTAB_XPERMS_NLMSG && x->driver == 0) {
            permitted |= x->perms[0];
            if (!nlmsg) nlmsg = n;
        }
        if (x && x->specified == AVTAB_XPERMS_IOCTLFUNCTION && exact_setlink(x))
            mistaken_ioctl = n;
    }
    if ((permitted & REQUIRED_NLMSG_BITS) == REQUIRED_NLMSG_BITS) return changed;
    uint32_t missing = REQUIRED_NLMSG_BITS & ~permitted;
    if (mistaken_ioctl && !nlmsg) {
        // Correct only the exact one-bit rule produced by the ksud bug.
        mistaken_ioctl->datum.xperms->specified = AVTAB_XPERMS_NLMSG;
        mistaken_ioctl->datum.xperms->perms[0] |= missing;
    } else if (nlmsg) {
        nlmsg->datum.xperms->perms[0] |= missing;
    } else {
        avtab_extended_perms_t x = {
            .specified = AVTAB_XPERMS_NLMSG, .driver = 0,
            .perms = {missing, 0, 0, 0, 0, 0, 0, 0}
        };
        avtab_datum_t datum = {.data = 0, .xperms = &x};
        if (!avtab_insert_nonunique(&p->te_avtab, &key, &datum))
            die("insert nlmsg extended permission failed");
    }
    return 1;
}

static void validate_image(policydb_t *before, void *data, size_t length) {
    policydb_t after;
    if (policydb_init(&after)) die("initialize validation policy failed");
    if (policydb_from_image(NULL, data, length, &after)) die("invalid output policy");
    if (before->policyvers != after.policyvers ||
        before->policy_type != after.policy_type ||
        before->mls != after.mls ||
        before->handle_unknown != after.handle_unknown ||
        !ebitmap_cmp(&before->policycaps, &after.policycaps) ||
        !ebitmap_cmp(&before->permissive_map, &after.permissive_map))
        die("output changed policy metadata");
    // Idempotence confirms the base permission and all five NLMSG bits survived.
    if (patch_policy(&after)) die("output is missing the intended permission");
    policydb_destroy(&after);
}

static void write_output(const char *path, const void *data, size_t length) {
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd < 0) die_errno("open output");
    size_t done = 0;
    while (done < length) {
        ssize_t n = write(fd, (const unsigned char *)data + done, length - done);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) die_errno("write output");
        done += (size_t)n;
    }
    if (fsync(fd) || close(fd)) die_errno("finish output");
}

int main(int argc, char **argv) {
    int live = argc == 2 && !strcmp(argv[1], "--apply");
    if (!live && argc != 3) {
        fprintf(stderr, "Usage: %s INPUT OUTPUT | --apply\n", argv[0]);
        return 2;
    }
    int lock = -1;
    if (live) {
        if (geteuid() != 0 || !enforcing()) die("requires root and enforcing SELinux");
        lock = open("/data/adb/onyx-mosey-policy.lock",
                    O_WRONLY | O_CREAT | O_CLOEXEC | O_NOFOLLOW, 0600);
        if (lock < 0 || flock(lock, LOCK_EX)) die_errno("lock policy update");
    }
    size_t input_size;
    void *input = read_image(live ? POLICY_PATH : argv[1], &input_size);
    policydb_t policy;
    if (policydb_init(&policy)) die("initialize policy failed");
    if (policydb_from_image(NULL, input, input_size, &policy)) die("invalid input policy");
    int changed = patch_policy(&policy);
    void *output = NULL;
    size_t output_size = input_size;
    if (changed) {
        if (policydb_to_image(NULL, &policy, &output, &output_size))
            die("serialize policy failed");
        validate_image(&policy, output, output_size);
    } else {
        output = input;
    }
    if (live && changed) {
        size_t latest_size;
        void *latest = read_image(POLICY_PATH, &latest_size);
        if (latest_size != input_size || memcmp(latest, input, input_size))
            die("live policy changed; retry instead of overwriting concurrent changes");
        free(latest);
        if (!enforcing()) die("SELinux enforcing state changed");
        int fd = open(LOAD_PATH, O_WRONLY | O_CLOEXEC);
        if (fd < 0) die_errno("open policy loader");
        // selinuxfs requires the entire policy image in one write.
        ssize_t n;
        do { n = write(fd, output, output_size); } while (n < 0 && errno == EINTR);
        if (n < 0) die_errno("load policy");
        if ((size_t)n != output_size) die("short policy load");
        close(fd);
        if (!enforcing()) die("SELinux is no longer enforcing");
        size_t loaded_size;
        void *loaded = read_image(POLICY_PATH, &loaded_size);
        validate_image(&policy, loaded, loaded_size);
        free(loaded);
    } else if (!live) {
        write_output(argv[2], output, output_size);
    }
    printf("onyx-mosey-nlmsg: %s; domain=mosey_server class=netlink_route_socket nlmsg=18,19,28,29,30 policyvers=%u\n",
           changed ? "updated" : "already present", policy.policyvers);
    policydb_destroy(&policy);
    if (output != input) free(output);
    free(input);
    if (lock >= 0) close(lock);
    return 0;
}
