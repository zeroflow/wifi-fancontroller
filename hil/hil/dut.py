"""One device under test: bootloader entry, flash, reset, API read-back.

Dut.flash owns the only retry in the harness: a failed flash attempt is retried
once after re-entering the bootloader, and the retry is always visible (report
file, GitHub warning, step summary). There are no test-level reruns anywhere.
"""

import asyncio
import hashlib
import json
import os
import socket
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from aioesphomeapi import APIClient, APIConnectionError

from . import FirmwareFailure, RigError, bootlog, config, contract, entities, manifest
from .budget import ResetBudget, SafeModeError
from .flasher import FLASH_ATTEMPT_S
from .ota import Ota

API_CONNECT_S = 10
API_WAIT_S = 90
BOOT_SETTLE_S = 15
BOOTLOADER_SETTLE_S = 0.5
FLASH_ATTEMPTS = 2
OTA_BOOT_S = 90  # upload finished -> the new build ID answers on the API
OTA_CONFIRM_WINDOW_S = 75  # safe_mode boot_is_good_after (60 s) plus margin; see Dut.reset
BOOTLOADER_BANNER_S = 3  # Bootloader pressed -> the ROM download-mode banner is on UART0
CONFIRM_WAIT_S = 75  # most an EN reset waits for 'Boot seems successful' of an unconfirmed OTA image
SETTLE_S = 10  # one shared deadline for the whole of Dut.settle
SAFE_MODE_DETECT_S = 45  # most a safe-mode press may take until SAFE MODE IS ACTIVE shows on UART0
PORT_PROBE_S = 2  # TCP connect deadline of the OTA / API port probes after an API timeout
OTA_PORT = 3232

# HARN-03: every rig test names the image DUT A runs before and after it (marker `image`), except the
# tests listed here. A new rig test cannot become exempt by omission: it needs an entry and a reason.
STATE_EXEMPT = {
    "test_00_contract.py": "supervisor-only: checks the supervisor contract and switch states, never touches DUT A",
}


def state_roles(marker, module_name, roles=None):
    """(before, after) image roles a test starts and ends in, from its `image` marker.

    `image("qc-auto")` is ("qc-auto", "qc-auto"); the keywords before= and after= override one side
    and may be given alone (`image(after="commit")` is (None, "commit")). No marker is allowed only
    for the modules in STATE_EXEMPT and returns None. Pure: collection calls it without a manifest or
    rig.toml (roles=None checks the names against the roles a manifest can hold); the state fixture
    calls it again with the roles of the loaded manifest, so a role the manifest lacks is a RigError.
    """
    if marker is None:
        if module_name in STATE_EXEMPT:
            return None
        raise RigError("%s: no image marker and no recorded HARN-03 exemption" % module_name)
    if len(marker.args) > 1 or set(marker.kwargs) - {"before", "after"}:
        raise RigError("%s: image() takes one role, or the keywords before= and after=" % module_name)
    before = after = marker.args[0] if marker.args else None
    before = marker.kwargs.get("before", before)
    after = marker.kwargs.get("after", after)
    if before is None and after is None:
        raise RigError("%s: image() names no role" % module_name)
    known = set(manifest.ROLE_BUILD_ID_RE) if roles is None else set(roles)
    for role in (before, after):
        if role is not None and (not isinstance(role, str) or role not in known):
            raise RigError(
                "%s: image role %r is not %s" % (module_name, role, "a known role" if roles is None else "in the manifest")
            )
    return before, after


@dataclass(frozen=True)
class FlashReport:
    attempts: int
    durations_s: list
    retry_reason: str | None
    ok: bool
    verified: bool = False


