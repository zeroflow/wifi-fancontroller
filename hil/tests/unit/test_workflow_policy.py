"""Policy test for .github/workflows/hil.yml: the safety properties of the workflow are
locked by a test. The HIL job runs on a runner inside the LAN of a public repository, so
what triggers it, what it may read and what it uploads must not drift by accident.

Every mutation case edits an in-memory copy of the real workflow and must be caught.
The nightly schedule is CI-08 (Phase 5) and will extend the trigger set then.
"""

import copy
import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "hil.yml"
EXPECTED_BRANCHES = ("main", "claude/main")  # D-17
# The policy cap on the hil job's timeout-minutes. 03-04 Task 1: the maintainer chose cap-90
# (session 1500 s, run step 38 min) over the Phase 1 constant 60, which the Phase 3 chain cannot fit.
HIL_JOB_CAP_MINUTES = 90
# WR-07: the hil job runs only from these two refs, in the file itself. The refuse job carries
# exactly the inverse, so a run from any other ref is red instead of silently green.
HIL_GUARD = "${{ github.ref == 'refs/heads/main' || github.ref == 'refs/heads/claude/main' }}"
REFUSE_GUARD = "${{ github.ref != 'refs/heads/main' && github.ref != 'refs/heads/claude/main' }}"
REFUSE_ANNOTATION = "::error title=HIL refused::the hardware check runs only on main and claude/main; this run touched no hardware"
FIRMWARE_FILES = [
    "hil-out/firmware.factory.bin",
    "hil-out/firmware.ota.bin",
    "hil-out/qc-auto-3.2.ota.bin",
    "hil-out/canary-3.2.ota.bin",
    "hil-out/broken-3.2.ota.bin",
    "hil-out/manifest.json",
]
CANARY_RUN = "python3 -I hil/hil/canary.py"
# REG-01, T-03-22: the hosted prepare job is the only fetcher of the release baseline. It uploads exactly
# these two files, holds the only GitHub token (github.token, contents: read) in the one step that calls
# gh, and has no secret, no environment and no third-party action.
BASELINE_FILES = [
    "hil-baseline/fancontroller-r3-2-esp32s2.factory.bin",
    "hil-baseline/baseline.json",
]
BASELINE_ARTIFACT = "hil-baseline"
PREPARE_RUN = 'python3 hil/tools/fetch_baseline.py --repo "$GITHUB_REPOSITORY" --rev 3.2 --out hil-baseline'
PREPARE_TOKEN = "${{ github.token }}"
PREPARE_CAP_MINUTES = 10
# D-43, D-45: the rig checks itself right before the run step; a failed preflight (exit 3) skips the
# run step, because neither step carries an `if`, while Teardown and the upload (if: always()) still run.
PREFLIGHT_RUN = "exec .venv/bin/python -m hil preflight"
PREFLIGHT_ENV = {
    "HIL_SUPERVISOR_KEY": "${{ secrets.HIL_SUPERVISOR_KEY }}",
    "HIL_FW_DIR": "${{ github.workspace }}/hil-fw",
    "HIL_EXPECTED_COMMIT": "${{ github.sha }}",
}
HIL_STEP_NAMES = [
    "Checkout harness", "Runner credential canary", "Download firmware and manifest", "Sync environment",
    "Preflight", "Run hardware check", "Teardown", "Upload masked logs",
]
LOG_PATH = "hil/reports/redacted/"
# validate.yml's pin reader, copied verbatim on purpose, interpolates an expression in a
# run script. It runs on a GitHub-hosted runner, reads a file of this repository and has
# no secret; it is the one job exempt from the no-expression-in-run rule.
EXPRESSION_EXEMPT_JOBS = ("release-version",)


def load_workflow(text=None):
    data = yaml.safe_load(text if text is not None else WORKFLOW.read_text(encoding="utf-8"))
    if True in data:  # YAML 1.1 reads the key `on` as the boolean True
        data["on"] = data.pop(True)
    return data


def steps_of(data, job):
    return data["jobs"][job]["steps"]


def normalized_if(value):
    text = str(value).strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2]
    return "".join(text.split())


def step_named(data, job, name):
    matches = [s for s in steps_of(data, job) if s.get("name") == name]
    return matches[0] if len(matches) == 1 else None


