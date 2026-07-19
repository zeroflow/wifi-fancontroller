#!/bin/bash
# Run ESPHome from the official image against this directory.
#
# A TTY is only allocated when stdin actually is one. Forcing -it makes docker
# abort with "the input device is not a TTY" whenever this is called from a
# script or any non-interactive shell, which is how test-examples.sh calls it.
if [ -t 0 ]; then
  docker run --rm -v "${PWD}":/config -it ghcr.io/esphome/esphome "$@"
else
  docker run --rm -v "${PWD}":/config -i ghcr.io/esphome/esphome "$@"
fi
