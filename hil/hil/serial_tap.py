"""Always-on UART0 tap on the supervisor's serial bridge.

The tap only reads. It connects before any button press (the bridge needs about
0.3 s to register a client), keeps everything in memory and in a raw log under
reports/raw/, and lets callers cut the stream into windows with named marks.
"""

import json
import re
import socket
import threading
import time
from pathlib import Path

from . import RigError

TAP_CONNECT_S = 5
REGISTER_S = 0.3
RECV_TIMEOUT_S = 0.5


class SerialTap:
    def __init__(self, host, port, raw_path):
        self._host = host
        self._port = port
        self._raw_path = Path(raw_path)
        self._marks_path = self._raw_path.with_suffix(".marks.json")
        self._buf = bytearray()
        self._marks = {}
        self._lock = threading.Lock()
        self._sock = None
        self._thread = None
        self._stop = threading.Event()
        self.closed = False

    def start(self):
        try:
            sock = socket.create_connection((self._host, self._port), timeout=TAP_CONNECT_S)
        except OSError:
            raise RigError("serial bridge %d unreachable" % self._port) from None
        sock.settimeout(RECV_TIMEOUT_S)
        self._sock = sock
        self._raw_path.parent.mkdir(parents=True, exist_ok=True)
        self._raw_path.write_bytes(b"")
        self._marks_path.write_text("{}\n", encoding="utf-8")
        time.sleep(REGISTER_S)
        self._thread = threading.Thread(target=self._pump, name="hil-serial-tap", daemon=True)
        self._thread.start()

    def _pump(self):
        with self._raw_path.open("ab") as raw:
            while not self._stop.is_set():
                try:
                    chunk = self._sock.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    chunk = b""
                if not chunk:
                    self.closed = True
                    return
                with self._lock:
                    self._buf.extend(chunk)
                raw.write(chunk)
                raw.flush()

    def mark(self, name):
        with self._lock:
            self._marks[name] = len(self._buf)
            snapshot = dict(self._marks)
        self._marks_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def has_mark(self, name):
        return name in self._marks

    def text(self, since, until=None):
        """Decoded bytes between two marks (or from `since` to now)."""
        with self._lock:
            start = self._marks[since]
            end = self._marks[until] if until is not None else len(self._buf)
            return bytes(self._buf[start:end]).decode("utf-8", "replace")

    def wait_for(self, regex, since, deadline_s):
        pattern = re.compile(regex)
        end = time.monotonic() + deadline_s
        while True:
            found = pattern.search(self.text(since))
            if found:
                return found
            if time.monotonic() >= end:
                raise RigError("serial bridge %d: no match for /%s/ within %ss" % (self._port, regex, deadline_s))
            if self.closed:
                raise RigError("serial bridge %d closed while waiting" % self._port)
            time.sleep(0.1)

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(2)