def refuse_violations(data):
    """The hosted job that makes a run from any other ref red (T-03-35): exact inverse condition,
    hosted runner, no environment, no secret, no action, no expression in its script, a failing exit."""
    job = data["jobs"].get("refuse")
    if job is None:
        return ["job refuse is missing: a dispatch from another ref would be green without a hardware check"]
    found = []
    if normalized_if(job.get("if", "")) != normalized_if(REFUSE_GUARD):
        found.append("refuse job must carry exactly the inverse of the hil ref guard %s" % REFUSE_GUARD)
    runs_on = job.get("runs-on")
    if not isinstance(runs_on, str) or "self-hosted" in runs_on or not runs_on.startswith("ubuntu-"):
        found.append("refuse job must run on a GitHub-hosted ubuntu runner, never on the rig")
    if "environment" in job:
        found.append("refuse job must have no environment")
    if "needs" in job:
        found.append("refuse job must have no needs")
    if "secrets." in str(job):
        found.append("refuse job must not touch a secret")
    runs = []
    for step in job.get("steps", []):
        if "uses" in step:
            found.append("refuse job must not use an action")
        if "${{" in str(step.get("run", "")):
            found.append("refuse job must not put an expression inside a run script")
        runs.append(str(step.get("run", "")))
    script = "\n".join(runs)
    if REFUSE_ANNOTATION not in script:
        found.append("refuse job must print %s" % REFUSE_ANNOTATION)
    if re.search(r"^\s*exit\s+[1-9]", script, re.MULTILINE) is None:
        found.append("refuse job must exit non-zero")
    return found


