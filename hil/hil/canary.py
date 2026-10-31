#!/usr/bin/env python3
"""Runner credential canary (RUN-03 as amended by D-18).

Runs first in every hil job: `python3 -I hil/hil/canary.py`. Stdlib only, no
dependencies, so it runs before `uv sync`. It fails the job when job code could read
the fine-grained PAT that mints runner registrations, or could reach what the runner
must keep from it. The PAT lives on the Proxmox host only (D-10), so the canary looks
for its form: `github_pat_` followed by 20 or more word characters, and a classic
`ghp_` token (36 alphanumerics).

Positive controls come first, so a pass cannot be vacuous: the canary plants a random
PAT-shaped sentinel in a 0600 file under $RUNNER_TEMP and in the environment of a
child process, then requires the scan to find both. A scan that misses either one is
blind and the canary fails ("scanner blind: file" / "scanner blind: environ"). Hits on
the sentinel are controls, never findings.

Checks, in order:
  1. controls planted
  2. one scan: the canary's own environment, every /proc/<pid>/environ the runner uid
     can open, every regular file it can open from / (skipping /proc, /sys, /dev, no
     symlinks followed, files up to 5 MB; larger ones are counted by path prefix)
  3. the minter's PAT path: /etc/hil-runner, /etc/hil-runner/pat and
     /etc/hil-runner/mint.env must not exist in this container (only FileNotFoundError
     passes), and no mount in /proc/self/mountinfo may name hil-runner
  4. /run/hil (where the host pushes the next job's config) exists, is owned by root
     and has no group or other permission bit
  5. /etc/hil and everything in it is not writable by the runner user

Only check names, counts, pids, paths, pattern names and the duration are printed,
never a matched value. Exit 0 on a clean pass (or a skip off the runner), 1 otherwise.
The one-job JIT config the runner hands its own job is accepted (D-18): it has no PAT
form and is not a finding.
"""

import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time

MAX_FILE_BYTES = 5 * 1024 * 1024
SKIP_PREFIXES = ("/proc", "/sys", "/dev")
MINTER_PATHS = ("/etc/hil-runner", "/etc/hil-runner/pat", "/etc/hil-runner/mint.env")
MOUNTINFO = "/proc/self/mountinfo"
RUN_DIR = "/run/hil"
ETC_HIL = "/etc/hil"
SENTINEL_VAR = "HIL_CANARY_CONTROL"
SENTINEL_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# The patterns are assembled from pieces so this file never contains a match of its own.
PAT_RE = re.compile(rb"github" + rb"_pat_\w{20,}|gh" + rb"p_[A-Za-z0-9]{36}")
PATTERN_NAME = "github_pat_/ghp_"


def make_sentinel():
    """A random token of the PAT form: the prefix plus 82 characters."""
    return "github" + "_pat_" + "".join(secrets.choice(SENTINEL_ALPHABET) for _ in range(82))


def scan_bytes(data, sentinel):
    """(findings, controls): matches that are not the sentinel, matches that are."""
    needle = sentinel.encode("ascii")
    findings = controls = 0
    for match in PAT_RE.finditer(data):
        if match.group(0) == needle:
            controls += 1
        else:
            findings += 1
    return findings, controls


def scan_own_environ(environ, sentinel):
    """Names of variables in the canary's own environment that hold a PAT-shaped value."""
    names = []
    for name, value in environ.items():
        findings, controls = scan_bytes(value.encode("utf-8", "replace"), sentinel)
        if findings or controls:
            names.append(name)
    return names


def scan_environs(proc_dir, sentinel):
    """Scan /proc/<pid>/environ for every numeric entry the runner uid can open."""
    result = {"scanned": 0, "unreadable": 0, "findings": [], "controls": 0}
    try:
        entries = sorted(os.listdir(proc_dir))
    except OSError:
        return result
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_dir, entry, "environ"), "rb") as handle:
                data = handle.read()
        except OSError:
            result["unreadable"] += 1
            continue
        result["scanned"] += 1
        findings, controls = scan_bytes(data, sentinel)
        if findings:
            result["findings"].append(int(entry))
        result["controls"] += controls
    return result


