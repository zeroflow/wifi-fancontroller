"""Rig configuration: rig.toml (runner contract), supervisor key, DUT API key.

Every failure raises RigError naming the key, never the value.
"""

import ipaddress
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import RigError

NETWORK_FILE = Path(__file__).resolve().parent.parent / "hil-network.yaml"
DUT_KEY_NAME = "hil_dut_api_key"

# Duplicated on purpose from tools/build_image.py (repetition over indirection).
NETWORK_LINE_RE = re.compile(r'^(hil_[a-z_]+):[ \t]*"([^"]*)"[ \t]*(#.*)?$')
KEY_LIKE_RE = re.compile(r"^([A-Za-z0-9_.-]+):")
MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

DUT_REQUIRED = (
    "rev",
    "chip",
    "host",
    "mac",
    "flash_offset",
    "known_good_image",
    "known_good_sha256",
    "known_good_api_encryption",
    "nvs_backup",
    "nvs_offset",
    "nvs_size",
)
DUT_B_REQUIRED = ("rev", "chip", "host", "mac")
HEX_FIELDS = ("flash_offset", "nvs_offset", "nvs_size")


@dataclass(frozen=True)
class DutConfig:
    id: str
    rev: str
    chip: str
    host: str
    mac: str
    flash_offset: str = ""
    known_good_image: str = ""
    known_good_sha256: str = ""
    known_good_api_encryption: bool = False
    nvs_backup: str = ""
    nvs_offset: str = ""
    nvs_size: str = ""


@dataclass(frozen=True)
class RigConfig:
    supervisor_host: str
    supervisor_key: str
    duts: dict
    dut_api_key: str


def parse_network(text, path=NETWORK_FILE):
    """Strict parser for hil-network.yaml. Errors name the line, never the value."""
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
            raise RigError("%s:%d: %s" % (path.name, number, reason))
        key, value = match.group(1), match.group(2)
        if key in values:
            raise RigError("%s:%d: duplicate key %s" % (path.name, number, key))
        values[key] = value
    return values


def _host(table, name, key="host"):
    raw = table.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise RigError("rig.toml: %s.%s is missing or empty" % (name, key))
    try:
        return str(ipaddress.IPv4Address(raw.strip()))
    except ValueError:
        raise RigError("rig.toml: %s.%s is not an IPv4 address" % (name, key)) from None


def _dut(dut_id, table, required):
    name = "dut." + dut_id.lower()
    for key in required:
        if key not in table:
            raise RigError("rig.toml: %s.%s is missing" % (name, key))
    host = _host(table, name)
    mac = table["mac"]
    if not isinstance(mac, str) or not MAC_RE.match(mac):
        raise RigError("rig.toml: %s.mac must be lowercase colon form" % name)
    for key in ("rev", "chip"):
        if not isinstance(table[key], str) or not table[key]:
            raise RigError("rig.toml: %s.%s is empty" % (name, key))
    extra = {}
    if "flash_offset" in required:
        for key in HEX_FIELDS:
            try:
                int(table[key], 16)
            except (TypeError, ValueError):
                raise RigError("rig.toml: %s.%s is not hex" % (name, key)) from None
        if not SHA256_RE.match(str(table["known_good_sha256"])):
            raise RigError("rig.toml: %s.known_good_sha256 is not 64 hex digits" % name)
        if not isinstance(table["known_good_api_encryption"], bool):
            raise RigError("rig.toml: %s.known_good_api_encryption must be a boolean" % name)
        for key in ("known_good_image", "nvs_backup"):
            if not isinstance(table[key], str) or not table[key]:
                raise RigError("rig.toml: %s.%s is empty" % (name, key))
        extra = {k: table[k] for k in DUT_REQUIRED if k not in ("rev", "chip", "host", "mac")}
    return DutConfig(id=dut_id, rev=table["rev"], chip=table["chip"], host=host, mac=mac, **extra)


def load_dut_api_key(env=None, network_file=NETWORK_FILE):
    """DUT API key: the private local key on the developer host, else the published one."""
    env = os.environ if env is None else env
    local = env.get("HIL_LOCAL_DUT_API_KEY")
    if local:
        if env.get("GITHUB_ACTIONS") == "true":
            raise RigError("HIL_LOCAL_DUT_API_KEY is set under GITHUB_ACTIONS; refused")
        return local
    try:
        text = Path(network_file).read_text(encoding="utf-8")
    except OSError:
        raise RigError("%s cannot be read" % Path(network_file).name) from None
    key = parse_network(text, Path(network_file)).get(DUT_KEY_NAME, "")
    if not key:
        raise RigError("%s is missing in %s" % (DUT_KEY_NAME, Path(network_file).name))
    return key


def load(env=None, network_file=NETWORK_FILE):
    env = os.environ if env is None else env
    path = env.get("HIL_RIG_CONFIG")
    if not path:
        raise RigError("HIL_RIG_CONFIG is not set")
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except OSError:
        raise RigError("HIL_RIG_CONFIG file cannot be read") from None
    except tomllib.TOMLDecodeError as exc:
        raise RigError("rig.toml is not valid TOML: %s" % exc) from None
    if data.get("schema") != 1:
        raise RigError("rig.toml: schema must be 1")
    supervisor = data.get("supervisor")
    if not isinstance(supervisor, dict):
        raise RigError("rig.toml: [supervisor] is missing")
    supervisor_host = _host(supervisor, "supervisor")
    dut_tables = data.get("dut")
    if not isinstance(dut_tables, dict) or not isinstance(dut_tables.get("a"), dict):
        raise RigError("rig.toml: [dut.a] is missing")
    duts = {"A": _dut("A", dut_tables["a"], DUT_REQUIRED)}
    if "b" in dut_tables:
        if not isinstance(dut_tables["b"], dict):
            raise RigError("rig.toml: [dut.b] must be a table")
        duts["B"] = _dut("B", dut_tables["b"], DUT_B_REQUIRED)
    hosts = [("supervisor", supervisor_host)] + [("dut." + d.lower(), c.host) for d, c in duts.items()]
    macs = [("dut." + d.lower(), c.mac) for d, c in duts.items()]
    for label, items in (("host", hosts), ("mac", macs)):
        seen = {}
        for name, value in items:
            if value in seen:
                raise RigError("rig.toml: %s.%s duplicates %s.%s" % (name, label, seen[value], label))
            seen[value] = name
    key = env.get("HIL_SUPERVISOR_KEY", "")
    if not key.strip():
        raise RigError("HIL_SUPERVISOR_KEY is not set or empty")
    return RigConfig(
        supervisor_host=supervisor_host,
        supervisor_key=key,
        duts=duts,
        dut_api_key=load_dut_api_key(env, network_file),
    )


def reports_dir(env=None):
    env = os.environ if env is None else env
    return Path(env.get("HIL_REPORTS_DIR") or "reports")


def expected_commit(env=None):
    env = os.environ if env is None else env
    return env.get("HIL_EXPECTED_COMMIT") or env.get("GITHUB_SHA") or ""


def firmware_dir(env=None):
    env = os.environ if env is None else env
    value = env.get("HIL_FW_DIR")
    if not value:
        raise RigError("HIL_FW_DIR is not set")
    return Path(value)