class Dut:
    def __init__(self, dut_id, cfg, supervisor, flasher, tap=None, ota=None):
        self.id = dut_id
        self.tap = tap
        self.cfg = cfg
        self.flash_attempt_s = FLASH_ATTEMPT_S
        self._supervisor = supervisor
        self._flasher = flasher
        self._ota = ota  # default Ota(cfg.host) is built on first use, so flash-only callers need no host
        self._ota_log = []
        # monotonic() until which a freshly OTA-ed image is unconfirmed: ESP32 rollback is on,
        # and an EN reset before boot_is_good_after silently boots the previous image.
        self.unconfirmed_until = 0.0
        self._ota_mark = None  # the ota_end_<role> mark of the OTA that opened the window
        self.budget = ResetBudget(label="DUT %s" % dut_id)
        self._marks = 0  # unique mark names: bootloader_<n>, reset_<n>
        self._in_bootloader = False

    def _mark(self, name):
        if self.tap is not None:
            self.tap.mark(name)

    def _next_mark(self, prefix):
        self._marks += 1
        return "%s_%d" % (prefix, self._marks)

    def enter_bootloader(self):
        """Press Bootloader and, with a tap, wait for the ROM download-mode banner (RigError without it).

        The banner is the signal that esptool will find the chip in the loader; without a tap
        (teardown builds its Dut without one) the settle delay stays and esptool's own sync is the
        confirmation.
        """
        self._in_bootloader = True
        if self.tap is None:
            self._supervisor.press(contract.BUTTON[self.id]["bootloader"])
            time.sleep(BOOTLOADER_SETTLE_S)
            return
        mark = self._next_mark("bootloader")
        self._mark(mark)
        self._supervisor.press(contract.BUTTON[self.id]["bootloader"])
        code = bootlog.DOWNLOAD_BOOT[self.cfg.chip]
        try:
            self.tap.wait_for(bootlog.download_banner_regex(self.cfg.chip), since=mark, deadline_s=BOOTLOADER_BANNER_S)
        except RigError:
            raise RigError(
                "DUT %s did not enter download mode (no %s within %d s)" % (self.id, code, BOOTLOADER_BANNER_S)
            ) from None

    def _wait_confirmed(self):
        """Inside the rollback window: wait for 'Boot seems successful' or refuse. Never presses."""
        left = self.unconfirmed_until - time.monotonic()
        if left <= 0:
            return
        refusal = RigError("EN reset refused: the OTA image was not confirmed (no 'Boot seems successful')")
        if self.tap is None or self.tap.closed or self._ota_mark is None:
            raise refusal
        try:
            self.tap.wait_for(bootlog.BOOT_OK_RE.pattern, since=self._ota_mark, deadline_s=min(left, CONFIRM_WAIT_S))
        except RigError:
            raise refusal from None
        self.unconfirmed_until = 0.0

    def reset(self):
        """Press Reset and return the mark that precedes the press (the start of the boot to wait for).

        Leaving the bootloader after a flash or a read is always allowed and only recorded. An EN
        reset of a running image is budgeted (ResetBudgetExhausted before the press) and, while the
        running OTA image is unconfirmed, waits for its 'Boot seems successful' or is refused.
        """
        if self._in_bootloader:
            cause = "flash_reset"
        else:
            self._wait_confirmed()
            self.budget.before_reset()
            cause = "en_reset"
        mark = self._next_mark("reset")
        self._mark(mark)
        self._mark("reset_pressed")
        self._supervisor.press(contract.BUTTON[self.id]["reset"])
        self._in_bootloader = False
        self.budget.record(cause)
        return mark

    def _announce_retry(self, reason):
        label = "DUT %s" % self.id
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::warning title=HIL flash retry::%s flash needed a retry (%s)" % (label, reason))
        else:
            print("WARNING: %s flash needed a retry (%s)" % (label, reason))
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write("%s flash: ok after 2 attempts (%s)\n" % (label, reason))

    def _write_report(self, report, report_name=None):
        reports = config.reports_dir()
        reports.mkdir(parents=True, exist_ok=True)
        data = asdict(report)
        data["durations_s"] = [round(d, 1) for d in report.durations_s]
        path = reports / (report_name or "flash-dut-%s.json" % self.id.lower())
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def flash(self, image):
        """Flash one manifest image at its offset (see flash_regions)."""
        return self.flash_regions([(image.offset, image.path)])

    def flash_regions(self, regions, report_name=None):
        """Bootloader, write the (offset, path) regions in one call, reset. One visible retry, then RigError.

        Every attempt re-presses the bootloader button, so flashing the same image
        again ends in the same verified state. The board is always reset at the end,
        also after a failure or an interruption, so it never stays in the bootloader.
        """
        self._mark("flash_start")
        self.unconfirmed_until = 0.0  # a serial flash replaces the image: no rollback to guard against
        durations = []
        reasons = []
        result = None
        try:
            for _attempt in range(FLASH_ATTEMPTS):
                self.enter_bootloader()
                result = self._flasher.write(regions, deadline_s=self.flash_attempt_s)
                durations.append(result.duration_s)
                if result.ok:
                    break
                reasons.append(result.reason)
            self._mark("flash_end")
        finally:
            self.reset()
        retry_reason = reasons[0] if reasons else None
        report = FlashReport(
            attempts=len(durations),
            durations_s=durations,
            retry_reason=retry_reason,
            ok=bool(result and result.ok),
            verified=bool(result and result.verified),
        )
        self._write_report(report, report_name)
        if not report.ok:
            raise RigError(
                "flash failed after %d attempts (%s); last output:\n%s"
                % (report.attempts, ", ".join(reasons), result.output_tail)
            )
        if retry_reason is not None:
            self._announce_retry(retry_reason)
        return report

    def read_flash(self, offset, size, out_path, deadline_s=None):
        """Bootloader, then read a flash region into out_path (one attempt, no reset).

        The caller resets the board when it is done with the bootloader (see nvs.capture).
        """
        self.enter_bootloader()
        result = self._flasher.read(offset, size, out_path, deadline_s=deadline_s or self.flash_attempt_s)
        if not result.ok:
            raise RigError("flash read failed (%s); last output:\n%s" % (result.reason, result.output_tail))
        return result

    async def _attempt(self, noise_psk):
        client = APIClient(self.cfg.host, contract.API_PORT, None, noise_psk=noise_psk)
        try:
            async with asyncio.timeout(API_CONNECT_S):
                await client.connect(login=True)
                return await client.device_info()
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - a failed attempt must not leak the slot, nor mask its cause
                pass

    def probe(self, noise_psk):
        """One API attempt: device_info, or an exception (APIConnectionError, OSError, RigError)."""
        return self._supervisor.run(self._attempt(noise_psk), API_CONNECT_S + 5)

    def wait_api(self, noise_psk, deadline_s=API_WAIT_S):
        """Poll a fresh client until the DUT answers; no ReconnectLogic (mDNS-driven)."""
        end = time.monotonic() + deadline_s
        last = "no attempt finished"
        while time.monotonic() < end:
            try:
                info = self.probe(noise_psk)
                self._mark("api_ready")
                return info
            except RigError:
                last = "attempt timed out"
            except (APIConnectionError, OSError, TimeoutError) as exc:
                last = type(exc).__name__
            time.sleep(1)
        raise RigError("DUT %s API did not answer within %ss (last: %s)" % (self.id, deadline_s, last))

    def _port_open(self, port):
        """True when a TCP connect to the DUT's port succeeds within PORT_PROBE_S."""
        try:
            socket.create_connection((self.cfg.host, port), timeout=PORT_PROBE_S).close()
        except OSError:
            return False
        return True

    def _safe_mode_error(self, evidence):
        self.budget.record("safe_mode_reboot", orderly=True)  # safe mode clears the firmware's boot counter
        report = self.budget.report()
        return SafeModeError(
            "DUT %s booted into ESPHome safe mode (%s); boots this run: %d, streak %d/%d"
            % (self.id, evidence, report["used"], report["streak"], report["limit"])
        )

    def check_safe_mode_ports(self):
        """Raise SafeModeError when the OTA port answers and the API port refuses (no API, OTA up: safe mode)."""
        if self._port_open(OTA_PORT) and not self._port_open(contract.API_PORT):
            raise self._safe_mode_error(
                "port %d answers and API port %d refuses" % (OTA_PORT, contract.API_PORT)
            )

    def wait_running(self, noise_psk, since_mark, deadline_s=API_WAIT_S):
        """The DUT's device_info once it has booted after `since_mark` and answers on the API.

        Poll a fresh client once a second (no ReconnectLogic). With a tap, two things come first: the
        UART0 text since the mark is scanned for ESPHome safe mode (SafeModeError, never a plain
        timeout), and an answer only counts after the ROM boot banner since the mark, so the old image
        answering for a moment after a press cannot be mistaken for the new boot. At the deadline the
        ports tell safe mode from a dead DUT: SafeModeError when 3232 answers and 6053 refuses, else RigError.
        """
        end = time.monotonic() + deadline_s
        last = "no attempt finished"
        booted = self.tap is None  # without a tap the boot cannot be told from the answer
        while True:
            if self.tap is not None:
                text = self.tap.text(since_mark)
                found = bootlog.safe_mode_lines(text)
                if found:
                    raise self._safe_mode_error(found[0])
                booted = booted or bootlog.has_boot_banner(text, self.cfg.chip)
            if booted:
                try:
                    info = self.probe(noise_psk)
                    self._mark("api_ready")
                    return info
                except RigError:
                    last = "attempt timed out"
                except (APIConnectionError, OSError, TimeoutError) as exc:
                    last = type(exc).__name__
            else:
                last = "no ROM boot banner since %s" % since_mark
            if time.monotonic() >= end:
                break
            time.sleep(1)
        if booted:
            self.check_safe_mode_ports()
        raise RigError("DUT %s API did not answer within %ss (last: %s)" % (self.id, deadline_s, last))

    def settle(self, link):
        """Bring DUT A's inputs and outputs to the CLEAN baseline without a reboot; returns the sorted problems.

        Reset levels, lowest first (HARN-03): this settle (no reboot, between tests); one budgeted EN
        reset (reset(), only after a settle found problems, at most once per test); a reflash
        (flash_regions: the smoke test and teardown only, never inside a test).

        CLEAN: all four fans commanded off with a fresh tach reading of 0 each, every Button USRn OFF
        on the DUT API, every supervisor USR switch OFF. One deadline, SETTLE_S, covers the whole
        settle, whatever the number of signals; a signal that never arrives is a problem, not a pass.
        """
        end = time.monotonic() + SETTLE_S
        problems = []
        before = {n: link.count(entities.FAN_SPEED[n]) for n in entities.CHANNELS}
        for n in entities.CHANNELS:
            link.fan(n, False)
        for n in entities.CHANNELS:
            name = entities.FAN_SPEED[n]
            wanted = 1
            while True:
                fresh = link.wait_fresh(name, before[n], wanted, max(0.0, end - time.monotonic()))
                if len(fresh) < wanted:
                    problems.append("%s: no fresh reading within %d s" % (name, SETTLE_S))
                    break
                if fresh[-1] == 0:
                    break
                if time.monotonic() >= end:
                    problems.append("%s still reads %s" % (name, fresh[-1]))
                    break
                wanted += 1  # a partial window right after the command: the next fresh one decides
        for name in entities.BUTTON_USR.values():
            if link.wait_value(name, lambda value: value is False, max(0.0, end - time.monotonic())) is None:
                problems.append("%s is not OFF" % name)
        for n in (1, 2, 3):
            name = contract.SWITCH[self.id]["usr%d" % n]
            if self._supervisor.switch_is_on(name) is not False:
                problems.append("supervisor switch '%s' is not OFF" % name)
        return sorted(problems)

    def _write_ota_report(self):
        reports = config.reports_dir()
        reports.mkdir(parents=True, exist_ok=True)
        path = reports / ("ota-dut-%s.json" % self.id.lower())
        path.write_text(json.dumps(self._ota_log, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _record_ota(self, image, transfer_s, boot_s, ok, reason):
        self._ota_log.append(
            {
                "role": image.role,
                "build_id": image.build_id,
                "transfer_s": round(transfer_s, 1),
                "boot_s": None if boot_s is None else round(boot_s, 1),
                "ok": ok,
                "reason": reason,
            }
        )
        self._write_ota_report()

    def ota(self, image, noise_psk):
        """Encrypted OTA to `image`, confirmed by a ROM boot banner and the new build ID.

        A failed upload or a wrong image afterwards is a device-side outcome: FirmwareFailure
        (verdict FAIL, D-26). A worker that cannot run, a tampered file or a lost serial tap is
        a RigError. The old image can keep answering for a moment after the upload, so only the
        new build ID counts. Starts the confirmation window that blocks Dut.reset.
        """
        role = image.role
        if image.ota_path is None:
            raise RigError("manifest image '%s' has no OTA file" % role)
        try:
            digest = hashlib.sha256(Path(image.ota_path).read_bytes()).hexdigest()
        except OSError:
            raise RigError("OTA file of the '%s' image cannot be read" % role) from None
        if digest != image.ota_sha256:
            raise RigError("OTA file of the '%s' image does not match its manifest sha256" % role)

        self._mark("ota_start_%s" % role)
        if self._ota is None:
            self._ota = Ota(self.cfg.host)
        end_mark = "ota_end_%s" % role
        # The worker reports the acknowledged upload before the DUT reboots, so the mark lands
        # before its banner. Without that report (a changed espota2 message) the banner is looked
        # for from ota_start on: a banner in that window can only be this OTA's reboot.
        reported_done = []

        def done():
            reported_done.append(True)
            self._mark(end_mark)

        result = self._ota.upload(image.ota_path, noise_psk, on_done=done)
        if not result.ok:
            if result.reason == "setup":
                raise RigError("OTA worker could not run; last output:\n%s" % result.output_tail)
            self._record_ota(image, result.duration_s, None, False, result.reason)
            raise FirmwareFailure("OTA to %s failed (%s); last output:\n%s" % (role, result.reason, result.output_tail))
        if not reported_done:
            self._mark(end_mark)
        self._ota_mark = end_mark
        self.budget.record("ota_reboot", orderly=True)  # the DUT reboots at once after the upload, orderly
        window_start = end_mark if reported_done else "ota_start_%s" % role

        started = time.monotonic()
        end = started + OTA_BOOT_S
        reported = "no answer"
        while True:
            try:
                reported = self.probe(noise_psk).project_version
            except RigError:
                pass  # the attempt timed out inside the supervisor loop; keep polling to the deadline
            except (APIConnectionError, OSError, TimeoutError):
                pass  # the DUT is rebooting
            if reported == image.build_id:
                break
            if time.monotonic() >= end:
                self._record_ota(image, result.duration_s, None, False, "wrong build id")
                raise FirmwareFailure(
                    "after OTA to %s DUT %s reports %s, expected %s" % (role, self.id, reported, image.build_id)
                )
            time.sleep(1)
        boot_s = time.monotonic() - started
        self.unconfirmed_until = time.monotonic() + OTA_CONFIRM_WINDOW_S
        self._mark("api_ready")

        if self.tap is None or self.tap.closed:
            self._record_ota(image, result.duration_s, boot_s, False, "serial tap lost")
            raise RigError("serial tap lost the bridge after OTA to %s; the reboot cannot be confirmed" % role)
        if not bootlog.has_boot_banner(self.tap.text(window_start), self.cfg.chip):
            self._record_ota(image, result.duration_s, boot_s, False, "no reboot seen")
            raise FirmwareFailure("no reboot seen after OTA to %s" % role)
        self._record_ota(image, result.duration_s, boot_s, True, "")
        print("ota %s: ok transfer=%.1fs boot=%.1fs build_id=%s" % (role, result.duration_s, boot_s, image.build_id))
