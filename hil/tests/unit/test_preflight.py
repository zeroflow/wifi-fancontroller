"""Preflight (HARN-05, D-43) with a fake supervisor, a fake UART tap, a fake Dut and a fake clock (no hardware)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hil import FirmwareFailure, RigError, contract, preflight
from hil import __main__ as cli

# Labels and names come from the contract, so no supervisor name literal sits in a test.
LABEL_A = contract.SERIAL_CONNECTED["A"].removesuffix(" Serial Connected")
LABEL_B = contract.SERIAL_CONNECTED["B"].removesuffix(" Serial Connected")
LINES = [n for d in "AB" for n in contract.SWITCH[d].values()]
BANNER = "ESP-ROM:esp32s2-rc4-20191025\r\nrst:0x1 (POWERON),boot:0x8 (SPI_FAST_FLASH_BOOT)\r\n"
BUILD_ID = "3.2+hil." + "a" * 12
LAST_GREEN_ID = "3.2+hil." + "b" * 12
RELEASE = "2026.11.0"
KEY = "hil-key"
V160 = SimpleNamespace(
    source="v1.6.0",
    regions=[("0x0", Path("kg.bin")), ("0x3A0000", Path("nvs.bin"))],
    psk=None,
    expected_build_id=None,
    detail="store missing",
)
LAST_GREEN = SimpleNamespace(
    source="last-green", regions=[("0x0", Path("store/x.bin"))], psk=KEY, expected_build_id=LAST_GREEN_ID, detail=""
)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class FakeSupervisor:
    """Names, line states and sensor values; a sensor value may be a function of the fake clock's time."""

    def __init__(self, clock, names=None, on=(), clients=None, watchdog=None, unreachable=False, stuck=()):
        self.clock = clock
        self.names = sorted(contract.REQUIRED_ENTITIES) if names is None else list(names)
        self.on = set(on)
        self.values = {contract.SERIAL_CLIENTS[d]: 0.0 for d in "AB"}
        self.values.update({contract.WATCHDOG_RELEASES[d]: 0.0 for d in "AB"})
        self.values.update(clients or {})
        self.values.update(watchdog or {})
        self.unreachable = unreachable
        self.stuck = set(stuck)
        self.events = []
        self.closed = False

    def connect(self):
        self.events.append("connect")
        if self.unreachable:
            raise RigError("supervisor connection failed (TimeoutError)")

    def entity_name_list(self):
        return list(self.names)

    def switch_is_on(self, name):
        return name in self.on

    def release_all(self):
        self.events.append("release_all")
        self.on -= set(LINES) - self.stuck
        if self.stuck:
            raise RigError("switch '%s' not released" % "', '".join(sorted(self.stuck)))

    def sensor_value(self, name):
        if name not in self.names:
            raise RigError("entity '%s' missing on supervisor" % name)
        value = self.values.get(name)
        return value(self.clock.t) if callable(value) else value

    def press(self, name):
        self.events.append(("press", name))

    def close(self):
        self.closed = True


class FakeTap:
    def __init__(self, clock, fail_start=False):
        self.clock = clock
        self.fail_start = fail_start
        self.buf = ""
        self.marks = {}
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        if self.fail_start:
            raise RigError("serial bridge 6638 unreachable")
        self.started = True

    def stop(self):
        self.stopped = True

    def mark(self, name):
        self.marks[name] = len(self.buf)

    def text(self, since, until=None):
        return self.buf[self.marks[since]:]


