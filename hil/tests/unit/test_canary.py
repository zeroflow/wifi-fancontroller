"""The runner credential canary (RUN-03 as amended by D-18): it can fail on a PAT, and its
positive controls show the scanner is not blind. No test source contains a PAT-shaped
string: tokens are assembled at run time, so the canary never finds its own tests."""

import os
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest

from hil import canary

PAT_PREFIX = "github" + "_pat_"
CLASSIC_PREFIX = "gh" + "p_"
FIXED_SENTINEL = PAT_PREFIX + "S" * 82


def fake_pat(char="Z"):
    return PAT_PREFIX + char * 82


def fake_classic(char="Q"):
    return CLASSIC_PREFIX + char * 36


@pytest.fixture
def rig_dirs(tmp_path, monkeypatch):
    """A clean stand-in tree plus every path parameter of canary.run()."""
    tree = tmp_path / "tree"
    runner_temp = tree / "runner-temp"
    runner_temp.mkdir(parents=True)
    (tree / "data.txt").write_text("nothing to see here\n", encoding="utf-8")
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("25 1 0:21 / / rw - overlay overlay rw\n", encoding="utf-8")
    run_dir = tmp_path / "run-hil"
    run_dir.mkdir(mode=0o700)
    run_dir.chmod(0o700)
    etc_hil = tmp_path / "etc-hil"
    etc_hil.mkdir()
    (etc_hil / "rig.toml").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(canary, "make_sentinel", lambda: FIXED_SENTINEL)
    return types.SimpleNamespace(
        tree=tree, runner_temp=runner_temp, mountinfo=mountinfo, run_dir=run_dir, etc_hil=etc_hil,
        tmp=tmp_path,
        env={"RUNNER_ENVIRONMENT": "self-hosted", "RUNNER_TEMP": str(runner_temp), "PATH": os.environ.get("PATH", "")},
        kwargs=dict(
            scan_root=str(tree), proc_dir="/proc", skip_prefixes=(), mountinfo=str(mountinfo),
            minter_paths=(str(tmp_path / "no-hil-runner"), str(tmp_path / "no-hil-runner" / "pat"),
                          str(tmp_path / "no-hil-runner" / "mint.env")),
            run_dir=str(run_dir), etc_hil=str(etc_hil), owner_uid=os.getuid(), access=lambda _p, _m: False,
        ),
    )


def go(rig, capsys, env=None, **overrides):
    kwargs = dict(rig.kwargs)
    kwargs.update(overrides)
    code = canary.run(env=env if env is not None else rig.env, **kwargs)
    return code, capsys.readouterr().out


# ---- the clean pass and the controls ---------------------------------------------------


def test_clean_tree_passes_and_prints_the_control_line(rig_dirs, capsys):
    code, out = go(rig_dirs, capsys)
    assert code == 0, out
    assert "control hits: file 1, environ 1" in out
    assert "files with a github_pat_/ghp_ token: 0" in out
    assert "PASS" in out


def test_output_never_contains_the_sentinel_or_a_found_token(rig_dirs, capsys):
    (rig_dirs.tree / "leak.txt").write_text("token=%s\n" % fake_pat("L"), encoding="utf-8")
    code, out = go(rig_dirs, capsys)
    assert code == 1
    assert FIXED_SENTINEL not in out
    assert fake_pat("L") not in out


def test_file_with_a_pat_is_reported_by_path_and_pattern_name_not_value(rig_dirs, capsys):
    leak = rig_dirs.tree / "deep" / "dir" / "leak.env"
    leak.parent.mkdir(parents=True)
    leak.write_text("PAT=%s\n" % fake_pat("A"), encoding="utf-8")
    code, out = go(rig_dirs, capsys)
    assert code == 1
    assert "github_pat_/ghp_ token in file %s" % leak in out
    assert fake_pat("A") not in out
    assert "control hits: file 1, environ 1" in out  # the sentinel is a control, not a finding
    assert "files with a github_pat_/ghp_ token: 1" in out


def test_classic_token_is_found_too(rig_dirs, capsys):
    (rig_dirs.tree / "classic.txt").write_text(fake_classic() + "\n", encoding="utf-8")
    code, out = go(rig_dirs, capsys)
    assert code == 1 and "classic.txt" in out and fake_classic() not in out


