#!/usr/bin/env python3
"""Rewrite the packages: block of each example to use local !include.

The examples in examples/ reference this repository over github://...@main, so
validating them tests the published version rather than the working tree. This
tool rewrites those references to local !include paths and writes the result to
.test-build/, so test-examples.sh validates the code actually sitting on disk.

This is deliberately a line-based text transformer and not a YAML parser.
ESPHome configs carry !secret, !lambda and !include tags that yaml.safe_load
rejects, and a round trip through any parser would destroy the comments and
formatting that make these files useful as customer templates. Every line
outside the packages: block is emitted byte for byte unchanged.

Three package reference forms are recognised.

Form A, shorthand:
    hardware: github://zeroflow/wifi-fancontroller/hardware-rev-1.0.yaml@main

Form B, long form with an inline flow-style files list:
    hardware:
      url: https://github.com/zeroflow/wifi-fancontroller
      ref: main
      files: [hardware-rev-3.1.yaml]

Form C, long form with a block files list carrying path: and vars:
    usr_buttons:
      url: https://github.com/zeroflow/wifi-fancontroller
      ref: main
      files:
        - path: modules/usr_buttons.yaml
          vars:
            speed_step: "10"

Anything inside a packages: block that matches none of these is a fatal error.
A silently mis-transformed config would test the wrong thing, which is worse
than no test at all, so this tool never falls back to passing a line through
when it was expected to match.

Usage:
    python3 tools/localize-examples.py              generate .test-build/
    python3 tools/localize-examples.py --emit-map   print the JSON path map
    python3 tools/localize-examples.py --self-test  run the built-in fixtures
"""

import json
import os
import re
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES_DIR = os.path.join(REPO_ROOT, "examples")
BUILD_DIR = os.path.join(REPO_ROOT, ".test-build")

# The only repository these examples may reference. A package pointing anywhere
# else cannot be localized against this working tree, so it is a fatal error.
EXPECTED_OWNER = "zeroflow"
EXPECTED_REPO = "wifi-fancontroller"
EXPECTED_URL = "https://github.com/zeroflow/wifi-fancontroller"

PACKAGES_START_RE = re.compile(r"^packages:\s*$")
COMMENT_RE = re.compile(r"^\s*#")
SHORTHAND_RE = re.compile(
    r"^(\s+)([A-Za-z0-9_-]+):\s+github://([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/(\S+?)@(\S+)$"
)
LONG_KEY_RE = re.compile(r"^(\s+)([A-Za-z0-9_-]+):\s*$")
URL_RE = re.compile(r"^\s*url:\s*(\S+)$")
REF_RE = re.compile(r"^\s*ref:\s*(\S+)$")
FILES_INLINE_RE = re.compile(r"^\s*files:\s*\[(.*)\]$")
FILES_BLOCK_RE = re.compile(r"^\s*files:\s*$")
LIST_ENTRY_RE = re.compile(r"^(\s*)-\s+path:\s*(\S+)$")
ANY_LIST_ENTRY_RE = re.compile(r"^\s*-\s")
VARS_RE = re.compile(r"^(\s*)vars:\s*$")


class LocalizeError(Exception):
    """A package form that could not be transformed safely."""

    def __init__(self, path, lineno, line, reason):
        self.path = path
        self.lineno = lineno
        self.line = line
        self.reason = reason
        super().__init__(
            "%s:%d: %s\n    offending line: %r" % (path, lineno, reason, line)
        )


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def localize(text, path):
    """Transform one example.

    Returns a tuple of the rewritten text and the sorted list of repo-relative
    paths the example references.
    """
    lines = text.split("\n")
    out = []
    refs = []

    i = 0
    n = len(lines)
    while i < n:
        if not PACKAGES_START_RE.match(lines[i].rstrip()):
            out.append(lines[i])
            i += 1
            continue

        # Inside the packages: block.
        out.append(lines[i])
        i += 1
        while i < n:
            raw = lines[i]
            stripped = raw.rstrip()

            # Blank lines and comment lines pass through untouched.
            if not stripped or COMMENT_RE.match(stripped):
                # A blank line only ends the block if the next content line is
                # at column zero, which the dedent check below handles.
                out.append(raw)
                i += 1
                continue

            # A line at column zero ends the packages: block.
            if indent_of(stripped) == 0:
                break

            emitted, consumed, ref = transform_package(lines, i, path)
            out.extend(emitted)
            refs.append(ref)
            i += consumed

    return "\n".join(out), sorted(set(refs))


