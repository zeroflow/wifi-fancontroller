#!/usr/bin/env python3
"""Build the Rev 3.2 HIL images (commit, qc-auto, canary, broken) from the working tree.

Runs inside the pinned ESPHome container (ghcr.io/esphome/esphome:<pin>), stdlib
plus the image's PyYAML, from the repository root:

    docker run --rm -v "$PWD":/repo -w /repo --entrypoint python3 \\
        ghcr.io/esphome/esphome:2026.10.1 \\
        hil/tools/build_image.py --all --out hil-out --commit "$(git rev-parse HEAD)"

Output, and nothing else, in --out:

    firmware.factory.bin   the commit image the hil job flashes at offset 0x0
    firmware.ota.bin       the commit image as an OTA binary
    qc-auto-3.2.ota.bin    the qc-auto image (OTA only, never a final image)
    canary-3.2.ota.bin     the canary image (OTA only, never a final image)
    broken-3.2.ota.bin     the broken image: no network at all, OTA file only, never final
                           and never a heal image (D-40)
    manifest.json          schema 2: one entry per image with role, rev, chip, offset,
                           framework, build_id, final, sha256 of every file, ...

Without --all only the commit target is built (the current hil.yml command keeps
working). manifest.json is written last and removed first, so an interrupted build
leaves nothing that can be flashed.

What it does:

 1. Localizes fancontroller-rev3.2-esp32s2.yaml with tools/localize-examples.py
    (its one github:// hardware line becomes a local include) into .hil-build/,
    so the image comes from the working tree and never from @main. Any remote
    package reference to this repository that survives is a fatal error.
 2. Reads the HIL network values from hil/hil-network.yaml with a strict line
    parser (not a YAML parser: the file is public and non-secret by decision,
    but a lenient parser would let a tag or an unquoted value slip through).
 3. Resolves every target's wrapper with `esphome config` into
    .hil-build/resolved-<role>-<rev>.yaml (parsed, never printed: the resolved
    config holds the substitution values) and reads the fan PWM frequency from it.
 4. Compiles each wrapper (hil/rev3.2.hil.yaml, rev3.2.qc-auto.yaml, ...). ESPHome
    output goes to .hil-build/esphome-compile.log and is never printed raw, because
    ESPHome echoes substitution values (conceal sequences) into its own output.

--check-configs resolves every target with placeholder values (no compile) and checks
each resolved config against hil/frameworks.toml, the entity names the tests drive, the
UART0 logger, one fan PWM frequency and, for the canary, its deliberate pin swap and, for
the broken image, the absence of wifi, api, ota and safe_mode (D-40, D-41). It
prints one line per problem and "checked <n> configs: <k> problem(s)", and exits 2 on any
problem. --all and the default build run the same check on the real-value configs before
the first compile, so a config with the wrong framework can never be built (D-34).

--config PATH (local only) builds the commit wrapper from a config inside .hil-build/.
--config ROLE=PATH (local only, repeatable, with --all) replaces one target's wrapper
the same way. Any override makes the whole build local: every build ID gets the .local
suffix (the manifest allows one marker per build, and the last-green store refuses it).
Both forms are refused in GitHub Actions (exit 2). The override exists for the canary
proof: a canary whose fault is cancelled at runtime must turn the HIL run red (QC-06).

--check-pins compares the aioesphomeapi and esptool versions installed in the
ESPHome image with the pins in hil/pyproject.toml and builds nothing (a Dependabot
bump of the ESPHome pin then forces a pin update in hil/).

Exit codes: 0 built, 1 compile or output failure, 2 refused or invalid input
(--check-pins: 2 on any pin mismatch).

Local builds carry the maintainer's WiFi credentials (HIL_LOCAL_WIFI_SSID and
HIL_LOCAL_WIFI_PASSWORD) and must stay in the gitignored .hil-build/ and
hil-out/ paths. They are never uploaded or committed.
"""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NETWORK_FILE = os.path.join("hil", "hil-network.yaml")
BUILD_DIR_NAME = ".hil-build"
COMPILE_LOG_NAME = "esphome-compile.log"

FACTORY_IMAGE_NAME = "firmware.factory.bin"
OTA_IMAGE_NAME = "firmware.ota.bin"
MANIFEST_NAME = "manifest.json"

CUSTOMER_REV32 = "fancontroller-rev3.2-esp32s2.yaml"

# Build order is manifest order. The commit image comes first; qc-auto, canary and broken
# are never final (D-25) and carry no factory file: they only ever travel by OTA (D-23).
# The broken image has no network at all (D-40): the runner delivers it over UART.
TARGETS = (
    {
        "role": "commit", "rev": "3.2", "customer_config": CUSTOMER_REV32,
        "wrapper": os.path.join("hil", "rev3.2.hil.yaml"),
        "chip": "esp32s2", "offset": "0x0", "framework": "arduino",
        "esphome_name": "fancontroller-r3-2", "final": True, "factory": True,
        "ota_out": "firmware.ota.bin", "factory_out": "firmware.factory.bin",
    },
    {
        "role": "qc-auto", "rev": "3.2", "customer_config": CUSTOMER_REV32,
        "wrapper": os.path.join("hil", "rev3.2.qc-auto.yaml"),
        "chip": "esp32s2", "offset": "0x0", "framework": "arduino",
        "esphome_name": "fancontroller-qc-r3-2", "final": False, "factory": False,
        "ota_out": "qc-auto-3.2.ota.bin", "factory_out": None,
    },
    {
        "role": "canary", "rev": "3.2", "customer_config": CUSTOMER_REV32,
        "wrapper": os.path.join("hil", "rev3.2.canary.yaml"),
        "chip": "esp32s2", "offset": "0x0", "framework": "arduino",
        "esphome_name": "fancontroller-can-r3-2", "final": False, "factory": False,
        "ota_out": "canary-3.2.ota.bin", "factory_out": None,
    },
    {
        "role": "broken", "rev": "3.2", "customer_config": CUSTOMER_REV32,
        "wrapper": os.path.join("hil", "rev3.2.broken.yaml"),
        "chip": "esp32s2", "offset": "0x0", "framework": "arduino",
        "esphome_name": "fancontroller-brk-r3-2", "final": False, "factory": False,
        "ota_out": "broken-3.2.ota.bin", "factory_out": None,
    },
)
# The tag between "<rev>+" and ".<hil_commit>" in each role's build ID.
BUILD_ID_TAG = {"commit": "hil", "qc-auto": "qc", "canary": "canary", "broken": "broken"}
FAN_OUTPUT_IDS = ("pwm_fan1", "pwm_fan2", "pwm_fan3", "pwm_fan4")

NETWORK_KEYS = ("hil_wifi_ssid", "hil_wifi_password", "hil_dut_api_key")
LOCAL_OVERRIDE_ENV = ("HIL_LOCAL_WIFI_SSID", "HIL_LOCAL_WIFI_PASSWORD", "HIL_LOCAL_DUT_API_KEY")
MIN_VALUE_LENGTH = 8
FAILURE_TAIL_LINES = 80

PYPROJECT = os.path.join("hil", "pyproject.toml")
PINNED_PACKAGES = ("aioesphomeapi", "esptool", "esphome")
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)$")

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
NETWORK_LINE_RE = re.compile(r'^(hil_[a-z_]+):[ \t]*"([^"]*)"[ \t]*(#.*)?$')
KEY_LIKE_RE = re.compile(r"^([A-Za-z0-9_.-]+):")
PACKAGES_START_RE = re.compile(r"^packages:\s*$")
REMOTE_REF_RE = re.compile(r"github://|https?://github\.com/", re.IGNORECASE)


