#!/bin/bash
# Validate the examples against the working tree.
#
# The files in examples/ reference this repository over github://...@main, so
# testing them directly validates the published version and not the code on
# disk. tools/localize-examples.py rewrites those references to local !include
# and writes the result to .test-build/, which is what this script tests.
#
# Usage:
#   ./test-examples.sh                  config only, all examples. Fast loop.
#   ./test-examples.sh --compile        config then compile, all examples
#   ./test-examples.sh --compile NAME   config then compile, one example
#
# NAME accepts either a bare name or a filename, for example
# with-usr-buttons-rev-3.1 or with-usr-buttons-rev-3.1.yaml
#
# The ESPHome version defaults to the pin that ships to customer hardware, read
# from .github/workflows/publish-firmware.yml. Override it to test another:
#
#   ESPHOME_VERSION=beta ./test-examples.sh
#   ESPHOME_VERSION=latest ./test-examples.sh

set -u

cd "$(dirname "$0")" || exit 1

# Resolve the ESPHome version before anything runs. esphome.sh defaults to
# "latest", which is whatever the local docker cache happens to hold, so an
# unpinned sweep tests an unknown version. That is not hypothetical: a stale
# 2026.2.4 once failed an example on a CMake error while the shipped pin built
# it clean. A red sweep meaning "your cache is old" must not be indistinguishable
# from one meaning "you broke a module".
#
# publish-firmware.yml is the single source of truth for the pin. ci.yml and
# esphome-version-check.yml both parse it rather than duplicating the literal,
# and so does this. A targeted grep keeps the script free of a PyYAML dependency
# it would otherwise abort on. The version-shape check below is what makes that
# safe: if the file's layout changes, this fails loudly instead of quietly
# picking up the wrong value.
PIN_FILE=".github/workflows/publish-firmware.yml"

if [ -n "${ESPHOME_VERSION:-}" ]; then
  echo "=== ESPHome ${ESPHOME_VERSION} (from ESPHOME_VERSION)"
else
  if [ ! -f "$PIN_FILE" ]; then
    echo "ABORT: $PIN_FILE not found, cannot resolve the ESPHome version."
    echo "Set ESPHOME_VERSION explicitly to proceed."
    exit 1
  fi

  PINNED="$(grep -E '^[[:space:]]*esphome-version:' "$PIN_FILE" \
    | head -1 | sed -E 's/.*esphome-version:[[:space:]]*//' | tr -d '"'"'"' \r')"

  # Deliberately strict. Anything that is not a plain N.N.N means the file moved
  # on and the fallback would be a guess, so refuse rather than test the wrong
  # version silently.
  if ! echo "$PINNED" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "ABORT: could not read a version-shaped esphome-version: from $PIN_FILE"
    echo "Got: '${PINNED}'"
    echo "Set ESPHOME_VERSION explicitly to proceed."
    exit 1
  fi

  export ESPHOME_VERSION="$PINNED"
  echo "=== ESPHome ${ESPHOME_VERSION} (release pin from $PIN_FILE)"
fi

COMPILE=0
SELECT=""

for arg in "$@"; do
  case "$arg" in
    --compile)
      COMPILE=1
      ;;
    -*)
      echo "Unknown option: $arg"
      echo "Usage: ./test-examples.sh [--compile] [example-name]"
      exit 2
      ;;
    *)
      SELECT="${arg%.yaml}"
      ;;
  esac
done

# Step 1: regenerate .test-build/. A failed transform must never fall through
# into a test run against stale generated files.
echo "=== Generating .test-build/ from examples/"
if ! python3 tools/localize-examples.py; then
  echo ""
  echo "ABORT: tools/localize-examples.py failed. Not testing stale files."
  exit 1
fi

# Step 2: ESPHome resolves !secret relative to the main config directory.
if [ ! -f .test-build/secrets.yaml ]; then
  echo "Writing a dummy .test-build/secrets.yaml"
  echo 'wifi_ssid: "dummy-ssid"' > .test-build/secrets.yaml
  echo 'wifi_password: "dummy-password"' >> .test-build/secrets.yaml
fi

# Step 3: build the list of examples to test.
ALL_NAMES=()
for f in .test-build/*.yaml; do
  b="$(basename "$f")"
  [ "$b" = "secrets.yaml" ] && continue
  ALL_NAMES+=("${b%.yaml}")
done

if [ ${#ALL_NAMES[@]} -eq 0 ]; then
  echo "ABORT: no generated configs found in .test-build/"
  exit 1
fi

NAMES=()
if [ -n "$SELECT" ]; then
  for n in "${ALL_NAMES[@]}"; do
    if [ "$n" = "$SELECT" ]; then
      NAMES+=("$n")
    fi
  done
  if [ ${#NAMES[@]} -eq 0 ]; then
    echo ""
    echo "ERROR: no example named '$SELECT'."
    echo "Valid names:"
    for n in "${ALL_NAMES[@]}"; do echo "  $n"; done
    exit 1
  fi
else
  NAMES=("${ALL_NAMES[@]}")
fi

echo "Testing ${#NAMES[@]} example(s)"
echo ""

# Step 4: config phase. Fresh counters.
CONFIG_PASS=0
CONFIG_FAIL=0
CONFIG_FAILURES=()

echo "=== Config phase"
for n in "${NAMES[@]}"; do
  echo "--- config: $n"
  if ./esphome.sh config ".test-build/$n.yaml"; then
    CONFIG_PASS=$((CONFIG_PASS + 1))
  else
    CONFIG_FAIL=$((CONFIG_FAIL + 1))
    CONFIG_FAILURES+=("$n")
  fi
done

echo ""
echo "Config phase results: $CONFIG_PASS passed, $CONFIG_FAIL failed"
if [ ${#CONFIG_FAILURES[@]} -gt 0 ]; then
  echo "Failed:"
  for n in "${CONFIG_FAILURES[@]}"; do echo "  $n"; done
fi

# The compile phase is strictly conditional on a clean config phase. Compiling
# a config that does not even validate only produces noise.
if [ $CONFIG_FAIL -gt 0 ]; then
  echo ""
  echo "Config phase failed, skipping compile phase."
  exit 1
fi

if [ $COMPILE -eq 0 ]; then
  echo ""
  echo "Config phase passed. Pass --compile to also build."
  exit 0
fi

# Step 5: compile phase. Its own fresh counters and its own failure list, so
# the two phases can never be summed into one meaningless number.
COMPILE_PASS=0
COMPILE_FAIL=0
COMPILE_FAILURES=()

echo ""
echo "=== Compile phase"
for n in "${NAMES[@]}"; do
  echo "--- compile: $n"
  if ./esphome.sh compile ".test-build/$n.yaml"; then
    COMPILE_PASS=$((COMPILE_PASS + 1))
  else
    COMPILE_FAIL=$((COMPILE_FAIL + 1))
    COMPILE_FAILURES+=("$n")
  fi
done

echo ""
echo "Compile phase results: $COMPILE_PASS passed, $COMPILE_FAIL failed"
if [ ${#COMPILE_FAILURES[@]} -gt 0 ]; then
  echo "Failed:"
  for n in "${COMPILE_FAILURES[@]}"; do echo "  $n"; done
  exit 1
fi

echo ""
echo "All phases passed."
exit 0
