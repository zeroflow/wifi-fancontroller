"""The latest release as DUT A's baseline on the runner (REG-01, D-36, D-06, D-07).

The hosted prepare job (tools/fetch_baseline.py, 03-09) is the only fetcher: it writes the
factory image and baseline.json (schema 1) after every digest agreed. Nothing here downloads.
On the runner, load_verified re-hashes the image against baseline.json and checks it against
rig.toml before anything is pressed; flash hashes it once more right before the write, writes
it with the NVS backup (region writes, never an erase) and waits until DUT A answers without
encryption (D-04) on the release's version.

The release is not the firmware under test: a DUT that does not rejoin on it is a rig fault
(RigError, RIG ERROR), never a FAIL. Errors name keys, never values.
"""

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from . import FirmwareFailure, RigError, summary
from .known_good import sha256_file
from .manifest import BARE_NAME_RE

BASELINE_FILE = "baseline.json"
REPORT = "baseline-dut-a.json"
FLASH_REPORT = "baseline-flash-dut-a.json"
TAG_RE = re.compile(r"v\d+\.\d+\.\d+")  # fullmatch: a trailing newline is not a tag
SHA256_RE = re.compile(r"[0-9a-f]{64}")
CHIP_FAMILY = {"ESP32-S2": "esp32s2", "ESP32-C6": "esp32c6"}
# The prepare job compares these with the computed digest; api is null when GitHub has none.
REQUIRED_DIGESTS = ("manifest", "sidecar")
OPTIONAL_DIGESTS = ("api",)
REJOIN_S = 90  # D-37 deadline: the flash's reset -> DUT A answers on the release


@dataclass(frozen=True)
class Baseline:
    tag: str
    rev: str
    path: Path
    sha256: str
    offset: str
    version: str
    digests: dict


def _fail(message):
    raise RigError("baseline.json: %s" % message)


def load_verified(directory, dutcfg):
    """The baseline in `directory`, after baseline.json agreed with rig.toml and the file re-hashed to its sha256."""
    directory = Path(directory)
    name = "dut.%s" % dutcfg.id.lower()
    try:
        data = json.loads((directory / BASELINE_FILE).read_text(encoding="utf-8"))
    except OSError:
        raise RigError("baseline.json cannot be read") from None
    except ValueError:
        raise RigError("baseline.json is not valid JSON") from None
    if not isinstance(data, dict):
        raise RigError("baseline.json is not an object")
    if data.get("schema") != 1:
        _fail("schema must be 1")
    tag = data.get("tag")
    if not isinstance(tag, str) or not TAG_RE.fullmatch(tag):
        _fail("tag is not vX.Y.Z")
    if data.get("rev") != dutcfg.rev:
        _fail("rev does not match rig.toml %s.rev" % name)
    asset = data.get("asset")
    if not isinstance(asset, str) or not BARE_NAME_RE.match(asset) or ".." in asset:
        _fail("asset must be a bare file name")
    if CHIP_FAMILY.get(data.get("chip_family")) != dutcfg.chip:
        _fail("chip_family does not match rig.toml %s.chip" % name)
    offset = data.get("offset")
    try:
        offset_value = int(offset, 16)
    except (TypeError, ValueError):
        _fail("offset is not hex")
    if offset_value != int(dutcfg.flash_offset, 16):
        _fail("offset does not match rig.toml %s.flash_offset" % name)
    sha256 = data.get("sha256")
    if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
        _fail("sha256 is not 64 lowercase hex digits")
    digests = data.get("digests")
    if not isinstance(digests, dict):
        _fail("digests is not an object")
    for key in OPTIONAL_DIGESTS + REQUIRED_DIGESTS:
        value = digests.get(key)
        if value is None and key in OPTIONAL_DIGESTS:
            continue
        if value != sha256:
            _fail("digests.%s does not match sha256" % key)
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        _fail("version is missing or empty")
    path = directory / asset
    if not path.is_file():
        _fail("asset is not in the baseline directory")
    _check_hash(path, sha256)
    return Baseline(
        tag=tag,
        rev=data["rev"],
        path=path,
        sha256=sha256,
        offset=offset,
        version=version,
        digests={key: digests.get(key) for key in OPTIONAL_DIGESTS + REQUIRED_DIGESTS},
    )


def _check_hash(path, sha256):
    try:
        digest = sha256_file(path)
    except OSError:
        _fail("asset is not in the baseline directory")
    if digest != sha256:
        _fail("sha256 does not match the factory file")