class BuildError(Exception):
    """Refused or invalid input. Never carries a network value."""


class CompileFailed(Exception):
    """A compile or image lookup failed; the details are already printed (exit 1)."""


# ---------------------------------------------------------------- localizing


def load_localizer(repo_root):
    # Loading a module from the work tree must not leave a __pycache__ in it.
    sys.dont_write_bytecode = True
    path = os.path.join(repo_root, "tools", "localize-examples.py")
    spec = importlib.util.spec_from_file_location("localize_examples", path)
    if spec is None or spec.loader is None:
        raise BuildError("cannot load %s" % path)
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


def localize_config(repo_root, customer_config, localizer=None):
    """Return the localized text of a customer config."""
    localizer = localizer or load_localizer(repo_root)
    path = os.path.join(repo_root, customer_config)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    try:
        out, _refs = localizer.localize(text, customer_config)
    except localizer.LocalizeError as err:
        raise BuildError(str(err))
    check_no_remote_packages(out, customer_config)
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
            "(HIL_LOCAL_* and --config are for local builds only)"
        )


def resolve_network(file_values, env, ci):
    """Return the three network values.

    CI: all three from the file, a missing key is an error naming the key.
    Local: WiFi from the HIL_LOCAL_WIFI_* pair when set, else the file. A local
    WiFi override also needs HIL_LOCAL_DUT_API_KEY: the published DUT key is only
    acceptable on the isolated HIL network, never on the developer's own WiFi.
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
            key_env = env.get("HIL_LOCAL_DUT_API_KEY")
            if not key_env:
                raise BuildError(
                    "HIL_LOCAL_WIFI_* needs HIL_LOCAL_DUT_API_KEY: the published "
                    "hil_dut_api_key is for the isolated HIL network only"
                )
            if key_env == file_values.get("hil_dut_api_key"):
                raise BuildError(
                    "HIL_LOCAL_DUT_API_KEY must differ from the published hil_dut_api_key"
                )
            values["hil_wifi_ssid"] = ssid_env
            values["hil_wifi_password"] = pass_env
            values["hil_dut_api_key"] = key_env
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


def build_hil_commit(commit, overrides):
    """The hil_commit of a build: any wrapper override makes every build ID of it local."""
    return hil_commit_for(commit, bool(overrides))


ROLE_NAME_RE = re.compile(r"^[a-z][a-z-]*$")


def parse_config_args(values, roles):
    """--config values -> (plain path or None, {role: path}).

    `ROLE=PATH` names one of `roles`; anything else is the single plain path of the
    original form. Mixing the forms, a repeated role, an unknown role or an empty path
    is an error naming the flag, never a file content.
    """
    plain, by_role = None, {}
    for value in values or ():
        head, sep, path = value.partition("=")
        if sep and ROLE_NAME_RE.match(head):
            if head not in roles:
                raise BuildError("--config %s=...: unknown role (known: %s)" % (head, ", ".join(roles)))
            if head in by_role:
                raise BuildError("--config %s=... given twice" % head)
            if not path:
                raise BuildError("--config %s= needs a path" % head)
            by_role[head] = path
        else:
            if plain is not None:
                raise BuildError("--config takes one plain path (use ROLE=PATH for several targets)")
            plain = value
    if plain is not None and by_role:
        raise BuildError("--config: do not mix a plain path with ROLE=PATH")
    return plain, by_role


def resolve_overrides(plain, by_role, targets, repo_root):
    """{role: absolute path} of every wrapper override; each path must lie inside .hil-build/.

    A plain path replaces the first (commit) target. A role that is not among `targets`
    (no --all) is refused rather than silently ignored.
    """
    if plain is not None:
        by_role = {targets[0]["role"]: plain}
    built = [t["role"] for t in targets]
    resolved = {}
    for role, path in by_role.items():
        if role not in built:
            raise BuildError("--config %s=...: that image is not built (add --all)" % role)
        config = resolve_config(path, repo_root)
        if not os.path.isfile(config):
            raise BuildError("--config file not found inside %s/" % BUILD_DIR_NAME)
        resolved[role] = config
    return resolved


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


def esphome_command(hil_commit, network, verb, config):
    cmd = ["esphome", "-s", "hil_commit", hil_commit]
    for key in NETWORK_KEYS:
        cmd += ["-s", key, network[key]]
    return cmd + [verb, config]


def run_compile(repo_root, config, hil_commit, network, log_path):
    """Compile with all output captured to log_path. Returns the exit code."""
    cmd = esphome_command(hil_commit, network, "compile", config)
    with open(log_path, "wb") as log:
        proc = subprocess.run(cmd, cwd=repo_root, stdout=log, stderr=subprocess.STDOUT)
    return proc.returncode


def run_resolve(repo_root, config, hil_commit, network, resolved_path, log_path):
    """`esphome config`: the resolved config goes to resolved_path, the rest to log_path.

    Neither file is ever printed (both can hold substitution values). Returns the exit code.
    """
    cmd = esphome_command(hil_commit, network, "config", config)
    with open(resolved_path, "wb") as out, open(log_path, "wb") as log:
        proc = subprocess.run(cmd, cwd=repo_root, stdout=out, stderr=log)
    return proc.returncode


def build_tree(config_path, esphome_name):
    return os.path.join(os.path.dirname(os.path.abspath(config_path)),
                        ".esphome", "build", esphome_name)


def clean_stale_images(config_path, esphome_name):
    """Remove firmware.* images left in this target's build tree by an earlier compile (Pitfall 3)."""
    removed = []
    for root, _dirs, files in os.walk(build_tree(config_path, esphome_name)):
        for name in files:
            if name in (FACTORY_IMAGE_NAME, OTA_IMAGE_NAME):
                os.remove(os.path.join(root, name))
                removed.append(os.path.join(root, name))
    return removed


def find_image(config_path, esphome_name, file_name):
    tree = build_tree(config_path, esphome_name)
    found = []
    for root, _dirs, files in os.walk(tree):
        if file_name in files:
            found.append(os.path.join(root, file_name))
    if len(found) != 1:
        raise RuntimeError(
            "expected exactly one %s under %s, found %d" % (file_name, tree, len(found))
        )
    return found[0]


def build_id_for(target, hil_commit):
    return "%s+%s.%s" % (target["rev"], BUILD_ID_TAG[target["role"]], hil_commit)


def output_names(targets):
    names = {MANIFEST_NAME}
    for target in targets:
        names.add(target["ota_out"])
        if target["factory"]:
            names.add(target["factory_out"])
    return names


def check_targets(targets):
    """Two targets with one esphome.name would share a build tree: refuse (QC-01 adjacency)."""
    seen = {}
    for target in targets:
        name = target["esphome_name"]
        if name in seen:
            raise BuildError("targets %s and %s share the esphome.name %s"
                             % (seen[name], target["role"], name))
        seen[name] = target["role"]
    outputs = {}
    for target in targets:
        for key in ("ota_out", "factory_out"):
            out = target[key]
            if out is None:
                continue
            if out in outputs or out == MANIFEST_NAME:
                raise BuildError("output file name %s is used twice" % out)
            outputs[out] = target["role"]


def prepare_out_dir(out_dir, targets):
    """Create --out, refuse strangers in it, and remove our own earlier outputs and manifest."""
    os.makedirs(out_dir, exist_ok=True)
    allowed = output_names(TARGETS) | output_names(targets)
    stale = [n for n in os.listdir(out_dir) if n not in allowed]
    if stale:
        raise BuildError("output directory %s holds unexpected entries" % out_dir)
    for name in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, name))


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_into(path, out_dir, name):
    data_path = os.path.join(out_dir, name)
    with open(path, "rb") as source, open(data_path, "wb") as target:
        target.write(source.read())
    return data_path


