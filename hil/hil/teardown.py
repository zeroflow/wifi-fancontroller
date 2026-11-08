"""Idempotent teardown: every line released, DUT A on an image it has just confirmed (HARN-09).

Order: release every supervisor switch, decide green or not, then
  green      -> the commit image stays; confirm it over the API with the HIL key and its
                build ID; a green run on refs/heads/main then updates the last-green store
  not green  -> the known-good image (D-15), chosen by known_good.select like the preflight
                heal: the last green main image when the store checks out completely, else
                v1.6.0 factory plus NVS replay; one attempt only: if DUT A does not answer
                within its deadline, or the known-good image does not verify (WR-03), the
                verdict becomes RIG ERROR and the commit image is flashed instead (D-09)
Only regions are written; nothing in this module erases flash. Safe to run twice.

Exit codes: 0 confirmed and the run's verdict stands, 3 verdict.json rewritten to RIG ERROR
(a green run whose commit image is not confirmed, or a failed known-good attempt) or the
lines could not be released. A recorded FAIL is never rewritten (D-46): the cause goes to
rig-errors.json as kind Teardown and the step still exits 3.
"""

import json
import os
import time
from pathlib import Path

from . import RigError, config, known_good, last_green, manifest

# Moved to known_good.py (WR-03); kept importable here for cmd_known_good and older callers.
from .known_good import known_good_psk, known_good_regions, sha256_file, verify_known_good  # noqa: F401

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