def test_own_environment_is_scanned_by_variable_name(rig_dirs, capsys):
    env = dict(rig_dirs.env, SOME_TOKEN=fake_pat("E"))
    code, out = go(rig_dirs, capsys, env=env)
    assert code == 1
    assert "own environment variable SOME_TOKEN" in out
    assert fake_pat("E") not in out


def test_fake_proc_tree_environ_is_reported_by_pid(tmp_path):
    proc = tmp_path / "proc"
    (proc / "4242").mkdir(parents=True)
    (proc / "4242" / "environ").write_bytes(b"PATH=/usr/bin\0TOKEN=" + fake_classic().encode() + b"\0HOME=/x\0")
    (proc / "4343").mkdir()
    (proc / "4343" / "environ").write_bytes(b"PATH=/usr/bin\0")
    (proc / "self").mkdir()
    result = canary.scan_environs(str(proc), FIXED_SENTINEL)
    assert result["findings"] == [4242]
    assert result["scanned"] == 2 and result["controls"] == 0


def test_unreadable_environ_is_counted_not_a_finding(tmp_path):
    proc = tmp_path / "proc"
    (proc / "77").mkdir(parents=True)  # no environ file at all: open() fails like a hidden process
    result = canary.scan_environs(str(proc), FIXED_SENTINEL)
    assert result["unreadable"] == 1 and result["findings"] == [] and result["scanned"] == 0


def test_real_child_with_a_pat_in_its_environment_is_found_through_the_real_proc(rig_dirs, capsys):
    child = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; print('r', flush=True); time.sleep(60)"],
        env={"PATH": os.environ.get("PATH", ""), "LEAKY": fake_pat("C")},
        stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
    )
    try:
        assert child.stdout.readline().strip() == b"r"
        result = canary.scan_environs("/proc", FIXED_SENTINEL)
        assert child.pid in result["findings"]
        code, out = go(rig_dirs, capsys)
        assert code == 1 and "/proc/%d/environ" % child.pid in out
        assert fake_pat("C") not in out
    finally:
        child.kill()
        child.wait()
        child.stdout.close()


def test_positive_control_file_blind_when_the_scan_roots_exclude_the_sentinel(rig_dirs, capsys):
    elsewhere = rig_dirs.tmp / "elsewhere"
    elsewhere.mkdir()
    code, out = go(rig_dirs, capsys, scan_root=str(elsewhere))
    assert code == 1
    assert "scanner blind: file" in out
    assert "control hits: file 0" in out


def test_positive_control_environ_blind_when_the_childs_environ_is_not_scanned(rig_dirs, capsys):
    empty = rig_dirs.tmp / "empty-proc"
    empty.mkdir()
    code, out = go(rig_dirs, capsys, proc_dir=str(empty))
    assert code == 1
    assert "scanner blind: environ" in out


def test_skipped_trees_are_not_scanned_and_are_named(rig_dirs, capsys):
    hidden = rig_dirs.tree / "skipme"
    hidden.mkdir()
    (hidden / "leak.txt").write_text(fake_pat("H"), encoding="utf-8")
    code, out = go(rig_dirs, capsys, skip_prefixes=(str(hidden),))
    assert code == 0 and "skipped trees: %s" % hidden in out


def test_large_files_are_counted_by_path_prefix_not_scanned(rig_dirs, capsys):
    big = rig_dirs.tree / "big.bin"
    big.write_bytes(b"x" * 2048 + fake_pat("B").encode())
    code, out = go(rig_dirs, capsys, max_bytes=1024)
    assert code == 0, out
    assert "over 1024 bytes skipped by path prefix" in out and "x1" in out


def test_symlinks_are_not_followed(rig_dirs, capsys):
    outside = rig_dirs.tmp / "outside"
    outside.mkdir()
    (outside / "leak.txt").write_text(fake_pat("Y"), encoding="utf-8")
    (rig_dirs.tree / "link").symlink_to(outside)
    (rig_dirs.tree / "filelink").symlink_to(outside / "leak.txt")
    code, out = go(rig_dirs, capsys)
    assert code == 0, out


# ---- the minter path, the run directory and /etc/hil -----------------------------------


