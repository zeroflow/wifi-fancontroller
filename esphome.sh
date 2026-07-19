#!/bin/bash
# Run ESPHome from the official image against this directory.
#
# The image tag is pinned through ESPHOME_VERSION so a run states which version
# it used. Without it the untagged image resolves to whatever "latest" happened
# to be cached locally, which can be months old, and a green sweep then says
# nothing about the version you meant to test.
#
#   ./esphome.sh config examples/basic-rev-3.1.yaml
#   ESPHOME_VERSION=2026.7.0 ./esphome.sh compile fancontroller-rev3.3-esp32s2.yaml
#
# A TTY is only allocated when stdin actually is one. Forcing -it makes docker
# abort with "the input device is not a TTY" whenever this is called from a
# script or any non-interactive shell, which is how test-examples.sh calls it.
ESPHOME_VERSION="${ESPHOME_VERSION:-latest}"
IMAGE="ghcr.io/esphome/esphome:${ESPHOME_VERSION}"

# Report the resolved version once per run, on stderr so it never lands in a
# config dump that gets piped or diffed.
echo "esphome.sh: using ${IMAGE}" >&2

if [ -t 0 ]; then
  docker run --rm -v "${PWD}":/config -it "${IMAGE}" "$@"
else
  docker run --rm -v "${PWD}":/config -i "${IMAGE}" "$@"
fi
