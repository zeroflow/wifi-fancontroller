"""03-11 (maintainer decision serial-restore-after-upgrade, 2026-11-09): after the upgrade, the commit image
is written over serial so every later leg runs under the commit's own bootloader.

test_11 leaves the release's second-stage bootloader in flash (an OTA writes only the app partition). Under
it UART0 shows no app line of any image, even after an EN reset (measured 2026-11-09), so the QC, canary,
broken-image and rollback legs could not read their UART0 evidence. This test writes the full commit factory
image at 0x0 (bootloader, partition table and app, a region write; no erase, so the NVS stays) through the
Bootloader button, boots it with the Reset press, and requires the commit's build ID on the API, its
`Project ... version <build id>` line on UART0 (the commit bootloader took over) and a clean D-14 boot log
on UART0 (Amendment 4 included). From here on every leg runs exactly as in 03-10.
"""

import re
import time

import pytest

from hil import RigError, bootlog, recovery, summary
from hil import dut as dut_module

pytestmark = pytest.mark.image("commit")


def test_commit_image_is_written_over_serial_after_the_upgrade(dut_a, tap_a, fw_manifest, rig_config):
    cfg = rig_config.duts["A"]
    label = "DUT %s" % dut_a.id
    image = fw_manifest.image("commit")
    try:
        at_zero = int(str(image.offset), 16) == 0
    except ValueError:
        at_zero = False
    if not at_zero:
        raise RigError("the commit factory image is at %s, not 0x0: it would not replace the release bootloader" % image.offset)

    report = dut_a.flash(image)
    flashed_at = time.monotonic()
    info = dut_a.wait_running(rig_config.dut_api_key, dut_a.last_reset_mark)
    boot_s = time.monotonic() - flashed_at

    time.sleep(dut_module.BOOT_SETTLE_S)
    tap_a.mark("restore_scan_end")
    errors, allowed = bootlog.check_boot_window(tap_a, dut_a.last_reset_mark, "restore_scan_end", cfg.chip, "restore")
    window = bootlog.strip_ansi(tap_a.text(dut_a.last_reset_mark, "restore_scan_end"))
    project_line = re.search(recovery.project_line_regex(image.build_id), window) is not None
    summary.record_timing("restore_flash", sum(report.durations_s))
    summary.record_timing("restore_boot", boot_s)

    problems = []
    if not report.verified:
        problems.append("%s: the serial restore was not verified" % label)
    if info.project_version != image.build_id:
        problems.append("%s reports %s after the serial restore, expected %s" % (label, info.project_version, image.build_id))
    if not project_line:
        problems.append("%s: no Project line of %s on UART0 after the restore (the commit bootloader did not take over)" % (label, image.build_id))
    if errors:
        problems.append("%d [E] line(s) in the UART0 boot log of the restore:\n%s" % (len(errors), "\n".join(errors)))
    assert not problems, "\n".join(problems)
    print(
        "%s restored over serial: %s (flash %.1f s, boot %.1f s), UART0 boot log clean (%d allowlisted)"
        % (label, image.build_id, sum(report.durations_s), boot_s, len(allowed))
    )
