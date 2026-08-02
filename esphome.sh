#!/bin/bash
# Run ESPHome from the official image against this directory.
#
# The version defaults to the release pin read from publish-firmware.yml, so a
# run states which version it used without anyone needing to remember to set
# one. ESPHOME_VERSION remains the override for trying another release.
#
#   ./esphome.sh config examples/basic-rev-3.1.yaml
#   ESPHOME_VERSION=2026.7.2 ./esphome.sh compile fancontroller-rev3.3-esp32s2.yaml
#
# When the esphome CLI is already on PATH, which is the case inside the
# official ESPHome image and therefore inside a CI container job, this script
# runs it directly instead of starting a nested container.
#
# A TTY is only allocated when stdin actually is one. Forcing -it makes docker
# abort with "the input device is not a TTY" whenever this is called from a
# script or any non-interactive shell, which is how test-examples.sh calls it.

# Resolve PIN_FILE relative to this script's own location, not $PWD. This
# script must NOT cd, because it bind-mounts "${PWD}" into the container as
# /config and changing the working directory would silently change what gets
# mounted.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIN_FILE="${SCRIPT_DIR}/.github/workflows/publish-firmware.yml"

if [ -n "${ESPHOME_VERSION:-}" ]; then
  echo "esphome.sh: using ESPHome ${ESPHOME_VERSION} (from ESPHOME_VERSION)" >&2
else
  if [ ! -f "$PIN_FILE" ]; then
    echo "ABORT: $PIN_FILE not found, cannot resolve the ESPHome version." >&2
    echo "Set ESPHOME_VERSION explicitly to proceed." >&2
    exit 1
  fi

  PINNED="$(grep -E '^[[:space:]]*esphome-version:' "$PIN_FILE" \
    | head -1 | sed -E 's/.*esphome-version:[[:space:]]*//' | tr -d '"'"'"' \r')"

  # Deliberately strict. Anything that is not a plain N.N.N means the file moved
  # on and the fallback would be a guess, so refuse rather than test the wrong
  # version silently.
  if ! echo "$PINNED" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "ABORT: could not read a version-shaped esphome-version: from $PIN_FILE" >&2
    echo "Got: '${PINNED}'" >&2
    echo "Set ESPHOME_VERSION explicitly to proceed." >&2
    exit 1
  fi

  ESPHOME_VERSION="$PINNED"
  echo "esphome.sh: using ESPHome ${ESPHOME_VERSION} (release pin from ${PIN_FILE})" >&2
fi

# In-container passthrough: when the esphome CLI is directly runnable, run it
# in place of starting a nested docker container. A GitHub Actions container:
# job has no Docker daemon, so docker run cannot work there and does not need
# to. Detected by testing whether the binary is actually runnable, not by
# probing for a CI environment variable or /.dockerenv.
if command -v esphome >/dev/null 2>&1; then
  echo "esphome.sh: using the esphome binary on PATH directly (ESPHome ${ESPHOME_VERSION})" >&2
  exec esphome "$@"
fi

IMAGE="ghcr.io/esphome/esphome:${ESPHOME_VERSION}"

# Report the resolved version once per run, on stderr so it never lands in a
# config dump that gets piped or diffed.
echo "esphome.sh: using ${IMAGE}" >&2

if [ -t 0 ]; then
  docker run --rm -v "${PWD}":/config -it "${IMAGE}" "$@"
else
  docker run --rm -v "${PWD}":/config -i "${IMAGE}" "$@"
fi
