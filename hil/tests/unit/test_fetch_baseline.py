"""hil/tools/fetch_baseline.py: the latest release is resolved once, fetched by tag and proven by
three independent digests before anything that could be flashed exists (REG-01, T-03-20..23).

A fake `gh` on PATH serves a release JSON and the three asset files from a fixture directory and logs
every call, so the tests can count the `releases/latest` requests and see which tag later calls use.
"""

import hashlib
import importlib.util
import json
import os
import stat
import sys
import textwrap
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "fetch_baseline.py"
REPO = "zeroflow/wifi-fancontroller"
TAG = "v1.6.0"
FACTORY = "fancontroller-r3-2-esp32s2.factory.bin"
SIDECAR = FACTORY + ".sha256"
MANIFEST = "fancontroller-r3-2.manifest.json"
IMAGE = b"\xe9\x03\x02\x20" + bytes(range(256)) * 16
IMAGE_SHA = hashlib.sha256(IMAGE).hexdigest()
OTHER_SHA = hashlib.sha256(b"something else").hexdigest()

FAKE_GH = textwrap.dedent(
    """\
    #!{python}
    import json, os, shutil, sys
    root = os.environ["FAKE_GH_ROOT"]
    with open(os.path.join(root, "calls.log"), "a", encoding="utf-8") as log:
        log.write(json.dumps(sys.argv[1:]) + "\\n")
    args = sys.argv[1:]
    if args[:1] == ["api"]:
        name = args[1].replace("/", "_") + ".json"
        path = os.path.join(root, "api", name)
        if not os.path.exists(path):
            sys.stderr.write("HTTP 404: Not Found\\n")
            sys.exit(1)
        sys.stdout.write(open(path, encoding="utf-8").read())
        sys.exit(0)
    if args[:2] == ["release", "download"]:
        tag = args[2]
        patterns = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
        out = args[args.index("-D") + 1]
        os.makedirs(out, exist_ok=True)
        served = os.path.join(root, "assets", tag)
        copied = 0
        for pattern in patterns:
            source = os.path.join(served, pattern)
            if os.path.exists(source):
                shutil.copy(source, os.path.join(out, pattern))
                copied += 1
        if copied == 0:
            sys.stderr.write("no assets match the file pattern\\n")
            sys.exit(1)
        sys.exit(0)
    sys.stderr.write("fake gh: unexpected call\\n")
    sys.exit(2)
    """
)


def load_tool():
    spec = importlib.util.spec_from_file_location("fetch_baseline_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_json(tag=TAG, digest="sha256:" + IMAGE_SHA, names=(FACTORY, SIDECAR, MANIFEST), draft=False, prerelease=False):
    assets = []
    for name in names:
        assets.append({"name": name, "size": 1, "digest": digest if name == FACTORY else "sha256:" + OTHER_SHA})
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease, "assets": assets}


def manifest_json(sha=IMAGE_SHA, offset=0, chip="ESP32-S2", version="3.2", path=FACTORY):
    return {
        "name": "zeroflow.fancontroller-rev3-2",
        "version": version,
        "builds": [{"chipFamily": chip, "parts": [{"path": path, "offset": offset, "sha256": sha}]}],
    }


class FakeRelease:
    """The fixture tree the fake gh serves; tests change one piece and run the tool."""

    def __init__(self, root, monkeypatch):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH.format(python=sys.executable), encoding="utf-8")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        (root / "api").mkdir()
        monkeypatch.setenv("FAKE_GH_ROOT", str(root))
        monkeypatch.setenv("PATH", "%s%s%s" % (self.bin, os.pathsep, os.environ.get("PATH", "")))
        self.out = root / "out"
        self.publish()

    def api(self, path, data):
        (self.root / "api" / (path.replace("/", "_") + ".json")).write_text(json.dumps(data), encoding="utf-8")

    def publish(self, tag=TAG, latest=None, tagged=None, image=IMAGE, sidecar=None, manifest=None, skip=()):
        latest = latest if latest is not None else release_json(tag=tag)
        tagged = tagged if tagged is not None else release_json(tag=tag)
        self.api("repos/%s/releases/latest" % REPO, latest)
        self.api("repos/%s/releases/tags/%s" % (REPO, tag), tagged)
        served = self.root / "assets" / tag
        served.mkdir(parents=True, exist_ok=True)
        files = {
            FACTORY: image,
            SIDECAR: (sidecar if sidecar is not None else "%s  %s\n" % (IMAGE_SHA, FACTORY)).encode(),
            MANIFEST: json.dumps(manifest if manifest is not None else manifest_json()).encode(),
        }
        for name, content in files.items():
            if name not in skip:
                (served / name).write_bytes(content)
            elif (served / name).exists():
                (served / name).unlink()

    def calls(self):
        log = self.root / "calls.log"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def run(self, *extra):
        argv = ["fetch_baseline.py", "--repo", REPO, "--rev", "3.2", "--out", str(self.out), *extra]
        return load_tool().main(argv)


@pytest.fixture
def release(tmp_path, monkeypatch):
    return FakeRelease(tmp_path, monkeypatch)


