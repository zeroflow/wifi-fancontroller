"""REC-01, D-42: the dark DUT is recovered through the Bootloader button and a UART flash, and only so.

DUT A runs the broken image (test_40). The commit factory image is written over the serial bridge after
the Bootloader button; the Reset press that follows boots it. The test passes only when every fact of the
UART path holds (recovery.uart_path_problems): DUT A was dark at the start, the flash is ok and verified,
the ROM download banner followed the Bootloader mark, no OTA upload happened during the test, the API
answered for the first time after the flash, and it reports the commit's build ID.

This flash is the run's last write: DUT A ends on the commit image, running the commit image's own
bootloader, so the final image is never inside an OTA rollback window (D-36).
"""

import pytest

from hil import FirmwareFailure, bootlog, contract, recovery
from hil import dut as dut_module

pytestmark = pytest.mark.image(after="commit")


def test_uart_flash_recovers_the_dark_dut(dut_a, tap_a, fw_manifest, rig_config):
    cfg = rig_config.duts["A"]
    label = "DUT %s" % dut_a.id
    image = fw_manifest.image("commit")

    dark_at_start = not dut_a._port_open(contract.API_PORT) and not dut_a._port_open(dut_module.OTA_PORT)
    uploads_before = dut_a.ota_count
    reset_before = dut_a.last_reset_mark
    report = dut_a.flash(image)
    download_banner = bootlog.has_download_banner(tap_a.text(dut_a.last_bootloader_mark), cfg.chip)

    info, failure = None, ""
    try:
        info = dut_a.wait_running(rig_config.dut_api_key, dut_a.last_reset_mark)
    except FirmwareFailure as exc:  # booted but never answered: reported with the other facts
        failure = str(exc)

    facts = {
        "dark_at_start": dark_at_start,
        "flash_ok": report.ok,
        "verified": report.verified,
        "download_banner": download_banner,
        "ota_uploads_during_test": dut_a.ota_count - uploads_before,
        "build_id_after": None if info is None else info.project_version,
        "expected_build_id": image.build_id,
        "api_after_flash": info is not None and dut_a.last_reset_mark != reset_before,
    }
    recovery.write_report("uart", facts)

    problems = recovery.uart_path_problems(facts, label)
    assert not problems, "\n".join(problems + ([failure] if failure else []))
    print("%s recovered over UART: %s" % (label, info.project_version))
