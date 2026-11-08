"""Skeleton for the RED commit of 03-06: the names exist, the behaviour does not yet."""

import re
import socket
import time

from . import dut

DARK_WINDOW_S = 65
DARK_POLL_S = 5
OTA_STATE_LINE_S = 10
OTA_STATE_RE = re.compile(r"HIL broken image OTA state: (valid)")


def project_line_regex(build_id):
    return ""


def ota_state_in(text):
    return None


def watch_dark(host, supervisor_host, window_s=DARK_WINDOW_S, poll_s=DARK_POLL_S, connect_s=dut.PORT_PROBE_S,
               clock=time.monotonic, sleep=time.sleep, connect=socket.create_connection):
    return []


def control_lost(polls):
    return False


def dark_problems(polls, rebooted, label="DUT A"):
    return []


def uart_path_problems(facts):
    return []


def write_report(section, data):
    return None
