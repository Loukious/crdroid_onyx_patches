#!/usr/bin/env python3
"""
Filter a unified diff hunk-by-hunk.

Needed because two unrelated features edit the same file:
core/java/android/provider/Settings.java gains one constant block for the
gesture navbar space mode. `git diff -- <file>`
cannot split those, and letting both patches carry the whole file diff would
make apply.sh's reverse-check ambiguous (a patch that is half-applied neither
applies nor reverse-applies, so it becomes a hard error).

Reads a diff on stdin, writes the filtered diff on stdout. A per-file header
(`diff --git`, `index`, `---`, `+++`, and any `old mode`/`new file` lines) is
emitted only if at least one of that file's hunks survives, so a file whose
every hunk is dropped disappears cleanly.

  --keep REGEX   keep only hunks whose body matches REGEX
  --drop REGEX   drop hunks whose body matches REGEX
Both may be given; --drop is applied after --keep.
"""
import argparse
import re
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--keep')
    ap.add_argument('--drop')
    args = ap.parse_args()
    keep = re.compile(args.keep) if args.keep else None
    drop = re.compile(args.drop) if args.drop else None

    lines = sys.stdin.read().splitlines(keepends=True)
    out = []
    header = []          # pending per-file header
    header_written = False
    hunk = []

    def flush_hunk():
        nonlocal hunk, header, header_written
        if not hunk:
            return
        body = ''.join(hunk)
        wanted = True
        if keep and not keep.search(body):
            wanted = False
        if wanted and drop and drop.search(body):
            wanted = False
        if wanted:
            if not header_written:
                out.extend(header)
                header_written = True
            out.extend(hunk)
        hunk = []

    for line in lines:
        if line.startswith('diff --git '):
            flush_hunk()
            header = [line]
            header_written = False
        elif line.startswith('@@'):
            flush_hunk()
            hunk = [line]
        elif hunk:
            hunk.append(line)
        else:
            header.append(line)
    flush_hunk()

    sys.stdout.write(''.join(out))


if __name__ == '__main__':
    main()
