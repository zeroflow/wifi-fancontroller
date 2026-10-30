"""One device under test: bootloader entry, flash, reset, API read-back."""

import asyncio
import time

from aioesphomeapi import APIClient, APIConnectionError

from . import RigError, contract

ATTEMPT_TIMEOUT = 10
BOOTLOADER_SETTLE_S = 0.5
BOOT_SETTLE_S = 15


class Dut:
    def __init__(self, dut_id, cfg, supervisor, flasher, tap=None):
        self.id = dut_id
        self.tap = tap
        self.cfg = cfg
        self._supervisor = supervisor
        self._flasher = flasher

    def enter_bootloader(self):
        self._supervisor.press(contract.BUTTON[self.id]["bootloader"])
        time.sleep(BOOTLOADER_SETTLE_S)

    def _mark(self, name):
        if self.tap is not None:
            self.tap.mark(name)

    def reset(self):
        self._mark("reset_pressed")
        self._supervisor.press(contract.BUTTON[self.id]["reset"])

    def flash(self, image):
        """Bootloader, write at the image offset, reset. Returns the FlashResult."""
        self._mark("flash_start")
        self.enter_bootloader()
        try:
            result = self._flasher.write(image.offset, image.path)
            self._mark("flash_end")
        finally:
            self.reset()
        return result

    async def _attempt(self, noise_psk):
        client = APIClient(self.cfg.host, contract.API_PORT, None, noise_psk=noise_psk)
        try:
            async with asyncio.timeout(ATTEMPT_TIMEOUT):
                await client.connect(login=True)
                return await client.device_info()
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - a failed attempt must not leak the slot, nor mask its cause
                pass

    def wait_api(self, noise_psk, deadline_s=90):
        """Poll a fresh client until the DUT answers; no ReconnectLogic (mDNS-driven)."""
        end = time.monotonic() + deadline_s
        last = "no attempt finished"
        while time.monotonic() < end:
            try:
                info = self._supervisor.run(self._attempt(noise_psk), ATTEMPT_TIMEOUT + 5)
                self._mark("api_ready")
                return info
            except RigError:
                last = "attempt timed out"
            except (APIConnectionError, OSError, TimeoutError) as exc:
                last = type(exc).__name__
            time.sleep(1)
        raise RigError("DUT %s API did not answer within %ss (last: %s)" % (self.id, deadline_s, last))
