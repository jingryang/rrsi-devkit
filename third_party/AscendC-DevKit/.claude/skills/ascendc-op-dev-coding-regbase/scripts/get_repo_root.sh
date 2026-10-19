#!/bin/bash
# Resolve the repository root without assuming how deeply this portable skill
# is installed.  Optional injection is accepted only when it names a real dir.
set -uo pipefail

injected=""
if [ "${1:-}" = "--inject" ]; then
    injected="${2:-}"
    shift 2
fi
start="${1:-$PWD}"

if [ -n "$injected" ] && [ -d "$injected" ]; then
    (cd "$injected" && pwd -P)
    exit 0
fi

if [ -f "$start" ]; then
    start=$(dirname "$start")
fi
if [ ! -d "$start" ]; then
    exit 1
fi
start=$(cd "$start" && pwd -P)

if command -v git >/dev/null 2>&1; then
    root=$(git -C "$start" rev-parse --show-toplevel 2>/dev/null || true)
    if [ -n "$root" ] && [ -d "$root" ]; then
        printf '%s\n' "$root"
        exit 0
    fi
fi

cursor="$start"
while [ "$cursor" != "/" ]; do
    if [ -f "$cursor/CLAUDE.md" ] || [ -d "$cursor/.claude" ]; then
        printf '%s\n' "$cursor"
        exit 0
    fi
    cursor=$(dirname "$cursor")
done
exit 1
