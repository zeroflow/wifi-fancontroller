"""REC-02, D-41, D-42: a broken image delivered by OTA is alive but dark, and stays that way for 65 s.

DUT A is on the commit image (test_35). The broken image (no wifi, no api, no ota; rev3.2.broken.yaml) is
sent to it by encrypted OTA, the way a customer gets an update (D-41). Three facts are checked and reported
together, because the dark window always runs to its end:

  * it booted: its `Project ... version 3.2+broken.<hex>` line is on UART0 (Dut.ota_dark);
  * D-41 holds: its own `HIL broken image OTA state:` line says `valid`. A broken image that is not marked
    valid would be rolled back by the bootloader on the next reboot, which would void the recovery proof;
  * it is dark: for 65 s (an observation window, never shortened) neither 6053 nor 3232 accepts a
    connection and no ROM boot banner appears. The supervisor's own 6053 is the control on every poll: a
    supervisor that stops answering is a RigError, because then the window shows the network, not the DUT.

There is no `after` state: a dark DUT cannot be checked. test_41 recovers it.
"""

import pytest

from hil import RigError, bootlog, recovery

pytestmark = pytest.mark.image(before="commit")


def test_broken_image_is_alive_but_dark(dut_a, tap_a, fw_manifest, rig_config):
    cfg = rig_config.duts["A"]
    label = "DUT %s" % dut_a.id
    dut_a.ota_dark(fw_manifest.image("broken"), noise_psk=rig_config.dut_api_key)

    # The state line is logged late in setup, after the Project line ota_dark waited for.
    try:
        tap_a.wait_for(recovery.OTA_STATE_RE.pattern, since="ota_end_broken", deadline_s=recovery.OTA_STATE_LINE_S)
    except RigError:
        pass  # state stays None; it is reported with everything else below
    if tap_a.closed:
        raise RigError("serial tap lost the bridge during the dark window; the reboot check would be vacuous")
    state = recovery.ota_state_in(tap_a.text("ota_end_broken"))

    polls = recovery.watch_dark(cfg.host, rig_config.supervisor_host)
    rebooted = bootlog.has_boot_banner(tap_a.text("broken_up"), cfg.chip)
    recovery.write_report("dark", {"ota_state": state, "polls": polls, "rebooted": rebooted})
    if recovery.control_lost(polls):
        lost = next(p["t"] for p in polls if not p["supervisor"])
        raise RigError("negative control void: the supervisor stopped answering at t=%d s" % lost)

    problems = recovery.dark_problems(polls, rebooted, label)
    if state != "valid":
        problems.append(
            "D-41 does not hold: the broken image booted with OTA state %s, so the bootloader would roll it back on "
            "the next reboot" % ("no OTA-state line on UART0" if state is None else repr(state))
        )
    assert not problems, "\n".join(problems)
    print(
        "%s is alive but dark: Project line seen, OTA state valid, 6053 and 3232 refused for %d s"
        % (label, recovery.DARK_WINDOW_S)
    )