def rewrite_verdict(reports_dir, verdict, new="RIG ERROR", cause=""):
    """Rewrite verdict.json to `new`, except over a recorded FAIL (D-46).

    A FAIL is the firmware's outcome and a later rig condition never relabels it: verdict.json
    stays FAIL, the cause is appended to rig-errors.json (kind Teardown) and said in the log.
    """
    reports_dir = Path(reports_dir)
    if (verdict or {}).get("verdict") == "FAIL":
        record_teardown_condition(reports_dir, cause)
        return
    data = dict(verdict or {"schema": 1})
    data["verdict"] = new
    (reports_dir / "verdict.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record_teardown_condition(reports_dir, cause):
    """Append {"nodeid": null, "kind": "Teardown", "message": cause} to rig-errors.json (created as a list when missing)."""
    path = Path(reports_dir) / "rig-errors.json"
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        records = []
    if not isinstance(records, list):
        records = []
    records.append({"nodeid": None, "kind": "Teardown", "message": cause})
    path.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    say("WARNING: rig condition after a FAIL run: %s" % cause)


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
    """The verified commit manifest, or None when there is no firmware directory or it does not verify.

    Also None when the commit entry is not final (D-25): nothing but a final image may be kept on
    DUT A or flashed back to it.
    """
    if not fw_dir:
        return None
    try:
        verified = manifest.load_verified(fw_dir, config.expected_commit(), dutcfg)
        if verified.image("commit").final is not True:
            return None
    except RigError:
        return None
    return verified


def non_final_image_reporting(verified, version):
    """The manifest's non-final image (qc-auto, canary) whose build ID DUT A reports, or None."""
    if verified is None or version is None:
        return None
    for image in verified.images.values():
        if not image.final and image.build_id == version:
            return image
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


def warn(text):
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::warning title=HIL teardown::%s" % text)
    else:
        print("WARNING: %s" % text)


def run_teardown(cfg, fw_dir, job_status, reports_dir, *, supervisor, dut, dut_key):
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    state = new_state()
    try:
        supervisor.release_all()
    except RigError as exc:
        say("RIG ERROR: %s" % exc)
        state["steps"].append("lines not released")
        write_final(reports_dir, state)
        return 3
    except Exception as exc:  # noqa: BLE001 - any API fault still ends in the final-image bookkeeping
        say("RIG ERROR: switch release failed (%s)" % type(exc).__name__)
        state["steps"].append("lines not released")
        write_final(reports_dir, state)
        return 3
    say("DUT A lines released")
    state["steps"].append("lines released")

    verdict = read_verdict(reports_dir)
    green = is_green(verdict, job_status)
    state["steps"].append("run verdict: %s" % ("green" if green else "not green"))
    try:
        if green:
            exit_code = keep_commit_image(cfg, fw_dir, reports_dir, verdict, dut, dut_key, state)
        else:
            exit_code = restore_known_good(cfg, fw_dir, reports_dir, verdict, supervisor, dut, dut_key, state)
    except Exception:  # noqa: BLE001 - keep the steps recorded so far, then let the caller report it
        write_final(reports_dir, state)
        raise
    write_final(reports_dir, state)
    say("DUT A final image: %s (%s)" % (state["image"], state["version"] or "unknown version"))
    return exit_code


def keep_commit_image(cfg, fw_dir, reports_dir, verdict, dut, dut_key, state):
    """Green: the commit image stays. Confirm its build ID, then maybe update the last-green store.

    A green run whose image cannot be confirmed is no longer a PASS: the public verdict.json
    becomes RIG ERROR, as on the not-green path, so it never contradicts the red Teardown step.
    """
    dutcfg = cfg.duts["A"]
    verified = load_commit_manifest(fw_dir, dutcfg)
    version = confirm(dut, dut_key)
    matched = verified is not None and version is not None and version == verified.build_id
    state.update(image="commit", version=version, confirmed=matched)
    state["steps"].append("commit image: %s" % ("confirmed" if matched else "not confirmed"))
    update_store(dutcfg, verified, matched, state)
    if not matched:
        other = non_final_image_reporting(verified, version)
        if other is not None:
            say("RIG ERROR: DUT A runs the %s image (%s), not a final image" % (other.role, other.build_id))
        say("RIG ERROR: the commit image on DUT A could not be confirmed after a green run")
        rewrite_verdict(reports_dir, verdict, cause="commit image not confirmed after a green run")
        return 3
    return 0


def update_store(dutcfg, verified, matched, state):
    """D-15: only a confirmed green run on refs/heads/main becomes the last-green image."""
    ref = os.environ.get("GITHUB_REF", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not matched:
        stored, detail = False, "build ID not confirmed"
    else:
        try:
            net_sha = last_green.network_sha256(config.NETWORK_FILE)
            stored, detail = last_green.promote(dutcfg, verified, ref, run_id, net_sha)
        except Exception as exc:  # noqa: BLE001 - a store fault must never change the verdict or the exit code
            stored, detail = False, type(exc).__name__
    if stored:
        say("Last-green store: updated (%s)" % detail)
        state["last_green"] = {"action": "updated", "detail": detail}
        return
    say("Last-green store: unchanged (%s)" % detail)
    state["last_green"] = {"action": "unchanged", "detail": detail}
    if ref == last_green.STORE_REF and not detail.startswith("already"):
        warn("last-green store was not updated after a green main run (%s)" % detail)


def restore_known_good(cfg, fw_dir, reports_dir, verdict, supervisor, dut, dut_key, state):
    """Not green: the image known_good.select chooses (shared with the preflight heal). Returns the exit code.

    WR-03: a known-good image that does not verify no longer stops teardown on whatever DUT A runs
    (qc-auto, canary, broken); it is recorded and D-09's commit fallback runs.
    """
    try:
        chosen = known_good.select(cfg, dut_key)
    except RigError as exc:
        say("RIG ERROR: known-good image does not verify: %s" % exc)
        state["steps"].append("known-good image does not verify: %s" % exc)
        return fall_back_to_commit(
            cfg, fw_dir, reports_dir, verdict, dut, dut_key, state, cause="known-good image does not verify"
        )
    if chosen.source == "last-green":
        return restore_last_green(cfg, fw_dir, reports_dir, verdict, supervisor, dut, dut_key, state, chosen)
    return restore_v160(cfg, fw_dir, reports_dir, verdict, supervisor, dut, dut_key, state, chosen)


def restore_last_green(cfg, fw_dir, reports_dir, verdict, supervisor, dut, dut_key, state, chosen):
    say("Known-good source: last-green (%s)" % chosen.expected_build_id)
    state["known_good_source"] = "last-green"
    state["last_green"] = {"action": "used", "detail": chosen.expected_build_id}
    wait_bridge_free(supervisor)
    version = None
    try:
        # A commit image carries the HIL WiFi and key in firmware: no NVS region.
        dut.flash_regions(chosen.regions, report_name=TEARDOWN_FLASH_REPORT)
    except RigError:
        state["steps"].append("last-green flash failed")
    else:
        version = confirm(dut, chosen.psk)
    if version is not None and version == chosen.expected_build_id:
        state.update(image="last-green", version=version, confirmed=True)
        state["steps"].append("last-green image: confirmed")
        return 0
    state["steps"].append("last-green image: not confirmed")
    return fall_back_to_commit(cfg, fw_dir, reports_dir, verdict, dut, dut_key, state)


def restore_v160(cfg, fw_dir, reports_dir, verdict, supervisor, dut, dut_key, state, chosen):
    say("Known-good source: v1.6.0 (%s)" % chosen.detail)
    state["known_good_source"] = "v1.6.0"
    state["last_green"] = {"action": "rejected", "detail": chosen.detail}
    wait_bridge_free(supervisor)
    version = None
    try:
        dut.flash_regions(chosen.regions, report_name=TEARDOWN_FLASH_REPORT)
    except RigError:
        state["steps"].append("known-good flash failed")
    else:
        version = confirm(dut, chosen.psk)
    if version is not None:
        state.update(image="known-good", version=version, confirmed=True)
        state["steps"].append("known-good image: confirmed")
        return 0
    state["steps"].append("known-good image: no answer within the deadline")
    return fall_back_to_commit(cfg, fw_dir, reports_dir, verdict, dut, dut_key, state)


def fall_back_to_commit(cfg, fw_dir, reports_dir, verdict, dut, dut_key, state, cause="known-good image did not come back"):
    """D-09: the one known-good attempt failed, or its image does not verify. RIG ERROR, then the commit image."""
    if cause == "known-good image did not come back":
        say("RIG ERROR: DUT A did not come back on the known-good image; flashing the commit image (D-09)")
    else:
        say("RIG ERROR: %s; flashing the commit image (D-09)" % cause)
    rewrite_verdict(reports_dir, verdict, cause=cause)
    flash_commit_image(dut, fw_dir, cfg.duts["A"], dut_key, state)
    return 3
