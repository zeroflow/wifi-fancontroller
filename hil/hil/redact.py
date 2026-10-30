"""Redaction of everything that may leave the runner (HARN-13, D-16).

Only reports/redacted/ is ever uploaded. redact_tree() builds it from reports/raw/
plus the JSON reports in the reports root, replacing every rig literal (hosts,
MACs in every form, keys, SSID, PSK), then anything shaped like an IPv4 address,
a MAC or a socket:// URL, and stripping ANSI escapes. Literals go first, longest
first, so a literal that contains a shorter one is masked as a whole.
"""

import re
import shutil
from pathlib import Path

MASK = "***"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
SOCKET_URL = re.compile(r"socket://\S+")


def redact(text, literals):
    text = ANSI.sub("", text)
    for literal in sorted({lit for lit in literals if lit}, key=len, reverse=True):
        text = text.replace(literal, MASK)
    text = SOCKET_URL.sub("socket://" + MASK, text)
    text = IPV4.sub(MASK, text)
    text = MAC.sub(MASK, text)
    return text


def _write(src, dest, literals):
    text = Path(src).read_bytes().decode("utf-8", "replace")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(redact(text, literals), encoding="utf-8")
    return dest


def redact_tree(raw_dir, out_dir, literals, include_raw=True):
    """Write redacted copies of raw_dir's files and the reports root's *.json files into out_dir.

    out_dir is emptied first, so nothing from an earlier run survives. Returns the written paths.
    """
    raw_dir = Path(raw_dir)
    out_dir = Path(out_dir)
    if out_dir.resolve() in (raw_dir.resolve(), raw_dir.resolve().parent):
        raise ValueError("refusing to clear a directory that holds the raw reports")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    written = []
    if include_raw and raw_dir.is_dir():
        for src in sorted(raw_dir.rglob("*")):
            if src.is_file():
                written.append(_write(src, out_dir / src.relative_to(raw_dir), literals))
    for src in sorted(raw_dir.parent.glob("*.json")):
        if src.is_file():
            written.append(_write(src, out_dir / src.name, literals))
    return written
