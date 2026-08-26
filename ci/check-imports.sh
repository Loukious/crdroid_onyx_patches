#!/usr/bin/env bash
#
# Post-apply symbol check -- catches "the port imports an API this tree does not
# have" in ~10 seconds, instead of ~4 hours into a crave compile.
#
# Real case it was written for (crave build 295615): the Now Playing port came
# from Evolution-X, whose plugin API has BaseLockscreenElement.ElementSource.
# crDroid's tree predates that nested type, so SystemUI-core died at 38% with
#   error: symbol not found ...BaseLockscreenElement$ElementSource
# after a 3h queue wait plus a 4h build.
#
# Method: build one index of every simple name DECLARED in the tree, then check
# every in-tree-namespace `import` the patch set ADDS against that index. It is
# deliberately name-based (not full resolution) -- cheap, and it catches the
# entire "symbol does not exist here" class.
#
# Usage: ci/check-imports.sh /path/to/rom
#
set -uo pipefail

ROM="${1:-.}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCHDIR="$(dirname "$HERE")/patches"
INDEX_DIRS="${INDEX_DIRS:-frameworks packages}"
ALLOW="$HERE/import-allowlist.txt"

red() { printf '\033[0;31m%s\033[0m\n' "$*"; }
ylw() { printf '\033[0;33m%s\033[0m\n' "$*"; }
grn() { printf '\033[0;32m%s\033[0m\n' "$*"; }

cd "$ROM" || { red "FATAL: no such tree: $ROM"; exit 1; }
[ -d "$PATCHDIR" ] || { red "FATAL: no patches dir at $PATCHDIR"; exit 1; }

idx="$(mktemp)"; imps="$(mktemp)"
trap 'rm -f "$idx" "$imps"' EXIT

dirs=()
for d in $INDEX_DIRS; do [ -d "$d" ] && dirs+=("$d"); done
[ "${#dirs[@]}" -gt 0 ] || { red "FATAL: none of INDEX_DIRS ($INDEX_DIRS) exist under $PWD"; exit 1; }

# --- 1. index every declared simple name -------------------------------------
{
  grep -rhoE '(class|interface|object|enum class|typealias|annotation class|@interface) +[A-Za-z_][A-Za-z0-9_]*' \
    --include=*.kt --include=*.java "${dirs[@]}" 2>/dev/null | awk '{print $NF}'
  # top-level functions, with or without an extension receiver
  grep -rhoE 'fun +([A-Za-z0-9_<>,.?]+\.)?[A-Za-z_][A-Za-z0-9_]*' \
    --include=*.kt "${dirs[@]}" 2>/dev/null | sed -E 's/^fun +//; s/^.*\.//'
  grep -rhoE '(val|var|const val) +[A-Za-z_][A-Za-z0-9_]*' \
    --include=*.kt "${dirs[@]}" 2>/dev/null | awk '{print $NF}'
} | sort -u > "$idx"
echo "indexed $(wc -l < "$idx") declared symbols from: ${dirs[*]}"

# --- 2. every in-tree-namespace import the patch set adds --------------------
grep -rh '^+import ' "$PATCHDIR" 2>/dev/null \
  | sed 's/^+import //; s/;[[:space:]]*$//; s/[[:space:]]*$//; s/ as .*//' \
  | grep -E '^(com\.android|com\.google\.android)' \
  | grep -vE '\.(R|BuildConfig)$' \
  | grep -vE '\*$' \
  | sort -u > "$imps"
echo "checking $(wc -l < "$imps") in-tree imports added by the patch set"

# --- 3. compare ---------------------------------------------------------------
miss=0
while read -r fq; do
    [ -n "$fq" ] || continue
    sym="${fq##*.}"
    grep -qx "$sym" "$idx" && continue
    if [ -f "$ALLOW" ] && grep -qxF "$fq" "$ALLOW"; then
        ylw "  allowlisted (generated at build time): $fq"
        continue
    fi
    red "  UNRESOLVED: $fq"
    red "              '$sym' is declared nowhere under ${dirs[*]}"
    miss=$((miss+1))
done < "$imps"

echo
if [ "$miss" -eq 0 ]; then
    grn "IMPORT CHECK PASSED: every symbol the patch set imports exists in this tree."
    exit 0
fi
red "IMPORT CHECK FAILED: $miss unresolved import(s)."
ylw "This is the ElementSource class of failure: the patch was written against a"
ylw "newer/other ROM's API. Either backport the missing declaration, or drop the"
ylw "reference from the patch. Fix it now -- the compile would fail hours from now."
exit 1
