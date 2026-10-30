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

NETWORK_KEYS = ("hil_wifi_ssid", "hil_wifi_password", "hil_dut_api_key")
LOCAL_OVERRIDE_ENV = ("HIL_LOCAL_WIFI_SSID", "HIL_LOCAL_WIFI_PASSWORD")
MIN_VALUE_LENGTH = 8
FAILURE_TAIL_LINES = 80

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


def is_ci(env):
    return env.get("GITHUB_ACTIONS") == "true"


def refuse_local_overrides(args, env):
    """CI builds take every value from hil-network.yaml and nothing else (D-02, P5)."""
    if any(key in env for key in LOCAL_OVERRIDE_ENV) or args.config is not None:
        raise BuildError(
            "local override refused in GitHub Actions "
            "(HIL_LOCAL_WIFI_* and --config are for local builds only)"
        )


def resolve_network(file_values, env, ci):
    """Return the three network values.

    CI: all three from the file, a missing key is an error naming the key.
    Local: WiFi from the HIL_LOCAL_WIFI_* pair when set, else the file.
    """
    values = {}
    if not ci:
        ssid_env = env.get("HIL_LOCAL_WIFI_SSID")
        pass_env = env.get("HIL_LOCAL_WIFI_PASSWORD")
        if bool(ssid_env) != bool(pass_env):
            raise BuildError(
                "set both HIL_LOCAL_WIFI_SSID and HIL_LOCAL_WIFI_PASSWORD, or neither"
            )
        if ssid_env:
            values["hil_wifi_ssid"] = ssid_env
            values["hil_wifi_password"] = pass_env
    for key in NETWORK_KEYS:
        if key not in values and key in file_values:
            values[key] = file_values[key]
    for key in NETWORK_KEYS:
        if key not in values:
            raise BuildError("missing network value: %s" % key)
    return values


def check_value_lengths(values):
    """Short or common values make ::add-mask:: blank ordinary log text (P4)."""
    for key in NETWORK_KEYS:
        if key in values and len(values[key]) < MIN_VALUE_LENGTH:
            raise BuildError(
                "network value %s is shorter than %d characters" % (key, MIN_VALUE_LENGTH)
            )


def resolve_config(arg, repo_root):
    """Local mode: a --config must resolve inside .hil-build/ (never a tracked path)."""
    build_dir = os.path.realpath(os.path.join(repo_root, BUILD_DIR_NAME))
    candidate = arg if os.path.isabs(arg) else os.path.join(repo_root, arg)
    path = os.path.realpath(candidate)
    if path == build_dir or os.path.commonpath([build_dir, path]) != build_dir:
        raise BuildError("--config must resolve inside %s/" % BUILD_DIR_NAME)
    return path


def hil_commit_for(commit, local_config):
    return commit[:12] + (".local" if local_config else "")


def redact(text, values):
    for value in sorted({v for v in values if v}, key=len, reverse=True):
        text = text.replace(value, "***")
    return text


def failure_tail(log_path, values, limit=FAILURE_TAIL_LINES):
    """The last `limit` lines of the compile log with every network value hidden."""
    with open(log_path, "rb") as handle:
        text = handle.read().decode("utf-8", errors="replace")
    return redact("\n".join(text.splitlines()[-limit:]), values)


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
    parser.add_argument("--config", help="local mode only: a config inside .hil-build/")
    parser.add_argument("--self-test", action="store_true", help="run the built-in fixtures")
    return parser.parse_args(argv)


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def build(args, env, reader=read_text):
    ci = is_ci(env)
    # 1. Refuse local overrides before reading or writing anything.
    if ci:
        refuse_local_overrides(args, env)

    # 2. Read the network values. Errors here name a line number, never a value.
    file_values = parse_network(reader(os.path.join(REPO_ROOT, NETWORK_FILE)))

    # 3. CI: mask every value before any other output (D-16, P3).
    if ci:
        for key in NETWORK_KEYS:
            if key in file_values:
                print("::add-mask::" + file_values[key])
        sys.stdout.flush()

    # 4. Missing keys and short values.
    network = resolve_network(file_values, env, ci)
    check_value_lengths(network)

    commit = args.commit or env.get("HIL_COMMIT", "")
    if not COMMIT_RE.match(commit):
        raise BuildError("--commit (or HIL_COMMIT) must be 40 lowercase hex characters")
    hil_commit = hil_commit_for(commit, args.config is not None)

    build_dir = os.path.join(REPO_ROOT, BUILD_DIR_NAME)
    config = os.path.join(REPO_ROOT, WRAPPER_CONFIG)
    if args.config is not None:
        config = resolve_config(args.config, REPO_ROOT)
        if not os.path.isfile(config):
            raise BuildError("--config file not found inside %s/" % BUILD_DIR_NAME)

    os.makedirs(build_dir, exist_ok=True)
    localized = localize_config(REPO_ROOT)
    with open(os.path.join(build_dir, CUSTOMER_CONFIG), "w", encoding="utf-8") as handle:
        handle.write(localized)

    out_dir = args.out if os.path.isabs(args.out) else os.path.join(REPO_ROOT, args.out)
    log_path = os.path.join(build_dir, COMPILE_LOG_NAME)

    print("compiling %s (log: %s/%s)" % (os.path.relpath(config, REPO_ROOT),
                                         BUILD_DIR_NAME, COMPILE_LOG_NAME))
    code = run_compile(REPO_ROOT, config, hil_commit, network, log_path)
    if code != 0:
        print("compile failed (exit %d); last %d log lines, network values hidden:"
              % (code, FAILURE_TAIL_LINES), file=sys.stderr)
        print(failure_tail(log_path, network.values()), file=sys.stderr)
        return 1

    try:
        image = find_image(config)
    except RuntimeError as err:
        print("error: %s" % err, file=sys.stderr)
        return 1
    manifest = write_outputs(image, out_dir, commit, hil_commit, esphome_version())
    print("wrote %s and %s (build_id %s)" % (IMAGE_NAME, MANIFEST_NAME, manifest["build_id"]))
    return 0


