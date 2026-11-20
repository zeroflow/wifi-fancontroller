"""Encrypted OTA upload to a DUT through ESPHome's own client, in a killable worker.

The launcher (class Ota) mirrors flasher.py: one attempt per call, a named deadline, the
worker in its own session so the deadline kills the whole process group, and the command
line and environment are never printed. The worker (python -m hil.ota) is the only place
that imports esphome, so importing this module in the pytest process loads nothing heavy.

The DUT API key reaches the worker only through the HIL_OTA_KEY environment variable,
never argv. Plaintext is refused: no fallback and no plaintext upload (D-23, T-02-11), unless the
caller sets `allow_plaintext` for one upload. Only the release-to-commit upgrade
(test_11, maintainer decision allow-one-plaintext of 2026-11-08, T-03-24) does: the release
predates OTA encryption. The flag reaches the worker as HIL_OTA_ALLOW_PLAINTEXT=1 in its
environment, never argv and never by default, and the key is still offered, so a device that
offers encryption gets it.

The worker runs with a minimal environment (IN-04, T-03-26): PATH, HOME, LANG, LC_ALL and TMPDIR
when set, the key and the plaintext flag. HIL_SUPERVISOR_KEY, GITHUB_* and everything else the
harness inherited never reach a process that imports esphome.
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

OTA_PORT = 3232
OTA_ATTEMPT_S = 180  # run_ota itself retries 3 times, 5 s apart, 20 s connect timeout each
TAIL_LINES = 40
KEY_ENV = "HIL_OTA_KEY"
ALLOW_PLAINTEXT_ENV = "HIL_OTA_ALLOW_PLAINTEXT"
PASSED_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")  # the only inherited variables the worker sees
# The worker prints this line the moment espota2 logs "OTA successful", i.e. right after it
# sent the end acknowledgement and before the DUT reboots. The launcher turns it into the
# on_done callback, so the caller's "OTA end" mark lands before the reboot banner. Marking when
# run_ota returns is too late: espota2 sleeps 1 s after that log line, and the process exit
# takes longer still (seen on DUT A, 2026-11-01: the banner sat 2 KB before the mark).
DONE_LINE = "HIL-OTA-DONE"
SUCCESS_LOG_PREFIX = "OTA successful"
ESPOTA_LOGGER = "esphome.espota2"

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

    def upload(self, path, key, deadline_s=OTA_ATTEMPT_S, on_done=None, allow_plaintext=False):
        """Upload one firmware file once. Never raises for an upload outcome; see OtaResult.reason.

        `on_done()` is called from a reader thread as soon as the worker reports a finished
        upload, before the worker process has exited. A true `allow_plaintext` lets this one upload
        go to a device that offers no encryption (the release-to-commit upgrade only); the default
        refuses it.
        """
        argv = self._cmd + [self._host, str(self._port), str(path)]
        env = worker_env(key, allow_plaintext)
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
        collected = []

        def read():
            for raw_line in iter(proc.stdout.readline, b""):
                line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
                if line == DONE_LINE:
                    if on_done is not None:
                        on_done()
                else:
                    collected.append(line)

        reader = threading.Thread(target=read, name="hil-ota-reader", daemon=True)
        reader.start()

        def kill_group():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        timed_out = False
        try:
            proc.wait(timeout=deadline_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_group()
            proc.wait()
        except BaseException:
            # Interrupted (SIGTERM handler, pytest-timeout): never leave a worker uploading.
            kill_group()
            proc.wait()
            raise
        reader.join(5)
        seconds = time.monotonic() - started
        text = "\n".join(collected).replace("\r", "\n")
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


def worker_env(key, allow_plaintext=False):
    """The worker's whole environment: PASSED_ENV when set, the key, and the plaintext flag only when asked."""
    env = {name: os.environ[name] for name in PASSED_ENV if name in os.environ}
    env[KEY_ENV] = key
    if allow_plaintext is True:
        env[ALLOW_PLAINTEXT_ENV] = "1"
    return env


class _SuccessMark(logging.Handler):
    """Print DONE_LINE when espota2 logs that the upload was acknowledged. A missing line only
    costs the caller its precise end mark (it falls back); it never changes the upload."""

    def emit(self, record):
        if record.getMessage().startswith(SUCCESS_LOG_PREFIX):
            print(DONE_LINE, flush=True)


def main(argv):
    """Worker entry: python -m hil.ota <host> <port> <firmware path>; the key is in HIL_OTA_KEY.

    HIL_OTA_ALLOW_PLAINTEXT=1 (set by Ota.upload only for an upload that asked for it) allows a
    plaintext upload to a device that offers no encryption; anything else refuses it.
    """
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
    # espota2 reports through logging; show its messages (they end up in the failure tail) and
    # watch for the success message. Both handlers are removed again so main() can be called twice.
    logger = logging.getLogger(ESPOTA_LOGGER)
    shown = logging.StreamHandler(sys.stdout)
    shown.setFormatter(logging.Formatter("%(message)s"))
    handlers = [shown, _SuccessMark()]
    previous_level = logger.level
    for handler in handlers:
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    allow_plaintext = os.environ.get(ALLOW_PLAINTEXT_ENV) == "1"
    try:
        # Keywords only: ota_type sits before noise_psk in the signature. No fallback ever: a failed
        # encrypted handshake ends the upload. allow_plaintext_upload only for the one upload that
        # asked for it, to a device that offers no encryption at all (the release image).
        code, _detail = espota2.run_ota(
            host,
            port,
            None,
            Path(path),
            noise_psk=key,
            plaintext_fallback=False,
            allow_plaintext_upload=allow_plaintext,
        )
    finally:
        for handler in handlers:
            logger.removeHandler(handler)
        logger.setLevel(previous_level)
    if code == 0:
        return EXIT_OK
    print("OTA upload failed (run_ota returned %s)" % code)
    return EXIT_OTA_FAILED


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
