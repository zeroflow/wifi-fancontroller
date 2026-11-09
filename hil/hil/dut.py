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

from . import FirmwareFailure, RigError, bootlog, config, contract, entities, manifest, summary
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
SOAK_S = 70  # test_11 observes the upgraded image until this long after the OTA end (boot_is_good_after 60 s + margin)
LINK_WAIT_S = 30  # the DutLink session of an image whose probe already answered: a few reconnect polls
SETTLE_S = 10  # one shared deadline for the whole of Dut.settle
SAFE_MODE_DETECT_S = 45  # most a safe-mode press may take until SAFE MODE IS ACTIVE shows on UART0
PORT_PROBE_S = 2  # TCP connect deadline of the OTA / API port probes after an API timeout
OTA_PORT = 3232
# D-36: the pseudo-role of the latest release on DUT A. It is not a manifest role: its version comes from
# the verified hil-baseline directory (conftest fixture fw_baseline) and it answers without encryption.
BASELINE_ROLE = "baseline"

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
    BASELINE_ROLE is always known: it comes from the release baseline, never from a manifest.
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
    known = (set(manifest.ROLE_BUILD_ID_RE) if roles is None else set(roles)) | {BASELINE_ROLE}
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
        self._ota_mark = None  # the ota_end_<label> mark of the OTA that opened the window
        # Where that window's 'Boot seems successful' is read: "uart" (UART0 since _ota_mark) or "api" (the
        # DutLink API log, for the release-to-commit upgrade only: UART0 is dark under the release bootloader).
        self._confirm_via = None
        self.ota_end_at = None  # time.monotonic() of the latest OTA's end (the done report, else the end mark)
        self.budget = ResetBudget(label="DUT %s" % dut_id)
        self._marks = 0  # unique mark names: bootloader_<n>, reset_<n>
        self._in_bootloader = False
        self._time_boot = False  # True only inside the run's own flash (not the teardown's, not a read)
        self._flash_reset_at = None  # monotonic() of the press that leaves the bootloader after a timed flash
        self.ota_count = 0  # OTA uploads attempted this run (ota and ota_dark); test_41 asserts it did not move
        self.last_reset_mark = None  # the mark of the latest Reset press (reset())
        self.last_reset_at = None  # time.monotonic() right after that press: API sessions from before it are stale
        self.last_bootloader_mark = None  # the mark of the latest Bootloader press (enter_bootloader())
        self.last_ota = None  # label, transfer_s and boot_s of the latest successful ota()
        self.api_ready_at = None  # time.monotonic() of the latest api_ready mark (a boot answered on the API)
        self._ota_window = {}  # end_at/until_at (monotonic) per OTA log index; kept out of ota-dut-a.json
        self._upload_end_mark = None  # the end mark of the upload in progress, once it is set
        self._upload_old_uptime = None  # seconds the old image had answered on the API when the upload started

    def _mark(self, name):
        if self.tap is not None:
            self.tap.mark(name)

    def _next_mark(self, prefix):
        self._marks += 1
        return "%s_%d" % (prefix, self._marks)

    def _api_ready(self):
        """Mark api_ready and keep its time: the old image's uptime at the next OTA start counts from here."""
        self.api_ready_at = time.monotonic()
        self._mark("api_ready")

    def _close_ota_window(self, mark):
        """End the latest OTA's log window at `mark` (the next upload's start or a Bootloader press).

        A later boot's lines are then never read as that OTA's (rollback.rows). Only the latest entry can
        be open, and only once: an entry without an end mark (the upload failed early) has no window.
        """
        if not self._ota_log:
            return
        entry = self._ota_log[-1]
        if entry.get("end_mark") is None or entry.get("until_mark") is not None:
            return
        entry["until_mark"] = mark
        self._ota_window.setdefault(len(self._ota_log) - 1, {})["until_at"] = time.monotonic()
        self._write_ota_report()

    def ota_windows(self):
        """Copies of the OTA log entries with their window times end_at and until_at (monotonic, None if open)."""
        out = []
        for index, entry in enumerate(self._ota_log):
            times = self._ota_window.get(index, {})
            out.append(dict(entry, end_at=times.get("end_at"), until_at=times.get("until_at")))
        return out

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
        self.last_bootloader_mark = mark
        self._mark(mark)
        self._close_ota_window(mark)  # the running OTA image's boot ends here (serial flash or read)
        self._supervisor.press(contract.BUTTON[self.id]["bootloader"])
        code = bootlog.DOWNLOAD_BOOT[self.cfg.chip]
        try:
            self.tap.wait_for(bootlog.download_banner_regex(self.cfg.chip), since=mark, deadline_s=BOOTLOADER_BANNER_S)
        except RigError:
            raise RigError(
                "DUT %s did not enter download mode (no %s within %d s)" % (self.id, code, BOOTLOADER_BANNER_S)
            ) from None

    def wait_confirmed(self, deadline_s=CONFIRM_WAIT_S, link=None):
        """Inside the rollback window: wait for 'Boot seems successful' or refuse. Never presses.

        Returns the seconds from the OTA end to the mark and closes the window; 0.0 at once when no window
        is open. A signal wait within min(window left, deadline_s). The mark is read where the OTA said:
        on UART0 since the OTA end mark, or, after the release-to-commit upgrade (Dut.ota with
        uart_banner off), in the API log of `link` (a DutLink) since ota_end_at, because UART0 is dark
        under the release bootloader. Without that link the upgrade cannot be confirmed and the refusal
        stands: reset() passes none, so an EN reset after the upgrade needs this call with the link first.
        """
        left = self.unconfirmed_until - time.monotonic()
        if left <= 0:
            return 0.0
        wait_s = min(left, deadline_s)
        if self._confirm_via == "api":
            refusal = RigError(
                "EN reset refused: the upgraded image is confirmed over the API log only "
                "(no 'Boot seems successful' in the API log since the OTA end)"
            )
            if link is None or self.ota_end_at is None:
                raise refusal
            try:
                at = link.wait_log(bootlog.BOOT_OK_RE.pattern, self.ota_end_at, wait_s)
            except RigError:
                raise refusal from None
        else:
            refusal = RigError("EN reset refused: the OTA image was not confirmed (no 'Boot seems successful')")
            if self.tap is None or self.tap.closed or self._ota_mark is None:
                raise refusal
            try:
                self.tap.wait_for(bootlog.BOOT_OK_RE.pattern, since=self._ota_mark, deadline_s=wait_s)
            except RigError:
                raise refusal from None
            at = time.monotonic()  # the tap polls every 0.1 s, so this is the line's arrival within that
        self.unconfirmed_until = 0.0
        return max(0.0, at - self.ota_end_at) if self.ota_end_at is not None else 0.0

    def reset(self, force=False):
        """Press Reset and return the mark that precedes the press (the start of the boot to wait for).

        Leaving the bootloader after a flash or a read is always allowed and only recorded. An EN
        reset of a running image is budgeted (ResetBudgetExhausted before the press) and, while the
        running OTA image is unconfirmed, waits for its 'Boot seems successful' or is refused.

        `force` skips that rollback-window guard and only it: the press is still budgeted and recorded
        (`forced` in the budget report), and the window stays open for the next normal reset. Only
        test_36 uses it, for the deliberate EN reset before the mark (REG-05, D-39; grep-guarded).
        """
        forced = False
        if self._in_bootloader:
            cause = "flash_reset"
        else:
            if force is True:
                forced = True
            else:
                self.wait_confirmed()
            self.budget.before_reset()
            cause = "en_reset"
        mark = self._next_mark("reset")
        self.last_reset_mark = mark
        self._mark(mark)
        self._mark("reset_pressed")
        self._supervisor.press(contract.BUTTON[self.id]["reset"])
        self.last_reset_at = time.monotonic()
        if cause == "flash_reset" and self._time_boot:
            self._flash_reset_at = time.monotonic()
        self._in_bootloader = False
        self.budget.record(cause, forced=forced)
        return mark

    def _record_boot(self):
        """Timing `boot`: the press that left the bootloader after the run's flash to the first API answer."""
        if self._flash_reset_at is not None:
            summary.record_timing("boot", time.monotonic() - self._flash_reset_at)
            self._flash_reset_at = None

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
            self._time_boot = report_name is None  # the teardown's flash (its own report name) is not the run's flash
            try:
                self.reset()
            finally:
                self._time_boot = False
        if report_name is None and durations:
            summary.record_timing("flash", sum(durations))
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
                self._api_ready()
                self._record_boot()
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
        ports tell safe mode from a dead DUT: SafeModeError when 3232 answers and 6053 refuses. A DUT that
        booted (banner since the mark), is not in safe mode and never answers is the firmware's outcome:
        FirmwareFailure (D-46). No banner at all is the rig's: RigError. Callers that must treat both as
        rig-side (preflight, heal, baseline) catch FirmwareFailure themselves; teardown uses wait_api.
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
                    self._api_ready()
                    self._record_boot()
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
        message = "DUT %s API did not answer within %ss (last: %s)" % (self.id, deadline_s, last)
        if booted:
            self.check_safe_mode_ports()
            if self.tap is not None:
                # D-46: it booted (ROM banner since the mark), is not in safe mode, and never answers.
                raise FirmwareFailure(
                    "DUT %s booted after %s (ROM boot banner seen) but its API did not answer within %ss (last: %s)"
                    % (self.id, since_mark, deadline_s, last)
                )
        raise RigError(message)

    def settle(self, link):
        """Bring DUT A's inputs and outputs to the CLEAN baseline without a reboot; returns the sorted problems.

        Reset levels, lowest first (HARN-03): this settle (no reboot, between tests); one budgeted EN
        reset (reset(), only after a settle found problems, at most once per test); a reflash
        (flash_regions: the release baseline test, the UART recovery and teardown only, never inside a test).

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

    def _record_ota(self, image, label, transfer_s, boot_s, ok, reason, dark=False, reboot_proof="uart0 banner"):
        entry = {
            "role": image.role,
            "label": label,
            "build_id": image.build_id,
            "transfer_s": round(transfer_s, 1),
            "boot_s": None if boot_s is None else round(boot_s, 1),
            "ok": ok,
            "reason": reason,
            "reboot_proof": reboot_proof,
            # The log window of this OTA's boot (rollback.rows): from its end mark to the next upload's start
            # or the next Bootloader press (until_mark, None while open or for the last OTA of the run).
            "end_mark": self._upload_end_mark,
            "until_mark": None,
            "old_uptime_s": None if self._upload_old_uptime is None else round(self._upload_old_uptime, 1),
        }
        if dark:
            entry["dark"] = True  # delivered without an API to confirm it (ota_dark)
        self._ota_log.append(entry)
        if self._upload_end_mark is not None:
            self._ota_window[len(self._ota_log) - 1] = {"end_at": self.ota_end_at, "until_at": None}
        self._write_ota_report()

    def _upload(self, image, noise_psk, label, dark=False, allow_plaintext=False):
        """The upload half of ota and ota_dark: the file checks, the marks, the upload, the orderly reboot.

        Returns (result, window_start): the tap mark from which the new image's boot is looked for. A failed
        upload is a FirmwareFailure, a worker that cannot run or a tampered file a RigError. The marks are
        named after `label` (ota_start_<label>, ota_end_<label>), so two OTAs to one role stay apart.
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

        start_mark = "ota_start_%s" % label
        self._mark(start_mark)
        self._close_ota_window(start_mark)  # the previous OTA image's window ends where this upload starts
        self._upload_end_mark = None
        self._upload_old_uptime = None if self.api_ready_at is None else time.monotonic() - self.api_ready_at
        if self._ota is None:
            self._ota = Ota(self.cfg.host)
        end_mark = "ota_end_%s" % label
        # The worker reports the acknowledged upload before the DUT reboots, so the mark lands
        # before its banner. Without that report (a changed espota2 message) the banner is looked
        # for from ota_start on: a banner in that window can only be this OTA's reboot.
        reported_done = []

        def done():
            reported_done.append(True)
            self.ota_end_at = time.monotonic()
            self._mark(end_mark)
            self._upload_end_mark = end_mark

        self.ota_count += 1
        # The flag is passed only when set, so every other upload is the plain refusing call (T-03-25).
        plaintext = {"allow_plaintext": True} if allow_plaintext is True else {}
        result = self._ota.upload(image.ota_path, noise_psk, on_done=done, **plaintext)
        if not result.ok:
            if result.reason == "setup":
                raise RigError("OTA worker could not run; last output:\n%s" % result.output_tail)
            self._record_ota(image, label, result.duration_s, None, False, result.reason, dark)
            raise FirmwareFailure("OTA to %s failed (%s); last output:\n%s" % (role, result.reason, result.output_tail))
        if not reported_done:
            self.ota_end_at = time.monotonic()
            self._mark(end_mark)
            self._upload_end_mark = end_mark
        self.budget.record("ota_reboot", orderly=True)  # the DUT reboots at once after the upload, orderly
        return result, end_mark if reported_done else "ota_start_%s" % label

    def ota(self, image, noise_psk, allow_plaintext=False, label=None, uart_banner=True):
        """OTA to `image` (encrypted unless allowed otherwise), confirmed by a ROM boot banner and the new build ID.

        A failed upload or a wrong image afterwards is a device-side outcome: FirmwareFailure
        (verdict FAIL, D-26). A worker that cannot run, a tampered file or a lost serial tap is
        a RigError. The old image can keep answering for a moment after the upload, so only the
        new build ID counts. Starts the confirmation window that blocks Dut.reset.

        `label` (default: the role) names the marks, the timings ota_<label> and ota_<label>_boot and
        the report entry. A true `allow_plaintext` is for the release-to-commit upgrade only (test_11,
        T-03-24): the release offers no OTA encryption; the key is still offered.

        `uart_banner` off is for that same upgrade only (03-11 maintainer decision serial-restore-after-
        upgrade): under the release's bootloader UART0 shows no app line and the upgrade reboot's ROM banner
        goes to USB, so the reboot is proven by the build ID changing from the release's version (the state
        check before test_11 confirmed it) to the commit's, and wait_confirmed reads the mark from the API log.
        It is refused without the plaintext upgrade, so no other OTA can drop the banner check.
        """
        role = image.role
        label = role if label is None else label
        banner = uart_banner is not False
        if not banner and allow_plaintext is not True:
            raise RigError("the UART0 reboot check may be skipped only for the release-to-commit upgrade (plaintext OTA)")
        proof = "uart0 banner" if banner else "build id"
        result, window_start = self._upload(image, noise_psk, label, allow_plaintext=allow_plaintext)
        self._ota_mark = "ota_end_%s" % label
        self._confirm_via = "uart" if banner else "api"

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
                self._record_ota(image, label, result.duration_s, None, False, "wrong build id", reboot_proof=proof)
                raise FirmwareFailure(
                    "after OTA to %s DUT %s reports %s, expected %s" % (role, self.id, reported, image.build_id)
                )
            time.sleep(1)
        boot_s = time.monotonic() - started
        self.unconfirmed_until = time.monotonic() + OTA_CONFIRM_WINDOW_S
        self._api_ready()

        if self.tap is None or self.tap.closed:
            self._record_ota(image, label, result.duration_s, boot_s, False, "serial tap lost", reboot_proof=proof)
            raise RigError("serial tap lost the bridge after OTA to %s; the reboot cannot be confirmed" % role)
        if banner and not bootlog.has_boot_banner(self.tap.text(window_start), self.cfg.chip):
            self._record_ota(image, label, result.duration_s, boot_s, False, "no reboot seen")
            raise FirmwareFailure("no reboot seen after OTA to %s" % role)
        self._record_ota(image, label, result.duration_s, boot_s, True, "", reboot_proof=proof)
        summary.record_timing("ota_%s" % label, result.duration_s)
        summary.record_timing("ota_%s_boot" % label, boot_s)
        self.last_ota = {"label": label, "transfer_s": result.duration_s, "boot_s": boot_s, "window_start": window_start}
        named = role if label == role else "%s (%s)" % (role, label)
        print("ota %s: ok transfer=%.1fs boot=%.1fs build_id=%s" % (named, result.duration_s, boot_s, image.build_id))

    def ota_dark(self, image, noise_psk):
        """Encrypted OTA of an image that has no API (the broken image), confirmed on UART0 only.

        Uploads like ota() but never probes the API and opens no rollback-window guard: the broken image
        is marked valid at boot (D-41, measured on every run by test_40) and never prints `Boot seems
        successful`, so a Bootloader press or the reset after a UART flash must not wait for it. The new
        image counts as booted when its ROM normal-boot banner and its `Project ... version <build id>`
        line are on UART0 since the upload. Any rollback window of an earlier OTA is closed too: the
        running image is a different one now.
        """
        from . import recovery  # recovery imports this module for its constants

        role = image.role
        result, window_start = self._upload(image, noise_psk, role, dark=True)
        self.unconfirmed_until = 0.0
        self._ota_mark = None
        self._confirm_via = None
        started = time.monotonic()
        if self.tap is None or self.tap.closed:
            self._record_ota(image, role, result.duration_s, None, False, "serial tap lost", dark=True)
            raise RigError("serial tap lost the bridge after OTA to %s; the reboot cannot be confirmed" % role)
        try:
            self.tap.wait_for(recovery.project_line_regex(image.build_id), since=window_start, deadline_s=OTA_BOOT_S)
        except RigError:
            if self.tap.closed:
                self._record_ota(image, role, result.duration_s, None, False, "serial tap lost", dark=True)
                raise RigError("serial tap lost the bridge after OTA to %s; the reboot cannot be confirmed" % role) from None
            self._record_ota(image, role, result.duration_s, None, False, "no Project line", dark=True)
            raise FirmwareFailure("the %s image did not boot (no Project line on UART0)" % role) from None
        boot_s = time.monotonic() - started
        if not bootlog.has_boot_banner(self.tap.text(window_start), self.cfg.chip):
            self._record_ota(image, role, result.duration_s, boot_s, False, "no reboot seen", dark=True)
            raise FirmwareFailure("no reboot seen after OTA to %s" % role)
        self._mark("%s_up" % role)
        self._record_ota(image, role, result.duration_s, boot_s, True, "", dark=True)
        summary.record_timing("ota_%s" % role, result.duration_s)
        print("ota %s: ok transfer=%.1fs boot=%.1fs build_id=%s (no API, confirmed on UART0)" % (role, result.duration_s, boot_s, image.build_id))