def run(argv, env, reader=read_text):
    """Parse argv and build. Returns the exit code: 0, 1 or 2."""
    args = parse_args(argv)
    try:
        return build(args, env, reader)
    except BuildError as err:
        print("error: %s" % err, file=sys.stderr)
        return 2


SELF_TEST_RAW = """\
# WiFi Fan Controller - Revision 3.2 (ESP32-S2)
packages:
  # Include hardware-specific configuration
  hardware: github://zeroflow/wifi-fancontroller/hardware-rev-3.2.yaml@main

esphome:
  name: fancontroller-r3-2

dashboard_import:
  package_import_url: github://zeroflow/wifi-fancontroller/fancontroller-rev3.2-esp32s2.yaml@main
"""

SELF_TEST_NETWORK_OK = (
    "# header comment\n"
    "\n"
    'hil_wifi_ssid: "selftest-ssid-01"  # trailing comment\n'
    'hil_wifi_password: "selftest-password-02"\n'
    'hil_dut_api_key: "selftest-dut-key-0123456789"\n'
)
SELF_TEST_VALUES = ["selftest-ssid-01", "selftest-password-02", "selftest-dut-key-0123456789"]
SELF_TEST_SHA = "0123456789abcdef0123456789abcdef01234567"


def self_run(argv, env, files):
    """Run run() with captured output and a fake network-file reader."""
    import contextlib
    import io

    reads = []

    def reader(path):
        reads.append(path)
        return files

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run(argv, env, reader)
    return code, out.getvalue(), err.getvalue(), reads


