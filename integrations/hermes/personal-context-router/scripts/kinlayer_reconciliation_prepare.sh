#!/bin/sh
set -eu
umask 077

: "${HOME:?HOME must be set}"
HERMES_HOME=${HERMES_HOME:-"$HOME/.hermes"}
HERMES_BIN=${HERMES_BIN:-"$HOME/.local/bin/hermes"}
RECONCILIATION_LOCK_FILE=${RECONCILIATION_LOCK_FILE:-"$HERMES_HOME/.kinlayer-reconciliation.lock"}
export HERMES_HOME

if [ "${1:-}" = "--pcr-locked" ]; then
    shift
    exec "$HERMES_BIN" context-router reconciliation-prepare "$@"
fi

[ -d "$HERMES_HOME" ] || {
    printf 'kinlayer reconciliation: HERMES_HOME is not a directory: %s\n' "$HERMES_HOME" >&2
    exit 78
}
[ -x "$HERMES_BIN" ] || {
    printf 'kinlayer reconciliation: HERMES_BIN is not executable: %s\n' "$HERMES_BIN" >&2
    exit 127
}

case $0 in
    /*) script=$0 ;;
    *) script=$(pwd)/$0 ;;
esac

if command -v flock >/dev/null 2>&1; then
    exec flock -n -E 75 "$RECONCILIATION_LOCK_FILE" "$script" --pcr-locked "$@"
fi
if command -v lockf >/dev/null 2>&1; then
    exec lockf -k -s -t 0 "$RECONCILIATION_LOCK_FILE" "$script" --pcr-locked "$@"
fi

printf 'kinlayer reconciliation: neither flock nor lockf is available\n' >&2
exit 69
