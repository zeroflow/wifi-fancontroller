"""Encrypted OTA upload to a DUT through ESPHome's own client, in a killable worker.

The launcher (class Ota) mirrors flasher.py: one attempt per call, a named deadline, the
worker in its own session so the deadline kills the whole process group, and the command
line and environment are never printed. The worker (python -m hil.ota) is the only place
that imports esphome, so importing this module in the pytest process loads nothing heavy.

The DUT API key reaches the worker only through the HIL_OTA_KEY environment variable,
never argv. Plaintext is refused: no fallback and no plaintext upload (D-23, T-02-11).
"""

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

OTA_PORT = 3232
OTA_ATTEMPT_S = 180  # run_ota itself retries 3 times, 5 s apart, 20 s connect timeout each
TAIL_LINES = 40
KEY_ENV = "HIL_OTA_KEY"

EXIT_OK = 0
EXIT_OTA_FAILED = 1
EXIT_SETUP = 3

HIL_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class OtaResult:
    ok: bool
    duration_s: float
    reason: str  # "" when ok, else "exit <n>", "setup" or "deadline"
    output_tail: str


class Ota:
    def __init__(self, host, port=OTA_PORT, worker_cmd=None):
        self._host = host
        self._port = port
        self._cmd = list(worker_cmd) if worker_cmd else [sys.executable, "-m", "hil.ota"]

    def upload(self, path, key, deadline_s=OTA_ATTEMPT_S):
        """Upload one firmware file once. Never raises for an upload outcome; see OtaResult.reason."""
        argv = self._cmd + [self._host, str(self._port), str(path)]
        env = dict(os.environ)
        env[KEY_ENV] = key
        started = time.monotonic()
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(HIL_DIR),
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
            # Interrupted (SIGTERM handler, pytest-timeout): never leave a worker uploading.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            raise
        seconds = time.monotonic() - started
        text = raw.decode("utf-8", "replace").replace("\r", "\n")
        lines = [line for line in text.split("\n") if line.strip()]
        tail = lines[-TAIL_LINES:]
        if timed_out:
            tail.append("OTA deadline of %ss exceeded; process group killed" % deadline_s)
            reason = "deadline"
        elif proc.returncode == EXIT_OK:
            reason = ""
        elif proc.returncode == EXIT_SETUP:
            reason = "setup"
        else:
            reason = "exit %d" % proc.returncode
        return OtaResult(ok=reason == "", duration_s=seconds, reason=reason, output_tail="\n".join(tail))


def main(argv):
    """Worker entry: python -m hil.ota <host> <port> <firmware path>; the key is in HIL_OTA_KEY."""
    if len(argv) != 3:
        print("usage: python -m hil.ota <host> <port> <firmware path>")
        return EXIT_SETUP
    host, port_text, path = argv
    key = os.environ.get(KEY_ENV, "")
    if not key:
        print("%s is not set" % KEY_ENV)
        return EXIT_SETUP
    try:
        port = int(port_text)
    except ValueError:
        print("port is not a number")
        return EXIT_SETUP
    try:
        from esphome import espota2
    except ImportError as exc:
        print("cannot import esphome.espota2 (missing module: %s)" % (exc.name or "unknown"))
        return EXIT_SETUP
    # Keywords only: ota_type sits before noise_psk in the signature. Both plaintext
    # keywords are False, so a failed encrypted handshake ends the upload.
    code, _detail = espota2.run_ota(
        host,
        port,
        None,
        Path(path),
        noise_psk=key,
        plaintext_fallback=False,
        allow_plaintext_upload=False,
    )
    if code == 0:
        return EXIT_OK
    print("OTA upload failed (run_ota returned %s)" % code)
    return EXIT_OTA_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
