#!/usr/bin/env python3
"""Resolve the latest release once, fetch its factory image by tag and prove it three ways (REG-01).

Runs in the hosted `prepare` job of hil.yml and on the dev host, stdlib plus the `gh` CLI, from the
repository root:

    python3 hil/tools/fetch_baseline.py --repo OWNER/NAME --rev 3.2 --out hil-baseline

What it does, in this order, and nothing else:

 1. Refuses an --out that exists and is not an empty directory (before any gh call), an unknown
    --rev and a --repo that is not OWNER/NAME.
 2. Asks GitHub for the latest release exactly once. That endpoint skips drafts and prereleases; the
    baseline is never computed from tag names (RESEARCH Pitfall 13). The tag must be vX.Y.Z, and it
    is logged once as `Baseline release tag: <tag>`. Every later call addresses the release by this
    tag, so a release published mid-run cannot split the run across two tags (T-03-21).
 3. Reads the asset list of that tag and the factory asset's API `digest` ("sha256:<hex>" or null).
 4. Downloads the factory image, its .sha256 sidecar and the release manifest by tag.
 5. Computes the image's sha256 and compares it with the sidecar, the manifest's
    builds[0].parts[0].sha256 and, when GitHub reports one, the API digest. The manifest must
    describe this file, at offset 0, for the revision's chip family.
 6. Removes the sidecar and the manifest and writes baseline.json last (schema 1: repo, tag, rev,
    asset, sha256, offset, chip_family, version, digests {api, sidecar, manifest}).

On any failure it prints `fetch_baseline: <what>` to stderr, removes every file it put into --out
and exits 1, so a later step finds nothing it could flash. Nothing but the tag, asset names,
digests (12 hex digits in the log) and the manifest version is printed; gh's own output is never
echoed. Every gh call is an argument list with a timeout, never a shell.

--self-test is not offered: hil/tests/unit/test_fetch_baseline.py drives this tool against a fake gh.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

# Per revision: the release asset names and the chip family the manifest must name. Asset names come
# from this table only, never from the release (T-03-23).
ASSETS = {
    "3.2": {
        "factory": "fancontroller-r3-2-esp32s2.factory.bin",
        "manifest": "fancontroller-r3-2.manifest.json",
        "chip_family": "ESP32-S2",
    },
}
BASELINE_FILE = "baseline.json"
SCHEMA = 1
TAG_RE = re.compile(r"v\d+\.\d+\.\d+")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
HEX64_RE = re.compile(r"[0-9a-f]{64}")
API_TIMEOUT_S = 60
DOWNLOAD_TIMEOUT_S = 600
SHORT = 12


class FetchError(Exception):
    """A refusal; the message names what disagreed and never carries gh output."""


def gh(args, timeout):
    """Run gh with an argument list and a timeout; stdout on success, FetchError otherwise."""
    what = " ".join(args[:2])
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as err:
        raise FetchError("gh is not installed") from err
    except subprocess.TimeoutExpired as err:
        raise FetchError("gh %s did not finish within %d s" % (what, timeout)) from err
    if done.returncode != 0:
        raise FetchError("gh %s failed (exit %d)" % (what, done.returncode))
    return done.stdout


def gh_json(path, what):
    try:
        data = json.loads(gh(["api", path], API_TIMEOUT_S))
    except json.JSONDecodeError as err:
        raise FetchError("%s is not JSON" % what) from err
    if not isinstance(data, dict):
        raise FetchError("%s is not a JSON object" % what)
    return data


def check_out_dir(out):
    if os.path.lexists(out) and not os.path.isdir(out):
        raise FetchError("--out %s exists and is not a directory" % out)
    if os.path.isdir(out) and os.listdir(out):
        raise FetchError("--out %s is not empty; fetch into an empty directory" % out)


def resolve_latest(repo):
    """The one `latest` request of a run; returns the validated tag."""
    latest = gh_json("repos/%s/releases/latest" % repo, "the latest release")
    tag = latest.get("tag_name")
    if not isinstance(tag, str) or TAG_RE.fullmatch(tag) is None:
        raise FetchError("the latest release tag is not of the form vX.Y.Z")
    for flag in ("draft", "prerelease"):
        if latest.get(flag) is not False:
            raise FetchError("the latest release %s is marked %s or does not say" % (tag, flag))
    return tag


def api_digest(release, tag, names):
    """The factory asset's API digest (hex or None); every name in `names` must be an asset of `tag`."""
    if release.get("tag_name") != tag:
        raise FetchError("the release fetched by tag %s names another tag" % tag)
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise FetchError("release %s has no asset list" % tag)
    by_name = {a.get("name"): a for a in assets if isinstance(a, dict)}
    for name in names:
        if name not in by_name:
            raise FetchError("release %s has no asset %s" % (tag, name))
    digest = by_name[names[0]].get("digest")
    if digest is None:
        return None
    if not isinstance(digest, str) or not digest.startswith("sha256:") or HEX64_RE.fullmatch(digest[7:]) is None:
        raise FetchError("the api digest of %s is not sha256:<64 hex>" % names[0])
    return digest[7:]


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def read_sidecar(path, factory):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        tokens = handle.read().split()
    token = tokens[0].lower() if tokens else ""
    if HEX64_RE.fullmatch(token) is None:
        raise FetchError("the sidecar %s.sha256 does not start with a sha256 digest" % factory)
    return token