def expressions_in(value, path=()):
    """(path, text) of every string under `value` that contains an expression."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from expressions_in(item, path + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from expressions_in(item, path + (index,))
    elif isinstance(value, str) and "${{" in value:
        yield path, value


def prepare_violations(data):
    """REG-01, T-03-22: the hosted prepare job fetches and verifies the release baseline. Hosted runner, no
    environment, no needs, no job permissions, no secret, first-party actions only, no expression anywhere
    except GH_TOKEN = github.token in the fetch step's env, exactly the two baseline files uploaded, and a
    timeout of at most 10 minutes. The hil job may consume hil-baseline only if it needs prepare, so a failed
    prepare job skips it (fail-closed, Pitfall 18)."""
    job = data["jobs"].get("prepare")
    if job is None:
        return ["job prepare is missing: the release baseline would have no verified source (REG-01)"]
    found = []
    runs_on = job.get("runs-on")
    if not isinstance(runs_on, str) or "self-hosted" in runs_on or not runs_on.startswith("ubuntu-"):
        found.append("prepare job must run on a GitHub-hosted ubuntu runner, never on the rig")
    for key in ("environment", "needs", "permissions", "env", "container", "services"):
        if key in job:
            found.append("prepare job must have no %s" % key)
    if "secrets." in str(job):
        found.append("prepare job must not touch a secret")
    if not isinstance(job.get("timeout-minutes"), int) or job["timeout-minutes"] > PREPARE_CAP_MINUTES:
        found.append("prepare job timeout-minutes must be set and at most %d" % PREPARE_CAP_MINUTES)
    steps = job.get("steps", [])
    fetch = [i for i, step in enumerate(steps) if str(step.get("run", "")).strip() == PREPARE_RUN]
    if len(fetch) != 1:
        found.append("prepare job must have exactly one step running %s" % PREPARE_RUN)
    for path, text in expressions_in(job):
        allowed = (len(fetch) == 1 and path == ("steps", fetch[0], "env", "GH_TOKEN")
                   and text.strip() == PREPARE_TOKEN)
        if not allowed:
            found.append("prepare job may hold no expression but GH_TOKEN: %s in the fetch step (found at %s)"
                         % (PREPARE_TOKEN, ".".join(str(p) for p in path)))
    if len(fetch) == 1 and steps[fetch[0]].get("env") != {"GH_TOKEN": PREPARE_TOKEN}:
        found.append("the fetch step env must be exactly GH_TOKEN: %s" % PREPARE_TOKEN)
    for step in steps:
        uses = step.get("uses")
        if uses is not None and not str(uses).startswith("actions/"):
            found.append("prepare job uses a non-actions/ action: %s" % uses)
        if "${{" in str(step.get("run", "")):
            found.append("prepare job must not put an expression inside a run script")
    uploads = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    if len(uploads) != 1:
        found.append("prepare job must have exactly one upload-artifact step")
    else:
        options = uploads[0].get("with", {})
        paths = [line.strip() for line in str(options.get("path", "")).splitlines() if line.strip()]
        if paths != BASELINE_FILES:
            found.append("prepare upload path must be exactly the two baseline files %s" % BASELINE_FILES)
        if options.get("name") != BASELINE_ARTIFACT:
            found.append("prepare upload must be named %s" % BASELINE_ARTIFACT)
        if options.get("if-no-files-found") != "error":
            found.append("prepare upload must set if-no-files-found: error")
    for step in steps_of(data, "hil"):
        if str(step.get("uses", "")).startswith("actions/download-artifact@") and \
                step.get("with", {}).get("name") == BASELINE_ARTIFACT:
            needs = data["jobs"]["hil"].get("needs", [])
            if "prepare" not in (needs if isinstance(needs, list) else [needs]):
                found.append("the hil job downloads %s but does not need prepare (fail-closed)" % BASELINE_ARTIFACT)
    return found


def preflight_violations(data):
    """D-43, D-45: Preflight sits right after Sync environment and right before Run hardware check, runs
    `hil preflight` from hil/ with the run step's environment, and neither step has an `if`, so a red
    preflight skips the run step and nothing can run it anyway."""
    names = [s.get("name") for s in steps_of(data, "hil")]
    step = step_named(data, "hil", "Preflight")
    if step is None:
        return ["hil job has no single Preflight step (D-43)"]
    found = []
    at = names.index("Preflight")
    if at == 0 or names[at - 1] != "Sync environment" or at + 1 >= len(names) or names[at + 1] != "Run hardware check":
        found.append("Preflight must sit between Sync environment and Run hardware check")
    if str(step.get("run", "")).strip() != PREFLIGHT_RUN:
        found.append("Preflight must run exactly %s" % PREFLIGHT_RUN)
    if step.get("working-directory") != "hil":
        found.append("Preflight must run with working-directory: hil")
    if step.get("env") != PREFLIGHT_ENV:
        found.append("Preflight env must be exactly %s" % sorted(PREFLIGHT_ENV))
    run = step_named(data, "hil", "Run hardware check")
    for checked in (step, run):
        if checked is not None and "if" in checked:
            found.append("step %r must have no if: a failed preflight must skip the run step" % checked.get("name"))
    return found


def violations(data):
    """Every policy violation of a parsed workflow, as short messages."""
    found = []
    trigger = data.get("on")
    if not isinstance(trigger, dict) or set(trigger) != {"push", "workflow_dispatch"}:
        found.append("triggers must be exactly push and workflow_dispatch")
        return found
    push = trigger["push"] or {}
    if set(push) != {"branches"}:
        found.append("push must have exactly the key branches (no paths or paths-ignore filter)")
    if "paths" in push or "paths-ignore" in push:
        found.append("push must not filter paths: every push gets a check")
    if list(push.get("branches", [])) != list(EXPECTED_BRANCHES):
        found.append("push branches must be exactly %s" % (list(EXPECTED_BRANCHES),))
    dispatch = trigger["workflow_dispatch"]
    if dispatch not in (None, {}):
        found.append("workflow_dispatch must have no inputs")
    if data.get("permissions") != {"contents": "read"}:
        found.append("top-level permissions must be exactly contents: read")
    if "concurrency" in data or any("concurrency" in job for job in data["jobs"].values()):
        found.append("no concurrency key at workflow or job level")

    hil = data["jobs"].get("hil")
    if hil is None:
        return found + ["job hil is missing"]
    runs_on = hil.get("runs-on")
    labels = runs_on if isinstance(runs_on, list) else [runs_on]
    if "self-hosted" not in labels or "hil" not in labels:
        found.append("hil job must run on [self-hosted, hil]")
    environment = hil.get("environment")
    if (environment.get("name") if isinstance(environment, dict) else environment) != "hil":
        found.append("hil job must use environment hil")
    if not isinstance(hil.get("timeout-minutes"), int) or hil["timeout-minutes"] > HIL_JOB_CAP_MINUTES:
        found.append("hil job timeout-minutes must be set and at most %d" % HIL_JOB_CAP_MINUTES)
    if normalized_if(hil.get("if", "")) != normalized_if(HIL_GUARD):
        found.append("hil job must carry exactly the ref guard %s (WR-07)" % HIL_GUARD)
    hil_job_steps = hil.get("steps", [])
    if not all(isinstance(s.get("timeout-minutes"), int) for s in hil_job_steps):
        found.append("every hil step must set timeout-minutes")
    elif isinstance(hil.get("timeout-minutes"), int) and sum(s["timeout-minutes"] for s in hil_job_steps) >= hil["timeout-minutes"]:
        found.append("hil step timeouts must sum to less than the job timeout-minutes, or the job deadline can cut Teardown")

    found.extend(refuse_violations(data))
    found.extend(prepare_violations(data))

    for job_name, job in data["jobs"].items():
        if "continue-on-error" in job:
            found.append("job %s must not set continue-on-error (D-45)" % job_name)
        for step in job.get("steps", []):
            if "continue-on-error" in step:
                found.append("job %s step %r must not set continue-on-error (D-45)" % (job_name, step.get("name")))
            uses = step.get("uses")
            if uses is not None and not str(uses).startswith("actions/"):
                found.append("job %s uses a non-actions/ action: %s" % (job_name, uses))
            if job_name not in EXPRESSION_EXEMPT_JOBS and "${{" in str(step.get("run", "")):
                found.append("job %s step %r puts an expression inside a run script" % (job_name, step.get("name")))

    steps = steps_of(data, "hil")
    if not steps or not str(steps[0].get("uses", "")).startswith("actions/checkout@"):
        found.append("the first hil step must be actions/checkout")
    canary = steps[1] if len(steps) > 1 else {}
    if canary.get("name") != "Runner credential canary" or str(canary.get("run", "")).strip() != CANARY_RUN:
        found.append("the step right after checkout must be 'Runner credential canary' running %s" % CANARY_RUN)

    found.extend(preflight_violations(data))

    teardown = step_named(data, "hil", "Teardown")
    if teardown is None:
        found.append("hil job has no Teardown step")
    elif normalized_if(teardown.get("if", "")) != "always()":
        found.append("Teardown must have if: always()")
    if teardown is not None and (not isinstance(teardown.get("timeout-minutes"), int) or teardown["timeout-minutes"] < 10):
        found.append("Teardown must have its own timeout-minutes of at least 10 (its worst case is about 14 minutes)")

    venv_steps = [s for s in steps if ".venv" in str(s.get("run", ""))]
    if len(venv_steps) < 2:
        found.append("expected at least two hil steps that invoke .venv")
    for step in venv_steps:
        if step.get("working-directory") != "hil":
            found.append("step %r invokes .venv without working-directory: hil" % step.get("name"))

    uploads = [s for s in steps_of(data, "build") if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    if len(uploads) != 1:
        found.append("build job must have exactly one upload-artifact step")
    elif [line.strip() for line in str(uploads[0].get("with", {}).get("path", "")).splitlines() if line.strip()] != FIRMWARE_FILES:
        found.append("build upload path must be exactly the six firmware files")

    last = steps[-1] if steps else {}
    if last.get("name") != "Upload masked logs":
        found.append("the last hil step must be 'Upload masked logs'")
    else:
        if normalized_if(last.get("if", "")) != "always()":
            found.append("Upload masked logs must have if: always()")
        options = last.get("with", {})
        if options.get("if-no-files-found") != "ignore":
            found.append("Upload masked logs must set if-no-files-found: ignore")
        if str(options.get("path", "")).strip() != LOG_PATH:
            found.append("Upload masked logs path must be exactly %s" % LOG_PATH)
        if teardown is not None and steps.index(teardown) > len(steps) - 2:
            found.append("Upload masked logs must come after Teardown")
    return found


def test_the_real_workflow_satisfies_the_policy():
    assert violations(load_workflow()) == []


def test_the_real_workflow_has_the_expected_shape():
    data = load_workflow()
    assert set(data["jobs"]) == {"release-version", "build", "prepare", "hil", "refuse"}
    assert data["on"]["push"]["branches"] == list(EXPECTED_BRANCHES)
    assert data["jobs"]["hil"]["needs"] == "build"
    assert data["jobs"]["build"]["timeout-minutes"] == 40
    build_run = next(s for s in steps_of(data, "build") if s.get("name") == "Build image and manifest")["run"]
    assert "build_image.py --all --out hil-out" in build_run
    assert data["jobs"]["hil"]["timeout-minutes"] == 86 <= HIL_JOB_CAP_MINUTES
    assert data["jobs"]["hil"]["if"] == HIL_GUARD
    assert data["jobs"]["refuse"]["if"] == REFUSE_GUARD
    assert data["jobs"]["refuse"]["runs-on"] == "ubuntu-latest"
    names = [s["name"] for s in steps_of(data, "hil")]
    assert names.index("Runner credential canary") < names.index("Sync environment")
    assert names == HIL_STEP_NAMES
    preflight = step_named(data, "hil", "Preflight")
    assert preflight["env"] == PREFLIGHT_ENV and preflight["timeout-minutes"] == 14
    assert step_named(data, "hil", "Run hardware check")["env"] == PREFLIGHT_ENV
    prepare = data["jobs"]["prepare"]
    assert prepare["runs-on"] == "ubuntu-latest" and prepare["timeout-minutes"] == 10
    assert [s.get("uses", "run") for s in prepare["steps"]] == [
        "actions/checkout@v7", "run", "actions/upload-artifact@v7"]
    assert prepare["steps"][0]["with"] == {"persist-credentials": False, "sparse-checkout": "hil/tools"}
    assert prepare["steps"][1]["run"].strip() == PREPARE_RUN
    assert prepare["steps"][1]["env"] == {"GH_TOKEN": PREPARE_TOKEN}
    assert prepare["steps"][2]["with"]["retention-days"] == 7
    # Until 03-14 wires it, the hil job neither needs prepare nor downloads hil-baseline.
    assert not any(s.get("with", {}).get("name") == BASELINE_ARTIFACT for s in steps_of(data, "hil"))


def test_a_wrapped_always_condition_is_accepted():
    data = load_workflow()
    step_named(data, "hil", "Upload masked logs")["if"] = "${{ always() }}"
    step_named(data, "hil", "Teardown")["if"] = " ${{always()}} "
    assert violations(data) == []


def mutate(function):
    def apply(data):
        function(data)
        return data
    apply.__name__ = function.__name__
    return apply


def hil_steps(data):
    return steps_of(data, "hil")


@mutate
def add_pull_request(d):
    d["on"]["pull_request"] = {"branches": ["main"]}


@mutate
def add_pull_request_target(d):
    d["on"]["pull_request_target"] = None


@mutate
def add_workflow_run(d):
    d["on"]["workflow_run"] = {"workflows": ["Validate"]}


@mutate
def add_schedule(d):
    d["on"]["schedule"] = [{"cron": "0 3 * * *"}]


@mutate
def add_dispatch_inputs(d):
    d["on"]["workflow_dispatch"] = {"inputs": {"firmware_url": {"type": "string"}}}


@mutate
def add_paths_ignore(d):
    d["on"]["push"]["paths-ignore"] = ["**/*.md"]


@mutate
def add_paths(d):
    d["on"]["push"]["paths"] = ["hil/**"]


@mutate
def change_branches(d):
    d["on"]["push"]["branches"] = ["main", "claude-main"]


@mutate
def add_a_branch(d):
    d["on"]["push"]["branches"] = ["main", "claude/main", "dev"]


@mutate
def add_workflow_concurrency(d):
    d["concurrency"] = {"group": "hil", "cancel-in-progress": True}


@mutate
def add_job_concurrency(d):
    d["jobs"]["hil"]["concurrency"] = "hil"


@mutate
def widen_permissions(d):
    d["permissions"] = {"contents": "write"}


@mutate
def drop_permissions(d):
    del d["permissions"]


@mutate
def widen_firmware_upload(d):
    for step in steps_of(d, "build"):
        if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
            step["with"]["path"] = "hil-out/\n"


@mutate
def add_a_third_firmware_file(d):
    for step in steps_of(d, "build"):
        if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
            step["with"]["path"] += "hil-out/extra.bin\n"


@mutate
def drop_the_broken_firmware_file(d):
    for step in steps_of(d, "build"):
        if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
            step["with"]["path"] = step["with"]["path"].replace("hil-out/broken-3.2.ota.bin\n", "")


@mutate
def add_a_seventh_firmware_file(d):
    for step in steps_of(d, "build"):
        if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
            step["with"]["path"] += "hil-out/extra.bin\n"


@mutate
def drop_environment(d):
    del d["jobs"]["hil"]["environment"]


@mutate
def other_environment(d):
    d["jobs"]["hil"]["environment"] = "production"


@mutate
def hosted_runner(d):
    d["jobs"]["hil"]["runs-on"] = "ubuntu-latest"


@mutate
def drop_timeout(d):
    del d["jobs"]["hil"]["timeout-minutes"]


@mutate
def huge_timeout(d):
    d["jobs"]["hil"]["timeout-minutes"] = 360


@mutate
def step_without_timeout(d):
    del next(s for s in hil_steps(d) if s.get("name") == "Run hardware check")["timeout-minutes"]


@mutate
def teardown_without_own_timeout(d):
    del next(s for s in hil_steps(d) if s.get("name") == "Teardown")["timeout-minutes"]


@mutate
def teardown_timeout_too_short(d):
    next(s for s in hil_steps(d) if s.get("name") == "Teardown")["timeout-minutes"] = 5


@mutate
def job_timeout_below_the_step_sum(d):
    d["jobs"]["hil"]["timeout-minutes"] = 25


@mutate
def job_timeout_equal_to_the_step_sum(d):
    d["jobs"]["hil"]["timeout-minutes"] = sum(s["timeout-minutes"] for s in hil_steps(d))


@mutate
def job_timeout_one_above_the_cap(d):
    d["jobs"]["hil"]["timeout-minutes"] = HIL_JOB_CAP_MINUTES + 1


@mutate
def remove_the_ref_guard(d):
    del d["jobs"]["hil"]["if"]


@mutate
def widen_the_ref_guard(d):
    d["jobs"]["hil"]["if"] = "${{ github.ref == 'refs/heads/main' || github.ref == 'refs/heads/dev' }}"


@mutate
def ref_guard_always(d):
    d["jobs"]["hil"]["if"] = "${{ always() }}"


@mutate
def remove_the_refuse_job(d):
    del d["jobs"]["refuse"]


@mutate
def refuse_condition_false(d):
    d["jobs"]["refuse"]["if"] = False


@mutate
def refuse_condition_not_the_inverse(d):
    d["jobs"]["refuse"]["if"] = "${{ github.ref != 'refs/heads/main' }}"


@mutate
def refuse_on_the_rig(d):
    d["jobs"]["refuse"]["runs-on"] = ["self-hosted", "hil"]


@mutate
def refuse_gains_the_environment(d):
    d["jobs"]["refuse"]["environment"] = "hil"


@mutate
def refuse_gains_a_secret(d):
    d["jobs"]["refuse"]["steps"][0]["env"] = {"HIL_SUPERVISOR_KEY": "${{ secrets.HIL_SUPERVISOR_KEY }}"}


@mutate
def refuse_gains_an_action(d):
    d["jobs"]["refuse"]["steps"].insert(0, {"name": "Checkout", "uses": "actions/checkout@v7"})


@mutate
def refuse_exits_green(d):
    d["jobs"]["refuse"]["steps"][0]["run"] = "echo \"%s\"\nexit 0\n" % REFUSE_ANNOTATION


@mutate
def continue_on_error_on_the_run_step(d):
    next(s for s in hil_steps(d) if s.get("name") == "Run hardware check")["continue-on-error"] = True


@mutate
def continue_on_error_on_the_hil_job(d):
    d["jobs"]["hil"]["continue-on-error"] = True


@mutate
def continue_on_error_on_the_refuse_job(d):
    d["jobs"]["refuse"]["continue-on-error"] = True


@mutate
def drop_canary(d):
    d["jobs"]["hil"]["steps"] = [s for s in d["jobs"]["hil"]["steps"] if s.get("name") != "Runner credential canary"]


@mutate
def canary_behind_sync(d):
    steps = hil_steps(d)
    canary = next(s for s in steps if s.get("name") == "Runner credential canary")
    steps.remove(canary)
    steps.insert([s.get("name") for s in steps].index("Sync environment") + 1, canary)


@mutate
def canary_runs_something_else(d):
    next(s for s in hil_steps(d) if s.get("name") == "Runner credential canary")["run"] = "python3 hil/hil/canary.py"


@mutate
def third_party_action_in_hil_job(d):
    hil_steps(d).insert(1, {"name": "Setup", "uses": "astral-sh/setup-uv@v5"})


@mutate
def expression_in_hil_run(d):
    next(s for s in hil_steps(d) if s.get("name") == "Sync environment")["run"] = "echo ${{ github.event.head_commit.message }}"


@mutate
def expression_in_build_run(d):
    next(s for s in steps_of(d, "build") if s.get("name") == "Check harness pins")["run"] = "echo ${{ github.sha }}"


@mutate
def teardown_without_always(d):
    del next(s for s in hil_steps(d) if s.get("name") == "Teardown")["if"]


@mutate
def teardown_only_on_failure(d):
    next(s for s in hil_steps(d) if s.get("name") == "Teardown")["if"] = "failure()"


@mutate
def teardown_without_working_directory(d):
    del next(s for s in hil_steps(d) if s.get("name") == "Teardown")["working-directory"]


@mutate
def run_check_without_working_directory(d):
    del next(s for s in hil_steps(d) if s.get("name") == "Run hardware check")["working-directory"]


@mutate
def logs_only_on_failure(d):
    next(s for s in hil_steps(d) if s.get("name") == "Upload masked logs")["if"] = "failure()"


@mutate
def logs_only_on_failure_or_cancelled(d):
    next(s for s in hil_steps(d) if s.get("name") == "Upload masked logs")["if"] = "failure() || cancelled()"


@mutate
def logs_without_condition(d):
    del next(s for s in hil_steps(d) if s.get("name") == "Upload masked logs")["if"]


@mutate
def logs_without_ignore(d):
    del next(s for s in hil_steps(d) if s.get("name") == "Upload masked logs")["with"]["if-no-files-found"]


@mutate
def logs_error_on_empty(d):
    next(s for s in hil_steps(d) if s.get("name") == "Upload masked logs")["with"]["if-no-files-found"] = "error"


@mutate
def logs_upload_raw_reports(d):
    next(s for s in hil_steps(d) if s.get("name") == "Upload masked logs")["with"]["path"] = "hil/reports/"


@mutate
def logs_before_teardown(d):
    steps = hil_steps(d)
    logs = next(s for s in steps if s.get("name") == "Upload masked logs")
    steps.remove(logs)
    steps.insert([s.get("name") for s in steps].index("Teardown"), logs)


@mutate
def drop_preflight(d):
    d["jobs"]["hil"]["steps"] = [s for s in hil_steps(d) if s.get("name") != "Preflight"]


@mutate
def preflight_after_the_run_step(d):
    steps = hil_steps(d)
    step = next(s for s in steps if s.get("name") == "Preflight")
    steps.remove(step)
    steps.insert([s.get("name") for s in steps].index("Run hardware check") + 1, step)


@mutate
def preflight_before_sync(d):
    steps = hil_steps(d)
    step = next(s for s in steps if s.get("name") == "Preflight")
    steps.remove(step)
    steps.insert([s.get("name") for s in steps].index("Sync environment"), step)


@mutate
def preflight_continue_on_error(d):
    next(s for s in hil_steps(d) if s.get("name") == "Preflight")["continue-on-error"] = True


@mutate
def run_step_after_a_failed_preflight(d):
    next(s for s in hil_steps(d) if s.get("name") == "Run hardware check")["if"] = "always()"


@mutate
def preflight_without_the_key(d):
    del next(s for s in hil_steps(d) if s.get("name") == "Preflight")["env"]["HIL_SUPERVISOR_KEY"]


@mutate
def preflight_runs_something_else(d):
    next(s for s in hil_steps(d) if s.get("name") == "Preflight")["run"] = "exec .venv/bin/python -m hil status"


@mutate
def preflight_without_working_directory(d):
    del next(s for s in hil_steps(d) if s.get("name") == "Preflight")["working-directory"]


def prepare_steps(data):
    return steps_of(data, "prepare")


def prepare_fetch(data):
    return next(s for s in prepare_steps(data) if str(s.get("run", "")).strip() == PREPARE_RUN)


def prepare_upload(data):
    return next(s for s in prepare_steps(data) if str(s.get("uses", "")).startswith("actions/upload-artifact@"))


@mutate
def prepare_gains_a_secret(d):
    prepare_fetch(d)["env"]["HIL_SUPERVISOR_KEY"] = "${{ secrets.HIL_SUPERVISOR_KEY }}"


@mutate
def prepare_on_the_rig(d):
    d["jobs"]["prepare"]["runs-on"] = ["self-hosted", "hil"]


@mutate
def prepare_uses_a_third_party_action(d):
    prepare_steps(d).insert(1, {"name": "Setup gh", "uses": "cli/gh-action@v1"})


@mutate
def prepare_expression_in_run(d):
    prepare_fetch(d)["run"] = PREPARE_RUN.replace('"$GITHUB_REPOSITORY"', "${{ github.repository }}")


@mutate
def prepare_uploads_another_path(d):
    prepare_upload(d)["with"]["path"] += "hil-baseline/fancontroller-r3-2.manifest.json\n"


@mutate
def prepare_uploads_the_whole_directory(d):
    prepare_upload(d)["with"]["path"] = "hil-baseline/\n"


@mutate
def prepare_gains_the_environment(d):
    d["jobs"]["prepare"]["environment"] = "hil"


@mutate
def prepare_gains_write_permissions(d):
    d["jobs"]["prepare"]["permissions"] = {"contents": "write"}


@mutate
def prepare_token_in_the_checkout(d):
    prepare_steps(d)[0]["with"]["token"] = "${{ github.token }}"


@mutate
def prepare_token_at_job_level(d):
    d["jobs"]["prepare"]["env"] = {"GH_TOKEN": "${{ github.token }}"}


@mutate
def prepare_token_is_a_pat(d):
    prepare_fetch(d)["env"]["GH_TOKEN"] = "${{ secrets.RELEASE_PAT }}"


@mutate
def prepare_without_timeout(d):
    del d["jobs"]["prepare"]["timeout-minutes"]


@mutate
def prepare_timeout_above_ten(d):
    d["jobs"]["prepare"]["timeout-minutes"] = 11


@mutate
def prepare_upload_tolerates_missing_files(d):
    prepare_upload(d)["with"]["if-no-files-found"] = "warn"


@mutate
def remove_the_prepare_job(d):
    del d["jobs"]["prepare"]


@mutate
def hil_downloads_the_baseline_without_needing_prepare(d):
    hil_steps(d).insert(3, {"name": "Download release baseline", "uses": "actions/download-artifact@v8",
                            "timeout-minutes": 1, "with": {"name": BASELINE_ARTIFACT, "path": "hil-baseline"}})


MUTATIONS = [
    add_pull_request, add_pull_request_target, add_workflow_run, add_schedule, add_dispatch_inputs,
    add_paths_ignore, add_paths, change_branches, add_a_branch, add_workflow_concurrency,
    add_job_concurrency, widen_permissions, drop_permissions, widen_firmware_upload,
    add_a_third_firmware_file, drop_the_broken_firmware_file, add_a_seventh_firmware_file,
    drop_environment, other_environment, hosted_runner, drop_timeout,
    huge_timeout, step_without_timeout, teardown_without_own_timeout, teardown_timeout_too_short,
    job_timeout_below_the_step_sum, job_timeout_equal_to_the_step_sum, job_timeout_one_above_the_cap,
    remove_the_ref_guard, widen_the_ref_guard, ref_guard_always, remove_the_refuse_job,
    refuse_condition_false, refuse_condition_not_the_inverse, refuse_on_the_rig,
    refuse_gains_the_environment, refuse_gains_a_secret, refuse_gains_an_action, refuse_exits_green,
    continue_on_error_on_the_run_step, continue_on_error_on_the_hil_job,
    continue_on_error_on_the_refuse_job,
    drop_canary, canary_behind_sync, canary_runs_something_else,
    third_party_action_in_hil_job, expression_in_hil_run, expression_in_build_run,
    teardown_without_always, teardown_only_on_failure, teardown_without_working_directory,
    run_check_without_working_directory, logs_only_on_failure, logs_only_on_failure_or_cancelled,
    logs_without_condition, logs_without_ignore, logs_error_on_empty, logs_upload_raw_reports,
    logs_before_teardown,
    drop_preflight, preflight_after_the_run_step, preflight_before_sync, preflight_continue_on_error,
    run_step_after_a_failed_preflight, preflight_without_the_key, preflight_runs_something_else,
    preflight_without_working_directory,
    prepare_gains_a_secret, prepare_on_the_rig, prepare_uses_a_third_party_action, prepare_expression_in_run,
    prepare_uploads_another_path, prepare_uploads_the_whole_directory, prepare_gains_the_environment,
    prepare_gains_write_permissions, prepare_token_in_the_checkout, prepare_token_at_job_level,
    prepare_token_is_a_pat, prepare_without_timeout, prepare_timeout_above_ten,
    prepare_upload_tolerates_missing_files, remove_the_prepare_job,
    hil_downloads_the_baseline_without_needing_prepare,
]


@pytest.mark.parametrize("mutation", MUTATIONS, ids=[m.__name__ for m in MUTATIONS])
def test_every_mutation_of_the_workflow_is_caught(mutation):
    mutated = mutation(copy.deepcopy(load_workflow()))
    assert violations(mutated), "policy test did not catch %s" % mutation.__name__


def test_the_hil_job_may_download_the_baseline_once_it_needs_prepare():
    """The 03-14 shape: needs [build, prepare] plus the download; the fail-closed rule then holds."""
    data = hil_downloads_the_baseline_without_needing_prepare(copy.deepcopy(load_workflow()))
    data["jobs"]["hil"]["needs"] = ["build", "prepare"]
    assert prepare_violations(data) == []


def test_each_prepare_mutation_is_caught_by_the_prepare_rules():
    for mutation in (prepare_gains_a_secret, prepare_on_the_rig, prepare_uses_a_third_party_action,
                     prepare_expression_in_run, prepare_uploads_another_path):
        assert prepare_violations(mutation(copy.deepcopy(load_workflow()))), mutation.__name__


def test_the_release_version_job_is_the_only_one_allowed_an_expression_in_run():
    data = load_workflow()
    assert re.search(r"\$\{\{", str(steps_of(data, "release-version"))) is not None
    assert EXPRESSION_EXEMPT_JOBS == ("release-version",)
