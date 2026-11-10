"""Redaction of everything that may leave the runner (HARN-13, D-16).

Only reports/redacted/ is ever uploaded. redact_tree() builds it from reports/raw/
plus the JSON reports in the reports root, replacing every rig literal (hosts,
MACs in every form, keys, SSID, PSK), then anything shaped like an IPv4 address,
an IPv4 run cut by truncation (IPV4_CUT, 03-17), a MAC or a socket:// URL (also when glued to a letter
or an underscore), and
stripping ANSI escapes. Literals go first, longest first, so a literal that contains
a shorter one is masked as a whole.
"""

import json
import re
import shutil
from pathlib import Path

MASK = "***"
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
# Only a digit may keep a run from being an address: a letter or an underscore next to it ("host_192.0.2.40",
# "x192.0.2.40y") does not, and \b read exactly those as no boundary (03-17 follow-up, WR-03). The trailing
# lookahead is (?!\d), not (?![\d.]): an address before a full stop ("see 192.0.2.40.") is still an address.
# Shape conflict, settled in favour of masking: any four dot-separated groups of 1-3 digits is an address
# ("1.6.0.1" too); a first group of four digits ("2026.10.1.5") is not one, and neither is "2026.10.1".
IPV4 = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
# An address cut by a repr or a message limit ("192.0.2...", "192.0.", "192.0.2.2..."): two to four
# dot-separated groups, the last possibly empty, directly followed by an ellipsis. No full-value mask
# and not IPV4 matches it (03-14, run p1). The lookbehind rejects a digit or a dot, so the tail of a
# version ("2026.10.1...", "esphome 2026.10.1...") is not read as a run, while a letter or an underscore
# before the run does not protect it ("host_192.0.2...", "abc198.51.100..."). The ellipsis stays in the text.
IPV4_CUT = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){1,3}\.?(?=\.\.\.|\u2026)")
# No \b: "id02:00:00:00:00:0a" and "mac_02:..." are MACs too.
MAC = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
SOCKET_URL = re.compile(r"socket://\S+")


def _forms(literal):
    """The literal plus the forms a JSON report stores it in (escaped quotes,
    backslashes, control and non-ASCII characters)."""
    return {literal, json.dumps(literal)[1:-1], json.dumps(literal, ensure_ascii=False)[1:-1]}


def redact(text, literals):
    text = ANSI.sub("", text)
    forms = set()
    for literal in literals:
        if literal:
            forms |= _forms(literal)
    for literal in sorted(forms, key=len, reverse=True):
        text = text.replace(literal, MASK)
    text = SOCKET_URL.sub("socket://" + MASK, text)
    text = IPV4_CUT.sub(MASK, text)
    text = IPV4.sub(MASK, text)
    text = MAC.sub(MASK, text)
    return text


def _write(src, dest, literals):
    text = Path(src).read_bytes().decode("utf-8", "replace")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(redact(text, literals), encoding="utf-8")
    return dest


def redact_tree(raw_dir, out_dir, literals, include_raw=True, json_names=None, keep_existing=False):
    """Write redacted copies of raw_dir's files and the reports root's *.json files into out_dir.

    out_dir is emptied first, so nothing from an earlier run survives, unless keep_existing
    is set. json_names limits the root JSON reports to those file names. Returns the
    written paths.
    """
    raw_dir = Path(raw_dir)
    out_dir = Path(out_dir)
    if out_dir.resolve() in (raw_dir.resolve(), raw_dir.resolve().parent):
        raise ValueError("refusing to clear a directory that holds the raw reports")
    if out_dir.exists() and not keep_existing:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    if include_raw and raw_dir.is_dir():
        for src in sorted(raw_dir.rglob("*")):
            if src.is_file():
                written.append(_write(src, out_dir / src.relative_to(raw_dir), literals))
    for src in sorted(raw_dir.parent.glob("*.json")):
        if src.is_file() and (json_names is None or src.name in json_names):
            written.append(_write(src, out_dir / src.name, literals))
    return written
