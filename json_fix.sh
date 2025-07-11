#!/usr/bin/env bash

# json_fix.sh - Post-process a possibly malformed JSON array produced by other
# scripts. It removes dangling commas, adds a missing closing bracket and
# validates the result with jq.
#
# Usage:  json_fix.sh [INPUT_JSON [OUTPUT_JSON]]
#
# If OUTPUT_JSON is omitted the input file is fixed in-place. A temporary file
# is used so that the original file is only modified when a valid JSON document
# has been produced.

set -euo pipefail

# ---------------------------------------------------------------------------
# 1. Parse arguments
# ---------------------------------------------------------------------------
INPUT=${1:-output.json}
OUTPUT=${2:-"$INPUT"}
TMP=$(mktemp "${OUTPUT}.XXXXXX")

cleanup() { rm -f "$TMP"; }
trap cleanup EXIT

if [[ ! -f "$INPUT" ]]; then
  echo "json_fix: error: input file '$INPUT' does not exist" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "json_fix: error: 'jq' is required but not installed or not in PATH." >&2
  exit 1
fi

echo "Fixing '$INPUT' ..."

# ---------------------------------------------------------------------------
# 2. Remove trailing commas
# ---------------------------------------------------------------------------
# 2.1 Remove a comma at the very end of the file
sed -E '$ s/,[[:space:]]*$//' "$INPUT" > "$TMP"

# 2.2 Remove a comma that appears immediately before the closing bracket
sed -E -i 's/,([[:space:]]*])/\1/' "$TMP"

# ---------------------------------------------------------------------------
# 3. Ensure the JSON array is closed
# ---------------------------------------------------------------------------
if ! tail -c 1 "$TMP" | grep -q ']' ; then
  echo "]" >> "$TMP"
fi

# ---------------------------------------------------------------------------
# 4. Validate and commit
# ---------------------------------------------------------------------------
if jq empty "$TMP" 2>/dev/null; then
  mv "$TMP" "$OUTPUT"
  echo "Fixed and valid JSON written to '$OUTPUT'"
else
  echo "json_fix: warning: unable to automatically repair JSON. See '$TMP'." >&2
  exit 2
fi