def _skipped(path, skip_prefixes):
    return any(path == prefix or path.startswith(prefix + "/") for prefix in skip_prefixes)


def scan_files(root, sentinel, skip_prefixes=SKIP_PREFIXES, max_bytes=MAX_FILE_BYTES):
    """Scan every regular file under root that this user can open. Symlinks are not followed."""
    result = {"scanned": 0, "unreadable": 0, "large": {}, "findings": [], "control_paths": []}
    for directory, dirnames, filenames in os.walk(root, followlinks=False,
                                                   onerror=lambda _e: result.__setitem__("unreadable", result["unreadable"] + 1)):
        dirnames[:] = [d for d in dirnames if not _skipped(os.path.join(directory, d), skip_prefixes)]
        for name in filenames:
            path = os.path.join(directory, name)
            try:
                info = os.lstat(path)
                if not stat.S_ISREG(info.st_mode):
                    continue
                if info.st_size > max_bytes:
                    parts = path.split("/")
                    prefix = "/".join(parts[:3]) or "/"
                    result["large"][prefix] = result["large"].get(prefix, 0) + 1
                    continue
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
                try:
                    handle = os.fdopen(fd, "rb")
                except BaseException:
                    os.close(fd)
                    raise
                with handle:
                    data = handle.read()
            except OSError:
                result["unreadable"] += 1
                continue
            result["scanned"] += 1
            findings, controls = scan_bytes(data, sentinel)
            if findings:
                result["findings"].append(path)
            if controls:
                result["control_paths"].append(path)
    return result


def check_minter(paths=MINTER_PATHS, mountinfo=MOUNTINFO):
    """Problems with the minter's PAT path being visible in this container."""
    problems = []
    for path in paths:
        try:
            os.stat(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            problems.append("%s: %s (only 'does not exist' passes)" % (path, type(exc).__name__))
        else:
            problems.append("%s exists in the container" % path)
    try:
        with open(mountinfo, "r", encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                if "hil-runner" in line:
                    problems.append("%s line %d names hil-runner (host bind mount?)" % (mountinfo, number))
    except OSError as exc:
        problems.append("%s unreadable (%s)" % (mountinfo, type(exc).__name__))
    return problems


def run_dir_problems(info, owner_uid=0):
    """Problems with the stat result of /run/hil; None means the directory is missing."""
    if info is None:
        return ["missing"]
    problems = []
    if not stat.S_ISDIR(info.st_mode):
        problems.append("not a directory")
    if info.st_uid != owner_uid:
        problems.append("not owned by root (uid %d)" % info.st_uid)
    if info.st_mode & 0o077:
        problems.append("group or other permission bits set (mode %04o)" % stat.S_IMODE(info.st_mode))
    return problems


def check_run_dir(path=RUN_DIR, owner_uid=0):
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return run_dir_problems(None)
    except OSError as exc:
        return ["stat failed (%s)" % type(exc).__name__]
    return run_dir_problems(info, owner_uid)


def check_etc_hil(path=ETC_HIL, access=os.access):
    """Writable entries under the rig config directory (the directory itself included)."""
    if not os.path.isdir(path):
        return ["%s is missing" % path], 0
    problems = []
    count = 1
    if access(path, os.W_OK):
        problems.append("%s is writable by this user" % path)
    for directory, dirnames, filenames in os.walk(path, followlinks=False):
        for name in dirnames + filenames:
            entry = os.path.join(directory, name)
            count += 1
            if not os.path.islink(entry) and access(entry, os.W_OK):
                problems.append("%s is writable by this user" % entry)
    return problems, count


class Controls:
    """The sentinel file and the child process that carries it in its environment."""

    def __init__(self, sentinel, temp_dir):
        self.sentinel = sentinel
        self.temp_dir = temp_dir
        self.file_path = None
        self.child = None

    def plant(self):
        fd, path = tempfile.mkstemp(prefix="hil-canary-", dir=self.temp_dir)
        # The tree walk does not follow symlinks, so it meets the file by its real path.
        self.file_path = os.path.realpath(path)
        with os.fdopen(fd, "wb") as handle:
            handle.write(self.sentinel.encode("ascii") + b"\n")
        os.chmod(self.file_path, 0o600)
        child_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), SENTINEL_VAR: self.sentinel}
        self.child = subprocess.Popen(
            [sys.executable, "-I", "-c", "import sys, time; print('ready', flush=True); time.sleep(300)"],
            env=child_env, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
        )
        if self.child.stdout.readline().strip() != b"ready":
            raise RuntimeError("control child did not start")

    def remove(self):
        if self.child is not None:
            self.child.kill()
            self.child.wait()
            self.child.stdout.close()
        if self.file_path is not None:
            try:
                os.unlink(self.file_path)
            except OSError:
                pass


