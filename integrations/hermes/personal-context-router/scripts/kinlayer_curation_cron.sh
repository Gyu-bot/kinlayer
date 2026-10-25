#!/bin/sh
set -eu
umask 077

: "${HOME:?HOME must be set}"
HERMES_HOME=${HERMES_HOME:-"$HOME/.hermes"}
HERMES_BIN=${HERMES_BIN:-"$HOME/.local/bin/hermes"}
CURATION_LOCK_FILE=${CURATION_LOCK_FILE:-"$HERMES_HOME/.kinlayer-curation.lock"}
export HERMES_HOME

if [ "${1:-}" = "--pcr-locked" ]; then
    shift
    if output=$("$HERMES_BIN" context-router curation --quiet-no-change "$@" 2>&1); then
        exit 0
    else
        status=$?
        [ -z "$output" ] || printf '%s\n' "$output" >&2
        exit "$status"
    fi
fi

[ -d "$HERMES_HOME" ] || {
    printf 'kinlayer curation: HERMES_HOME is not a directory: %s\n' "$HERMES_HOME" >&2
    exit 78
}
[ -x "$HERMES_BIN" ] || {
    printf 'kinlayer curation: HERMES_BIN is not executable: %s\n' "$HERMES_BIN" >&2
    exit 127
}

case $0 in
    /*) script=$0 ;;
    *) script=$(pwd)/$0 ;;
esac

if command -v flock >/dev/null 2>&1; then
    exec flock -n -E 75 "$CURATION_LOCK_FILE" "$script" --pcr-locked "$@"
fi
if command -v lockf >/dev/null 2>&1; then
    exec lockf -k -s -t 0 "$CURATION_LOCK_FILE" "$script" --pcr-locked "$@"
fi

printf 'kinlayer curation: neither flock nor lockf is available\n' >&2
exit 69
