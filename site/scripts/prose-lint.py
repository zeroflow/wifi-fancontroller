#!/usr/bin/env python3
"""Helper for site/scripts/verify-prose.sh (Python 3 standard library only).

Run it as `python3 -I site/scripts/prose-lint.py <subcommand>` from any
directory. The repository root is derived from this file's location.

Subcommands
  config --write|--check   generate or verify the per-tier sections of site/.vale.ini
  pages                    print the built page (dist path) of every mapped content file
  dist <source-path>       print the built page (dist path) of one content file
  report <vale-json>       readable report, ratchet check, exit code
  inject <in> <out> <kind> copy a built page and plant a dash (kind: em-dash or hyphens)

Data files (grammars are fixed, anything else is a parse error)
  site/style-guide/page-tiers.yml  lines: blank, '#' comment, '<path>: <tier>'
  site/style-guide/blocking.yml    lines: blank, '#' comment, '<Style>.<Rule>:', '  - <path>'
"""

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
DOCS = SITE / "src" / "content" / "docs"
TIERS_FILE = SITE / "style-guide" / "page-tiers.yml"
BLOCKING_FILE = SITE / "style-guide" / "blocking.yml"
INI_FILE = SITE / ".vale.ini"

BEGIN_MARK = "# BEGIN GENERATED SECTIONS"
END_MARK = "# END GENERATED SECTIONS"

TIERS = ("strict", "moderate", "free")
STYLE_LANG = {"DocsEN": "en", "DocsDE": "de"}

TIER_LINE = re.compile(r"^(?P<path>[A-Za-z0-9][A-Za-z0-9/._-]*\.mdx?): (?P<tier>strict|moderate|free)$")
RULE_HEADER = re.compile(r"^(?P<style>[A-Za-z][A-Za-z0-9]*)\.(?P<rule>[A-Za-z][A-Za-z0-9]*):$")
BLOCK_ITEM = re.compile(r"^  - (?P<path>[A-Za-z0-9][A-Za-z0-9/._-]*\.mdx?)$")

CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
TAG = re.compile(r"<[^>]*>")
SPACES = re.compile(r"\s+")


class DataError(Exception):
    """A data file broke its grammar."""


# ---------------------------------------------------------------------------
# Data files
# ---------------------------------------------------------------------------

def parse_tiers(path):
    """Return a list of (source path, tier) in file order. Duplicates are kept."""
    entries = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = TIER_LINE.match(line)
        if not match:
            raise DataError("%s:%d: not a '<path>: <tier>' line: %r" % (path, number, line))
        entries.append((match.group("path"), match.group("tier")))
    return entries


def parse_blocking(path):
    """Return an ordered dict {'Style.Rule': [paths]} in file order."""
    rules = {}
    current = None
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        header = RULE_HEADER.match(line)
        if header:
            current = "%s.%s" % (header.group("style"), header.group("rule"))
            rules.setdefault(current, [])
            continue
        item = BLOCK_ITEM.match(line)
        if item:
            if current is None:
                raise DataError("%s:%d: list item before any '<Style>.<Rule>:' header" % (path, number))
            rules[current].append(item.group("path"))
            continue
        raise DataError("%s:%d: not a header or '  - <path>' item: %r" % (path, number, line))
    return rules


def lang_of(source_path):
    return "de" if source_path.startswith("de/") else "en"


def style_of(source_path):
    return "DocsDE" if lang_of(source_path) == "de" else "DocsEN"


def dist_of(source_path):
    """Source path below content/docs -> dist path relative to site/."""
    stem = re.sub(r"\.mdx?$", "", source_path)
    parts = stem.split("/")
    if parts[-1] == "index":
        parts = parts[:-1]
    folder = "/".join(parts)
    return "dist/%s/index.html" % folder if folder else "dist/index.html"


def source_of_dist(tiers):
    return {dist_of(path): path for path, _ in tiers}


# ---------------------------------------------------------------------------
# .vale.ini generation
# ---------------------------------------------------------------------------