class FakeDut:
    """Each reset() takes the next boot mode from `boots` (the last one repeats):

    ok    ROM banner on the tap, the API answers in the `accepts` modes
    dark  ROM banner, no API answer (a broken image)
    none  no ROM banner at all
    A flash writes the healed image: version and accepted modes change, the flash reset boots `after_flash`.
    """

    def __init__(self, tap, accepts=(KEY,), banner=True, version=BUILD_ID, boots=None, after_flash="ok",
                 healed_version=RELEASE, healed_accepts=(None,), flash_error=None, wait_error=None):
        self.tap = tap
        self.accepts = set(accepts)
        self.boots = list(boots) if boots is not None else ["ok" if banner else "none"]
        self.mode = None
        self.version = version
        self.after_flash = after_flash
        self.healed_version = healed_version
        self.healed_accepts = healed_accepts
        self.flash_error = flash_error
        self.wait_error = wait_error
        self.resets = 0
        self.probes = []
        self.flashes = []
        self.waits = []

    def reset(self):
        self.resets += 1
        self.mode = self.boots.pop(0) if len(self.boots) > 1 else self.boots[0]
        mark = "reset_%d" % self.resets
        self.tap.mark(mark)
        if self.mode != "none":
            self.tap.buf += BANNER
        return mark

    def probe(self, psk):
        self.probes.append(psk)
        if self.mode != "ok" or psk not in self.accepts:
            raise OSError("refused")
        return SimpleNamespace(project_version=self.version)

    def flash_regions(self, regions, report_name=None):
        self.flashes.append((list(regions), report_name))
        if self.flash_error:
            raise RigError(self.flash_error)
        self.version, self.accepts, self.mode = self.healed_version, set(self.healed_accepts), self.after_flash

    def wait_api(self, noise_psk, deadline_s=90):
        self.waits.append(noise_psk)
        if self.wait_error is not None:
            raise self.wait_error
        if self.mode != "ok" or noise_psk not in self.accepts:
            raise RigError("API did not answer within %ss" % deadline_s)
        return SimpleNamespace(project_version=self.version)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HIL_REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("HIL_EXPECTED_COMMIT", "a" * 40)
    for name in ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)
    rig = SimpleNamespace(
        supervisor_host="192.0.2.10",
        supervisor_key="sv-key",
        dut_api_key=KEY,
        duts={"A": SimpleNamespace(id="A", chip="esp32s2", host="192.0.2.20")},
    )
    selected = SimpleNamespace(calls=[], result=V160)

    def select(rig_arg, dut_key, *args, **kwargs):
        selected.calls.append((rig_arg, dut_key))
        if isinstance(selected.result, Exception):
            raise selected.result
        return selected.result

    # The heal's selector is the real known_good.select in test_known_good.py; here only its result matters.
    monkeypatch.setattr(preflight, "known_good", SimpleNamespace(select=select), raising=False)
    return SimpleNamespace(tmp=tmp_path, reports=tmp_path / "reports", rig=rig, clock=Clock(), selected=selected)


def go(env, sv=None, tap_fail=False, **dut_kwargs):
    sv = sv or FakeSupervisor(env.clock)
    made = SimpleNamespace(taps=[], duts=[])

    def make_tap(port, path):
        tap = FakeTap(env.clock, fail_start=tap_fail)
        tap.port, tap.path = port, path
        made.taps.append(tap)
        return tap

    def make_dut(tap):
        dut = FakeDut(tap, **dut_kwargs)
        made.duts.append(dut)
        return dut

    ok, cause, record = preflight.run_preflight(
        env.rig, env.reports, supervisor=sv, make_tap=make_tap, make_dut=make_dut, clock=env.clock, sleep=env.clock.sleep
    )
    written = json.loads((env.reports / preflight.REPORT).read_text(encoding="utf-8"))
    return SimpleNamespace(ok=ok, cause=cause, record=record, written=written, sv=sv, made=made)


def names(out):
    return [c["name"] for c in out.record["checks"]]


# ---------------------------------------------------------------- healthy rig


def test_a_healthy_rig_passes_every_check_without_a_warning(env):
    out = go(env)
    assert (out.ok, out.cause) == (True, None)
    assert out.record["warnings"] == [] and out.record["heal"] is None
    assert names(out) == [
        "supervisor reachable",
        "contract",
        "lines released",
        "%s bridge clients" % LABEL_A,
        "%s bridge clients" % LABEL_B,
        "watchdog counters",
        "%s boot" % LABEL_A,
        "%s boot" % LABEL_B,
    ]
    assert all(c["ok"] for c in out.record["checks"][:-1])
    assert out.record["checks"][-1] == {"name": "%s boot" % LABEL_B, "ok": False, "detail": preflight.DUT_B_BOOT}
    assert out.written == out.record and out.record["schema"] == 1 and out.record["commit"] == "a" * 40
    assert out.made.duts[0].resets == 1
    assert "boot:0x8 seen, API answered (HIL key), %s" % BUILD_ID == out.record["checks"][6]["detail"]


def test_the_release_image_answers_without_encryption_and_passes(env):
    out = go(env, accepts=(None,), version="2026.11.0")
    assert out.ok
    assert "API answered (no encryption), 2026.11.0" in out.record["checks"][6]["detail"]
    assert out.made.duts[0].probes == [KEY, None]