def transform_package(lines, i, path):
    """Transform a single package entry starting at line index i.

    Returns the emitted lines, how many source lines were consumed, and the
    repo-relative path the package references.
    """
    raw = lines[i]
    stripped = raw.rstrip()

    # Form A, shorthand on one line.
    match = SHORTHAND_RE.match(stripped)
    if match:
        pad, key, owner, repo, ref_path, _ref = match.groups()
        if owner != EXPECTED_OWNER or repo != EXPECTED_REPO:
            raise LocalizeError(
                path,
                i + 1,
                stripped,
                "package points at %s/%s, expected %s/%s"
                % (owner, repo, EXPECTED_OWNER, EXPECTED_REPO),
            )
        return ["%s%s: !include ../%s" % (pad, key, ref_path)], 1, ref_path

    # Form B and Form C both open with a bare key.
    match = LONG_KEY_RE.match(stripped)
    if not match:
        raise LocalizeError(
            path, i + 1, stripped, "unrecognised package form inside packages: block"
        )

    pad, key = match.groups()
    key_indent = len(pad)

    # Collect the sub-block: every following line indented deeper than the key.
    body = []
    j = i + 1
    while j < len(lines):
        sub = lines[j].rstrip()
        if not sub:
            break
        if indent_of(sub) <= key_indent:
            break
        body.append((j, sub))
        j += 1

    if not body:
        raise LocalizeError(
            path, i + 1, stripped, "package %r has an empty body" % key
        )

    ref_path = None
    vars_lines = []
    vars_indent = None
    saw_url = False
    saw_files = False

    k = 0
    while k < len(body):
        lineno, sub = body[k]

        url_match = URL_RE.match(sub)
        if url_match:
            if url_match.group(1) != EXPECTED_URL:
                raise LocalizeError(
                    path,
                    lineno + 1,
                    sub,
                    "package url is %r, expected %r" % (url_match.group(1), EXPECTED_URL),
                )
            saw_url = True
            k += 1
            continue

        if REF_RE.match(sub):
            k += 1
            continue

        inline_match = FILES_INLINE_RE.match(sub)
        if inline_match:
            entries = [e.strip() for e in inline_match.group(1).split(",") if e.strip()]
            if len(entries) != 1:
                raise LocalizeError(
                    path,
                    lineno + 1,
                    sub,
                    "files: list has %d entries, exactly one is required"
                    % len(entries),
                )
            ref_path = entries[0].strip("\"'")
            saw_files = True
            k += 1
            continue

        if FILES_BLOCK_RE.match(sub):
            saw_files = True
            k += 1
            # Parse the block list that follows.
            entry_count = 0
            while k < len(body):
                lineno2, sub2 = body[k]
                entry_match = LIST_ENTRY_RE.match(sub2)
                if entry_match:
                    entry_count += 1
                    if entry_count > 1:
                        raise LocalizeError(
                            path,
                            lineno2 + 1,
                            sub2,
                            "files: list has more than one entry, exactly one is required",
                        )
                    ref_path = entry_match.group(2).strip("\"'")
                    k += 1
                    continue
                if ANY_LIST_ENTRY_RE.match(sub2):
                    raise LocalizeError(
                        path,
                        lineno2 + 1,
                        sub2,
                        "files: list entry is not a 'path:' mapping",
                    )
                vars_match = VARS_RE.match(sub2)
                if vars_match:
                    vars_indent = len(vars_match.group(1))
                    vars_lines.append(sub2)
                    k += 1
                    # Everything deeper than vars: belongs to the vars block,
                    # including comment-only lines.
                    while k < len(body):
                        lineno3, sub3 = body[k]
                        if COMMENT_RE.match(sub3) or indent_of(sub3) > vars_indent:
                            vars_lines.append(sub3)
                            k += 1
                            continue
                        break
                    continue
                break
            continue

        raise LocalizeError(
            path, lineno + 1, sub, "unrecognised key inside package %r" % key
        )

    if not saw_url:
        raise LocalizeError(path, i + 1, stripped, "package %r has no url:" % key)
    if not saw_files or ref_path is None:
        raise LocalizeError(path, i + 1, stripped, "package %r has no files:" % key)

    consumed = j - i

    # Form B, no vars, collapses to the single-line include.
    if not vars_lines:
        return ["%s%s: !include ../%s" % (pad, key, ref_path)], consumed, ref_path

    # Form C keeps the vars, dedented to sit one level under the package key.
    target_indent = key_indent + 2
    delta = target_indent - vars_indent

    emitted = [
        "%s%s: !include" % (pad, key),
        "%sfile: ../%s" % (" " * target_indent, ref_path),
    ]
    for var_line in vars_lines:
        current = indent_of(var_line)
        new_indent = max(target_indent, current + delta)
        emitted.append(" " * new_indent + var_line.lstrip(" "))

    return emitted, consumed, ref_path


