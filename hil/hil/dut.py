"""One device under test: bootloader entry, flash, reset, API read-back.

Dut.flash owns the only retry in the harness: a failed flash attempt is retried
once after re-entering the bootloader, and the retry is always visible (report
file, GitHub warning, step summary). There are no test-level reruns anywhere.
"""

import asyncio
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from aioesphomeapi import APIClient, APIConnectionError

from . import FirmwareFailure, RigError, bootlog, config, contract
from .flasher import FLASH_ATTEMPT_S
from .ota import Ota

API_CONNECT_S = 10
API_WAIT_S = 90
BOOT_SETTLE_S = 15
BOOTLOADER_SETTLE_S = 0.5
FLASH_ATTEMPTS = 2
OTA_BOOT_S = 90  # upload finished -> the new build ID answers on the API
OTA_CONFIRM_WINDOW_S = 75  # safe_mode boot_is_good_after (60 s) plus margin; see Dut.reset


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

    def _mark(self, name):
        if self.tap is not None:
            self.tap.mark(name)

    def enter_bootloader(self):
        self._supervisor.press(contract.BUTTON[self.id]["bootloader"])
        time.sleep(BOOTLOADER_SETTLE_S)

    def reset(self):
        if time.monotonic() < self.unconfirmed_until:
            raise RigError("EN reset refused: the OTA image is not confirmed yet (rollback window)")
        self._mark("reset_pressed")
        self._supervisor.press(contract.BUTTON[self.id]["reset"])

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
        # The worker reports the finished upload before its process exits, so the mark lands
        # before the DUT's reboot banner; the check after the upload covers a launcher that never reports.
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
        if not bootlog.has_boot_banner(self.tap.text(end_mark), self.cfg.chip):
            self._record_ota(image, result.duration_s, boot_s, False, "no reboot seen")
            raise FirmwareFailure("no reboot seen after OTA to %s" % role)
        self._record_ota(image, result.duration_s, boot_s, True, "")
        print("ota %s: ok transfer=%.1fs boot=%.1fs build_id=%s" % (role, result.duration_s, boot_s, image.build_id))
