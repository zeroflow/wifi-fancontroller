#!/usr/bin/env python3
"""Build the Rev 3.2 HIL commit image from the working tree.

Runs inside the pinned ESPHome container (ghcr.io/esphome/esphome:<pin>), stdlib
only, from the repository root:

    docker run --rm -v "$PWD":/repo -w /repo --entrypoint python3 \\
        ghcr.io/esphome/esphome:2026.10.1 \\
        hil/tools/build_image.py --out hil-out --commit "$(git rev-parse HEAD)"

Output, and nothing else, in --out:

    firmware.factory.bin   the image the hil job flashes at offset 0x0
    manifest.json          schema 1: commit, build_id, sha256, chip, offset, ...

What it does:

 1. Localizes fancontroller-rev3.2-esp32s2.yaml with tools/localize-examples.py
    (its one github:// hardware line becomes a local include) into .hil-build/,
    so the image comes from the working tree and never from @main. Any remote
    package reference to this repository that survives is a fatal error.
 2. Reads the HIL network values from hil/hil-network.yaml with a strict line
    parser (not a YAML parser: the file is public and non-secret by decision,
    but a lenient parser would let a tag or an unquoted value slip through).
 3. Compiles hil/rev3.2.hil.yaml. ESPHome output goes to
    .hil-build/esphome-compile.log and is never printed raw, because ESPHome
    echoes substitution values (conceal sequences) into its own output.

Exit codes: 0 built, 1 compile or output failure, 2 refused or invalid input.

Local builds carry the maintainer's WiFi credentials (HIL_LOCAL_WIFI_SSID and
HIL_LOCAL_WIFI_PASSWORD) and must stay in the gitignored .hil-build/ and
hil-out/ paths. They are never uploaded or committed.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CUSTOMER_CONFIG = "fancontroller-rev3.2-esp32s2.yaml"
WRAPPER_CONFIG = os.path.join("hil", "rev3.2.hil.yaml")
NETWORK_FILE = os.path.join("hil", "hil-network.yaml")
BUILD_DIR_NAME = ".hil-build"
COMPILE_LOG_NAME = "esphome-compile.log"
BUILD_NAME = "fancontroller-r3-2"

IMAGE_NAME = "firmware.factory.bin"
MANIFEST_NAME = "manifest.json"

CHIP = "esp32s2"
OFFSET = "0x0"
REV = "3.2"
FRAMEWORK = "arduino"

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
NETWORK_LINE_RE = re.compile(r'^(hil_[a-z_]+):[ \t]*"([^"]*)"[ \t]*(#.*)?$')
KEY_LIKE_RE = re.compile(r"^([A-Za-z0-9_.-]+):")
PACKAGES_START_RE = re.compile(r"^packages:\s*$")
REMOTE_REF_RE = re.compile(r"github://|https?://github\.com/", re.IGNORECASE)


class BuildError(Exception):
    """Refused or invalid input. Never carries a network value."""


# ---------------------------------------------------------------- localizing


def load_localizer(repo_root):
    # Loading a module from the work tree must not leave a __pycache__ in it.
    sys.dont_write_bytecode = True
    path = os.path.join(repo_root, "tools", "localize-examples.py")
    spec = importlib.util.spec_from_file_location("localize_examples", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_no_remote_packages(text, path):
    """Fail if a line of the packages: block still names a remote reference.

    A surviving github:// reference would build part of the image from @main
    instead of the working tree. Only the packages: block is checked: the
    dashboard_import package_import_url is a plain string and harmless.
    """
    in_packages = False
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.rstrip()
        if PACKAGES_START_RE.match(stripped):
            in_packages = True
            continue
        if not in_packages:
            continue
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        if not stripped.startswith(" "):
            in_packages = False
            continue
        if REMOTE_REF_RE.search(stripped):
            raise BuildError(
                "%s:%d: remote package reference survives localization "
                "(the image would not be built from the working tree): %r"
                % (path, number, stripped)
            )


def localize_config(repo_root, localizer=None):
    """Return the localized text of the Rev 3.2 customer config."""
    localizer = localizer or load_localizer(repo_root)
    path = os.path.join(repo_root, CUSTOMER_CONFIG)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    try:
        out, _refs = localizer.localize(text, CUSTOMER_CONFIG)
    except localizer.LocalizeError as err:
        raise BuildError(str(err))
    check_no_remote_packages(out, CUSTOMER_CONFIG)
    return out


# ------------------------------------------------------------ network values


def parse_network(text, path=NETWORK_FILE):
    """Strict parser for hil-network.yaml: only 'key: "value"', comments, blanks.

    Errors name the line number, never the value.
    """
    values = {}
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = NETWORK_LINE_RE.match(line.rstrip())
        if not match:
            key = KEY_LIKE_RE.match(line)
            rest = line.split(":", 1)[1].strip() if ":" in line else ""
            if stripped.startswith("!") or rest.startswith("!"):
                reason = "YAML tag is not allowed"
            elif key and not re.match(r"^hil_[a-z_]+$", key.group(1)):
                reason = "key must match hil_[a-z_]+"
            elif key:
                reason = 'value must be double-quoted: key: "value"'
            else:
                reason = 'expected key: "value", a comment or a blank line'
            raise BuildError("%s:%d: %s" % (path, number, reason))
        key, value = match.group(1), match.group(2)
        if key in values:
            raise BuildError("%s:%d: duplicate key %s" % (path, number, key))
        values[key] = value
    return values


def resolve_network(file_values, env):
    """Local mode: WiFi from the HIL_LOCAL_WIFI_* pair when set, else the file."""
    ssid_env = env.get("HIL_LOCAL_WIFI_SSID")
    pass_env = env.get("HIL_LOCAL_WIFI_PASSWORD")
    if bool(ssid_env) != bool(pass_env):
        raise BuildError(
            "set both HIL_LOCAL_WIFI_SSID and HIL_LOCAL_WIFI_PASSWORD, or neither"
        )
    values = {}
    if ssid_env:
        values["hil_wifi_ssid"] = ssid_env
        values["hil_wifi_password"] = pass_env
    else:
        for key in ("hil_wifi_ssid", "hil_wifi_password"):
            if key in file_values:
                values[key] = file_values[key]
    if "hil_dut_api_key" in file_values:
        values["hil_dut_api_key"] = file_values["hil_dut_api_key"]
    for key in ("hil_wifi_ssid", "hil_wifi_password", "hil_dut_api_key"):
        if key not in values:
            raise BuildError("missing network value: %s" % key)
    return values


# ------------------------------------------------------------------- compile


def esphome_version():
    proc = subprocess.run(
        ["esphome", "version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
    match = re.search(r"(\d{4}\.\d+\.\d+\S*)", proc.stdout)
    if proc.returncode != 0 or not match:
        raise BuildError("could not read the esphome version")
    return match.group(1)


def run_compile(repo_root, config, hil_commit, network, log_path):
    """Compile with all output captured to log_path. Returns the exit code."""
    cmd = ["esphome", "-s", "hil_commit", hil_commit]
    for key in ("hil_wifi_ssid", "hil_wifi_password", "hil_dut_api_key"):
        cmd += ["-s", key, network[key]]
    cmd += ["compile", config]
    with open(log_path, "wb") as log:
        proc = subprocess.run(cmd, cwd=repo_root, stdout=log, stderr=subprocess.STDOUT)
    return proc.returncode


def find_image(config_path):
    tree = os.path.join(os.path.dirname(os.path.abspath(config_path)),
                        ".esphome", "build", BUILD_NAME)
    found = []
    for root, _dirs, files in os.walk(tree):
        if IMAGE_NAME in files:
            found.append(os.path.join(root, IMAGE_NAME))
    if len(found) != 1:
        raise RuntimeError(
            "expected exactly one %s under %s, found %d" % (IMAGE_NAME, tree, len(found))
        )
    return found[0]


def write_outputs(image_path, out_dir, commit, hil_commit, version):
    os.makedirs(out_dir, exist_ok=True)
    stale = [n for n in os.listdir(out_dir) if n not in (IMAGE_NAME, MANIFEST_NAME)]
    if stale:
        raise BuildError("output directory %s holds unexpected entries" % out_dir)
    with open(image_path, "rb") as handle:
        data = handle.read()
    with open(os.path.join(out_dir, IMAGE_NAME), "wb") as handle:
        handle.write(data)
    manifest = {
        "schema": 1,
        "commit": commit,
        "build_id": "3.2+hil." + hil_commit,
        "esphome_version": version,
        "images": [
            {
                "role": "commit",
                "file": IMAGE_NAME,
                "sha256": hashlib.sha256(data).hexdigest(),
                "chip": CHIP,
                "offset": OFFSET,
                "rev": REV,
                "framework": FRAMEWORK,
            }
        ],
    }
    with open(os.path.join(out_dir, MANIFEST_NAME), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


# ---------------------------------------------------------------------- main


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--commit", help="40 lowercase hex; falls back to env HIL_COMMIT")
    parser.add_argument("--out", default="hil-out", help="output directory (default hil-out)")
    return parser.parse_args(argv)


def build(args, env):
    commit = args.commit or env.get("HIL_COMMIT", "")
    if not COMMIT_RE.match(commit):
        raise BuildError("--commit (or HIL_COMMIT) must be 40 lowercase hex characters")
    hil_commit = commit[:12]

    with open(os.path.join(REPO_ROOT, NETWORK_FILE), "r", encoding="utf-8") as handle:
        file_values = parse_network(handle.read())
    network = resolve_network(file_values, env)

    build_dir = os.path.join(REPO_ROOT, BUILD_DIR_NAME)
    os.makedirs(build_dir, exist_ok=True)
    localized = localize_config(REPO_ROOT)
    with open(os.path.join(build_dir, CUSTOMER_CONFIG), "w", encoding="utf-8") as handle:
        handle.write(localized)

    out_dir = args.out if os.path.isabs(args.out) else os.path.join(REPO_ROOT, args.out)
    log_path = os.path.join(build_dir, COMPILE_LOG_NAME)
    config = os.path.join(REPO_ROOT, WRAPPER_CONFIG)

    print("compiling %s (log: %s/%s)" % (WRAPPER_CONFIG, BUILD_DIR_NAME, COMPILE_LOG_NAME))
    code = run_compile(REPO_ROOT, config, hil_commit, network, log_path)
    if code != 0:
        print("compile failed (exit %d); see %s/%s" % (code, BUILD_DIR_NAME, COMPILE_LOG_NAME),
              file=sys.stderr)
        return 1

    try:
        image = find_image(config)
    except RuntimeError as err:
        print("error: %s" % err, file=sys.stderr)
        return 1
    manifest = write_outputs(image, out_dir, commit, hil_commit, esphome_version())
    print("wrote %s and %s (build_id %s)" % (IMAGE_NAME, MANIFEST_NAME, manifest["build_id"]))
    return 0


def main(argv):
    args = parse_args(argv[1:])
    try:
        return build(args, os.environ)
    except BuildError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
