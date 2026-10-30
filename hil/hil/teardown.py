"""Idempotent teardown: every line released, DUT A on an image it has just confirmed (HARN-09).

Order: release every supervisor switch, decide green or not, then
  green      -> the commit image stays; confirm it over the API with the HIL key
  not green  -> the known-good image: v1.6.0 factory plus NVS replay (D-15);
                if DUT A does not answer within its deadline the verdict becomes
                RIG ERROR and the commit image is flashed instead (D-09)
Only regions are written; nothing in this module erases flash. Safe to run twice.

Exit codes: 0 confirmed and the run's verdict stands, 3 verdict rewritten to RIG ERROR
or nothing could be confirmed.
"""

import hashlib
import json
import os
import time
from pathlib import Path

from . import RigError, config, manifest

FINAL_IMAGE = "final-image.json"
TEARDOWN_FLASH_REPORT = "teardown-flash-dut-a.json"
BRIDGE_FREE_S = 15


def say(line):
    """Print a line and append it to the job step summary when there is one."""
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def read_verdict(reports_dir):
    """The run's verdict.json as a dict, or None when it is missing or unreadable."""
    try:
        data = json.loads((Path(reports_dir) / "verdict.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def is_green(verdict, job_status):
    return bool(verdict) and verdict.get("verdict") == "PASS" and job_status in ("", "success")


def rewrite_verdict(reports_dir, verdict, new="RIG ERROR"):
    data = dict(verdict or {"schema": 1})
    data["verdict"] = new
    (Path(reports_dir) / "verdict.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_known_good(dutcfg, with_nvs=True):
    """The v1.6.0 image must match rig.toml's sha256, and the NVS backup must have its size (before any press)."""
    try:
        digest = sha256_file(dutcfg.known_good_image)
    except OSError:
        raise RigError("known_good_image cannot be read") from None
    if digest != dutcfg.known_good_sha256:
        raise RigError("known_good_image sha256 does not match known_good_sha256")
    if with_nvs:
        try:
            size = Path(dutcfg.nvs_backup).stat().st_size
        except OSError:
            raise RigError("nvs_backup cannot be read") from None
        if size != int(dutcfg.nvs_size, 16):
            raise RigError("nvs_backup has %d bytes, nvs_size says %d" % (size, int(dutcfg.nvs_size, 16)))


def known_good_regions(dutcfg, with_nvs=True):
    regions = [(dutcfg.flash_offset, Path(dutcfg.known_good_image))]
    if with_nvs:
        regions.append((dutcfg.nvs_offset, Path(dutcfg.nvs_backup)))
    return regions


def known_good_psk(dutcfg, dut_key):
    """The release image has no API encryption; a known-good image that has it uses the HIL key."""
    return dut_key if dutcfg.known_good_api_encryption else None


def write_final(reports_dir, state):
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / FINAL_IMAGE).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def new_state():
    return {
        "image": "unknown",
        "version": None,
        "confirmed": False,
        "steps": [],
        "known_good_source": None,
        "last_green": {"action": None, "detail": ""},
    }


def wait_bridge_free(supervisor, clock=time.monotonic, sleep=time.sleep):
    """A cancelled run's esptool may still hold the bridge for a moment; wait briefly, then go on."""
    end = clock() + BRIDGE_FREE_S
    while supervisor.serial_connected("A"):
        if clock() >= end:
            say("WARNING: DUT A serial bridge still held by another client; continuing")
            return
        sleep(0.5)


def confirm(dut, psk):
    """Project version reported by DUT A within its API deadline, or None when it does not answer."""
    try:
        info = dut.wait_api(noise_psk=psk)
    except RigError:
        return None
    return info.project_version


def load_commit_manifest(fw_dir, dutcfg):
    """The verified commit manifest, or None when there is no firmware directory or it does not verify."""
    if not fw_dir:
        return None
    try:
        return manifest.load_verified(fw_dir, config.expected_commit(), dutcfg)
    except RigError:
        return None


def flash_commit_image(dut, fw_dir, dutcfg, dut_key, state):
    """D-09: put the commit image on DUT A over UART and confirm it with the HIL key."""
    verified = load_commit_manifest(fw_dir, dutcfg)
    if verified is None:
        state["steps"].append("commit image: manifest does not verify")
        return
    image = verified.image("commit")
    try:
        dut.flash_regions([(image.offset, image.path)], report_name=TEARDOWN_FLASH_REPORT)
    except RigError:
        state["steps"].append("commit image: flash failed")
        return
    version = confirm(dut, dut_key)
    state["version"] = version
    state["image"] = "commit"
    state["confirmed"] = version is not None and version == verified.build_id
    state["steps"].append("commit image: %s" % ("confirmed" if state["confirmed"] else "not confirmed"))


def run_teardown(cfg, fw_dir, job_status, reports_dir, *, supervisor, dut, dut_key):
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    dutcfg = cfg.duts["A"]
    state = new_state()
    try:
        supervisor.release_all()
    except RigError as exc:
        say("RIG ERROR: %s" % exc)
        state["steps"].append("lines not released")
        write_final(reports_dir, state)
        return 3
    say("DUT A lines released")
    state["steps"].append("lines released")

    verdict = read_verdict(reports_dir)
    green = is_green(verdict, job_status)
    state["steps"].append("run verdict: %s" % ("green" if green else "not green"))
    exit_code = 0
    try:
        if green:
            version = confirm(dut, dut_key)
            state.update(image="commit", version=version, confirmed=version is not None)
            state["steps"].append("commit image: %s" % ("confirmed" if state["confirmed"] else "no answer"))
            exit_code = 0 if state["confirmed"] else 3
        else:
            exit_code = known_good(cfg, fw_dir, reports_dir, verdict, supervisor, dut, dut_key, state)
    except RigError:
        write_final(reports_dir, state)
        raise
    write_final(reports_dir, state)
    say("DUT A final image: %s (%s)" % (state["image"], state["version"] or "unknown version"))
    return exit_code


def known_good(cfg, fw_dir, reports_dir, verdict, supervisor, dut, dut_key, state):
    """Not green: v1.6.0 factory plus NVS replay. Returns the exit code."""
    dutcfg = cfg.duts["A"]
    say("Known-good source: v1.6.0 (no last-green store)")
    state["known_good_source"] = "v1.6.0"
    verify_known_good(dutcfg)
    wait_bridge_free(supervisor)
    version = None
    try:
        dut.flash_regions(known_good_regions(dutcfg), report_name=TEARDOWN_FLASH_REPORT)
    except RigError:
        state["steps"].append("known-good flash failed")
    else:
        version = confirm(dut, known_good_psk(dutcfg, dut_key))
    if version is not None:
        state.update(image="known-good", version=version, confirmed=True)
        state["steps"].append("known-good image: confirmed")
        return 0
    state["steps"].append("known-good image: no answer within the deadline")
    say("RIG ERROR: DUT A did not answer on the known-good image; flashing the commit image (D-09)")
    rewrite_verdict(reports_dir, verdict)
    flash_commit_image(dut, fw_dir, dutcfg, dut_key, state)
    return 3