def test_the_tap_logs_to_the_preflight_uart_file_on_bridge_6638(env):
    out = go(env)
    tap = out.made.taps[0]
    assert tap.port == contract.BRIDGE_PORT["A"]
    assert tap.path == env.reports / "raw" / "uart-preflight-dut-a.log"


def test_watchdog_counters_are_recorded_at_the_start(env):
    sv = FakeSupervisor(env.clock, watchdog={contract.WATCHDOG_RELEASES["A"]: 6.0, contract.WATCHDOG_RELEASES["B"]: 1.0})
    out = go(env, sv)
    assert out.ok and out.record["watchdog_start"] == {"A": 6, "B": 1}


def test_a_watchdog_counter_without_a_value_is_rig_error(env):
    sv = FakeSupervisor(env.clock, watchdog={contract.WATCHDOG_RELEASES["B"]: None})
    out = go(env, sv)
    assert not out.ok and out.cause == "%s has no value" % contract.WATCHDOG_RELEASES["B"]
    assert out.made.duts == []


# ---------------------------------------------------------------- fixes are warnings


def test_a_line_found_on_is_released_and_named_in_one_warning(env):
    line = contract.SWITCH["A"]["usr1"]
    sv = FakeSupervisor(env.clock, on=[line])
    out = go(env, sv)
    assert out.ok
    assert out.record["warnings"] == ["line %s was on at preflight start; released" % line]
    assert "release_all" in sv.events


def test_a_line_that_stays_on_is_rig_error_naming_it(env):
    line = contract.SWITCH["B"]["boot"]
    sv = FakeSupervisor(env.clock, on=[line], stuck=[line])
    out = go(env, sv)
    assert not out.ok and out.cause == "line not released: '%s'" % line
    assert out.made.taps == []


# ---------------------------------------------------------------- adjacency at the eviction deadline (HARN-05)


def test_a_count_of_exactly_zero_passes_at_once(env):
    out = go(env)
    assert out.record["checks"][3] == {"name": "%s bridge clients" % LABEL_A, "ok": True, "detail": "0"}
    assert env.clock.t < 1


def test_a_stray_client_evicted_after_12_s_is_a_warning(env):
    sv = FakeSupervisor(env.clock, clients={contract.SERIAL_CLIENTS["A"]: lambda t: 1.0 if t < 12 else 0.0})
    out = go(env, sv)
    assert out.ok
    assert out.record["warnings"] == ["stray bridge client on %s evicted after 12 s" % LABEL_A]


def test_a_client_evicted_just_before_the_deadline_is_still_a_warning(env):
    sv = FakeSupervisor(env.clock, clients={contract.SERIAL_CLIENTS["B"]: lambda t: 1.0 if t < 39 else 0.0})
    out = go(env, sv)
    assert out.ok and out.record["warnings"] == ["stray bridge client on %s evicted after 39 s" % LABEL_B]


def test_a_client_that_stays_past_40_s_is_rig_error_and_no_dut_check_runs(env):
    sv = FakeSupervisor(env.clock, clients={contract.SERIAL_CLIENTS["A"]: 1.0})
    out = go(env, sv)
    assert not out.ok
    assert out.cause == "%s bridge client not evicted within 40 s" % LABEL_A
    assert out.made.taps == [] and out.made.duts == []
    assert names(out)[-1] == "%s bridge clients" % LABEL_A
    assert env.clock.t == pytest.approx(preflight.EVICT_WAIT_S)


# ---------------------------------------------------------------- empty and missing values


def test_serial_clients_without_a_value_is_rig_error_not_zero(env):
    sv = FakeSupervisor(env.clock, clients={contract.SERIAL_CLIENTS["A"]: None})
    out = go(env, sv)
    assert not out.ok and out.cause == "%s has no value" % contract.SERIAL_CLIENTS["A"]
    assert out.made.taps == []


def test_a_value_lost_while_waiting_for_eviction_is_rig_error(env):
    sv = FakeSupervisor(env.clock, clients={contract.SERIAL_CLIENTS["A"]: lambda t: 1.0 if t < 3 else None})
    out = go(env, sv)
    assert not out.ok and out.cause == "%s has no value" % contract.SERIAL_CLIENTS["A"]


def test_an_empty_entity_list_is_a_contract_mismatch(env):
    sv = FakeSupervisor(env.clock, names=[])
    out = go(env, sv)
    assert not out.ok and out.cause.startswith("contract mismatch: entity '")
    assert "release_all" not in sv.events