def say(line):
    print("canary: " + line, flush=True)


def run(env=None, scan_root="/", proc_dir="/proc", skip_prefixes=SKIP_PREFIXES, minter_paths=MINTER_PATHS,
        mountinfo=MOUNTINFO, run_dir=RUN_DIR, etc_hil=ETC_HIL, max_bytes=MAX_FILE_BYTES,
        owner_uid=0, access=os.access):
    env = os.environ if env is None else env
    if env.get("RUNNER_ENVIRONMENT") != "self-hosted":
        say("canary skipped: not on the self-hosted runner")
        return 0

    started = time.monotonic()
    temp_dir = env.get("RUNNER_TEMP") or tempfile.gettempdir()
    sentinel = make_sentinel()
    controls = Controls(sentinel, temp_dir)
    failures = []
    try:
        controls.plant()
        own = scan_own_environ(env, sentinel)
        environs = scan_environs(proc_dir, sentinel)
        files = scan_files(scan_root, sentinel, skip_prefixes, max_bytes)
    finally:
        controls.remove()

    file_hits = len([p for p in files["control_paths"] if p == controls.file_path])
    environ_hits = environs["controls"]
    say("control hits: file %d, environ %d" % (file_hits, environ_hits))
    if file_hits < 1:
        failures.append("scanner blind: file")
    if environ_hits < 1:
        failures.append("scanner blind: environ")

    say("own environment: %d variable(s) with a %s token" % (len(own), PATTERN_NAME))
    for name in own:
        failures.append("PAT-shaped value in own environment variable %s" % name)
    say("environs scanned %d, unreadable %d, with a %s token: %d"
        % (environs["scanned"], environs["unreadable"], PATTERN_NAME, len(environs["findings"])))
    for pid in environs["findings"]:
        failures.append("%s token in /proc/%d/environ" % (PATTERN_NAME, pid))
    large = ", ".join("%s x%d" % item for item in sorted(files["large"].items())) or "none"
    say("files scanned %d, unreadable %d, over %d bytes skipped by path prefix: %s; skipped trees: %s"
        % (files["scanned"], files["unreadable"], max_bytes, large, ", ".join(skip_prefixes)))
    say("files with a %s token: %d" % (PATTERN_NAME, len(files["findings"])))
    for path in files["findings"]:
        failures.append("%s token in file %s" % (PATTERN_NAME, path))

    problems = check_minter(minter_paths, mountinfo)
    say("minter path and host mount: %d problem(s)" % len(problems))
    failures.extend("minter: " + problem for problem in problems)

    problems = check_run_dir(run_dir, owner_uid)
    say("%s: %s" % (run_dir, "root-owned, no group or other access" if not problems else "; ".join(problems)))
    failures.extend("%s: %s" % (run_dir, problem) for problem in problems)

    problems, entries = check_etc_hil(etc_hil, access)
    say("%s: %d entries checked, %d writable by this user" % (etc_hil, entries, len(problems)))
    failures.extend(problems)

    say("scan duration %.1f s" % (time.monotonic() - started))
    if failures:
        for failure in failures:
            say("FAIL: " + failure)
        return 1
    say("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(run())
