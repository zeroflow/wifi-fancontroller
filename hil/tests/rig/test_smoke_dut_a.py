"""Smoke test: the commit image boots on DUT A, reports the manifest's build ID,
and its UART0 boot log from reset to API-ready plus a settle time has no [E] line
(D-14: no allowlist)."""

import json
import time

from hil import RigError, bootlog, config
from hil.dut import BOOT_SETTLE_S


def test_commit_image_boots_and_reports_build_id(dut_a, tap_a, fw_manifest, rig_config):
    image = fw_manifest.image("commit")
    report = dut_a.flash(image)  # one visible retry, RigError after two failed attempts
    print(
        "flash: ok=%s verified=%s attempts=%d durations=%s"
        % (report.ok, report.verified, report.attempts, ["%.1fs" % d for d in report.durations_s])
    )
    assert report.ok and report.verified

    info = dut_a.wait_api(noise_psk=rig_config.dut_api_key)

    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "dut-a.json").write_text(
        json.dumps(
            {"project_version": info.project_version, "compilation_time": info.compilation_time},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    problems = []
    if info.project_version == fw_manifest.build_id:
        print("build ID matches manifest: %s" % fw_manifest.build_id)
    else:
        problems.append(
            "DUT reports project_version %r, manifest build_id is %r" % (info.project_version, fw_manifest.build_id)
        )

    time.sleep(BOOT_SETTLE_S)
    tap_a.mark("scan_end")
    window = tap_a.text("reset_pressed", "scan_end")
    if tap_a.closed:
        raise RigError("serial tap lost the bridge during the scan window; boot log gate would be vacuous")
    if not bootlog.has_boot_banner(window, rig_config.duts["A"].chip):
        raise RigError("no ROM boot banner captured after reset; boot log gate would be vacuous")

    errors = bootlog.error_lines(window)
    if errors:
        problems.append("%d [E] line(s) in the UART0 boot log:\n%s" % (len(errors), "\n".join(errors)))
    else:
        print("boot log clean: 0 [E] lines")
    assert not problems, "\n".join(problems)
