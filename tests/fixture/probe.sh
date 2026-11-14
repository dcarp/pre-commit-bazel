#!/usr/bin/env bash
# Bazel runfiles initialization v3.
set -uo pipefail
set +e
f=bazel_tools/tools/bash/runfiles/runfiles.bash
source "${RUNFILES_DIR:-/dev/null}/$f" 2>/dev/null ||
    source "$(grep -sm1 "^$f " "${RUNFILES_MANIFEST_FILE:-/dev/null}" | cut -f2- -d' ')" 2>/dev/null ||
    source "$0.runfiles/$f" 2>/dev/null ||
    source "$(grep -sm1 "^$f " "$0.runfiles_manifest" | cut -f2- -d' ')" 2>/dev/null ||
    source "$(grep -sm1 "^$f " "$0.exe.runfiles_manifest" | cut -f2- -d' ')" 2>/dev/null ||
    { printf 'ERROR: cannot find %s\n' "$f" >&2; exit 1; }
unset f
set -eE
trap 'printf "Probe failed at line %s (cwd=%s), arguments:\n" "$LINENO" "$PWD" >&2; printf "<%s>\n" "$@" >&2' ERR
[[ -f MODULE.bazel ]]
[[ "$(cat "$(rlocation _main/message.txt)")" == 'runfiles fixture' ]]
[[ "$#" -eq 3 && "$1" == '--from-target' && "$2" == '--check' && "$3" == 'file with spaces.txt' ]]
[[ "$(cat "$3")" == fixture ]]
printf '%s\n' 'Managed probe executed successfully.'
