"""REG-02, D-36: DUT A is upgraded from the latest release to the commit image by OTA, the way a
customer board is upgraded, and the upgrade is proven safe.

The release predates OTA encryption, so this one upload is allowed in plaintext (maintainer decision
allow-one-plaintext, 2026-11-08, T-03-24): the image carries only the HIL values D-01 classed as
published, the HIL network is isolated, and the key is still offered. Every other OTA keeps refusing
plaintext. A failed upload or a wrong build ID afterwards is a FAIL (D-26).

While the release's bootloader is in flash, UART0 shows no app line of any image and the upgrade reboot's
ROM banner goes to USB (measured 2026-11-09). So this leg is proven over the API (maintainer decision
serial-restore-after-upgrade, 2026-11-09): the reboot by the build ID changing from the release's version to
the commit's (Dut.ota with the UART0 banner check off, for this upgrade only); then nothing is pressed until
`Boot seems successful` of the new image is in the API log since the OTA end (wait_confirmed with the
DutLink, a signal wait with a deadline), and that time is recorded (mark_s, the D-39 input for 03-13).
The rest of the window up to SOAK_S after the OTA end is observation only: the API session of the new image
must not drop, UART0 must show 0 ROM boot banners (a banner there is a reboot of the running image), the
D-14 boot-log gate (Amendment 4 included) runs over the API log, and the commit's build ID must still
answer at the end. Everything goes to reports/upgrade-dut-a.json. test_12 then writes the commit image
over serial so every later leg runs under the commit's own bootloader again.
"""

import json
import time

import pytest

from hil import RigError, bootlog, config, summary
from hil.dut import LINK_WAIT_S, SOAK_S

pytestmark = pytest.mark.image(before="baseline", after="commit")

LABEL = "baseline_commit"
UPGRADE_REPORT = "upgrade-dut-a.json"


def _round(value):
    return None if value is None else round(float(value), 1)


def test_ota_from_the_release_to_the_commit(dut_a, dut_link, tap_a, fw_manifest, fw_baseline, rig_config):
    chip = rig_config.duts["A"].chip
    key = rig_config.dut_api_key
    image = fw_manifest.image("commit")
    dut_link.use_key(key)  # the commit image answers with the HIL key only
    dut_a.ota(image, noise_psk=key, allow_plaintext=True, label=LABEL, uart_banner=False)
    upgrade = dict(dut_a.last_ota)
    ota_end_at = dut_a.ota_end_at
    dut_link.wait_connected(LINK_WAIT_S, project_version=image.build_id)  # the session the soak watches
    sessions = dut_link.sessions()

    mark_s = dut_a.wait_confirmed(link=dut_link)  # REG-02: no press before the new image is marked valid
    print("DUT %s marked the upgraded image valid %.1f s after the OTA (API log)" % (dut_a.id, mark_s))

    # Observation only: the soak waits for no state, it watches until SOAK_S after the OTA's end.
    soak_until = ota_end_at + SOAK_S
    while True:
        if tap_a.closed:
            raise RigError("serial tap lost the bridge during the soak; the UART0 banner count would be vacuous")
        left = soak_until - time.monotonic()
        if left <= 0:
            break
        time.sleep(min(1.0, left))
    tap_a.mark("soak_end")
    soak_s = time.monotonic() - ota_end_at
    dropped = not dut_link.connected() or dut_link.sessions() != sessions

    banners = bootlog.count_boot_banners(tap_a.text(upgrade["window_start"], "soak_end"), chip)
    api_lines = dut_link.log_since(ota_end_at)
    errors, allowed = bootlog.check_api_log(api_lines, "upgrade")
    reported = dut_a.probe(key)  # the commit's build ID must still answer at the end of the soak

    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "dut-a.json").write_text(
        json.dumps(
            {"project_version": reported.project_version, "compilation_time": reported.compilation_time},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    problems = []
    if reported.project_version != image.build_id:
        problems.append(
            "DUT %s reports %s after the upgrade, expected %s" % (dut_a.id, reported.project_version, image.build_id)
        )
    if banners:
        problems.append("%d ROM boot banner(s) on UART0 during the soak, expected 0 (a reboot of the upgraded image)" % banners)
    if dropped:
        problems.append("the API session dropped during the soak (a reboot or a lost link of the upgraded image)")
    if errors:
        problems.append("%d [E] line(s) in the API log of the upgraded boot:\n%s" % (len(errors), "\n".join(errors)))
    record = {
        "schema": 1,
        "tag": fw_baseline.tag,
        "from_version": fw_baseline.version,
        "build_id": image.build_id,
        "reported_build_id": reported.project_version,
        "label": LABEL,
        "reboot_proof": "build id",
        "transfer_s": _round(upgrade["transfer_s"]),
        "boot_s": _round(upgrade["boot_s"]),
        "mark_s": _round(mark_s),
        "mark_source": "api",
        "soak_s": _round(soak_s),
        "banners": banners,
        "api_session_dropped": dropped,
        "api_log_lines": len(api_lines),
        "errors": list(errors),
        "allowed": list(allowed),
        "gate": "fail" if errors else "pass",
        "gate_source": "api",
    }
    (reports / UPGRADE_REPORT).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary.record_timing("soak_mark", mark_s)
    assert not problems, "\n".join(problems)
    print(
        "DUT %s upgraded from %s to %s by OTA: transfer %.1f s, boot %.1f s, marked valid after %.1f s, "
        "%.1f s soak with 0 UART0 banners and no API drop, API boot log clean (%d allowlisted)"
        % (dut_a.id, fw_baseline.tag, image.build_id, upgrade["transfer_s"], upgrade["boot_s"], mark_s, soak_s, len(allowed))
    )