INCLUDE_RE = re.compile(r"!include\s+(\S+)\s*$")
INCLUDE_FILE_RE = re.compile(r"^\s*file:\s*(\S+)\s*$")


def transitive_refs(direct):
    """Expand direct package references to everything they pull in.

    A package reference is only the entry point. hardware-rev-3.2.yaml and
    hardware-rev-3.3.yaml are thin wrappers that !include hardware-rev-3.1.yaml,
    and every hardware package !includes modules/globals.yaml. Without following
    those edges, CI would decide that a change to modules/globals.yaml affects no
    example at all, and report a green check for coverage it never ran.
    """
    seen = set()
    queue = list(direct)

    while queue:
        rel = queue.pop()
        if rel in seen:
            continue
        seen.add(rel)

        target = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(target):
            continue

        with open(target, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.rstrip()
                # Usage examples in header comments are not real edges.
                if COMMENT_RE.match(stripped):
                    continue

                match = INCLUDE_RE.search(stripped) or INCLUDE_FILE_RE.match(stripped)
                if not match:
                    continue

                # !include paths resolve relative to the including file.
                nested = os.path.normpath(
                    os.path.join(os.path.dirname(target), match.group(1))
                )
                queue.append(os.path.relpath(nested, REPO_ROOT))

    return sorted(seen)


def example_files(explicit=None):
    """Every testable example, or an explicit list passed on the command line.

    The explicit form exists so a single file can be checked ad hoc, which is
    how the hard-fail behaviour is exercised against fixtures that must not be
    added to examples/.
    """
    if explicit:
        return [os.path.abspath(p) for p in explicit]
    names = sorted(
        f
        for f in os.listdir(EXAMPLES_DIR)
        if f.endswith(".yaml") and f != "secrets.yaml"
    )
    return [os.path.join(EXAMPLES_DIR, name) for name in names]


def relative(path):
    return os.path.relpath(path, REPO_ROOT)


def build_map(explicit=None):
    result = {}
    for path in example_files(explicit):
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        _out, refs = localize(text, relative(path))
        result[relative(path)] = transitive_refs(refs)
    return result


def generate():
    # Only the generated configs are cleared, never the whole directory.
    # A compile run leaves a .esphome build cache in here that is owned by root
    # when ESPHome runs through docker, so removing the tree outright fails with
    # a permission error and leaves the directory half deleted. Keeping the
    # cache also makes repeat compiles incremental.
    os.makedirs(BUILD_DIR, exist_ok=True)

    for stale in os.listdir(BUILD_DIR):
        if stale.endswith(".yaml") and stale != "secrets.yaml":
            os.remove(os.path.join(BUILD_DIR, stale))

    count = 0
    for path in example_files():
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        out, _refs = localize(text, relative(path))
        target = os.path.join(BUILD_DIR, os.path.basename(path))
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(out)
        count += 1

    # ESPHome resolves !secret relative to the directory of the main config, so
    # the generated directory needs its own copy.
    secrets = os.path.join(REPO_ROOT, "secrets.yaml")
    if os.path.isfile(secrets):
        shutil.copyfile(secrets, os.path.join(BUILD_DIR, "secrets.yaml"))
    else:
        print(
            "note: no secrets.yaml at the repo root, "
            "test-examples.sh and CI generate a dummy",
            file=sys.stderr,
        )

    print("generated %d configs in %s" % (count, relative(BUILD_DIR)))


SELF_TEST_GOOD = """\
packages:
  # a comment
  hardware: github://zeroflow/wifi-fancontroller/hardware-rev-3.1.yaml@main
  inline:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [modules/rpm_status_leds.yaml]
  withvars:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/usr_buttons.yaml
        vars:
          # a comment inside vars
          speed_step: "10"  # trailing comment

esphome:
  name: unchanged
"""

SELF_TEST_GOOD_EXPECTED = """\
packages:
  # a comment
  hardware: !include ../hardware-rev-3.1.yaml
  inline: !include ../modules/rpm_status_leds.yaml
  withvars: !include
    file: ../modules/usr_buttons.yaml
    vars:
      # a comment inside vars
      speed_step: "10"  # trailing comment

esphome:
  name: unchanged
"""

SELF_TEST_BAD = [
    (
        "unknown form",
        "packages:\n  hardware: some-random-value\n",
    ),
    (
        "multi entry inline files",
        "packages:\n  hardware:\n"
        "    url: https://github.com/zeroflow/wifi-fancontroller\n"
        "    ref: main\n"
        "    files: [hardware-rev-3.1.yaml, modules/usr_buttons.yaml]\n",
    ),
    (
        "multi entry block files",
        "packages:\n  hardware:\n"
        "    url: https://github.com/zeroflow/wifi-fancontroller\n"
        "    ref: main\n"
        "    files:\n"
        "      - path: hardware-rev-3.1.yaml\n"
        "      - path: modules/usr_buttons.yaml\n",
    ),
    (
        "foreign repository",
        "packages:\n  hardware: github://someoneelse/other-repo/hardware.yaml@main\n",
    ),
    (
        "unknown key inside package",
        "packages:\n  hardware:\n"
        "    url: https://github.com/zeroflow/wifi-fancontroller\n"
        "    branch: main\n"
        "    files: [hardware-rev-3.1.yaml]\n",
    ),
]


def self_test():
    failures = []

    got, refs = localize(SELF_TEST_GOOD, "self-test")
    if got != SELF_TEST_GOOD_EXPECTED:
        failures.append(
            "positive fixture mismatch\n--- got ---\n%s\n--- want ---\n%s"
            % (got, SELF_TEST_GOOD_EXPECTED)
        )
    else:
        print("ok: positive fixture, refs=%s" % refs)

    for name, text in SELF_TEST_BAD:
        try:
            localize(text, "self-test")
        except LocalizeError as err:
            print("ok: %s rejected: %s" % (name, err.reason))
        else:
            failures.append("negative fixture %r was accepted, expected a hard fail" % name)

    if failures:
        for failure in failures:
            print("FAIL: %s" % failure, file=sys.stderr)
        return 1

    print("self-test passed")
    return 0


def main(argv):
    args = argv[1:]

    if "--self-test" in args:
        return self_test()

    explicit = [a for a in args if not a.startswith("--")]

    try:
        if "--emit-map" in args:
            print(json.dumps(build_map(explicit), indent=None, sort_keys=True))
            return 0
        if explicit:
            # Checking specific files, so validate them without writing output.
            build_map(explicit)
            print("checked %d file(s), all package forms recognised" % len(explicit))
            return 0
        generate()
        return 0
    except LocalizeError as err:
        print("error: %s" % err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
