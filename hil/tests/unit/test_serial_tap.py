"""SerialTap boundary lines and marks with two offsets (HARN-08), against a local TCP server."""

import json
import re
import socket
import threading
import time

import pytest

from hil import serial_tap


@pytest.fixture
def bridge(monkeypatch):
    """(server socket, accepted-connection getter); the tap's 0.3 s register delay is skipped."""
    monkeypatch.setattr(serial_tap, "REGISTER_S", 0)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    yield server
    server.close()


@pytest.fixture
def tap(bridge, tmp_path):
    made = serial_tap.SerialTap("127.0.0.1", bridge.getsockname()[1], tmp_path / "raw" / "uart.log")
    made.start()
    conn, _ = bridge.accept()
    made.conn = conn
    made.raw_path = tmp_path / "raw" / "uart.log"
    yield made
    made.stop()
    conn.close()


def wait_until(predicate, what, deadline_s=5):
    end = time.monotonic() + deadline_s
    while not predicate():
        assert time.monotonic() < end, "timed out waiting for " + what
        time.sleep(0.01)


def send(tap, data):
    """Send one chunk and wait until the pump has taken it into the stream."""
    before = len(tap._buf)
    tap.conn.sendall(data)
    wait_until(lambda: len(tap._buf) >= before + len(data), "the pump to take %d bytes" % len(data))


def raw(tap):
    return tap.raw_path.read_bytes()


def test_a_boundary_between_two_chunks_lands_between_them_in_the_raw_file(tap):
    send(tap, b"first chunk\n")
    tap.boundary("START tests/rig/test_x.py::test_a t=1.0")
    send(tap, b"second chunk\n")
    assert raw(tap) == b"first chunk\n\n[HIL] ===== START tests/rig/test_x.py::test_a t=1.0 =====\nsecond chunk\n"


def test_a_boundary_never_enters_the_in_memory_stream(tap):
    send(tap, b"one\n")
    tap.mark("m")
    tap.boundary("START x t=0.0")
    send(tap, b"two\n")
    assert bytes(tap._buf) == b"one\ntwo\n"
    assert tap.text("m") == "two\n"


def test_existing_mark_offsets_do_not_move_when_a_boundary_is_written(tap):
    send(tap, b"abc")
    tap.mark("before")
    offsets = dict(tap._marks)
    tap.boundary("END x passed t=2.0")
    tap.boundary("START y t=2.0")
    assert tap._marks == offsets
    assert tap.text("before") == ""


def test_a_mark_after_a_boundary_has_a_file_offset_larger_by_the_boundary_length(tap):
    send(tap, b"boot one\n")
    tap.boundary("START x t=0.0")
    line = b"\n[HIL] ===== START x t=0.0 =====\n"
    tap.mark("after")
    send(tap, b"boot two\n")
    marks = json.loads(tap._marks_path.read_text(encoding="utf-8"))
    assert marks["after"] == {"buffer": 9, "file": 9 + len(line)}
    assert marks["after"]["file"] - marks["after"]["buffer"] == len(line)


def test_the_file_offset_of_a_mark_addresses_the_bytes_the_buffer_offset_addresses(tap):
    send(tap, b"old output\n")
    tap.boundary("START x t=0.0")
    tap.mark("m")
    send(tap, b"rst:0xc,boot:0x8\n")
    marks = json.loads(tap._marks_path.read_text(encoding="utf-8"))["m"]
    chunk = b"rst:0xc,boot:0x8\n"
    assert bytes(tap._buf)[marks["buffer"] : marks["buffer"] + len(chunk)] == chunk
    assert raw(tap)[marks["file"] : marks["file"] + len(chunk)] == chunk


def test_marks_json_holds_both_offsets_for_every_mark(tap):
    tap.mark("a")
    send(tap, b"xyz")
    tap.mark("b")
    marks = json.loads(tap._marks_path.read_text(encoding="utf-8"))
    assert marks == {"a": {"buffer": 0, "file": 0}, "b": {"buffer": 3, "file": 3}}


def test_a_boundary_before_start_or_after_stop_is_ignored(bridge, tmp_path):
    idle = serial_tap.SerialTap("127.0.0.1", bridge.getsockname()[1], tmp_path / "idle.log")
    idle.boundary("START x t=0.0")  # not started: nothing to write to, no exception
    assert not (tmp_path / "idle.log").exists()


def test_a_boundary_after_stop_does_not_raise_or_write(tap):
    send(tap, b"data\n")
    tap.stop()
    tap.boundary("END x passed t=9.0")
    assert raw(tap) == b"data\n"


def test_a_burst_of_boundaries_and_chunks_loses_and_splits_nothing(tap):
    """Concurrency: the pump and the test thread write the same file. Cutting the boundary lines out
    leaves exactly the received stream, and every boundary line is whole."""
    lines = [("serial line %04d with some padding to fill a chunk\n" % i).encode() for i in range(300)]

    def feed():
        for line in lines:
            tap.conn.sendall(line)

    thread = threading.Thread(target=feed)
    thread.start()
    for i in range(100):
        tap.boundary("START n%d t=0.0" % i)
    thread.join()
    stream = b"".join(lines)
    wait_until(lambda: len(tap._buf) >= len(stream), "all lines")
    data = raw(tap)
    whole = re.compile(rb"\n\[HIL\] ===== START n\d+ t=0\.0 =====\n")
    assert len(whole.findall(data)) == 100
    assert whole.sub(b"", data) == stream
    assert bytes(tap._buf) == stream