def read_manifest(path, name, factory):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        build = data["builds"][0]
        part = build["parts"][0]
        values = (part["sha256"], part["offset"], part.get("path"), build["chipFamily"], data["version"])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        raise FetchError("the manifest %s is not readable JSON" % name) from err
    except (KeyError, IndexError, TypeError) as err:
        raise FetchError("the manifest %s has no builds[0].parts[0] with sha256, offset, chipFamily and version" % name) from err
    sha, offset, part_path, chip_family, version = values
    if not isinstance(sha, str) or HEX64_RE.fullmatch(sha.lower()) is None:
        raise FetchError("the manifest %s part sha256 is not 64 hex" % name)
    if part_path != factory:
        raise FetchError("the manifest %s part path is not %s" % (name, factory))
    if not isinstance(version, str) or not version:
        raise FetchError("the manifest %s has no version string" % name)
    return sha.lower(), offset, chip_family, version


def compare(computed, api, sidecar, manifest):
    """Every available digest must equal the computed one; returns the log line."""
    for source, value in (("sidecar", sidecar), ("manifest", manifest), ("api", api)):
        if value is not None and value != computed:
            raise FetchError("the %s sha256 %s... differs from the computed sha256 %s..." % (source, value[:SHORT], computed[:SHORT]))
    shown = ["computed %s" % computed[:SHORT], "sidecar %s" % sidecar[:SHORT], "manifest %s" % manifest[:SHORT]]
    shown.append("api %s" % api[:SHORT] if api is not None else "api null (not compared)")
    return "Digests agree: %s" % ", ".join(shown)


def remove_ours(out, names):
    for name in names:
        path = os.path.join(out, name)
        if os.path.lexists(path):
            os.remove(path)


def fetch(repo, rev, out):
    table = ASSETS[rev]
    factory, manifest_name = table["factory"], table["manifest"]
    sidecar_name = factory + ".sha256"
    tag = resolve_latest(repo)
    print("Baseline release tag: %s" % tag, flush=True)
    release = gh_json("repos/%s/releases/tags/%s" % (repo, tag), "release %s" % tag)
    api = api_digest(release, tag, (factory, sidecar_name, manifest_name))

    os.makedirs(out, exist_ok=True)
    gh(["release", "download", tag, "-R", repo, "-p", factory, "-p", sidecar_name, "-p", manifest_name, "-D", out],
       DOWNLOAD_TIMEOUT_S)
    for name in (factory, sidecar_name, manifest_name):
        if not os.path.isfile(os.path.join(out, name)):
            raise FetchError("the download of release %s did not deliver %s" % (tag, name))

    computed = sha256_file(os.path.join(out, factory))
    sidecar = read_sidecar(os.path.join(out, sidecar_name), factory)
    manifest_sha, offset, chip_family, version = read_manifest(os.path.join(out, manifest_name), manifest_name, factory)
    line = compare(computed, api, sidecar, manifest_sha)
    if chip_family != table["chip_family"]:
        raise FetchError("the manifest %s chip family is not %s" % (manifest_name, table["chip_family"]))
    if type(offset) is not int or offset != 0:
        raise FetchError("the manifest %s offset of %s is not 0" % (manifest_name, factory))
    print(line, flush=True)

    remove_ours(out, (sidecar_name, manifest_name))
    record = {
        "schema": SCHEMA,
        "repo": repo,
        "tag": tag,
        "rev": rev,
        "asset": factory,
        "sha256": computed,
        "offset": "0x0",
        "chip_family": chip_family,
        "version": version,
        "digests": {"api": api, "sidecar": sidecar, "manifest": manifest_sha},
    }
    partial = os.path.join(out, BASELINE_FILE + ".partial")
    with open(partial, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(partial, os.path.join(out, BASELINE_FILE))
    print("Baseline %s %s, version %s, written to %s" % (tag, factory, version, os.path.join(out, BASELINE_FILE)), flush=True)


def parse_args(argv):
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("--repo", required=True, help="OWNER/NAME of the product repository")
    parser.add_argument("--rev", required=True, help="hardware revision, one of %s" % ", ".join(sorted(ASSETS)))
    parser.add_argument("--out", required=True, help="output directory; must be absent or empty")
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv[1:])
    out = args.out
    created = []
    try:
        if args.rev not in ASSETS:
            raise FetchError("--rev %s is not one of %s" % (args.rev, ", ".join(sorted(ASSETS))))
        if REPO_RE.fullmatch(args.repo) is None or ".." in args.repo:
            raise FetchError("--repo must be OWNER/NAME")
        check_out_dir(out)
        table = ASSETS[args.rev]
        created = [table["factory"], table["factory"] + ".sha256", table["manifest"], BASELINE_FILE,
                   BASELINE_FILE + ".partial"]
        fetch(args.repo, args.rev, out)
    except (FetchError, OSError) as err:
        if created and os.path.isdir(out):
            remove_ours(out, created)
        message = str(err) if isinstance(err, FetchError) else "cannot write to --out (%s)" % err.__class__.__name__
        print("fetch_baseline: %s" % message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