# ---------------------------------------------------------------- ordering: the first broken check is the cause


def test_a_missing_contract_name_is_rig_error_before_any_line_is_touched(env):
    gone = contract.SERIAL_CLIENTS["B"]
    sv = FakeSupervisor(env.clock, names=sorted(contract.REQUIRED_ENTITIES - {gone}), on=[LINES[0]])
    out = go(env, sv)
    assert not out.ok and out.cause == "contract mismatch: entity '%s' missing on supervisor" % gone
    assert "release_all" not in sv.events and out.record["warnings"] == []
    assert names(out) == ["supervisor reachable", "contract"]


def test_an_unreachable_supervisor_is_rig_error_before_any_line_is_touched(env):
    sv = FakeSupervisor(env.clock, unreachable=True)
    out = go(env, sv)
    assert not out.ok and out.cause == "supervisor unreachable (TimeoutError)"
    assert sv.events == ["connect"]
    assert names(out) == ["supervisor reachable"]


def test_fixes_before_a_later_cause_stay_listed_as_warnings(env):
    line = contract.SWITCH["A"]["en"]
    sv = FakeSupervisor(env.clock, on=[line], clients={contract.SERIAL_CLIENTS["B"]: 2.0})
    out = go(env, sv)
    assert not out.ok and out.cause == "%s bridge client not evicted within 40 s" % LABEL_B
    assert out.record["warnings"] == ["line %s was on at preflight start; released" % line]


# ---------------------------------------------------------------- the boot check and the single heal (HARN-10, D-44)


def test_a_tap_that_cannot_start_is_rig_error_and_no_reset_is_pressed(env):
    out = go(env, tap_fail=True)
    assert not out.ok and out.cause.startswith("%s UART tap did not start" % LABEL_A)
    assert out.made.duts == [] and out.made.taps[0].stopped


def test_a_healthy_boot_never_heals(env):
    out = go(env)
    assert out.made.duts[0].flashes == [] and env.selected.calls == []


def test_a_boot_check_that_fails_once_and_passes_after_the_heal_is_ok_with_one_warning(env):
    out = go(env, boots=["dark", "ok"])
    dut = out.made.duts[0]
    assert (out.ok, out.cause) == (True, None)
    assert out.record["warnings"] == ["%s healed with v1.6.0 (%s)" % (LABEL_A, RELEASE)]
    heal = out.record["heal"]
    assert (heal["source"], heal["ok"]) == ("v1.6.0", True)
    assert heal["detail"] == "v1.6.0 (%s) written and confirmed" % RELEASE
    assert heal["first_failure"].endswith("did not answer within 90 s with the HIL key or without encryption")
    assert dut.flashes == [(V160.regions, "heal-flash-dut-a.json")]
    assert dut.waits == [None]
    assert env.selected.calls == [(env.rig, KEY)]
    boot = [c for c in out.record["checks"] if c["name"] == "%s boot" % LABEL_A]
    assert boot[-1]["ok"] is True


def test_a_heal_with_last_green_checks_the_stored_build_id(env):
    env.selected.result = LAST_GREEN
    out = go(env, boots=["none", "ok"], healed_version=LAST_GREEN_ID, healed_accepts=(KEY,))
    assert out.ok
    assert out.record["warnings"] == ["%s healed with last-green (%s)" % (LABEL_A, LAST_GREEN_ID)]
    assert out.made.duts[0].waits == [KEY]


def test_a_last_green_heal_that_reports_another_build_is_a_failed_heal(env):
    env.selected.result = LAST_GREEN
    out = go(env, boots=["dark", "ok"], healed_version=BUILD_ID, healed_accepts=(KEY,))
    assert not out.ok and out.cause.startswith("heal failed: ")
    assert LAST_GREEN_ID in out.cause
    assert out.record["heal"]["ok"] is False


def test_a_boot_check_that_fails_again_after_the_heal_is_rig_error_and_never_heals_twice(env):
    out = go(env, boots=["dark", "dark"])
    dut = out.made.duts[0]
    assert not out.ok and out.cause.startswith("heal failed: ")
    assert len(dut.flashes) == 1
    assert out.record["heal"]["ok"] is False and out.record["heal"]["source"] == "v1.6.0"
    assert out.record["warnings"] == []


