"""Flash an image to a DUT through the supervisor's raw TCP serial bridge.

Rules (hil-rig README): always --chip, never a baud option, ESPTOOL_BAUD unset,
--before/--after no-reset, hyphenated subcommands. The command line is never
printed. A write counts only when esptool exits 0 and prints the hash line.
"""

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass

DEADLINE_S = 120
TAIL_LINES = 12
NOISE = "Failed to get VID/PID"
VERIFIED = "Hash of data verified."


@dataclass(frozen=True)
class FlashResult:
    ok: bool
    duration_s: float
    verified: bool
    output_tail: str


class Flasher:
    def __init__(self, host, port, chip, esptool_cmd=None):
        self._host = host
        self._port = port
        self._chip = chip
        self._cmd = list(esptool_cmd) if esptool_cmd else [sys.executable, "-m", "esptool"]

    def _argv(self, offset, path):
        return self._cmd + [
            "--chip", self._chip,
            "--port", "socket://%s:%d" % (self._host, self._port),
            "--before", "no-reset",
            "--after", "no-reset",
            "write-flash", offset, str(path),
        ]

    def write(self, offset, path, deadline_s=DEADLINE_S):
        env = {k: v for k, v in os.environ.items() if k != "ESPTOOL_BAUD"}
        started = time.monotonic()
        proc = subprocess.Popen(
            self._argv(offset, path),
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
        verified = any(VERIFIED in line for line in lines)
        tail = lines[-TAIL_LINES:]
        if timed_out:
            tail.append("flash deadline of %ss exceeded; process group killed" % deadline_s)
        return FlashResult(
            ok=(proc.returncode == 0 and verified and not timed_out),
            duration_s=time.monotonic() - started,
            verified=verified,
            output_tail="\n".join(tail),
        )