def written(release):
    return sorted(os.listdir(release.out)) if release.out.exists() else []


def assert_nothing_flashable(release):
    assert FACTORY not in written(release)
    assert "baseline.json" not in written(release)


def test_three_agreeing_digests_write_the_image_and_baseline_json(release, capsys):
    assert release.run() == 0
    out = capsys.readouterr().out
    assert out.count("Baseline release tag: v1.6.0") == 1
    assert [line for line in out.splitlines() if line.startswith("Baseline release tag:")] == ["Baseline release tag: v1.6.0"]
    assert written(release) == ["baseline.json", FACTORY]
    assert (release.out / FACTORY).read_bytes() == IMAGE
    data = json.loads((release.out / "baseline.json").read_text(encoding="utf-8"))
    assert data == {
        "schema": 1,
        "repo": REPO,
        "tag": TAG,
        "rev": "3.2",
        "asset": FACTORY,
        "sha256": IMAGE_SHA,
        "offset": "0x0",
        "chip_family": "ESP32-S2",
        "version": "3.2",
        "digests": {"api": IMAGE_SHA, "sidecar": IMAGE_SHA, "manifest": IMAGE_SHA},
    }
    # Every digest compared is named with its first 12 hex digits; no full digest in the log.
    assert IMAGE_SHA[:12] in out
    for source in ("computed", "api", "sidecar", "manifest"):
        assert source in out


def test_latest_is_asked_for_exactly_once_and_every_later_call_uses_that_tag(release):
    assert release.run() == 0
    calls = release.calls()
    latest = [c for c in calls if any("releases/latest" in a for a in c)]
    assert len(latest) == 1
    later = [c for c in calls if c not in latest]
    assert later and all(TAG in " ".join(c) for c in later)
    assert ["api", "repos/%s/releases/tags/%s" % (REPO, TAG)] in calls
    download = next(c for c in calls if c[:2] == ["release", "download"])
    assert download[2] == TAG and download[download.index("-R") + 1] == REPO
    assert sorted(download[i + 1] for i, a in enumerate(download) if a == "-p") == sorted([FACTORY, SIDECAR, MANIFEST])


def test_a_release_published_after_the_resolve_does_not_move_the_run(release):
    """T-03-21: the tag resolved once wins, even if `latest` would answer differently later."""
    release.publish(tag="v1.7.0")  # a complete newer release exists ...
    release.publish(tag=TAG)  # ... but `latest` answers v1.6.0 at the one resolve
    assert release.run() == 0
    assert not any("v1.7.0" in " ".join(c) for c in release.calls())


@pytest.mark.parametrize(
    "source, change",
    [
        ("sidecar", {"sidecar": "%s  %s\n" % (OTHER_SHA, FACTORY)}),
        ("manifest", {"manifest": manifest_json(sha=OTHER_SHA)}),
        ("api", {"tagged": release_json(digest="sha256:" + OTHER_SHA)}),
    ],
)
def test_a_disagreeing_digest_ends_the_run_naming_its_source(release, capsys, source, change):
    release.publish(**change)
    assert release.run() == 1
    err = capsys.readouterr().err
    assert err.startswith("fetch_baseline: ")
    assert source in err
    assert_nothing_flashable(release)


def test_a_changed_image_disagrees_with_all_three(release, capsys):
    release.publish(image=IMAGE + b"\x00")
    assert release.run() == 1
    assert "fetch_baseline: " in capsys.readouterr().err
    assert_nothing_flashable(release)


def test_a_null_api_digest_compares_the_other_two(release, capsys):
    release.publish(tagged=release_json(digest=None))
    assert release.run() == 0
    out = capsys.readouterr().out
    assert "api" in out and "not compared" in out
    data = json.loads((release.out / "baseline.json").read_text(encoding="utf-8"))
    assert data["digests"] == {"api": None, "sidecar": IMAGE_SHA, "manifest": IMAGE_SHA}
    assert written(release) == ["baseline.json", FACTORY]


def test_a_malformed_api_digest_is_refused(release, capsys):
    release.publish(tagged=release_json(digest="md5:" + IMAGE_SHA[:32]))
    assert release.run() == 1
    assert "api" in capsys.readouterr().err
    assert_nothing_flashable(release)


def test_a_sidecar_without_a_digest_is_refused(release, capsys):
    release.publish(sidecar="not a digest\n")
    assert release.run() == 1
    assert "sidecar" in capsys.readouterr().err
    assert_nothing_flashable(release)


@pytest.mark.parametrize("tag", ["1.6.0", "v1.6", "v1.6.0-rc1", "v1.6.0\n", "v1.6.0/../x", ""])
def test_a_tag_outside_vxyz_is_refused_before_any_download(release, capsys, tag):
    release.api("repos/%s/releases/latest" % REPO, release_json(tag=tag))
    assert release.run() == 1
    assert "tag" in capsys.readouterr().err
    calls = release.calls()
    assert len(calls) == 1 and calls[0][1].endswith("releases/latest")
    assert_nothing_flashable(release)


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_a_draft_or_prerelease_answer_is_refused(release, capsys, flag):
    release.api("repos/%s/releases/latest" % REPO, release_json(**{flag: True}))
    assert release.run() == 1
    assert flag in capsys.readouterr().err
    assert_nothing_flashable(release)