@pytest.mark.parametrize("make", ["dir_only", "pat", "mint_env"])
def test_minter_stand_in_that_exists_fails(rig_dirs, capsys, make):
    base = Path(rig_dirs.kwargs["minter_paths"][0])
    base.mkdir()
    if make == "pat":
        (base / "pat").write_text("x", encoding="utf-8")
    if make == "mint_env":
        (base / "mint.env").write_text("CTID=1\n", encoding="utf-8")
    code, out = go(rig_dirs, capsys)
    assert code == 1 and "minter:" in out


@pytest.mark.skipif(os.getuid() == 0, reason="root ignores directory permissions")
def test_minter_path_behind_permission_denied_is_a_finding_not_a_pass(rig_dirs, capsys):
    base = Path(rig_dirs.kwargs["minter_paths"][0])
    base.mkdir()
    (base / "pat").write_text("x", encoding="utf-8")
    base.chmod(0)
    try:
        code, out = go(rig_dirs, capsys, scan_root=str(rig_dirs.tree))
    finally:
        base.chmod(0o700)
    assert code == 1 and "PermissionError" in out


def test_mountinfo_naming_hil_runner_fails(rig_dirs, capsys):
    rig_dirs.mountinfo.write_text(
        "25 1 0:21 / / rw - overlay overlay rw\n99 25 8:1 /etc/hil-runner /etc/hil-runner ro - ext4 /dev/sda1 rw\n",
        encoding="utf-8",
    )
    code, out = go(rig_dirs, capsys)
    assert code == 1 and "line 2 names hil-runner" in out


def info(mode, uid=0, kind=stat.S_IFDIR):
    return types.SimpleNamespace(st_mode=kind | mode, st_uid=uid)


def test_run_dir_predicate():
    assert canary.run_dir_problems(info(0o700)) == []
    assert canary.run_dir_problems(None) == ["missing"]
    assert any("not owned by root" in p for p in canary.run_dir_problems(info(0o700, uid=1001)))
    for mode in (0o750, 0o705, 0o770, 0o707, 0o755, 0o701):
        assert any("permission bits" in p for p in canary.run_dir_problems(info(mode))), oct(mode)
    assert any("not a directory" in p for p in canary.run_dir_problems(info(0o700, kind=stat.S_IFREG)))


def test_missing_or_open_run_dir_fails_the_canary(rig_dirs, capsys):
    code, out = go(rig_dirs, capsys, run_dir=str(rig_dirs.tmp / "no-such-run-dir"))
    assert code == 1 and "missing" in out
    rig_dirs.run_dir.chmod(0o750)
    code, out = go(rig_dirs, capsys)
    assert code == 1 and "permission bits" in out


def test_writable_etc_hil_directory_or_file_fails(rig_dirs, capsys):
    code, out = go(rig_dirs, capsys, access=lambda p, m: True)
    assert code == 1 and "is writable by this user" in out
    target = str(rig_dirs.etc_hil / "rig.toml")
    code, out = go(rig_dirs, capsys, access=lambda p, m: p == target)
    assert code == 1 and "rig.toml is writable" in out


# ---- off the runner, and the canary does not trip on its own source ----------------------


def test_off_the_runner_it_is_skipped(rig_dirs, capsys):
    code, out = go(rig_dirs, capsys, env={"PATH": "/usr/bin"})
    assert code == 0
    assert out.strip() == "canary: canary skipped: not on the self-hosted runner"
    code, out = go(rig_dirs, capsys, env={"RUNNER_ENVIRONMENT": "github-hosted"})
    assert code == 0 and "skipped" in out


def test_no_source_file_of_the_canary_or_its_tests_matches_the_pattern():
    here = Path(__file__).resolve()
    for path in (here, here.parents[2] / "hil" / "canary.py"):
        findings, controls = canary.scan_bytes(path.read_bytes(), FIXED_SENTINEL)
        assert (findings, controls) == (0, 0), path


def test_script_mode_with_python_dash_i_runs_off_the_runner(tmp_path):
    script = Path(canary.__file__)
    proc = subprocess.run([sys.executable, "-I", str(script)], env={"PATH": os.environ.get("PATH", "")},
                          cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    assert proc.returncode == 0 and "canary skipped: not on the self-hosted runner" in proc.stdout