def write_manifest(out_dir, commit, hil_commit, version, entries):
    """manifest.json (schema 2), written last. `entries` are in TARGETS order."""
    commit_entries = [e for e in entries if e["role"] == "commit"]
    manifest = {
        "schema": 2,
        "commit": commit,
        "build_id": commit_entries[0]["build_id"] if commit_entries else "",
        "esphome_version": version,
        "images": entries,
    }
    with open(os.path.join(out_dir, MANIFEST_NAME), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def produce(targets, out_dir, commit, hil_commit, version, build_one, fan_hz):
    """Build every target into out_dir; manifest.json is the last thing written.

    build_one(target) -> (factory_path or None, ota_path), right after that target's
    compile. fan_hz maps (role, rev) to the Hz read from the resolved config.
    """
    check_targets(targets)
    prepare_out_dir(out_dir, targets)
    entries, digests = [], {}
    for target in targets:
        factory_path, ota_path = build_one(target)
        entry = {
            "role": target["role"],
            "rev": target["rev"],
            "chip": target["chip"],
            "offset": target["offset"],
            "framework": target["framework"],
            "build_id": build_id_for(target, hil_commit),
            "final": target["final"],
            "esphome_name": target["esphome_name"],
            "ota_file": target["ota_out"],
        }
        copied = [(target["ota_out"], copy_into(ota_path, out_dir, target["ota_out"]))]
        entry["ota_sha256"] = sha256_file(copied[0][1])
        if target["factory"]:
            factory_copy = copy_into(factory_path, out_dir, target["factory_out"])
            entry["file"] = target["factory_out"]
            entry["sha256"] = sha256_file(factory_copy)
            copied.append((target["factory_out"], factory_copy))
        if not target["final"]:
            hz = fan_hz.get((target["role"], target["rev"]))
            if hz is None:
                raise BuildError("no fan frequency was read for the %s image" % target["role"])
            entry["fan_hz"] = hz
        for name, path in copied:
            digest = sha256_file(path)
            if digest in digests:
                raise BuildError("%s and %s have identical content (a target did not build its own image)"
                                 % (digests[digest], name))
            digests[digest] = name
        entries.append(entry)
    return write_manifest(out_dir, commit, hil_commit, version, entries)


# ----------------------------------------------------------- resolved configs


def tolerant_loader():
    """yaml.SafeLoader that keeps every !tag (!lambda, !secret, ...) as its plain value."""
    import yaml

    class TagTolerantLoader(yaml.SafeLoader):
        pass

    def plain(loader, _suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return loader.construct_scalar(node)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node, deep=True)
        return loader.construct_mapping(node, deep=True)

    TagTolerantLoader.add_multi_constructor("!", plain)
    return yaml, TagTolerantLoader


def parse_resolved(text):
    """Parse the output of `esphome config`. Never echoes the text."""
    yaml, loader = tolerant_loader()
    try:
        data = yaml.load(text, Loader=loader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError:
        raise BuildError("the resolved config is not parseable YAML") from None
    if not isinstance(data, dict):
        raise BuildError("the resolved config is not a mapping")
    return data


def frequency_hz(value):
    """Hz from a number or a "<n> Hz" string; None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if float(value) == int(value) else None
    if isinstance(value, str):
        match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(k?)Hz\s*$", value)
        if match:
            hz = float(match.group(1)) * (1000 if match.group(2) else 1)
            return int(hz) if hz == int(hz) else None
    return None


def ledc_outputs(resolved):
    """{output id: output entry} of the ledc outputs in a resolved config."""
    outputs = resolved.get("output")
    found = {}
    if isinstance(outputs, list):
        for entry in outputs:
            if isinstance(entry, dict) and entry.get("platform") == "ledc":
                found[str(entry.get("id"))] = entry
    return found


def fan_frequency(resolved):
    """The one PWM frequency (Hz) of pwm_fan1..pwm_fan4; BuildError when absent or unequal."""
    outputs = ledc_outputs(resolved)
    values = set()
    for ident in FAN_OUTPUT_IDS:
        entry = outputs.get(ident)
        if entry is None:
            raise BuildError("the resolved config has no ledc output %s" % ident)
        hz = frequency_hz(entry.get("frequency"))
        if hz is None:
            raise BuildError("ledc output %s has no readable frequency" % ident)
        values.add(hz)
    if len(values) != 1:
        raise BuildError("fan PWM frequencies differ")
    return values.pop()


# ------------------------------------------------------------ configuration checks

FRAMEWORKS_FILE = os.path.join("hil", "frameworks.toml")
# Validation-only values for `--check-configs` (RESEARCH Pitfall 9): ESPHome rejects the
# all-zeros API key, so this is base64 of the bytes 1..32. They must never equal a real value.
PLACEHOLDERS = {
    "hil_wifi_ssid": "hil-placeholder",
    "hil_wifi_password": "placeholder-pass",
    "hil_dut_api_key": "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=",
}
PLACEHOLDER_COMMIT = "000000000000"
REQUIRED_ENTITIES = (
    tuple("Fan %d" % n for n in (1, 2, 3, 4))
    + tuple("Fan %d Speed" % n for n in (1, 2, 3, 4))
    + ("Temperature", "Humidity")
    + tuple("Button USR%d" % n for n in (1, 2, 3))
)
QC_ENTITIES = ("QC Device Info", "QC Safe Mode Boot")
# Roles that must not carry the QC entities: the commit image is the shipped configuration and
# the broken image is the commit wrapper without its network (D-40).
NO_QC_ROLES = ("commit", "broken")
# Top-level keys a broken image must not have (D-40): any of them would make it reachable.
BROKEN_FORBIDDEN_KEYS = ("wifi", "api", "ota", "safe_mode", "captive_portal", "improv_serial",
                         "http_request", "update")
ENTITY_DOMAINS = ("fan", "sensor", "binary_sensor", "text_sensor", "button", "switch", "light")


def load_framework_table(text):
    """hil/frameworks.toml as {"schema": 1, "revisions": {rev: framework}}."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise BuildError("%s is not valid TOML" % FRAMEWORKS_FILE) from None
    if data.get("schema") != 1:
        raise BuildError("%s: schema must be 1" % FRAMEWORKS_FILE)
    if not isinstance(data.get("revisions"), dict):
        raise BuildError("%s: the [revisions] table is missing" % FRAMEWORKS_FILE)
    return data


def entity_names(resolved):
    """Every entity name in a resolved config, including names nested one level (hdc1080, debug)."""
    names = set()
    for domain in ENTITY_DOMAINS:
        entries = resolved.get(domain)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if isinstance(entry.get("name"), str):
                names.add(entry["name"])
            for value in entry.values():
                if isinstance(value, dict) and isinstance(value.get("name"), str):
                    names.add(value["name"])
    return names


def pin_number(entry):
    pin = entry.get("pin") if isinstance(entry, dict) else None
    if isinstance(pin, dict):
        pin = pin.get("number")
    if isinstance(pin, str):
        match = re.match(r"^(?:GPIO)?([0-9]+)$", pin.strip())
        pin = int(match.group(1)) if match else None
    return pin if isinstance(pin, int) and not isinstance(pin, bool) else None


def placeholder_problems(placeholders, network_values):
    """A placeholder that equals a real HIL value would make a validation build look real."""
    return ["placeholder %s equals the value in hil/hil-network.yaml" % key
            for key in sorted(placeholders) if placeholders[key] == network_values.get(key)]


def check_configs(resolved_by_target, table, network_values, placeholders=None):
    """Problems (sorted strings; keys and names only, never a value) in the resolved configs.

    resolved_by_target maps (role, rev) to a parsed `esphome config` output. Enforces the
    framework table (D-34), the identity of each image, the entities the tests drive, one fan
    PWM frequency, and the canary's deliberate pin swap (D-31).
    """
    problems = placeholder_problems(placeholders or {}, network_values)
    revisions = table.get("revisions", {}) if isinstance(table, dict) else {}
    for target in TARGETS:
        key = (target["role"], target["rev"])
        resolved = resolved_by_target.get(key)
        if resolved is None:
            continue
        who = target["role"]
        rev = target["rev"]
        expected = revisions.get(rev)
        if rev not in revisions:
            problems.append("%s: rev %s is not in %s" % (who, rev, FRAMEWORKS_FILE))
        elif not isinstance(expected, str) or not expected:
            problems.append("%s: rev %s: the framework value in %s is empty" % (who, rev, FRAMEWORKS_FILE))
        esp32 = resolved.get("esp32")
        framework = esp32.get("framework") if isinstance(esp32, dict) else None
        actual = framework.get("type") if isinstance(framework, dict) else None
        if not isinstance(actual, str) or not actual:
            problems.append("%s: the resolved config has no esp32.framework.type" % who)
        else:
            if isinstance(expected, str) and expected and actual != expected:
                problems.append("%s: rev %s: framework %s, table says %s" % (who, rev, actual, expected))
            if actual != target["framework"]:
                problems.append("%s: framework %s, the build target says %s" % (who, actual, target["framework"]))
        logger = resolved.get("logger")
        if not isinstance(logger, dict) or logger.get("hardware_uart") != "UART0":
            problems.append("%s: logger.hardware_uart is not UART0" % who)
        esphome = resolved.get("esphome") if isinstance(resolved.get("esphome"), dict) else {}
        if esphome.get("name") != target["esphome_name"]:
            problems.append("%s: esphome.name is not %s" % (who, target["esphome_name"]))
        project = esphome.get("project") if isinstance(esphome.get("project"), dict) else {}
        version = project.get("version")
        prefix = "%s+%s." % (rev, BUILD_ID_TAG[target["role"]])
        if not isinstance(version, str) or not version.startswith(prefix):
            problems.append("%s: esphome.project.version does not start with %s" % (who, prefix))
        names = entity_names(resolved)
        wanted = REQUIRED_ENTITIES + (QC_ENTITIES if target["role"] not in NO_QC_ROLES else ())
        for name in wanted:
            if name not in names:
                problems.append("%s: entity missing: %s" % (who, name))
        try:
            fan_frequency(resolved)
        except BuildError as err:
            problems.append("%s: %s" % (who, err))
        if target["role"] == "broken":
            for forbidden in BROKEN_FORBIDDEN_KEYS:
                if forbidden in resolved:
                    problems.append("broken: the resolved config still has %s (D-40)" % forbidden)
            advanced = esp32.get("advanced") if isinstance(esp32, dict) else None
            rollback = advanced.get("enable_ota_rollback") if isinstance(advanced, dict) else None
            if rollback is not None and rollback is not False:
                problems.append("broken: esp32.advanced.enable_ota_rollback is not false (D-41)")
    canary = resolved_by_target.get(("canary", "3.2"))
    if canary is not None:
        qc = resolved_by_target.get(("qc-auto", "3.2"))
        if qc is None:
            problems.append("canary: no qc-auto config to compare the pins against")
        else:
            qc_pins = {i: pin_number(e) for i, e in ledc_outputs(qc).items()}
            can_pins = {i: pin_number(e) for i, e in ledc_outputs(canary).items()}
            one, two = "pwm_fan1", "pwm_fan2"
            swapped = (None not in (can_pins.get(one), can_pins.get(two), qc_pins.get(one), qc_pins.get(two))
                       and can_pins[one] == qc_pins[two] and can_pins[two] == qc_pins[one]
                       and can_pins[one] != qc_pins[one])
            if not swapped:
                problems.append("canary: pwm_fan1/pwm_fan2 pins are not swapped")
    return sorted(problems)


# ----------------------------------------------------------------- pin guard


def pinned_versions(pyproject_text, packages=PINNED_PACKAGES):
    """The `name==version` pins of `packages` in a pyproject.toml, as {name: version}."""
    data = tomllib.loads(pyproject_text)
    pins = {}
    for entry in data.get("project", {}).get("dependencies", []):
        match = PIN_RE.match(entry.strip())
        if match and match.group(1).lower() in packages:
            pins[match.group(1).lower()] = match.group(2)
    missing = [name for name in packages if name not in pins]
    if missing:
        raise BuildError("%s has no exact pin for: %s" % (PYPROJECT, ", ".join(missing)))
    return pins


def installed_version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def check_pins(pyproject_text, installed=installed_version):
    """Print pinned and installed versions; return 0 when equal, 2 on any difference."""
    pins = pinned_versions(pyproject_text)
    code = 0
    for name in PINNED_PACKAGES:
        have = installed(name)
        state = "ok" if have == pins[name] else "MISMATCH"
        print("%s: hil/pyproject.toml pins %s, ESPHome image has %s (%s)"
              % (name, pins[name], have or "not installed", state))
        if have != pins[name]:
            code = 2
    if code:
        print("error: update the pins in hil/pyproject.toml (and hil/uv.lock) to the versions "
              "the ESPHome image ships", file=sys.stderr)
    return code


# ---------------------------------------------------------------------- main


def parse_args(argv):
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--commit", help="40 lowercase hex; falls back to env HIL_COMMIT")
    parser.add_argument("--out", default="hil-out", help="output directory (default hil-out)")
    parser.add_argument("--config", action="append", metavar="[ROLE=]PATH",
                        help="local mode only: a config inside .hil-build/ (PATH alone builds the "
                             "commit wrapper from it; ROLE=PATH, repeatable with --all, replaces "
                             "that target's wrapper)")
    parser.add_argument("--all", action="store_true",
                        help="build every target (commit, qc-auto, ...); default is the commit image only")
    parser.add_argument("--self-test", action="store_true", help="run the built-in fixtures")
    parser.add_argument("--check-configs", action="store_true",
                        help="resolve every target with placeholder values and check framework, "
                             "entities and the canary fault; builds nothing")
    parser.add_argument("--check-pins", action="store_true",
                        help="compare the installed aioesphomeapi, esptool and esphome with hil/pyproject.toml")
    return parser.parse_args(argv)


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def selected_targets(args):
    if args.all:
        return TARGETS
    return tuple(t for t in TARGETS if t["role"] == "commit")


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
    targets = selected_targets(args)
    check_targets(targets)
    plain, by_role = parse_config_args(args.config, [t["role"] for t in TARGETS])
    if plain is not None and len(targets) != 1:
        raise BuildError("--config builds one wrapper: do not combine it with --all")

    build_dir = os.path.join(REPO_ROOT, BUILD_DIR_NAME)
    configs = {t["role"]: os.path.join(REPO_ROOT, t["wrapper"]) for t in targets}
    overrides = resolve_overrides(plain, by_role, targets, REPO_ROOT)
    configs.update(overrides)
    hil_commit = build_hil_commit(commit, overrides)  # one marker per build (manifest rule)

    os.makedirs(build_dir, exist_ok=True)
    for customer in sorted({t["customer_config"] for t in targets}):
        with open(os.path.join(build_dir, customer), "w", encoding="utf-8") as handle:
            handle.write(localize_config(REPO_ROOT, customer))

    out_dir = args.out if os.path.isabs(args.out) else os.path.join(REPO_ROOT, args.out)
    log_path = os.path.join(build_dir, COMPILE_LOG_NAME)

    # 5. Resolve every wrapper first (output parsed, never printed): the fan frequency
    #    of each non-final image comes from here.
    fan_hz, resolved_by_key = {}, {}
    for target in targets:
        key = (target["role"], target["rev"])
        resolved_path = os.path.join(build_dir, "resolved-%s-%s.yaml" % key)
        config_log = os.path.join(build_dir, "esphome-config-%s-%s.log" % key)
        code = run_resolve(REPO_ROOT, configs[target["role"]], hil_commit, network,
                           resolved_path, config_log)
        if code != 0:
            print("config failed for the %s image (exit %d); last %d log lines, network values hidden:"
                  % (target["role"], code, FAILURE_TAIL_LINES), file=sys.stderr)
            for path in (config_log, resolved_path):
                print(failure_tail(path, network.values()), file=sys.stderr)
            return 1
        resolved_by_key[key] = parse_resolved(read_text(resolved_path))
        if not target["final"]:
            fan_hz[key] = fan_frequency(resolved_by_key[key])

    # 5b. D-34 at build time: nothing compiles while a config has the wrong framework,
    #     a missing entity or (canary) a lost fault. A plain --config experiment is not
    #     one of the build targets and is not held to them; a ROLE=PATH override is.
    if plain is None:
        table = load_framework_table(reader(os.path.join(REPO_ROOT, FRAMEWORKS_FILE)))
        problems = check_configs(resolved_by_key, table, network)
        if problems:
            for problem in problems:
                print("config check: %s" % problem, file=sys.stderr)
            print("refusing to build: %d config problem(s); nothing was compiled" % len(problems),
                  file=sys.stderr)
            return 2

    # 6. Compile each target; copy its images out right after, clean its tree before.
    def build_one(target):
        config = configs[target["role"]]
        clean_stale_images(config, target["esphome_name"])
        print("compiling %s (log: %s/%s)" % (os.path.relpath(config, REPO_ROOT),
                                             BUILD_DIR_NAME, COMPILE_LOG_NAME))
        sys.stdout.flush()
        code = run_compile(REPO_ROOT, config, hil_commit, network, log_path)
        if code != 0:
            print("compile failed (exit %d); last %d log lines, network values hidden:"
                  % (code, FAILURE_TAIL_LINES), file=sys.stderr)
            print(failure_tail(log_path, network.values()), file=sys.stderr)
            raise CompileFailed()
        try:
            factory = (find_image(config, target["esphome_name"], FACTORY_IMAGE_NAME)
                       if target["factory"] else None)
            ota = find_image(config, target["esphome_name"], OTA_IMAGE_NAME)
        except RuntimeError as err:
            print("error: %s" % err, file=sys.stderr)
            raise CompileFailed() from None
        return factory, ota

    try:
        manifest = produce(targets, out_dir, commit, hil_commit, esphome_version(), build_one, fan_hz)
    except CompileFailed:
        return 1
    print("wrote %s and %s (build_id %s)" % (
        ", ".join(sorted(output_names(targets) - {MANIFEST_NAME})), MANIFEST_NAME, manifest["build_id"]))
    return 0


def check_configs_command(reader=read_text):
    """--check-configs: resolve every target with placeholder values and check them. Builds nothing."""
    file_values = parse_network(reader(os.path.join(REPO_ROOT, NETWORK_FILE)))
    refused = placeholder_problems(PLACEHOLDERS, file_values)
    if refused:
        for problem in refused:
            print(problem)
        print("checked 0 configs: %d problem(s)" % len(refused))
        return 2
    table = load_framework_table(reader(os.path.join(REPO_ROOT, FRAMEWORKS_FILE)))
    build_dir = os.path.join(REPO_ROOT, BUILD_DIR_NAME)
    os.makedirs(build_dir, exist_ok=True)
    for customer in sorted({t["customer_config"] for t in TARGETS}):
        with open(os.path.join(build_dir, customer), "w", encoding="utf-8") as handle:
            handle.write(localize_config(REPO_ROOT, customer))
    resolved_by_key = {}
    for target in TARGETS:
        key = (target["role"], target["rev"])
        resolved_path = os.path.join(build_dir, "resolved-%s-%s.yaml" % key)
        config_log = os.path.join(build_dir, "esphome-config-%s-%s.log" % key)
        code = run_resolve(REPO_ROOT, os.path.join(REPO_ROOT, target["wrapper"]), PLACEHOLDER_COMMIT,
                           PLACEHOLDERS, resolved_path, config_log)
        if code != 0:
            print("config failed for the %s image (exit %d); last %d log lines:"
                  % (target["role"], code, FAILURE_TAIL_LINES))
            for path in (config_log, resolved_path):
                print(failure_tail(path, PLACEHOLDERS.values()))
            return 1
        resolved_by_key[key] = parse_resolved(reader(resolved_path))
    problems = check_configs(resolved_by_key, table, file_values, placeholders=PLACEHOLDERS)
    for problem in problems:
        print(problem)
    print("checked %d configs: %d problem(s)" % (len(resolved_by_key), len(problems)))
    return 2 if problems else 0


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
        ({"HIL_LOCAL_DUT_API_KEY": "refused-key-0001"}, [], "HIL_LOCAL_DUT_API_KEY"),
        ({}, ["--config", ".hil-build/x.yaml"], "--config"),
        ({}, ["--all", "--config", "canary=.hil-build/x.yaml"], "--config canary=PATH"),
        ({}, ["--all", "--config", "qc-auto=.hil-build/x.yaml", "--config", "canary=.hil-build/y.yaml"],
         "two --config ROLE=PATH"),
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
        row for row in SELF_TEST_NETWORK_OK.split("\n") if not row.startswith("hil_wifi_ssid"))
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
                              "HIL_LOCAL_WIFI_PASSWORD": "local-pass-0001",
                              "HIL_LOCAL_DUT_API_KEY": "local-dut-key-0123456789"}, False)
    check("local mode takes WiFi from the env pair",
          values["hil_wifi_ssid"] == "local-ssid-0001")
    check("local WiFi takes the local DUT key, never the published one",
          values["hil_dut_api_key"] == "local-dut-key-0123456789")
    check("local WiFi without HIL_LOCAL_DUT_API_KEY is refused",
          raises(resolve_network, {"hil_dut_api_key": "selftest-dut-key-0123456789"},
                 {"HIL_LOCAL_WIFI_SSID": "local-ssid-0001",
                  "HIL_LOCAL_WIFI_PASSWORD": "local-pass-0001"}, False) is not None)
    check("a local DUT key equal to the published key is refused",
          raises(resolve_network, {"hil_dut_api_key": "selftest-dut-key-0123456789"},
                 {"HIL_LOCAL_WIFI_SSID": "local-ssid-0001",
                  "HIL_LOCAL_WIFI_PASSWORD": "local-pass-0001",
                  "HIL_LOCAL_DUT_API_KEY": "selftest-dut-key-0123456789"}, False) is not None)
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

    # 6b. --config ROLE=PATH (local only): parsing, confinement and the .local build IDs.
    check("a build with a role override is local for every target, one without is not",
          build_hil_commit(SELF_TEST_SHA, {"canary": "/x"}) == SELF_TEST_SHA[:12] + ".local"
          and build_hil_commit(SELF_TEST_SHA, {}) == SELF_TEST_SHA[:12])
    roles = [t["role"] for t in TARGETS]
    check("canary=.hil-build/x.yaml is accepted as a role override",
          parse_config_args(["canary=.hil-build/x.yaml"], roles) == (None, {"canary": ".hil-build/x.yaml"}))
    check("the plain form still parses to one path",
          parse_config_args([".hil-build/x.yaml"], roles) == (".hil-build/x.yaml", {}))
    check("no --config parses to nothing", parse_config_args(None, roles) == (None, {}))
    check("--config is repeatable for different roles",
          parse_config_args(["qc-auto=.hil-build/a.yaml", "canary=.hil-build/b.yaml"], roles)[1]
          == {"qc-auto": ".hil-build/a.yaml", "canary": ".hil-build/b.yaml"})
    for label, values in (
        ("an unknown role", ["nonsense=.hil-build/x.yaml"]),
        ("a repeated role", ["canary=.hil-build/x.yaml", "canary=.hil-build/y.yaml"]),
        ("an empty path", ["canary="]),
        ("two plain paths", [".hil-build/a.yaml", ".hil-build/b.yaml"]),
        ("a plain path mixed with a role", [".hil-build/a.yaml", "canary=.hil-build/b.yaml"]),
    ):
        check("--config with %s is refused" % label, raises(parse_config_args, values, roles) is not None)
    resolved = resolve_overrides(None, {}, TARGETS, REPO_ROOT)
    check("no override resolves to nothing", resolved == {})
    for outside in ("/tmp/other.yaml", "../other.yaml", "hil/rev3.2.canary.yaml", ".hil-build/../x.yaml"):
        check("canary=%s is refused (outside .hil-build/)" % outside,
              raises(resolve_overrides, None, {"canary": outside}, TARGETS, REPO_ROOT) is not None)
    check("a role that is not built (no --all) is refused",
          "not built" in (raises(resolve_overrides, None, {"canary": ".hil-build/x.yaml"}, TARGETS[:1], REPO_ROOT) or ""))
    check("a missing override file is refused",
          "not found" in (raises(resolve_overrides, None, {"canary": ".hil-build/no-such-file.yaml"},
                                 TARGETS, REPO_ROOT) or ""))
    import tempfile as _tmp
    build_dir = os.path.join(REPO_ROOT, BUILD_DIR_NAME)
    os.makedirs(build_dir, exist_ok=True)
    with _tmp.NamedTemporaryFile("w", suffix=".yaml", dir=build_dir) as proof:
        relative = os.path.relpath(proof.name, REPO_ROOT)
        check("a role override inside .hil-build/ resolves to its absolute path",
              resolve_overrides(None, {"canary": relative}, TARGETS, REPO_ROOT)
              == {"canary": os.path.realpath(proof.name)})
        check("a plain override replaces the commit target only",
              list(resolve_overrides(relative, {}, TARGETS[:1], REPO_ROOT)) == ["commit"])

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

    # 8. The pin guard: equal versions pass, any difference or absence exits 2.
    toml_text = ('[project]\nname = "x"\ndependencies = [\n    "aioesphomeapi==46.12.0",\n'
                 '    "esptool==5.4.0",\n    "esphome==2026.10.1",\n    "pytest==9.2.0",\n]\n')
    good = {"aioesphomeapi": "46.12.0", "esptool": "5.4.0", "esphome": "2026.10.1"}
    check("pin reader finds all three pins", pinned_versions(toml_text) == good)
    check("pin reader refuses a missing pin",
          raises(pinned_versions, '[project]\ndependencies = ["esptool==5.4.0"]\n') is not None)
    check("pin reader refuses a missing esphome pin",
          raises(pinned_versions, '[project]\ndependencies = ["aioesphomeapi==46.12.0", "esptool==5.4.0"]\n')
          is not None)
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        same = check_pins(toml_text, lambda n: good[n])
        drift = check_pins(toml_text, lambda n: dict(good, aioesphomeapi="46.23.0")[n])
        esphome_drift = check_pins(toml_text, lambda n: dict(good, esphome="2026.11.0")[n])
        absent = check_pins(toml_text, lambda n: None)
    check("equal versions pass", same == 0, str(same))
    check("a version difference exits 2", drift == 2, str(drift))
    check("an esphome version difference exits 2", esphome_drift == 2, str(esphome_drift))
    check("a missing package exits 2", absent == 2, str(absent))

    # 9. Multi-target builds: shared names, equal images, stray files, manifest last.
    clash = [dict(TARGETS[0]), dict(TARGETS[0], role="qc-auto")]
    message = raises(check_targets, clash)
    check("two targets sharing an esphome.name are refused",
          message is not None and "share the esphome.name" in message, repr(message))
    check("the real TARGETS pass the name check", raises(check_targets, TARGETS) is None)
    check("TARGETS order puts the commit image first and only it is final",
          TARGETS[0]["role"] == "commit"
          and [t["role"] for t in TARGETS if t["final"]] == ["commit"])
    broken_target = [t for t in TARGETS if t["role"] == "broken"]
    check("the broken target is non-final, has no factory file and ships as broken-3.2.ota.bin (D-40)",
          len(broken_target) == 1 and broken_target[0]["final"] is False
          and broken_target[0]["factory"] is False and broken_target[0]["factory_out"] is None
          and broken_target[0]["ota_out"] == "broken-3.2.ota.bin"
          and broken_target[0]["framework"] == "arduino"
          and broken_target[0]["esphome_name"] == "fancontroller-brk-r3-2", str(broken_target))
    check("every target has a build ID tag", all(t["role"] in BUILD_ID_TAG for t in TARGETS))

    import tempfile
    fan_hz = {(t["role"], t["rev"]): 25000 for t in TARGETS if not t["final"]}

    def fake_builder(work, log, tamper=None):
        def build_one(target):
            log.append(target["role"])
            ota = os.path.join(work, "%s.ota" % target["role"])
            with open(ota, "wb") as handle:
                handle.write(("ota image of " + target["role"]).encode())
            factory = None
            if target["factory"]:
                factory = os.path.join(work, "%s.factory" % target["role"])
                with open(factory, "wb") as handle:
                    handle.write(("factory image of " + target["role"]).encode())
            if tamper:
                tamper(target, ota, factory)
            return factory, ota
        return build_one

    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        os.makedirs(work)
        out = os.path.join(tmp, "out")
        built = []
        seen = {}

        def watching(target):
            seen[target["role"]] = (
                os.path.exists(os.path.join(out, MANIFEST_NAME)),
                sorted(os.listdir(out)))
            return inner(target)

        inner = fake_builder(work, built)
        produce(TARGETS, out, SELF_TEST_SHA, SELF_TEST_SHA[:12], "9.9.9", watching, fan_hz)
        check("every target is built in TARGETS order",
              built == [t["role"] for t in TARGETS], str(built))
        check("no manifest.json exists while any target is still building",
              all(not present for present, _names in seen.values()), str(seen))
        later = seen[TARGETS[-1]["role"]][1]
        check("an earlier target's images are in --out before the next target builds",
              TARGETS[0]["ota_out"] in later and TARGETS[0]["factory_out"] in later, str(later))
        with open(os.path.join(out, MANIFEST_NAME), encoding="utf-8") as handle:
            on_disk = json.load(handle)
        check("manifest is schema 2 with the images in TARGETS order",
              on_disk["schema"] == 2
              and [i["role"] for i in on_disk["images"]] == [t["role"] for t in TARGETS], str(on_disk))
        check("manifest top-level build_id is the commit image's",
              on_disk["build_id"] == "3.2+hil." + SELF_TEST_SHA[:12]
              and on_disk["images"][0]["build_id"] == on_disk["build_id"])
        commit_entry = on_disk["images"][0]
        check("only the commit entry is final and has a factory file",
              commit_entry["final"] is True and commit_entry["file"] == "firmware.factory.bin"
              and all(i["final"] is False and "file" not in i and "sha256" not in i
                      for i in on_disk["images"][1:]))
        check("non-final entries carry fan_hz, the commit entry does not",
              "fan_hz" not in commit_entry
              and all(i["fan_hz"] == 25000 for i in on_disk["images"][1:]))
        check("every listed file's sha256 matches its content",
              all(sha256_file(os.path.join(out, i["ota_file"])) == i["ota_sha256"] for i in on_disk["images"])
              and sha256_file(os.path.join(out, commit_entry["file"])) == commit_entry["sha256"])
        with open(os.path.join(out, MANIFEST_NAME), encoding="utf-8") as handle:
            text = handle.read()
        check("manifest keys are sorted (two builds differ only in hashes)",
              text == json.dumps(on_disk, indent=2, sort_keys=True) + "\n")
        check("--out holds exactly the output names",
              sorted(os.listdir(out)) == sorted(output_names(TARGETS)), str(sorted(os.listdir(out))))

        # An interrupted build leaves no manifest, not even the previous one.
        crashed = []

        def crash_on_second(target):
            if target["role"] != TARGETS[0]["role"]:
                raise CompileFailed()
            return fake_builder(work, crashed)(target)

        try:
            produce(TARGETS, out, SELF_TEST_SHA, SELF_TEST_SHA[:12], "9.9.9", crash_on_second, fan_hz)
            interrupted = False
        except CompileFailed:
            interrupted = True
        check("an interrupted build raises and leaves no manifest.json",
              interrupted and not os.path.exists(os.path.join(out, MANIFEST_NAME)))

        # A stray file in --out is refused before anything is touched.
        with open(os.path.join(out, "stray.txt"), "w") as handle:
            handle.write("x")
        refused = []
        message = raises(lambda: produce(TARGETS, out, SELF_TEST_SHA, SELF_TEST_SHA[:12], "9.9.9",
                                         fake_builder(work, refused), fan_hz))
        check("a stray file in --out is refused before any build",
              message is not None and "unexpected entries" in message and not refused, repr(message))
        os.remove(os.path.join(out, "stray.txt"))

        # Two roles with the same image bytes are refused, with no manifest written.
        def same_bytes(target, ota, factory):
            with open(ota, "wb") as handle:
                handle.write(b"identical")

        message = raises(lambda: produce(TARGETS, out, SELF_TEST_SHA, SELF_TEST_SHA[:12], "9.9.9",
                                         fake_builder(work, [], same_bytes), fan_hz))
        check("equal sha256 across roles is refused and writes no manifest",
              message is not None and "identical content" in message
              and not os.path.exists(os.path.join(out, MANIFEST_NAME)), repr(message))

        # A non-final target without a fan frequency is refused.
        message = raises(lambda: produce(TARGETS, out, SELF_TEST_SHA, SELF_TEST_SHA[:12], "9.9.9",
                                         fake_builder(work, []), {}))
        check("a missing fan frequency is refused",
              message is not None and "fan frequency" in message, repr(message))

    # 10. Reading the fan frequency from a resolved config.
    def resolved_with(*frequencies):
        return {"output": [{"platform": "ledc", "id": "pwm_fan%d" % n, "pin": 11 + n, "frequency": f}
                           for n, f in enumerate(frequencies, 1)]}

    check("fan frequency accepts numbers and '<n> Hz' strings",
          fan_frequency(resolved_with(25000.0, "25000 Hz", 25000, "25000Hz")) == 25000)
    check("fan frequency 1000 Hz is read as 1000",
          fan_frequency(resolved_with(*["1000 Hz"] * 4)) == 1000)
    message = raises(fan_frequency, resolved_with(25000, 25000, 25000, 1000))
    check("unequal fan frequencies are refused",
          message is not None and "fan PWM frequencies differ" in message, repr(message))
    check("a missing fan output is refused naming it",
          "pwm_fan4" in (raises(fan_frequency, resolved_with(25000, 25000, 25000)) or ""))
    check("an unreadable frequency is refused naming the output",
          "pwm_fan1" in (raises(fan_frequency, resolved_with("fast", 25000, 25000, 25000)) or ""))
    check("tags in a resolved config are kept as plain values",
          parse_resolved("a: !lambda |-\n  return 1;\nb: !secret x\n")["b"] == "x")
    check("an unparseable resolved config is refused without echoing it",
          "SECRETVALUE" not in (raises(parse_resolved, "a: [SECRETVALUE\n") or ""))

    # 11. check_configs: framework table, identity, entities, canary fault (D-34, D-31).
    table = {"schema": 1, "revisions": {"3.2": "arduino", "4.0": "esp-idf"}}

    def good_resolved(target):
        names_fan = ["Fan %d" % n for n in (1, 2, 3, 4)]
        names_speed = ["Fan %d Speed" % n for n in (1, 2, 3, 4)]
        swapped = target["role"] == "canary"
        pins = {1: 12, 2: 13, 3: 14, 4: 15}
        if swapped:
            pins[1], pins[2] = 13, 12
        resolved = {
            "esphome": {"name": target["esphome_name"],
                        "project": {"version": "%s+%s.000000000000" % (
                            target["rev"], BUILD_ID_TAG[target["role"]])}},
            "esp32": {"framework": {"type": target["framework"]}},
            "logger": {"hardware_uart": "UART0"},
            "output": [{"platform": "ledc", "id": "pwm_fan%d" % n, "pin": {"number": pins[n]},
                        "frequency": 25000.0} for n in (1, 2, 3, 4)],
            "fan": [{"platform": "speed", "name": name} for name in names_fan],
            "sensor": [{"platform": "pulse_counter", "name": name} for name in names_speed]
                      + [{"platform": "hdc1080", "temperature": {"name": "Temperature"},
                          "humidity": {"name": "Humidity"}}],
            "binary_sensor": [{"platform": "gpio", "name": "Button USR%d" % n} for n in (1, 2, 3)],
        }
        if target["role"] not in NO_QC_ROLES:
            resolved["text_sensor"] = [{"platform": "debug", "device": {"name": "QC Device Info"},
                                        "reset_reason": {"name": "QC Reset Reason"}}]
            resolved["button"] = [{"platform": "safe_mode", "name": "QC Safe Mode Boot"}]
        return resolved

    import copy

    def all_good():
        return {(t["role"], t["rev"]): good_resolved(t) for t in TARGETS}

    network_real = {"hil_wifi_ssid": "real-ssid-0001", "hil_wifi_password": "real-pass-0001",
                    "hil_dut_api_key": "real-key-0123456789"}
    check("a correct set of resolved configs has no problems",
          check_configs(all_good(), table, network_real) == [], str(check_configs(all_good(), table, network_real)))

    wrong = all_good()
    wrong[("commit", "3.2")]["esp32"]["framework"]["type"] = "esp-idf"
    problems = check_configs(wrong, table, network_real)
    check("a framework that differs from the table is reported",
          any("rev 3.2: framework esp-idf, table says arduino" in p for p in problems), str(problems))

    missing_rev = check_configs(all_good(), {"schema": 1, "revisions": {"4.0": "esp-idf"}}, network_real)
    check("a revision missing from the table names the revision and the key",
          any("rev 3.2" in p and "frameworks.toml" in p for p in missing_rev), str(missing_rev))
    empty_value = check_configs(all_good(), {"schema": 1, "revisions": {"3.2": ""}}, network_real)
    check("an empty framework value names the revision and the key",
          any("rev 3.2" in p and "empty" in p for p in empty_value), str(empty_value))
    no_framework = all_good()
    del no_framework[("qc-auto", "3.2")]["esp32"]["framework"]
    problems = check_configs(no_framework, table, network_real)
    check("a resolved config without esp32.framework.type is reported naming the key",
          any("esp32.framework.type" in p for p in problems), str(problems))

    same_pins = all_good()
    same_pins[("canary", "3.2")]["output"] = copy.deepcopy(same_pins[("qc-auto", "3.2")]["output"])
    problems = check_configs(same_pins, table, network_real)
    check("a canary whose pins are not swapped is reported",
          any("canary: pwm_fan1/pwm_fan2 pins are not swapped" in p for p in problems), str(problems))
    half_swapped = all_good()
    half_swapped[("canary", "3.2")]["output"][1]["pin"]["number"] = 13
    problems = check_configs(half_swapped, table, network_real)
    check("a canary with only one swapped pin is reported",
          any("canary: pwm_fan1/pwm_fan2 pins are not swapped" in p for p in problems), str(problems))

    differ = all_good()
    differ[("qc-auto", "3.2")]["output"][3]["frequency"] = 1000.0
    problems = check_configs(differ, table, network_real)
    check("different ledc frequencies are reported",
          any("fan PWM frequencies differ" in p for p in problems), str(problems))

    no_uart = all_good()
    no_uart[("commit", "3.2")]["logger"] = {}
    problems = check_configs(no_uart, table, network_real)
    check("a config without the UART0 logger is reported",
          any("logger.hardware_uart" in p for p in problems), str(problems))
    wrong_name = all_good()
    wrong_name[("qc-auto", "3.2")]["esphome"]["name"] = "fancontroller-r3-2"
    problems = check_configs(wrong_name, table, network_real)
    check("an esphome.name other than the target's is reported",
          any("esphome.name" in p for p in problems), str(problems))
    wrong_version = all_good()
    wrong_version[("canary", "3.2")]["esphome"]["project"]["version"] = "3.2+qc.000000000000"
    problems = check_configs(wrong_version, table, network_real)
    check("a version prefix of another role is reported",
          any("esphome.project.version" in p for p in problems), str(problems))

    for entity, domain in (("Fan 3", "fan"), ("Fan 2 Speed", "sensor"), ("Button USR3", "binary_sensor")):
        broken = all_good()
        broken[("commit", "3.2")][domain] = [e for e in broken[("commit", "3.2")][domain]
                                             if e.get("name") != entity]
        problems = check_configs(broken, table, network_real)
        check("a missing entity %s is named" % entity,
              any(("entity missing: " + entity) in p for p in problems), str(problems))
    no_hdc = all_good()
    no_hdc[("commit", "3.2")]["sensor"] = [e for e in no_hdc[("commit", "3.2")]["sensor"]
                                           if e["platform"] != "hdc1080"]
    problems = check_configs(no_hdc, table, network_real)
    check("missing Temperature and Humidity are both named",
          any("entity missing: Temperature" in p for p in problems)
          and any("entity missing: Humidity" in p for p in problems), str(problems))
    no_qc = all_good()
    no_qc[("qc-auto", "3.2")]["button"] = []
    no_qc[("canary", "3.2")]["text_sensor"] = []
    problems = check_configs(no_qc, table, network_real)
    check("the QC entities are required on qc-auto and canary only",
          any(p.startswith("qc-auto") and "entity missing: QC Safe Mode Boot" in p for p in problems)
          and any(p.startswith("canary") and "entity missing: QC Device Info" in p for p in problems)
          and not any(p.startswith("commit") for p in problems), str(problems))
    check("the commit image does not need the QC entities",
          check_configs({k: v for k, v in all_good().items() if k[0] == "commit"}, table, network_real) == [])
    check("the broken image does not need the QC entities (D-40)",
          check_configs({k: v for k, v in all_good().items() if k[0] == "broken"}, table, network_real) == [])
    for forbidden in BROKEN_FORBIDDEN_KEYS:
        networked = all_good()
        networked[("broken", "3.2")][forbidden] = {}
        problems = check_configs(networked, table, network_real)
        check("a broken config that still has %s is reported (D-40)" % forbidden,
              any(p.startswith("broken: the resolved config still has %s" % forbidden) for p in problems),
              str(problems))
    rollback_on = all_good()
    rollback_on[("broken", "3.2")]["esp32"]["advanced"] = {"enable_ota_rollback": True}
    problems = check_configs(rollback_on, table, network_real)
    check("a broken config with esp32.advanced.enable_ota_rollback true is reported (D-41)",
          any("broken: esp32.advanced.enable_ota_rollback is not false" in p for p in problems), str(problems))
    rollback_off = all_good()
    rollback_off[("broken", "3.2")]["esp32"]["advanced"] = {"enable_ota_rollback": False}
    check("a broken config with enable_ota_rollback false is accepted",
          check_configs(rollback_off, table, network_real) == [])
    wrong_broken = all_good()
    wrong_broken[("broken", "3.2")]["esp32"]["framework"]["type"] = "esp-idf"
    problems = check_configs(wrong_broken, table, network_real)
    check("a broken config with another framework is reported",
          any(p.startswith("broken: rev 3.2: framework esp-idf") for p in problems), str(problems))
    lonely = {k: v for k, v in all_good().items() if k[0] == "canary"}
    problems = check_configs(lonely, table, network_real)
    check("a canary without a qc-auto config to compare against is reported",
          any("canary" in p and "qc-auto" in p for p in problems), str(problems))

    problems = check_configs(wrong, table, network_real)
    check("problems are sorted and never carry a network value",
          problems == sorted(problems)
          and not any(v in p for p in problems for v in network_real.values()))
    equal = check_configs(all_good(), table, dict(network_real, hil_wifi_ssid=PLACEHOLDERS["hil_wifi_ssid"]),
                          placeholders=PLACEHOLDERS)
    check("a placeholder equal to a real network value is refused naming the key only",
          equal == ["placeholder hil_wifi_ssid equals the value in hil/hil-network.yaml"], str(equal))
    check("distinct placeholders are not reported",
          check_configs(all_good(), table, network_real, placeholders=PLACEHOLDERS) == [])
    check("the real placeholders differ from every committed network value",
          placeholder_problems(PLACEHOLDERS, parse_network(
              read_text(os.path.join(REPO_ROOT, NETWORK_FILE)))) == [])
    check("the placeholder API key is not the all-zeros key ESPHome rejects",
          PLACEHOLDERS["hil_dut_api_key"] != "A" * 43 + "=")

    # 12. The framework table file.
    real_table = load_framework_table(read_text(os.path.join(REPO_ROOT, FRAMEWORKS_FILE)))
    check("frameworks.toml holds the shipped frameworks",
          real_table["revisions"] == {"1.0": "esp-idf", "2.0": "arduino", "3.0": "arduino",
                                      "3.1": "arduino", "3.2": "arduino", "3.3": "arduino",
                                      "4.0": "esp-idf"}, str(real_table))
    check("a table without [revisions] is refused",
          raises(load_framework_table, "schema = 1\n") is not None)
    check("a table with another schema is refused",
          raises(load_framework_table, 'schema = 2\n[revisions]\n"3.2" = "arduino"\n') is not None)

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
    if args.check_configs:
        try:
            return check_configs_command()
        except BuildError as err:
            print("error: %s" % err, file=sys.stderr)
            return 2
    if args.check_pins:
        try:
            return check_pins(read_text(os.path.join(REPO_ROOT, PYPROJECT)))
        except BuildError as err:
            print("error: %s" % err, file=sys.stderr)
            return 2
    return run(argv[1:], os.environ)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
