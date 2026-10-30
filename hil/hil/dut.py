"""One device under test: bootloader entry, flash, reset, API read-back.

Dut.flash owns the only retry in the harness: a failed flash attempt is retried
once after re-entering the bootloader, and the retry is always visible (report
file, GitHub warning, step summary). There are no test-level reruns anywhere.
"""

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass

from aioesphomeapi import APIClient, APIConnectionError

from . import RigError, config, contract
from .flasher import FLASH_ATTEMPT_S

API_CONNECT_S = 10
API_WAIT_S = 90
BOOT_SETTLE_S = 15
BOOTLOADER_SETTLE_S = 0.5
FLASH_ATTEMPTS = 2


@dataclass(frozen=True)
class FlashReport:
    attempts: int
    durations_s: list
    retry_reason: str | None
    ok: bool
    verified: bool = False


class Dut:
    def __init__(self, dut_id, cfg, supervisor, flasher, tap=None):
        self.id = dut_id
        self.tap = tap
        self.cfg = cfg
        self.flash_attempt_s = FLASH_ATTEMPT_S
        self._supervisor = supervisor
        self._flasher = flasher

    def _mark(self, name):
        if self.tap is not None:
            self.tap.mark(name)

    def enter_bootloader(self):
        self._supervisor.press(contract.BUTTON[self.id]["bootloader"])
        time.sleep(BOOTLOADER_SETTLE_S)

    def reset(self):
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