def generate_block(tiers, blocking):
    page_rules = {}
    for rule, paths in blocking.items():
        for page in paths:
            page_rules.setdefault(page, set()).add(rule)
    groups = {}
    for page, tier in tiers:
        style = style_of(page)
        rules = tuple(sorted(r for r in page_rules.get(page, ()) if r.startswith(style + ".")))
        groups.setdefault((style, tier, rules), set()).add(dist_of(page))
    lines = []
    for key in sorted(groups):
        style, tier, rules = key
        lines.append("# %s %s" % (style, tier))
        lines.append("[{%s}]" % ",".join(sorted(groups[key])))
        lines.append("BasedOnStyles = %s" % style)
        for rule in rules:
            lines.append("%s = error" % rule)
        lines.append("")
    return "\n".join(lines)


def split_ini(text):
    """Return (head, block, tail) around the marker lines."""
    lines = text.split("\n")
    try:
        begin = lines.index(BEGIN_MARK)
        end = lines.index(END_MARK)
    except ValueError:
        raise DataError("%s: marker lines '%s' and '%s' are required" % (INI_FILE, BEGIN_MARK, END_MARK))
    if end < begin:
        raise DataError("%s: END marker comes before BEGIN marker" % INI_FILE)
    head = "\n".join(lines[: begin + 1]) + "\n"
    block = "\n".join(lines[begin + 1 : end])
    tail = "\n".join(lines[end:])
    return head, block, tail


def cmd_config(args):
    tiers = parse_tiers(args.tiers)
    blocking = parse_blocking(args.blocking)
    fresh = generate_block(tiers, blocking)
    ini = Path(args.ini)
    head, current, tail = split_ini(ini.read_text(encoding="utf-8"))
    if args.write:
        ini.write_text(head + fresh + "\n" * (0 if fresh.endswith("\n") else 1) + tail, encoding="utf-8")
        print("wrote generated sections to %s" % ini)
        return 0
    if current.strip("\n") != fresh.strip("\n"):
        print("FAIL: generated block of %s is stale; run: bash site/scripts/verify-prose.sh --write-config" % ini)
        return 1
    print("generated block of %s is current" % ini)
    return 0


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------

def cmd_pages(args):
    for dist in sorted(dist_of(path) for path, _ in parse_tiers(args.tiers)):
        print(dist)
    return 0


def cmd_dist(args):
    print(dist_of(args.source))
    return 0


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

LEVELS = {"error": "ERROR", "warning": "WARN", "suggestion": "HINT"}


def clean(text):
    return SPACES.sub(" ", CONTROL.sub(" ", text)).strip()


def snippet(dist_root, dist_path, line, column):
    """First 100 characters of tag-stripped text of the HTML line from the span start."""
    name = dist_path[len("dist/"):] if dist_path.startswith("dist/") else dist_path
    try:
        lines = (Path(dist_root) / name).read_text(encoding="utf-8", errors="replace").split("\n")
        raw = lines[line - 1][max(column - 1, 0):]
    except (OSError, IndexError):
        return ""
    # A slice that starts inside a tag begins with attribute leftovers up to the next '>'.
    if ">" in raw and ("<" not in raw or raw.index(">") < raw.index("<")):
        raw = raw[raw.index(">") + 1:]
    text = html.unescape(TAG.sub("", raw))
    return clean(text)[:100]