def test_no_boot_banner_before_and_after_the_heal_is_a_failed_heal_naming_the_banner(env):
    out = go(env, banner=False)
    assert not out.ok and out.cause.startswith("heal failed: ")
    assert "no boot:0x8 within 5 s after the EN reset" in out.cause
    assert len(out.made.duts[0].flashes) == 1


def test_a_heal_whose_dut_never_answers_after_the_flash_is_a_failed_heal(env):
    out = go(env, boots=["dark"], after_flash="dark")
    assert not out.ok and out.cause.startswith("heal failed: ")
    assert len(out.made.duts[0].flashes) == 1


def test_a_heal_flash_that_fails_is_a_failed_heal(env):
    out = go(env, boots=["dark"], flash_error="flash failed after 2 attempts (timeout); last output:\nline")
    assert not out.ok and out.cause == "heal failed: flash failed after 2 attempts (timeout); last output:"


def test_a_firmware_failure_during_the_heal_is_a_failed_heal_not_a_fail_verdict(env):
    out = go(env, boots=["dark"], wait_error=FirmwareFailure("booted but its API did not answer"))
    assert not out.ok and out.cause == "heal failed: booted but its API did not answer"


def test_select_raising_is_heal_impossible_and_nothing_is_flashed(env):
    env.selected.result = RigError("known_good_image sha256 does not match known_good_sha256")
    out = go(env, boots=["dark"])
    assert not out.ok
    assert out.cause == "heal impossible: known_good_image sha256 does not match known_good_sha256"
    assert out.made.duts[0].flashes == []
    assert out.record["heal"]["ok"] is False
    assert not (env.reports / "heal-flash-dut-a.json").exists()


def test_the_dut_b_boot_line_follows_a_successful_heal(env):
    out = go(env, boots=["dark", "ok"])
    assert out.record["checks"][-1] == {"name": "%s boot" % LABEL_B, "ok": False, "detail": preflight.DUT_B_BOOT}


# ---------------------------------------------------------------- concurrency: tap and supervisor closed on every path


@pytest.mark.parametrize(
    "case",
    ["healthy", "unreachable", "stuck client", "no banner", "tap fails"],
)
def test_tap_and_supervisor_are_closed_on_every_path(env, case):
    sv = FakeSupervisor(
        env.clock,
        unreachable=case == "unreachable",
        clients={contract.SERIAL_CLIENTS["A"]: 1.0} if case == "stuck client" else None,
    )
    out = go(env, sv, tap_fail=case == "tap fails", banner=case != "no banner")
    assert sv.closed
    assert all(tap.stopped for tap in out.made.taps)
    assert (env.reports / preflight.REPORT).is_file()


# ---------------------------------------------------------------- hil preflight (CLI)


@pytest.fixture
def cli_env(env, monkeypatch):
    monkeypatch.setattr(cli, "load_rig", lambda: env.rig)
    monkeypatch.setattr(cli, "redact_reports", lambda rig: None)
    return env


def fake_run(ok, cause, warnings=(), seen=None):
    def run(rig, reports_dir, *, supervisor, make_tap, make_dut, clock=None, sleep=None):
        if seen is not None:
            seen.append(json.loads((reports_dir / "verdict.json").read_text(encoding="utf-8")))
        supervisor.close()
        record = {"schema": 1, "commit": None, "checks": [{"name": "contract", "ok": ok, "detail": cause or ""}],
                  "warnings": list(warnings), "heal": None, "watchdog_start": {}}
        return ok, cause, record
    return run


def verdict(env):
    return json.loads((env.reports / "verdict.json").read_text(encoding="utf-8"))


def test_hil_preflight_writes_rig_error_before_it_starts(cli_env, monkeypatch):
    seen = []
    monkeypatch.setattr(preflight, "run_preflight", fake_run(True, None, seen=seen))
    assert cli.main(["preflight"]) == 0
    assert seen[0]["verdict"] == "RIG ERROR" and seen[0]["reason"] == "preflight did not complete"


def test_a_killed_preflight_leaves_rig_error(cli_env, monkeypatch):
    def killed(*_a, supervisor, **_k):
        supervisor.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(preflight, "run_preflight", killed)
    with pytest.raises(KeyboardInterrupt):
        cli.main(["preflight"])
    assert verdict(cli_env)["verdict"] == "RIG ERROR"
    assert verdict(cli_env)["reason"] == "preflight did not complete"


