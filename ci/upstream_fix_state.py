#!/usr/bin/env python3
"""Recognize upstream replacements for two small carried userspace fixes.

This only inspects source. apply.sh still applies needed patches exactly and
reports conflicts as errors; a failed patch is never treated as an upstream fix.
"""
import argparse
from pathlib import Path
import re
import subprocess


PERMISSION_PATCH = "bionic/0001-exempt-permissioncontroller-from-rom-hiding.patch"
TRICKYSTORE_PATCH = "frameworks_base/0011-trickystore-current-user-identity.patch"
SOURCES = {
    PERMISSION_PATCH: "libc/bionic/custom_rom_hide.cpp",
    TRICKYSTORE_PATCH: "services/core/java/com/android/server/spoof/AxSpoofManager.java",
}

# Keep offsets stable while ignoring comments and (optionally) string literals.
LEXEMES = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)


def code_only(source, keep_strings=False):
    def replace(match):
        token = match.group()
        if keep_strings and token.startswith(('"', "'")):
            return token
        return re.sub(r"[^\n]", " ", token)
    return LEXEMES.sub(replace, source)


def block_end(code, start):
    """Return the index after a balanced {...} block in masked source."""
    if code[start] != "{":
        raise ValueError("expected a source block")
    depth = 0
    for index in range(start, len(code)):
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
            if not depth:
                return index + 1
    raise ValueError("unbalanced source block")


def method_span(source, name):
    code = code_only(source)
    match = re.search(r"\bboolean\s+" + re.escape(name) + r"\s*\(\s*\)\s*\{", code)
    if not match:
        return None
    start = code.index("{", match.start())
    return match.start(), block_end(code, start)


def permission_state(source):
    if source is None:
        return "obsolete"
    code = code_only(source, keep_strings=True)
    allowlist = re.search(r"\bkAllowlistedPackages\s*\[\s*\]\s*=\s*\{([^}]+)\}", code)
    if not allowlist:
        raise ValueError("ROM-hiding exemption list changed; review the PermissionController patch")
    if '"com.android.permissioncontroller"' in allowlist[1]:
        return "upstream"
    return "needed"


def trickystore_state(source):
    if source is None:
        return "obsolete"
    span = method_span(source, "canReadTrickyStoreKeybox")
    if span is None:
        return "obsolete"
    body = code_only(source[span[0]:span[1]])
    query = r"\bActivityManager\s*\.\s*getCurrentUser\s*\(\s*\)"
    calls = list(re.finditer(query, body))
    if not calls:
        # Includes upstream use of ActivityManagerInternal or a new helper.
        # The obsolete direct Binder call must not be reintroduced by our patch.
        return "upstream"

    protected = []
    uid_reads = list(re.finditer(r"\bBinder\s*\.\s*getCallingUid\s*\(\s*\)", body))
    clear = r"\blong\s+(\w+)\s*=\s*Binder\s*\.\s*clearCallingIdentity\s*\(\s*\)\s*;"
    for match in re.finditer(clear, body):
        # Accept the standard scoped Binder identity idiom, never a clear in
        # another method or a token restored before the protected query.
        begin = re.match(r"\s*try\s*\{", body[match.end():])
        if not begin or not any(read.end() < match.start() for read in uid_reads):
            continue
        start = match.end() + begin.end() - 1
        end = block_end(body, start)
        final = re.match(r"\s*finally\s*\{", body[end:])
        if not final:
            continue
        final_start = end + final.end() - 1
        final_end = block_end(body, final_start)
        restore = r"\s*Binder\s*\.\s*restoreCallingIdentity\s*\(\s*" + re.escape(match[1]) + r"\s*\)\s*;\s*"
        if not re.fullmatch(restore, body[final_start + 1:final_end - 1]):
            continue
        if any(match.end() <= read.start() < end for read in uid_reads):
            continue  # Clearing identity must not replace the original caller UID.
        protected.append((start, end))

    # Evolution could instead use Binder's scoped functional helper.
    clean_call = r"\bBinder\s*\.\s*withCleanCallingIdentity\s*\(\s*\(\s*\)\s*->\s*" + query + r"\s*\)"
    for match in re.finditer(clean_call, body):
        if any(read.end() < match.start() for read in uid_reads):
            protected.append(match.span())

    if all(any(start <= call.start() and call.end() <= end for start, end in protected)
           for call in calls):
        return "upstream"
    return "needed"


def state(patch, source):
    if patch == PERMISSION_PATCH:
        return permission_state(source)
    if patch == TRICKYSTORE_PATCH:
        return trickystore_state(source)
    raise ValueError("not a guarded patch: " + patch)


def read_source(project, relative, ref=None):
    if ref:
        # An empty, successful ls-tree means this implementation was removed.
        found = subprocess.check_output(
            ["git", "-C", str(project), "ls-tree", "--name-only", ref, "--", relative],
            text=True)
        if not found.strip():
            return None
        return subprocess.check_output(
            ["git", "-C", str(project), "show", f"{ref}:{relative}"], text=True)
    path = project / relative
    return path.read_text() if path.is_file() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("patch", choices=SOURCES)
    parser.add_argument("project", type=Path)
    parser.add_argument("--ref", help="Inspect a committed snapshot, e.g. HEAD, without changing it")
    args = parser.parse_args()
    try:
        print(state(args.patch, read_source(args.project, SOURCES[args.patch], args.ref)))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"upstream fix check failed: {error}\n")


if __name__ == "__main__":
    main()
