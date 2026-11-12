#!/usr/bin/env python3
"""Helper for site/scripts/verify-prose.sh (Python 3 standard library only).

Run it as `python3 -I site/scripts/prose-lint.py <subcommand>` from any
directory. The repository root is derived from this file's location.

Subcommands
  config --write|--check   generate or verify the per-tier sections of site/.vale.ini
  pages                    print the built page (dist path) of every mapped content file
  dist <source-path>       print the built page (dist path) of one content file
  report <vale-json>       readable report, ratchet check, exit code
  map                      integrity checks of the tier map, rule levels, twins, generated config and ratchet list
  glossary [--glossary-file F]  glossary rows, term, brand and role rules, ignore list agree
  guide [--guide-dir D]    guide files: dashes, claims, standard names, rule catalogue, routes
  baseline <vale-json> --out <file>  write the measured violations per tier, rule and page
  inject <in> <out> <kind> copy a built page and plant a dash (kind: em-dash or hyphens)

Data files (grammars are fixed, anything else is a parse error)
  site/style-guide/page-tiers.yml  lines: blank, '#' comment, '<path>: <tier>'
  site/style-guide/blocking.yml    lines: blank, '#' comment, '<Style>.<Rule>:', '  - <path>'
  site/style-guide/rule-levels.yml lines: blank, '#' comment,
                                   '<Style>.<Rule>: {strict: <L>, moderate: <L>, free: <L>}'
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
LEVELS_FILE = SITE / "style-guide" / "rule-levels.yml"
STYLES_DIR = SITE / ".vale" / "styles"
GUIDE_DIR = SITE / "style-guide"
GLOSSARY_FILE = GUIDE_DIR / "glossary.md"
INI_FILE = SITE / ".vale.ini"

BEGIN_MARK = "# BEGIN GENERATED SECTIONS"
END_MARK = "# END GENERATED SECTIONS"

TIERS = ("strict", "moderate", "free")
STYLE_LANG = {"DocsEN": "en", "DocsDE": "de"}

TIER_LINE = re.compile(r"^(?P<path>[A-Za-z0-9][A-Za-z0-9/._-]*\.mdx?): (?P<tier>strict|moderate|free)$")
RULE_HEADER = re.compile(r"^(?P<style>[A-Za-z][A-Za-z0-9]*)\.(?P<rule>[A-Za-z][A-Za-z0-9]*):$")
BLOCK_ITEM = re.compile(r"^  - (?P<path>[A-Za-z0-9][A-Za-z0-9/._-]*\.mdx?)$")
LEVEL_LINE = re.compile(
    r"^(?P<style>[A-Za-z][A-Za-z0-9]*)\.(?P<rule>[A-Za-z][A-Za-z0-9]*): "
    r"\{strict: (?P<strict>[A-Za-z]+), moderate: (?P<moderate>[A-Za-z]+), free: (?P<free>[A-Za-z]+)\}$"
)
VALID_LEVELS = ("NO", "suggestion", "warning")

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


def parse_levels(path):
    """Return a list of (style, rule, {tier: level}) in file order. Duplicates are kept.

    The grammar fixes the shape of a line. Whether a level value is allowed is a
    separate check (invalid_levels), so map can report it on its own line.
    """
    entries = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = LEVEL_LINE.match(line)
        if not match:
            raise DataError(
                "%s:%d: not a '<Style>.<Rule>: {strict: <L>, moderate: <L>, free: <L>}' line: %r" % (path, number, line)
            )
        entries.append((match.group("style"), match.group("rule"), {t: match.group(t) for t in TIERS}))
    return entries


def level_table(entries):
    """{'Style.Rule': {tier: level}} (a later duplicate wins; map reports duplicates)."""
    return {"%s.%s" % (style, rule): levels for style, rule, levels in entries}


def invalid_levels(entries):
    problems = []
    for style, rule, levels in entries:
        for tier in TIERS:
            if levels[tier] not in VALID_LEVELS:
                problems.append(
                    "%s.%s: level '%s' for %s is not one of %s"
                    % (style, rule, levels[tier], tier, ", ".join(VALID_LEVELS))
                )
    return problems


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

def generate_block(tiers, blocking, levels):
    bad = invalid_levels(levels)
    if bad:
        raise DataError("rule-levels.yml: " + "; ".join(bad))
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
        for rule_style, rule, table in levels:
            if rule_style == style:
                lines.append("%s.%s = %s" % (style, rule, table[tier]))
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
    fresh = generate_block(tiers, blocking, parse_levels(args.levels))
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
    levels = level_table(parse_levels(args.levels))
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
        for page, tier in tiers:
            if language is None or lang_of(page) != language:
                continue
            # A page whose tier switches the rule off can never be a ratchet candidate.
            if levels.get(rule, {}).get(tier) == "NO":
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
# map
# ---------------------------------------------------------------------------

MIRROR_HEAD = re.compile(r"^# mirrors: (?P<names>[A-Za-z0-9]+(?:, [A-Za-z0-9]+)*)$")


def rule_files(styles_dir):
    """{'Style.Rule': path} for every non-test rule file below the two own styles."""
    found = {}
    for style in STYLE_LANG:
        folder = Path(styles_dir) / style
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.yml")):
            if path.name.endswith(".test.yml"):
                continue
            found["%s.%s" % (style, path.stem)] = path
    return found


def mirror_sources(path):
    """The rule names listed in a '# mirrors:' first line, or None when there is none."""
    first = Path(path).read_text(encoding="utf-8").split("\n", 1)[0].rstrip()
    match = MIRROR_HEAD.match(first)
    if not match:
        return None
    return match.group("names").split(", ")


def rule_list(path):
    """('tokens' or 'swap', [list lines as text]) of a rule file, or (None, [])."""
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    for index, line in enumerate(lines):
        if line.rstrip() in ("tokens:", "swap:"):
            kind = line.rstrip()[:-1]
            items = []
            for follow in lines[index + 1:]:
                if not follow.strip():
                    continue
                if not follow.startswith((" ", "\t")):
                    break
                items.append(follow.rstrip())
            return kind, items
    return None, []


def mirror_problems(ident, path, sources, folder):
    kind, own = rule_list(path)
    if kind is None:
        return ["%s: a '# mirrors:' rule needs a tokens or swap list" % ident]
    expected = []
    for name in sources:
        source = Path(folder) / (name + ".yml")
        if not source.is_file():
            return ["%s: mirrored rule %s has no file" % (ident, name)]
        source_kind, items = rule_list(source)
        if source_kind != kind:
            return ["%s: mirrored rule %s has a %s list, this rule has a %s list" % (ident, name, source_kind, kind)]
        expected += items
    if own == expected:
        return []
    detail = "%d items against %d expected" % (len(own), len(expected))
    for index in range(min(len(own), len(expected))):
        if own[index] != expected[index]:
            detail = "first difference at item %d: %s against expected %s" % (index + 1, own[index].strip(), expected[index].strip())
            break
    return ["%s: %s list differs from the rules it mirrors (%s); %s" % (ident, kind, ", ".join(sources), detail)]


MAIN_LANG = re.compile(r"<main\b[^>]*?\blang=\"([^\"]*)\"")


def cmd_map(args):
    """Print one PASS or FAIL line per check, exit 1 when any check fails."""
    tiers = parse_tiers(args.tiers)
    blocking = parse_blocking(args.blocking)
    level_entries = parse_levels(args.levels)
    styles_dir = Path(args.styles)
    mapped = [path for path, _ in tiers]
    failures = 0

    def verdict(label, problems, ok_text):
        nonlocal failures
        if problems:
            failures += 1
            print("FAIL: map %s: %d problem(s)" % (label, len(problems)))
            for problem in problems:
                print("  %s" % problem)
        else:
            print("PASS: map %s: %s" % (label, ok_text))

    on_disk = sorted(
        str(p.relative_to(DOCS)).replace(os.sep, "/")
        for p in DOCS.rglob("*")
        if p.is_file() and p.suffix in (".md", ".mdx")
    )
    counts = {}
    for path in mapped:
        counts[path] = counts.get(path, 0) + 1
    problems = ["no entry for %s" % f for f in on_disk if f not in counts]
    problems += ["duplicate entry for %s" % f for f in sorted(counts) if counts[f] > 1]
    verdict("(a) coverage", problems, "%d content files, each with exactly one entry" % len(on_disk))

    problems = ["source file missing for entry %s" % f for f in sorted(counts) if not (DOCS / f).is_file()]
    verdict("(b) sources", problems, "every entry has a source file")

    problems = []
    for f in sorted(counts):
        if not (SITE / dist_of(f)).is_file():
            problems.append("built page %s missing for entry %s (run the site build)" % (dist_of(f), f))
    verdict("(c) built pages", problems, "every entry has a built page")

    problems = []
    for f in sorted(counts):
        built = SITE / dist_of(f)
        if not built.is_file():
            continue
        found = MAIN_LANG.search(built.read_text(encoding="utf-8", errors="replace"))
        actual = found.group(1) if found else "<none>"
        if actual != lang_of(f):
            problems.append("%s: <main lang=%s> but the entry says %s" % (f, actual, lang_of(f)))
    verdict("(d) language", problems, "main[lang] of every built page matches its entry")

    ini = Path(args.ini)
    try:
        _, current, _ = split_ini(ini.read_text(encoding="utf-8"))
        stale = current.strip("\n") != generate_block(tiers, blocking, level_entries).strip("\n")
        problems = ["generated block of %s is stale; run --write-config" % ini] if stale else []
    except DataError as error:
        problems = [str(error)]
    verdict("(e) generated config", problems, "generated block of .vale.ini is current")

    problems = []
    known = set(counts)
    for rule, pages in blocking.items():
        style, _, name = rule.partition(".")
        if style not in STYLE_LANG:
            problems.append("%s: unknown style %s" % (rule, style))
            continue
        if not (styles_dir / style / (name + ".yml")).is_file():
            problems.append("%s: rule file site/.vale/styles/%s/%s.yml missing" % (rule, style, name))
        for page in pages:
            if page not in known:
                problems.append("%s: %s is not in page-tiers.yml" % (rule, page))
            elif lang_of(page) != STYLE_LANG[style]:
                problems.append("%s: %s has the wrong language for this rule" % (rule, page))
    verdict("(f) ratchet list", problems, "every blocking page is mapped, matches its rule language, rule file exists")

    problems = ["%s: Rev 4.0 pages are out of scope (D-12)" % f for f in sorted(counts) if "rev-4" in f]
    verdict("(g) scope", problems, "no Rev 4.0 page is mapped")

    # (h) every rule file has exactly one rule-levels.yml entry, and every entry has a file.
    on_files = rule_files(styles_dir)
    seen = {}
    for style, rule, _ in level_entries:
        seen["%s.%s" % (style, rule)] = seen.get("%s.%s" % (style, rule), 0) + 1
    problems = ["%s: rule file without a rule-levels.yml entry" % r for r in sorted(on_files) if r not in seen]
    problems += ["%s: rule-levels.yml entry without a rule file" % r for r in sorted(seen) if r not in on_files]
    problems += ["%s: %d rule-levels.yml entries, exactly one is allowed" % (r, n) for r, n in sorted(seen.items()) if n > 1]
    verdict("(h) rule levels", problems, "%d rule files, each with exactly one rule-levels.yml entry" % len(on_files))

    # (i) mirrored twins carry the lists of the rules they mirror, line by line.
    problems = []
    twins = 0
    for ident in sorted(on_files):
        style, _, name = ident.partition(".")
        path = styles_dir / style / (name + ".yml")
        sources = mirror_sources(path)
        if sources is None:
            continue
        twins += 1
        problems += mirror_problems(ident, path, sources, styles_dir / style)
    verdict("(i) mirrored twins", problems, "%d twin rule(s) match the rules they mirror" % twins)

    # (j) no blocking page for a rule that its tier switches off.
    table = level_table(level_entries)
    tier_of = dict(tiers)
    problems = []
    for rule, pages in blocking.items():
        for page in pages:
            if page in tier_of and table.get(rule, {}).get(tier_of[page]) == "NO":
                problems.append("%s: %s is a %s page and the rule level there is NO" % (rule, page, tier_of[page]))
    verdict("(j) ratchet levels", problems, "no blocking page is listed for a rule that is NO in its tier")

    # (k) level values.
    verdict("(k) level values", invalid_levels(level_entries), "every level is NO, suggestion or warning")
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# glossary
# ---------------------------------------------------------------------------

GLOSSARY_ROW = re.compile(r"^\| G-\d{2} \|")
GLOSSARY_STATUS = ("APPROVED", "REJECTED", "LOCKED")
USABLE_STATUS = ("APPROVED", "LOCKED")
SWAP_LINE = re.compile(r"^\s+(?:'(?P<quoted>(?:[^']|'')*)'|(?P<plain>[^:'][^:]*)):\s+(?P<value>\S.*?)\s*$")
BRAND_NAME = re.compile(r"^(?P<name>.+?) \(the brand, verbatim\)")
PAIR_FORM = re.compile(r"[A-ZÄÖÜ][a-zäöüß]+ (?:oder|und) [A-ZÄÖÜ][a-zäöüß]+")
STANDALONE_OR = re.compile(r"(?<![A-Za-z])or(?![A-Za-z])")


def glossary_rows(path):
    """List of (line number, cells) for every '| G-NN |' row."""
    rows = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if GLOSSARY_ROW.match(raw):
            rows.append((number, [cell.strip() for cell in raw.strip()[1:-1].split("|")]))
    return rows


def swap_values(path):
    """The replacement value of every swap line of a substitution rule file."""
    kind, items = rule_list(path)
    if kind != "swap":
        return []
    values = []
    for item in items:
        found = SWAP_LINE.match(item)
        if found:
            values.append(found.group("value").strip("'\""))
    return values


def ini_token_ignores(ini):
    for line in Path(ini).read_text(encoding="utf-8").splitlines():
        if line.startswith("TokenIgnores"):
            return line
    return None


def cmd_glossary(args):
    """Print one PASS or FAIL line per check, exit 1 when any check fails."""
    failures = 0
    rows = glossary_rows(args.glossary_file)
    styles = Path(args.styles)

    def verdict(label, problems, ok_text):
        nonlocal failures
        if problems:
            failures += 1
            print("FAIL: glossary %s: %d problem(s)" % (label, len(problems)))
            for problem in problems:
                print("  %s" % problem)
        else:
            print("PASS: glossary %s: %s" % (label, ok_text))

    problems = []
    if not rows:
        problems.append("%s: no '| G-NN |' row found" % args.glossary_file)
    for number, cells in rows:
        ident = cells[0]
        if len(cells) != 8:
            problems.append("line %d: %s has %d cells, 8 are required" % (number, ident, len(cells)))
            continue
        status = cells[7]
        if status == "PROPOSED":
            problems.append("line %d: %s is a PROPOSED row, a decision is still open" % (number, ident))
        elif status not in GLOSSARY_STATUS:
            problems.append("line %d: %s has status '%s', expected APPROVED, REJECTED or LOCKED" % (number, ident, status))
    verdict("(1) rows", problems, "%d rows, 8 cells each, none PROPOSED" % len(rows))

    usable = [cells for _, cells in rows if len(cells) == 8 and cells[7] in USABLE_STATUS]
    preferred = {"en": [cells[2] for cells in usable], "de": [cells[4] for cells in usable]}
    problems = []
    checked = 0
    for style, lang in (("DocsEN", "en"), ("DocsDE", "de")):
        for name in ("Terms", "Brands"):
            path = styles / style / (name + ".yml")
            if not path.is_file():
                problems.append("%s.%s: rule file missing" % (style, name))
                continue
            for value in swap_values(path):
                checked += 1
                if not any(value in cell for cell in preferred[lang]):
                    problems.append(
                        "%s.%s: swap value not in glossary: '%s' is in no %s preferred cell of an APPROVED or LOCKED row"
                        % (style, name, value, lang.upper())
                    )
    verdict("(2) swap values", problems, "%d swap values, each from an APPROVED or LOCKED %s row" % (checked, "EN or DE"))

    problems = []
    role_path = styles / "DocsDE" / "RoleNouns.yml"
    role_text = role_path.read_text(encoding="utf-8") if role_path.is_file() else ""
    if not role_path.is_file():
        problems.append("DocsDE.RoleNouns: rule file missing")
    role_rows = [cells for cells in usable if cells[1].startswith("Role:") and cells[0] != ""]
    forms = 0
    for cells in role_rows:
        for form in cells[5].split(". "):
            form = form.strip().rstrip(".")
            form = form.split(" as a ")[0].strip()
            if not form or form == "none":
                continue
            forms += 1
            if form not in role_text:
                problems.append("%s: DE avoid form '%s' does not occur in DocsDE/RoleNouns.yml" % (cells[0], form))
    verdict("(3) role nouns", problems, "%d DE avoid forms of %d role rows occur in RoleNouns.yml" % (forms, len(role_rows)))

    problems = []
    for cells in role_rows:
        cell = cells[4]
        if "/" in cell or ";" in cell or "bzw." in cell or STANDALONE_OR.search(cell):
            problems.append("%s: DE preferred cell holds more than one form: %s" % (cells[0], cell))
    verdict("(4) one form per role", problems, "the DE preferred cell of each of %d role rows holds one form" % len(role_rows))

    problems = []
    line = ini_token_ignores(args.ini)
    names = []
    for cells in usable:
        if cells[0] == "G-01":
            for cell in (cells[2], cells[4]):
                found = BRAND_NAME.match(cell)
                if found:
                    names.append(found.group("name"))
    for cells in role_rows:
        names += PAIR_FORM.findall(cells[4])
    if line is None:
        problems.append("%s: no TokenIgnores line" % args.ini)
    else:
        for name in names:
            if name not in line:
                problems.append("%s is missing from the TokenIgnores line of %s" % (name, args.ini))
    if not any(cells[0] == "G-01" for cells in usable):
        problems.append("G-01 is not an APPROVED or LOCKED row, so no brand names can be checked")
    verdict("(5) ignore list", problems, "%d brand names and pair forms are in TokenIgnores" % len(names))
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# guide
# ---------------------------------------------------------------------------

GUIDE_FILES = (
    "README.md", "en.md", "de.md", "safety.md", "glossary.md", "baseline.md", "page-tiers.yml", "rule-levels.yml",
    "blocking.yml",
)
DASH_CHARS = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")
SPACED_DASH = re.compile(r"\S[ \t]+-{1,3}[ \t]+\S")
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
# Standard names and claim words for check (4). Matching is case insensitive and
# looks at one sentence at a time, in either order.
STANDARD_PATTERNS = (
    r"ASD[- ]?STE[- ]?100",
    r"\bSTE\b",
    r"IEC/IEEE[ ]?82079(?:-1)?",
    r"\b82079(?:-1)?\b",
    r"ISO[ ]?24495(?:-1)?",
    r"\b24495(?:-1)?\b",
    r"\btekom\b",
)
CLAIM_PATTERNS = (
    r"\bcompliant\b",
    r"\bconformant\b",
    r"\bconforms\b",
    r"\bcertified\b",
    r"\bkonform\b",
    r"\bzertifiziert\b",
)
STANDARD_RE = re.compile("|".join("(?:%s)" % p for p in STANDARD_PATTERNS), re.I)
CLAIM_RE = re.compile("|".join("(?:%s)" % p for p in CLAIM_PATTERNS), re.I)
CLAIM_PAIR_RE = re.compile(
    "(?:(?:%s).*(?:%s))|(?:(?:%s).*(?:%s))"
    % ("|".join(STANDARD_PATTERNS), "|".join(CLAIM_PATTERNS), "|".join(CLAIM_PATTERNS), "|".join(STANDARD_PATTERNS)),
    re.I,
)
BANNED_WORDS = re.compile(r"\b(?:ASD|STE|tekom)\b|82079|24495", re.I)
REV_FOUR = re.compile(r"rev[ -]?4", re.I)
RULE_MENTION = re.compile(r"\b(Docs(?:EN|DE))\.([A-Za-z][A-Za-z0-9]*)")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")


def prose_lines(text):
    """(line number, text) of guide Markdown with fenced blocks and inline code removed."""
    inside = False
    out = []
    for number, raw in enumerate(text.splitlines(), 1):
        if FENCE.match(raw):
            inside = not inside
            continue
        if inside:
            continue
        out.append((number, INLINE_CODE.sub("", raw)))
    return out


def sentences(text):
    """Sentences of a text, split at blank lines, line starts of list items and end punctuation."""
    found = []
    for block in re.split(r"\n\s*\n", text):
        for line in block.splitlines():
            found += [part for part in SENTENCE_BREAK.split(line) if part.strip()]
    return found


def own_files(guide_dir):
    """Every file the dash check reads: guide folder, Vale folder, scripts, workflow, README section."""
    files = [p for p in sorted(Path(guide_dir).rglob("*")) if p.is_file()]
    files += [p for p in sorted((SITE / ".vale").rglob("*")) if p.is_file()]
    files += [INI_FILE, SITE / "scripts" / "verify-prose.sh", SITE / "scripts" / "prose-lint.py"]
    files += [ROOT / ".github" / "workflows" / "lint-docs.yml"]
    return [p for p in files if p.is_file()]


def readme_contributing():
    readme = ROOT / "README.md"
    if not readme.is_file():
        return ""
    text = readme.read_text(encoding="utf-8")
    found = re.search(r"^## Contributing\s*$(.*?)(?=^## |\Z)", text, re.S | re.M)
    return found.group(1) if found else ""


def relative(path):
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def cmd_guide(args):
    """Print one PASS or FAIL line per check, exit 1 when any check fails."""
    failures = 0
    guide = Path(args.guide_dir)
    styles = Path(args.styles)

    def verdict(label, problems, ok_text):
        nonlocal failures
        if problems:
            failures += 1
            print("FAIL: guide %s: %d problem(s)" % (label, len(problems)))
            for problem in problems:
                print("  %s" % problem)
        else:
            print("PASS: guide %s: %s" % (label, ok_text))

    verdict("(1) files", ["%s is missing from %s" % (n, guide) for n in GUIDE_FILES if not (guide / n).is_file()],
            "all %d required files exist" % len(GUIDE_FILES))

    problems = []
    scanned = 0
    for path in own_files(guide):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        for number, line in enumerate(text.splitlines(), 1):
            if DASH_CHARS.search(line):
                problems.append("dash character U+2013 or U+2014 in %s:%d" % (relative(path), number))
    contributing = readme_contributing()
    for number, line in enumerate(contributing.splitlines(), 1):
        if DASH_CHARS.search(line):
            problems.append("dash character U+2013 or U+2014 in README.md, Contributing section, line %d" % number)
    verdict("(2) dash characters", problems, "no U+2013 or U+2014 in %d files and the README Contributing section" % scanned)

    problems = []
    guide_md = [p for p in sorted(guide.glob("*.md")) if p.is_file()]
    for path in guide_md:
        for number, line in prose_lines(path.read_text(encoding="utf-8")):
            if SPACED_DASH.search(line):
                problems.append("spaced hyphen dash in %s:%d: %s" % (relative(path), number, line.strip()[:80]))
    rule_files_all = [p for style in STYLE_LANG for p in sorted((styles / style).glob("*.yml"))] if styles.is_dir() else []
    for path in rule_files_all:
        if path.name.endswith(".test.yml"):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("message:") and SPACED_DASH.search(line[len("message:"):]):
                problems.append("spaced hyphen dash in the message of %s:%d" % (relative(path), number))
    verdict("(3) spaced hyphen dashes", problems, "none in %d guide files and in the rule messages" % len(guide_md))

    problems = []
    claim_files = guide_md + rule_files_all
    for path in claim_files:
        text = path.read_text(encoding="utf-8")
        for sentence in sentences(text):
            if CLAIM_PAIR_RE.search(sentence):
                problems.append("claim phrase in %s: %s" % (relative(path), SPACES.sub(" ", sentence).strip()[:100]))
    verdict("(4) conformity claims", problems, "no standard name near a claim word in %d files" % len(claim_files))

    problems = []
    style_files = [p for p in sorted(styles.rglob("*")) if p.is_file()] if styles.is_dir() else []
    for path in style_files:
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            found = BANNED_WORDS.search(line)
            if found:
                problems.append("'%s' in %s:%d" % (found.group(0), relative(path), number))
    verdict("(5) standard names in rules", problems, "no ASD, STE, tekom or standard number in %d rule and test files" % len(style_files))

    problems = []
    levels_path = guide / "rule-levels.yml"
    try:
        named = {"%s.%s" % (style, rule) for style, rule, _ in parse_levels(levels_path)} if levels_path.is_file() else set()
    except DataError as error:
        named = set()
        problems.append(str(error))
    docs = {}
    for name in ("en.md", "de.md"):
        path = guide / name
        docs[name] = set(
            "%s.%s" % (m.group(1), m.group(2)) for m in RULE_MENTION.finditer(path.read_text(encoding="utf-8"))
        ) if path.is_file() else set()
    for ident in sorted(named):
        home = "en.md" if ident.startswith("DocsEN.") else "de.md"
        if ident not in docs[home]:
            problems.append("undocumented rule: %s is in rule-levels.yml and not named in %s" % (ident, home))
    mentioned = set()
    for path in guide_md:
        mentioned |= set("%s.%s" % (m.group(1), m.group(2)) for m in RULE_MENTION.finditer(path.read_text(encoding="utf-8")))
    for ident in sorted(mentioned - named):
        problems.append("unknown rule: %s is named in the guide and not in rule-levels.yml" % ident)
    verdict("(6) rule catalogue", problems, "%d rules in rule-levels.yml, each documented, none unknown" % len(named))

    problems = []
    dist = SITE / "dist"
    if dist.is_dir():
        if (dist / "style-guide").exists():
            problems.append("site/dist/style-guide exists, the guide must not be published (D-10)")
        for sitemap in sorted(dist.glob("sitemap*.xml")):
            if "style-guide" in sitemap.read_text(encoding="utf-8", errors="replace"):
                problems.append("a style-guide URL is in %s (D-10)" % relative(sitemap))
        ok = "site/dist has no style-guide path and no sitemap URL"
    else:
        ok = "site/dist does not exist, nothing to check (build the site first)"
    verdict("(7) not published", problems, ok)

    readme = ROOT / "README.md"
    linked = readme.is_file() and "site/style-guide/README.md" in readme.read_text(encoding="utf-8")
    verdict("(8) root README link", [] if linked else ["README.md does not link site/style-guide/README.md"],
            "the root README links the guide")

    problems = []
    guide_all = [p for p in sorted(guide.rglob("*")) if p.is_file()]
    for path in guide_all:
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if REV_FOUR.search(line):
                problems.append("mention of unreleased hardware in %s:%d (D-12)" % (relative(path), number))
    verdict("(9) scope", problems, "no guide file mentions Rev 4.0")
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# baseline
# ---------------------------------------------------------------------------

SEVERITIES = ("error", "warning", "suggestion")
BASELINE_LANGS = (("en", "DocsEN", "English"), ("de", "DocsDE", "German"))
BASELINE_COMMAND = "bash site/scripts/verify-prose.sh --baseline"


def baseline_counts(data, tiers):
    """Tally Vale alerts. Returns (totals, per_page, alert_count).

    totals   {(lang, tier, rule): {severity: n}}
    per_page {source path: {rule: n}}
    Raises DataError for an alert on an unmapped page or with an unknown severity.
    """
    sources = source_of_dist(tiers)
    tier_of = dict(tiers)
    totals = {}
    per_page = {}
    count = 0
    for dist_path in sorted(data):
        for alert in data[dist_path]:
            source = sources.get(dist_path)
            if source is None:
                raise DataError("Vale reported an alert on %s, which is not a mapped page" % dist_path)
            severity = str(alert.get("Severity", "")).lower()
            if severity not in SEVERITIES:
                raise DataError("Vale reported an alert with unknown severity '%s' on %s" % (severity, dist_path))
            rule = clean(str(alert.get("Check", "?")))
            row = totals.setdefault((lang_of(source), tier_of[source], rule), {s: 0 for s in SEVERITIES})
            row[severity] += 1
            page = per_page.setdefault(source, {})
            page[rule] = page.get(rule, 0) + 1
            count += 1
    return totals, per_page, count


def baseline_text(totals, per_page, count, tiers, blocking, level_entries, image, commit):
    """The baseline Markdown. It holds counts and paths only: no matched text, no snippet, no timestamp."""
    table = level_table(level_entries)
    tier_of = dict(tiers)
    mapped = [path for path, _ in tiers]
    out = []
    add = out.append

    add("# Prose lint baseline")
    add("")
    add("Measured violations of the docs prose lint, handed to Phase 23 and the rewrite passes. Counts only: no page text is quoted, so the file does not change when a sentence is edited.")
    add("")
    add("## How this file is made")
    add("")
    add("- Command: `%s`" % BASELINE_COMMAND)
    add("- Vale image: `%s`" % image)
    add("- Commit: `%s` (HEAD when the file was generated; a rerun on a later commit changes this line and no other)" % commit)
    add("- Mapped pages: %d (see `page-tiers.yml`)" % len(mapped))
    add("- Alerts counted: %d" % count)
    add("")
    add("The command builds nothing. Run `npm --prefix site run build` first. It lints the mapped pages of `site/dist` with the same configuration as CI and does not fail on findings. The level columns are the levels Vale reports, which come from `rule-levels.yml` and `blocking.yml`.")
    add("")

    add("## Totals by tier and rule")
    add("")
    for lang, style, title in BASELINE_LANGS:
        rows = sorted(
            ((tier, rule, row) for (l, tier, rule), row in totals.items() if l == lang),
            key=lambda item: (TIERS.index(item[0]), item[1]),
        )
        sums = {s: 0 for s in SEVERITIES}
        add("### %s (%s)" % (title, style))
        add("")
        if rows:
            add("| Tier | Rule | Error | Warning | Suggestion | Total |")
            add("|---|---|---|---|---|---|")
            for tier, rule, row in rows:
                add("| %s | %s | %d | %d | %d | %d |" % (tier, rule, row["error"], row["warning"], row["suggestion"], sum(row.values())))
                for s in SEVERITIES:
                    sums[s] += row[s]
            add("")
        add("%s total: %d alerts (%d errors, %d warnings, %d suggestions)." % (
            title, sum(sums.values()), sums["error"], sums["warning"], sums["suggestion"]))
        add("")

    add("## Pages")
    add("")
    add("One row per mapped page. The last column lists the rules with at least one alert on the page and their counts.")
    add("")
    add("| Page | Tier | Alerts | Rules |")
    add("|---|---|---|---|")
    for path in sorted(mapped):
        rules = per_page.get(path, {})
        detail = ", ".join("%s %d" % (rule, rules[rule]) for rule in sorted(rules)) or "none"
        add("| %s | %s | %d | %s |" % (path, tier_of[path], sum(rules.values()), detail))
    add("")

    add("## Ratchet candidates")
    add("")
    add("A candidate is a page with zero alerts for a rule that is not yet blocking there, where the rule is on in the page's tier. Promoting a candidate means adding the page to `blocking.yml`, which is a decision for later and not an action of this file. The lint itself already fails when a page is clean for a rule that has a `blocking.yml` header and is not listed.")
    add("")
    for lang, style, title in BASELINE_LANGS:
        pages = sorted(path for path in mapped if lang_of(path) == lang)
        add("### %s (%s)" % (title, style))
        add("")
        shown = 0
        for rule_style, rule, _ in level_entries:
            if rule_style != style:
                continue
            ident = "%s.%s" % (style, rule)
            eligible = [p for p in pages if table[ident][tier_of[p]] != "NO"]
            listed = set(blocking.get(ident, []))
            candidates = [p for p in eligible if per_page.get(p, {}).get(ident, 0) == 0 and p not in listed]
            if not candidates:
                continue
            shown += 1
            if len(candidates) == len(eligible):
                add("- `%s`: %s." % (ident, "the one page where the rule is on is clean" if len(eligible) == 1
                                    else "all %d pages where the rule is on are clean" % len(eligible)))
            else:
                add("- `%s`: %d of %d pages are clean: %s" % (ident, len(candidates), len(eligible), ", ".join("`%s`" % p for p in candidates)))
        if shown == 0:
            add("No candidates.")
        add("")

    dash_pages = {lang: 0 for lang, _, _ in BASELINE_LANGS}
    for path in mapped:
        if any(rule.endswith(".Dashes") for rule in per_page.get(path, {})):
            dash_pages[lang_of(path)] += 1
    add("## Notes for Phase 23")
    add("")
    add("- The research phase counted violations with draft rules. This file supersedes those numbers: it uses the final rule set, the per-tier levels and the approved glossary.")
    add("- The rewrite passes after Phase 23 work from the Pages and Totals tables. A page leaves the table when its row shows zero alerts for the rules it is meant to pass.")
    add("- Accepted deferral (maintainer decision during Phase 22): ten MDX pages still carry a double hyphen and `index.mdx` still emits U+2014, because the MDX integration ignores the smartypants setting. They stay as they are, count in the dash rows above, and are fixed in the Phase 23 rewrite passes. This is not a failure of the lint.")
    add("- Pages with at least one dash finding today: %d English, %d German." % (dash_pages["en"], dash_pages["de"]))
    add("- Regenerate this file with `%s` after `npm --prefix site run build`. The command prints a PASS line when the table totals equal the alert count in the Vale output." % BASELINE_COMMAND)
    add("")
    return "\n".join(out)


def baseline_table_sum(text):
    """Sum every count in the Totals tables of a baseline file. Returns (sum, problems)."""
    problems = []
    total = 0
    inside = False
    for line in text.split("\n"):
        if line.startswith("## "):
            inside = line == "## Totals by tier and rule"
            continue
        if not inside or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells[0] not in TIERS:
            continue
        if len(cells) != 6 or not all(c.isdigit() for c in cells[2:]):
            problems.append("malformed totals row: %s" % line[:80])
            continue
        parts = [int(c) for c in cells[2:5]]
        if sum(parts) != int(cells[5]):
            problems.append("row total differs from its columns: %s" % line[:80])
        total += sum(parts)
    return total, problems


def cmd_baseline(args):
    tiers = parse_tiers(args.tiers)
    blocking = parse_blocking(args.blocking)
    level_entries = parse_levels(args.levels)
    data = load_alerts(args.vale_json)
    if data is None:
        print("FAIL: Vale output is not valid JSON")
        return 1
    totals, per_page, count = baseline_counts(data, tiers)
    text = baseline_text(totals, per_page, count, tiers, blocking, level_entries, args.image, args.commit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    # Read the file back: the proof is about the bytes on disk, not the in-memory tally.
    summed, problems = baseline_table_sum(out.read_text(encoding="utf-8"))
    if problems:
        for problem in problems:
            print("  %s" % problem)
        print("FAIL: baseline totals do not match: the table could not be read back")
        return 1
    if summed != count:
        print("FAIL: baseline totals do not match: tables sum to %d, Vale reported %d alerts" % (summed, count))
        return 1
    print("wrote %s" % relative(out))
    print("PASS: baseline totals match (%d alerts)" % count)
    return 0


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
        p.add_argument("--levels", default=str(LEVELS_FILE))

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

    p = sub.add_parser("map")
    p.add_argument("--ini", default=str(INI_FILE))
    p.add_argument("--styles", default=str(STYLES_DIR), help="styles directory (default site/.vale/styles)")
    paths(p)
    p.set_defaults(func=cmd_map)

    p = sub.add_parser("glossary")
    p.add_argument("--glossary-file", default=str(GLOSSARY_FILE))
    p.add_argument("--styles", default=str(STYLES_DIR), help="styles directory (default site/.vale/styles)")
    p.add_argument("--ini", default=str(INI_FILE))
    p.set_defaults(func=cmd_glossary)

    p = sub.add_parser("guide")
    p.add_argument("--guide-dir", default=str(GUIDE_DIR), help="guide directory (default site/style-guide)")
    p.add_argument("--styles", default=str(STYLES_DIR), help="styles directory (default site/.vale/styles)")
    p.set_defaults(func=cmd_guide)

    p = sub.add_parser("baseline")
    p.add_argument("vale_json")
    p.add_argument("--out", required=True, help="file to write (site/style-guide/baseline.md)")
    p.add_argument("--image", default="unknown", help="Vale image tag to record")
    p.add_argument("--commit", default="unknown", help="short commit SHA to record")
    paths(p)
    p.set_defaults(func=cmd_baseline)

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