def _check_nvs(dutcfg):
    """The runner-local NVS dump (outside _work, D-08) must be readable and exactly nvs_size long."""
    try:
        size = Path(dutcfg.nvs_backup).stat().st_size
    except OSError:
        raise RigError("nvs_backup cannot be read") from None
    expected = int(dutcfg.nvs_size, 16)
    if size != expected:
        raise RigError("nvs_backup has %d bytes, nvs_size says %d" % (size, expected))


def _first_line(exc):
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def drift_warning(baseline, dutcfg):
    """D-37: None when the NVS dump was captured with the baseline's release, else the warning text."""
    if dutcfg.nvs_release_tag == baseline.tag:
        return None
    return "NVS captured with %s, baseline %s" % (dutcfg.nvs_release_tag, baseline.tag)


def announce(warning):
    """The drift warning on stdout, and as a GitHub annotation under Actions."""
    print("WARNING: %s" % warning)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::warning title=HIL baseline::%s" % warning)


def flash(dut, baseline, dutcfg, report_name=FLASH_REPORT, with_nvs=True, deadline_s=REJOIN_S):
    """Write the baseline (plus the NVS backup) and wait for DUT A on it. Returns (version, rejoin_s).

    Every check runs before the first press. Without the NVS backup the image has no WiFi, so there
    is nothing to wait for: (None, None). A dump captured with another release is replayed anyway
    (D-37): a rejoin is announced as a warning, no rejoin is RigError naming the re-capture to do.
    """
    if with_nvs:
        _check_nvs(dutcfg)
    _check_hash(baseline.path, baseline.sha256)
    regions = [(baseline.offset, baseline.path)]
    if with_nvs:
        regions.append((dutcfg.nvs_offset, Path(dutcfg.nvs_backup)))
    report = dut.flash_regions(regions, report_name=report_name)
    summary.record_timing("baseline_flash", sum(report.durations_s))
    if not with_nvs:
        return None, None
    started = time.monotonic()
    try:
        info = dut.wait_running(None, dut.last_reset_mark, deadline_s=deadline_s)
    except (RigError, FirmwareFailure) as exc:  # SafeModeError is a RigError
        message = "DUT %s did not rejoin on the release baseline %s within %d s (%s)" % (
            dut.id,
            baseline.tag,
            deadline_s,
            _first_line(exc),
        )
        if drift_warning(baseline, dutcfg):
            message += "; NVS captured with %s: re-capture NVS for %s" % (dutcfg.nvs_release_tag, baseline.tag)
        raise RigError(message) from None
    rejoin_s = time.monotonic() - started
    if info.project_version != baseline.version:
        raise RigError(
            "DUT %s reports project_version %s, not the baseline's %s"
            % (dut.id, info.project_version, baseline.version)
        )
    warning = drift_warning(baseline, dutcfg)
    if warning:
        announce(warning)
    return info.project_version, rejoin_s


def _flash_seconds(reports_dir):
    try:
        data = json.loads((Path(reports_dir) / FLASH_REPORT).read_text(encoding="utf-8"))
        return round(sum(float(d) for d in data["durations_s"]), 1)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_report(reports_dir, baseline, dutcfg, version, rejoin_s, *, flash_s=None, nvs_replayed=True):
    """reports/baseline-dut-a.json; the summary line is rendered from it (03-12). Returns the dict written.

    flash_s defaults to the attempts recorded in baseline-flash-dut-a.json.
    """
    reports_dir = Path(reports_dir)
    if flash_s is None:
        flash_s = _flash_seconds(reports_dir)
    data = {
        "schema": 1,
        "tag": baseline.tag,
        "rev": baseline.rev,
        "asset": baseline.path.name,
        "sha256": baseline.sha256,
        "digests_compared": sorted(key for key, value in baseline.digests.items() if value is not None),
        "flash_s": None if flash_s is None else round(float(flash_s), 1),
        "rejoin_s": None if rejoin_s is None else round(float(rejoin_s), 1),
        "version": version,
        "nvs_replayed": bool(nvs_replayed),
        # Without the replay there is no dump whose tag could drift.
        "nvs_release_tag": dutcfg.nvs_release_tag if nvs_replayed else None,
        "drift_warning": drift_warning(baseline, dutcfg) if nvs_replayed else None,
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / REPORT).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data
