"""Flash an image to a DUT through the supervisor's raw TCP serial bridge.

Rules (hil-rig README): always --chip, never a baud option, ESPTOOL_BAUD unset,
--before/--after no-reset, hyphenated subcommands. The command line is never
printed. A write counts only when esptool exits 0 and prints the hash line. One attempt
only: the single visible retry belongs to Dut.flash.
"""

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

FLASH_ATTEMPT_S = 120
TAIL_LINES = 12
NOISE = "Failed to get VID/PID"
VERIFIED = "Hash of data verified."


@dataclass(frozen=True)
class FlashResult:
    ok: bool
    duration_s: float
    verified: bool
    output_tail: str
    reason: str = ""  # "" when ok, else "exit <n>", "not verified" or "deadline" (reads: "not verified" = short file)


class Flasher:
    def __init__(self, host, port, chip, esptool_cmd=None):
        self._host = host
        self._port = port
        self._chip = chip
        self._cmd = list(esptool_cmd) if esptool_cmd else [sys.executable, "-m", "esptool"]

    def _base(self):
        return self._cmd + [
            "--chip", self._chip,
            "--port", "socket://%s:%d" % (self._host, self._port),
            "--before", "no-reset",
            "--after", "no-reset",
        ]

    def _argv(self, regions):
        argv = self._base() + ["write-flash"]
        for offset, path in regions:
            argv += [offset, str(path)]
        return argv

    def _argv_read(self, offset, size, out_path):
        return self._base() + ["read-flash", str(offset), str(size), str(out_path)]

    def _run(self, argv, deadline_s):
        """Run one esptool process; returns (returncode, output lines, timed_out, seconds)."""
        env = {k: v for k, v in os.environ.items() if k != "ESPTOOL_BAUD"}
        started = time.monotonic()
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        timed_out = False
        try:
            raw, _ = proc.communicate(timeout=deadline_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            raw, _ = proc.communicate()
        except BaseException:
            # Interrupted (SIGTERM handler, pytest-timeout): never leave esptool holding the bridge.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            raise
        text = raw.decode("utf-8", "replace").replace("\r", "\n")
        lines = [line for line in text.split("\n") if line.strip() and NOISE not in line]
        return proc.returncode, lines, timed_out, time.monotonic() - started

    @staticmethod
    def _result(returncode, lines, timed_out, seconds, deadline_s, verified):
        tail = lines[-TAIL_LINES:]
        if timed_out:
            tail.append("flash deadline of %ss exceeded; process group killed" % deadline_s)
        ok = returncode == 0 and verified and not timed_out
        if ok:
            reason = ""
        elif timed_out:
            reason = "deadline"
        elif returncode != 0:
            reason = "exit %d" % returncode
        else:
            reason = "not verified"
        return FlashResult(ok=ok, duration_s=seconds, verified=verified, output_tail="\n".join(tail), reason=reason)

    def write(self, regions, deadline_s=FLASH_ATTEMPT_S):
        """Write (offset, path) regions in one esptool call: one bootloader entry, one stub upload.

        Never builds an erase command. Every region must report a verified hash.
        """
        regions = [(str(offset), path) for offset, path in regions]
        returncode, lines, timed_out, seconds = self._run(self._argv(regions), deadline_s)
        verified = sum(1 for line in lines if VERIFIED in line) >= len(regions)
        return self._result(returncode, lines, timed_out, seconds, deadline_s, verified)

    def read(self, offset, size, out_path, deadline_s=FLASH_ATTEMPT_S):
        """Read `size` bytes at `offset` into out_path. ok means exit 0 and a file of exactly that size."""
        returncode, lines, timed_out, seconds = self._run(self._argv_read(offset, size, out_path), deadline_s)
        try:
            complete = Path(out_path).stat().st_size == int(str(size), 0)
        except (OSError, ValueError):
            complete = False
        return self._result(returncode, lines, timed_out, seconds, deadline_s, complete)