def test_a_non_empty_out_is_refused_before_any_gh_call(release, capsys):
    release.out.mkdir()
    (release.out / "stale.bin").write_bytes(b"x")
    assert release.run() == 1
    assert "not empty" in capsys.readouterr().err
    assert release.calls() == []
    assert written(release) == ["stale.bin"]


def test_an_out_that_is_a_file_is_refused_before_any_gh_call(release, capsys):
    release.out.write_bytes(b"x")
    assert release.run() == 1
    assert "fetch_baseline: " in capsys.readouterr().err
    assert release.calls() == []


def test_an_existing_empty_out_is_accepted(release):
    release.out.mkdir()
    assert release.run() == 0
    assert written(release) == ["baseline.json", FACTORY]


@pytest.mark.parametrize("missing", [FACTORY, SIDECAR, MANIFEST])
def test_an_asset_missing_from_the_release_is_refused_before_the_download(release, capsys, missing):
    names = [n for n in (FACTORY, SIDECAR, MANIFEST) if n != missing]
    release.publish(tagged=release_json(names=names))
    assert release.run() == 1
    assert missing in capsys.readouterr().err
    assert not any(c[:2] == ["release", "download"] for c in release.calls())
    assert_nothing_flashable(release)


@pytest.mark.parametrize("missing", [SIDECAR, MANIFEST])
def test_an_asset_the_download_did_not_deliver_is_refused(release, capsys, missing):
    release.publish(skip=(missing,))
    assert release.run() == 1
    assert missing in capsys.readouterr().err
    assert_nothing_flashable(release)


def test_a_failing_gh_ends_the_run(release, capsys):
    (release.root / "api" / (("repos/%s/releases/latest" % REPO).replace("/", "_") + ".json")).unlink()
    assert release.run() == 1
    assert "fetch_baseline: " in capsys.readouterr().err
    assert_nothing_flashable(release)


def test_a_tagged_release_answering_with_another_tag_is_refused(release, capsys):
    release.publish(tagged=release_json(tag="v1.5.3"))
    assert release.run() == 1
    assert "tag" in capsys.readouterr().err
    assert_nothing_flashable(release)


@pytest.mark.parametrize(
    "manifest, word",
    [
        (manifest_json(chip="ESP32"), "chip"),
        (manifest_json(chip="ESP32-C6"), "chip"),
        (manifest_json(offset=4096), "offset"),
        (manifest_json(offset="0"), "offset"),
        (manifest_json(path="other.factory.bin"), "path"),
        ({"version": "3.2", "builds": []}, "manifest"),
        ({"version": "3.2", "builds": [{"chipFamily": "ESP32-S2", "parts": []}]}, "manifest"),
    ],
)
def test_a_manifest_for_another_chip_offset_or_file_is_refused(release, capsys, manifest, word):
    release.publish(manifest=manifest)
    assert release.run() == 1
    assert word in capsys.readouterr().err
    assert_nothing_flashable(release)


def test_a_manifest_that_is_not_json_is_refused(release, capsys):
    release.publish()
    (release.root / "assets" / TAG / MANIFEST).write_text("{not json", encoding="utf-8")
    assert release.run() == 1
    assert "manifest" in capsys.readouterr().err
    assert_nothing_flashable(release)


@pytest.mark.parametrize("argv_change", [("--rev", "9.9"), ("--repo", "zeroflow/wifi fancontroller"), ("--repo", "../x")])
def test_an_unknown_rev_or_a_malformed_repo_is_refused_before_any_gh_call(release, capsys, argv_change):
    flag, value = argv_change
    argv = ["fetch_baseline.py", "--repo", REPO, "--rev", "3.2", "--out", str(release.out)]
    argv[argv.index(flag) + 1] = value
    assert load_tool().main(argv) == 1
    assert "fetch_baseline: " in capsys.readouterr().err
    assert release.calls() == []


def test_the_tool_has_one_latest_call_site_and_no_shell():
    source = TOOL.read_text(encoding="utf-8")
    assert source.count("releases/latest") == 1
    assert "shell=True" not in source
    assert "os.system" not in source


def test_every_gh_call_has_a_timeout(release, monkeypatch):
    tool = load_tool()
    seen = []
    real = tool.subprocess.run

    def spy(args, **kwargs):
        seen.append((list(args), kwargs.get("timeout"), kwargs.get("shell", False)))
        return real(args, **kwargs)

    monkeypatch.setattr(tool.subprocess, "run", spy)
    argv = ["fetch_baseline.py", "--repo", REPO, "--rev", "3.2", "--out", str(release.out)]
    assert tool.main(argv) == 0
    assert len(seen) == 3
    for args, timeout, shell in seen:
        assert args[0] == "gh" and isinstance(timeout, (int, float)) and timeout > 0 and shell is False
