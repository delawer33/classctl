#!/bin/sh
# Parameterizable fake script for integration tests.
#
# Usage: fake_script.sh [--sleep N] [--exit-code N] [--output-pattern PATTERN]
#
# --sleep N          Sleep N seconds before finishing (default 0)
# --exit-code N      Exit with code N (default 0); ignored by classctl but
#                    available so tests can verify we really ignore it
# --output-pattern X Emit a line containing X to stdout (default: none)
#                    Use "error" to trigger the error detector

SLEEP=0
EXIT_CODE=0
OUTPUT_PATTERN=""
STDERR_PATTERN=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --sleep)          SLEEP="$2";          shift 2 ;;
    --exit-code)      EXIT_CODE="$2";      shift 2 ;;
    --output-pattern) OUTPUT_PATTERN="$2"; shift 2 ;;
    --stderr-pattern) STDERR_PATTERN="$2"; shift 2 ;;
    *) shift ;;
  esac
done

echo "fake_script: starting"

if [ -n "$OUTPUT_PATTERN" ]; then
  echo "fake_script: $OUTPUT_PATTERN"
fi

if [ -n "$STDERR_PATTERN" ]; then
  echo "fake_script: $STDERR_PATTERN" >&2
fi

sleep "$SLEEP"

echo "fake_script: done"
exit "$EXIT_CODE"