def load_alerts(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for value in data.values():
        if not isinstance(value, list):
            return None
    return data


def cmd_report(args):
    tiers = parse_tiers(args.tiers)
    blocking = parse_blocking(args.blocking)
    data = load_alerts(args.vale_json)
    if data is None:
        print("FAIL: Vale output is not valid JSON")
        return 1
    dist_root = Path(args.dist) if args.dist else SITE / "dist"
    sources = source_of_dist(tiers)

    lines = []
    counts = {}
    per_page = {}
    errors = 0
    for dist_path in sorted(data):
        shown = sources.get(dist_path, dist_path)
        for alert in data[dist_path]:
            check = clean(str(alert.get("Check", "?")))
            level = LEVELS.get(str(alert.get("Severity", "")).lower(), "WARN")
            span = alert.get("Span") or [1, 1]
            number = int(alert.get("Line", 0) or 0)
            text = snippet(dist_root, dist_path, number, int(span[0]))
            message = clean(str(alert.get("Message", "")))
            lines.append("%s %s %s:%d %s | %s" % (level, check, clean(shown), number, message, text))
            counts.setdefault(check, {"ERROR": 0, "WARN": 0, "HINT": 0})[level] += 1
            per_page.setdefault((dist_path, check), 0)
            per_page[(dist_path, check)] += 1
            if level == "ERROR":
                errors += 1

    ratchet = []
    only = set(args.only) if args.only else None
    for rule in blocking:
        style = rule.split(".", 1)[0]
        language = STYLE_LANG.get(style)
        listed = set(blocking[rule])
        for page, _ in tiers:
            if language is None or lang_of(page) != language:
                continue
            dist_path = dist_of(page)
            if only is not None and dist_path not in only:
                continue
            if per_page.get((dist_path, rule), 0) == 0 and page not in listed:
                ratchet.append("RATCHET: add '  - %s' under '%s:' in site/style-guide/blocking.yml" % (page, rule))

    for line in lines:
        print(line)
    for line in ratchet:
        print(line)
    print("")
    for check in sorted(counts):
        c = counts[check]
        print("COUNT %s error=%d warning=%d suggestion=%d" % (check, c["ERROR"], c["WARN"], c["HINT"]))
    print("TOTAL alerts=%d errors=%d ratchet_gaps=%d" % (len(lines), errors, len(ratchet)))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Prose lint\n\n| Rule | Errors | Warnings | Hints |\n|---|---|---|---|\n")
            for check in sorted(counts):
                c = counts[check]
                handle.write("| %s | %d | %d | %d |\n" % (check, c["ERROR"], c["WARN"], c["HINT"]))
            blocking_lines = [l for l in lines if l.startswith("ERROR ")] + ratchet
            if blocking_lines:
                handle.write("\n```text\n")
                for line in blocking_lines:
                    handle.write(line.replace("`", "'") + "\n")
                handle.write("```\n")
    return 1 if (errors or ratchet) else 0


# ---------------------------------------------------------------------------
# inject
# ---------------------------------------------------------------------------

INJECTIONS = {
    "em-dash": "Injected check sentence " + chr(0x2014) + " for the selftest. ",
    "hyphens": "Injected check sentence -- for the selftest. ",
}


def cmd_inject(args):
    source = Path(args.input).read_text(encoding="utf-8")
    container = source.find("sl-markdown-content")
    if container < 0:
        print("FAIL: no sl-markdown-content container in %s" % args.input, file=sys.stderr)
        return 1
    paragraph = re.compile(r"<p[\s>]").search(source, container)
    if not paragraph:
        print("FAIL: no <p element inside the content container of %s" % args.input, file=sys.stderr)
        return 1
    close = source.index(">", paragraph.start()) + 1
    out = source[:close] + INJECTIONS[args.kind] + source[close:]
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(out, encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog="prose-lint.py", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def paths(p):
        p.add_argument("--tiers", default=str(TIERS_FILE))
        p.add_argument("--blocking", default=str(BLOCKING_FILE))

    p = sub.add_parser("config")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    p.add_argument("--ini", default=str(INI_FILE))
    paths(p)
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("pages")
    p.add_argument("--tiers", default=str(TIERS_FILE))
    p.set_defaults(func=cmd_pages)

    p = sub.add_parser("dist")
    p.add_argument("source")
    p.set_defaults(func=cmd_dist)

    p = sub.add_parser("report")
    p.add_argument("vale_json")
    p.add_argument("--dist", default=None, help="directory to read HTML snippets from (default site/dist)")
    p.add_argument("--only", action="append", default=None, help="restrict the ratchet to this dist path (repeatable)")
    paths(p)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("inject")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("kind", choices=sorted(INJECTIONS))
    p.set_defaults(func=cmd_inject)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except DataError as error:
        print("FAIL: %s" % error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