def test_a_passed_preflight_exits_0_and_leaves_rig_error_with_the_not_started_reason(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(preflight, "run_preflight", fake_run(True, None, warnings=["a fix"]))
    assert cli.main(["preflight"]) == 0
    assert verdict(cli_env)["verdict"] == "RIG ERROR"
    assert verdict(cli_env)["reason"] == "preflight passed; the run has not started"
    out = capsys.readouterr().out
    assert "Preflight: contract: ok" in out and "WARNING: a fix" in out
    assert "HIL verdict" not in out


def test_a_preflight_cause_exits_3_with_rig_error_and_the_cause(cli_env, monkeypatch, capsys):
    monkeypatch.setattr(preflight, "run_preflight", fake_run(False, "contract mismatch: x"))
    assert cli.main(["preflight"]) == 3
    assert verdict(cli_env)["verdict"] == "RIG ERROR" and verdict(cli_env)["reason"] == "contract mismatch: x"
    out = capsys.readouterr().out
    assert "RIG ERROR: contract mismatch: x" in out and "::error" not in out


def test_under_github_actions_a_cause_is_annotated(cli_env, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(preflight, "run_preflight", fake_run(False, "contract mismatch: x"))
    assert cli.main(["preflight"]) == 3
    assert "::error title=RIG ERROR::preflight: contract mismatch: x" in capsys.readouterr().out.splitlines()


def test_warnings_and_checks_reach_the_step_summary(cli_env, monkeypatch):
    step = cli_env.tmp / "step.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    monkeypatch.setattr(preflight, "run_preflight", fake_run(True, None, warnings=["a fix"]))
    cli.main(["preflight"])
    text = step.read_text(encoding="utf-8")
    assert "Preflight: contract: ok" in text and "WARNING: a fix" in text


def test_hil_preflight_deletes_its_own_stale_outputs(cli_env, monkeypatch):
    cli_env.reports.mkdir(parents=True)
    (cli_env.reports / "raw").mkdir()
    for name in cli.PREFLIGHT_REPORTS:
        (cli_env.reports / name).write_text("old", encoding="utf-8")
    seen = []

    def run(rig, reports_dir, *, supervisor, **_k):
        seen.extend(n for n in cli.PREFLIGHT_REPORTS if (reports_dir / n).exists())
        return fake_run(True, None)(rig, reports_dir, supervisor=supervisor, make_tap=None, make_dut=None)

    monkeypatch.setattr(preflight, "run_preflight", run)
    cli.main(["preflight"])
    assert seen == []
    assert {"preflight.json", "heal-flash-dut-a.json", "watchdog.json", "raw/uart-preflight-dut-a.log"} <= set(
        cli.PREFLIGHT_REPORTS
    )


# ---------------------------------------------------------------- hil run start (WR-10)


def test_hil_run_deletes_the_earlier_final_image_teardown_flash_and_redacted_tree_but_keeps_preflight(
    cli_env, monkeypatch
):
    reports = cli_env.reports
    (reports / "redacted").mkdir(parents=True)
    (reports / "redacted" / "old.json").write_text("{}", encoding="utf-8")
    for name in ("final-image.json", "teardown-flash-dut-a.json", "preflight.json", "heal-flash-dut-a.json"):
        (reports / name).write_text("{}", encoding="utf-8")

    def stop(*_a, **_k):
        raise RigError("stop here")

    monkeypatch.setattr(cli, "load_rig", stop)
    assert cli._run({}) == 3
    assert not (reports / "final-image.json").exists()
    assert not (reports / "teardown-flash-dut-a.json").exists()
    assert not (reports / "redacted").exists()
    assert (reports / "preflight.json").exists() and (reports / "heal-flash-dut-a.json").exists()


def test_hil_preflight_prints_the_heal_with_its_first_failure(cli_env, monkeypatch, capsys):
    def run(rig, reports_dir, *, supervisor, **_k):
        supervisor.close()
        heal = {"source": "v1.6.0", "ok": True, "detail": "v1.6.0 (2026.11.0) written and confirmed",
                "first_failure": "boot check failed: y"}
        record = {"schema": 1, "commit": None, "checks": [], "warnings": ["healed"], "heal": heal,
                  "watchdog_start": {}}
        return True, None, record

    monkeypatch.setattr(preflight, "run_preflight", run)
    assert cli.main(["preflight"]) == 0
    out = capsys.readouterr().out
    assert "Preflight: heal: v1.6.0 (2026.11.0) written and confirmed (first: boot check failed: y)" in out
    assert "WARNING: healed" in out