def self_test():
    failures = []

    def check(name, condition, detail=""):
        if condition:
            print("ok: %s" % name)
        else:
            failures.append("%s %s" % (name, detail))

    def raises(func, *args):
        try:
            func(*args)
        except BuildError as err:
            return str(err)
        return None

    # 1. Localizing: the one github:// line becomes a local include; a package
    #    reference to this repository that survives takes the exit-2 path.
    localizer = load_localizer(REPO_ROOT)
    localized, _refs = localizer.localize(SELF_TEST_RAW, "self-test")
    check("localize rewrites the hardware line",
          "  hardware: !include ../hardware-rev-3.2.yaml" in localized.split("\n"))
    check("localized packages block passes the remote check",
          raises(check_no_remote_packages, localized, "self-test") is None)
    check("dashboard_import string is left alone",
          "package_import_url: github://zeroflow/" in localized)
    message = raises(check_no_remote_packages, SELF_TEST_RAW, "self-test")
    check("surviving shorthand github:// reference is refused",
          message is not None and "remote package reference" in message, repr(message))
    long_form = (
        "packages:\n  hardware:\n"
        "    url: https://github.com/zeroflow/wifi-fancontroller\n"
        "    files: [hardware-rev-3.2.yaml]\n"
    )
    check("surviving long-form url reference is refused",
          raises(check_no_remote_packages, long_form, "self-test") is not None)
    code, out, err, _reads = self_run(
        ["--commit", "nothex"], {"GITHUB_ACTIONS": "true"}, SELF_TEST_NETWORK_OK)
    check("exit code 2 is the refusal code", code == 2, str(code))

    # 2. CI mode refuses local overrides before reading or writing anything.
    for env_extra, argv_extra, label in (
        ({"HIL_LOCAL_WIFI_SSID": "refused-ssid-0001"}, [], "HIL_LOCAL_WIFI_SSID"),
        ({"HIL_LOCAL_WIFI_PASSWORD": "refused-pass-0001"}, [], "HIL_LOCAL_WIFI_PASSWORD"),
        ({}, ["--config", ".hil-build/x.yaml"], "--config"),
    ):
        env = {"GITHUB_ACTIONS": "true"}
        env.update(env_extra)
        code, out, err, reads = self_run(
            ["--commit", SELF_TEST_SHA, "--out", "unused"] + argv_extra, env, SELF_TEST_NETWORK_OK)
        check("CI refuses %s" % label,
              code == 2 and "local override refused in GitHub Actions" in err
              and not reads and out == "", "code=%s reads=%s out=%r" % (code, reads, out))

    # 3. CI mode prints one ::add-mask:: per network value before any other line.
    code, out, err, _reads = self_run(
        ["--commit", "nothex", "--out", "unused"], {"GITHUB_ACTIONS": "true"}, SELF_TEST_NETWORK_OK)
    lines = out.split("\n")
    check("CI masks come first, one per value, in key order",
          lines[:3] == ["::add-mask::" + v for v in SELF_TEST_VALUES]
          and all(line.startswith("::add-mask::") for line in lines if line), repr(out))
    check("the rejected commit comes after the masks", code == 2 and "40 lowercase hex" in err)

    # 4. CI mode names a missing key, never a value.
    without_ssid = "\n".join(
        l for l in SELF_TEST_NETWORK_OK.split("\n") if not l.startswith("hil_wifi_ssid"))
    code, out, err, _reads = self_run(
        ["--commit", SELF_TEST_SHA, "--out", "unused"], {"GITHUB_ACTIONS": "true"}, without_ssid)
    check("CI missing key exits 2 naming the key",
          code == 2 and "hil_wifi_ssid" in err and not any(v in err for v in SELF_TEST_VALUES), err)

    # 5. The strict parser.
    rejects = (
        ("tag line", 'hil_wifi_ssid: !secret wifi_ssid\n', 1),
        ("unquoted value", '# c\nhil_wifi_ssid: plainvalue\n', 2),
        ("key outside hil_[a-z_]+", 'wifi_ssid: "abcdefgh"\n', 1),
        ("duplicate key", 'hil_wifi_ssid: "abcdefgh"\n\nhil_wifi_ssid: "ijklmnop"\n', 3),
    )
    for name, text, lineno in rejects:
        message = raises(parse_network, text)
        check("parser rejects %s naming the line" % name,
              message is not None and (":%d:" % lineno) in message
              and "abcdefgh" not in message and "plainvalue" not in message, repr(message))
    check("parser accepts the fixture",
          raises(parse_network, SELF_TEST_NETWORK_OK) is None
          and parse_network(SELF_TEST_NETWORK_OK)["hil_wifi_ssid"] == "selftest-ssid-01")
    message = raises(check_value_lengths, {"hil_dut_api_key": "short"})
    check("a value shorter than 8 characters is rejected naming its key",
          message is not None and "hil_dut_api_key" in message and "short" not in message.replace(
              "shorter", ""), repr(message))

    # 6. Local mode: the env pair, and --config confined to .hil-build/.
    values = resolve_network({"hil_dut_api_key": "selftest-dut-key-0123456789"},
                             {"HIL_LOCAL_WIFI_SSID": "local-ssid-0001",
                              "HIL_LOCAL_WIFI_PASSWORD": "local-pass-0001"}, False)
    check("local mode takes WiFi from the env pair",
          values["hil_wifi_ssid"] == "local-ssid-0001")
    check("local mode wants both env values",
          raises(resolve_network, {"hil_dut_api_key": "selftest-dut-key-0123456789"},
                 {"HIL_LOCAL_WIFI_SSID": "local-ssid-0001"}, False) is not None)
    for outside in ("/tmp/other.yaml", "../other.yaml", "hil/rev3.2.hil.yaml", ".hil-build/../x.yaml"):
        check("--config %s is refused" % outside,
              raises(resolve_config, outside, REPO_ROOT) is not None)
    inside = resolve_config(".hil-build/experiment.yaml", REPO_ROOT)
    check("--config inside .hil-build/ is accepted",
          inside == os.path.join(os.path.realpath(REPO_ROOT), ".hil-build", "experiment.yaml"), inside)
    check("a local config build id is <sha12>.local",
          hil_commit_for(SELF_TEST_SHA, True) == SELF_TEST_SHA[:12] + ".local"
          and hil_commit_for(SELF_TEST_SHA, False) == SELF_TEST_SHA[:12])

    # 7. A failing compile prints at most 80 log lines, values replaced by ***.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        log = os.path.join(tmp, "esphome-compile.log")
        with open(log, "w", encoding="utf-8") as handle:
            for number in range(150):
                extra = " " + SELF_TEST_VALUES[number % 3] if number >= 60 else ""
                handle.write("log line %d%s\n" % (number, extra))
        tail = failure_tail(log, SELF_TEST_VALUES)
    check("failure tail is at most 80 lines", len(tail.split("\n")) <= 80, str(len(tail.split("\n"))))
    check("failure tail ends with the last log line", tail.split("\n")[-1].startswith("log line 149"))
    check("failure tail replaces every network value",
          not any(v in tail for v in SELF_TEST_VALUES) and "***" in tail)

    if failures:
        for failure in failures:
            print("FAIL: %s" % failure, file=sys.stderr)
        return 1
    print("self-test passed")
    return 0


def main(argv):
    args = parse_args(argv[1:])
    if args.self_test:
        return self_test()
    return run(argv[1:], os.environ)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
