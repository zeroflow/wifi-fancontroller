"""The broken-image recovery leg: the dark window, the OTA-state line and the UART-path facts (REC-01, REC-02).

D-41: the broken image is delivered by OTA from the commit image, the way a customer gets it. Its own boot
line says which OTA state it runs in; the bootloader would roll back an image that is not `valid`, which
would void the recovery proof, so test_40 reads the line on every run.
D-42: the 65 s dark window is an OBSERVATION window, not a state wait: it is never cut short, and any
accepted connection on 6053 or 3232, or a ROM boot banner inside it, fails the test. The supervisor's
own port 6053 on the same network is the control on every poll: a control that stops answering means the
network, not the DUT, was dark, and that is a RigError (the negative control would be void).
"""

import json
import re
import socket
import time

from . import bootlog, config, contract, dut

DARK_WINDOW_S = 65
DARK_POLL_S = 5
OTA_STATE_LINE_S = 10
REPORT = "recovery-dut-a.json"

# `HIL broken image OTA state: <state>` (rev3.2.broken.yaml, 03-05): esp_ota_img_states_t as text.
OTA_STATE_RE = re.compile(r"HIL broken image OTA state: (valid|pending verify|new|invalid|aborted|undefined|unknown)")


def project_line_regex(build_id):
    """Regex of ESPHome's `Project <name> version <build id>` line (the image's name is not assumed)."""
    return r"Project \S+ version " + re.escape(build_id)


def ota_state_in(text):
    """The OTA state the broken image printed on UART0, or None when its line is not in `text` (D-41)."""
    found = OTA_STATE_RE.search(bootlog.strip_ansi(text))
    return found.group(1) if found else None


def _accepts(connect, address, connect_s):
    try:
        connect(address, timeout=connect_s).close()
    except OSError:
        return False
    return True


def watch_dark(
    host,
    supervisor_host,
    window_s=DARK_WINDOW_S,
    poll_s=DARK_POLL_S,
    connect_s=dut.PORT_PROBE_S,
    clock=time.monotonic,
    sleep=time.sleep,
    connect=socket.create_connection,
):
    """Poll the DUT's API and OTA ports and the supervisor's API port every `poll_s` for `window_s` seconds.

    Returns the polls `{"t": s, "api": bool, "ota": bool, "supervisor": bool}` at t = 0, poll_s, ... up to and
    including window_s. An accepted port is recorded, never raised: the caller decides. Polls are scheduled
    from the start, so slow refusals (a dropped SYN costs up to connect_s per probe) delay a poll but never
    remove one, and the whole window is always observed.
    """
    polls = []
    start = clock()
    k = 0
    while k * poll_s <= window_s:
        wait = start + k * poll_s - clock()
        if wait > 0:
            sleep(wait)
        polls.append(
            {
                "t": round(clock() - start),
                "api": _accepts(connect, (host, contract.API_PORT), connect_s),
                "ota": _accepts(connect, (host, dut.OTA_PORT), connect_s),
                "supervisor": _accepts(connect, (supervisor_host, contract.API_PORT), connect_s),
            }
        )
        k += 1
    return polls


def control_lost(polls):
    """True when the supervisor refused on any poll: the window proves nothing about the DUT then."""
    return any(not poll["supervisor"] for poll in polls)


def dark_problems(polls, rebooted, label="DUT A"):
    """What makes the window not dark: the first poll at which each port answered, and a reboot (ROM banner)."""
    problems = []
    for key, port in (("api", contract.API_PORT), ("ota", dut.OTA_PORT)):
        for poll in polls:
            if poll[key]:
                problems.append("%s answered on port %d at t=%d s" % (label, port, poll["t"]))
                break
    if rebooted:
        problems.append("%s rebooted during the dark window" % label)
    return problems


def uart_path_problems(facts, label="DUT A"):
    """One named problem per UART-path fact that does not hold (D-42); an empty list is the recovery proof."""
    problems = []
    if not facts["dark_at_start"]:
        problems.append("%s was not dark at the start (6053 or 3232 answered): the recovery proves nothing" % label)
    if not facts["flash_ok"]:
        problems.append("the UART flash did not report ok")
    if not facts["verified"]:
        problems.append("the UART flash was not verified")
    if not facts["download_banner"]:
        problems.append("no ROM download banner after the Bootloader press: the loader was not entered")
    if facts["ota_uploads_during_test"]:
        problems.append(
            "%d OTA upload(s) during the recovery: only the Bootloader button and the UART flash may bring %s back"
            % (facts["ota_uploads_during_test"], label)
        )
    if not facts["api_after_flash"]:
        problems.append("the API did not answer after the flash")
    if facts["build_id_after"] != facts["expected_build_id"]:
        problems.append(
            "after the recovery %s reports %r, expected %r" % (label, facts["build_id_after"], facts["expected_build_id"])
        )
    return problems


def write_report(section, data):
    """Merge `data` as `section` into reports/recovery-dut-a.json (created when missing) and return its path."""
    reports = config.reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / REPORT
    try:
        merged = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        merged = {}
    if not isinstance(merged, dict):
        merged = {}
    merged[section] = data
    path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
