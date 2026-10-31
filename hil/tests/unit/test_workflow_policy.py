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
FIRMWARE_FILES = ["hil-out/firmware.factory.bin", "hil-out/manifest.json"]
CANARY_RUN = "python3 -I hil/hil/canary.py"
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
    if not isinstance(hil.get("timeout-minutes"), int) or hil["timeout-minutes"] > 60:
        found.append("hil job timeout-minutes must be set and at most 60")
    hil_job_steps = hil.get("steps", [])
    if not all(isinstance(s.get("timeout-minutes"), int) for s in hil_job_steps):
        found.append("every hil step must set timeout-minutes")
    elif isinstance(hil.get("timeout-minutes"), int) and sum(s["timeout-minutes"] for s in hil_job_steps) >= hil["timeout-minutes"]:
        found.append("hil step timeouts must sum to less than the job timeout-minutes, or the job deadline can cut Teardown")

    for job_name, job in data["jobs"].items():
        for step in job.get("steps", []):
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
        found.append("build upload path must be exactly the two firmware files")

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
    assert set(data["jobs"]) == {"release-version", "build", "hil"}
    assert data["on"]["push"]["branches"] == list(EXPECTED_BRANCHES)
    assert data["jobs"]["hil"]["needs"] == "build"
    assert data["jobs"]["hil"]["timeout-minutes"] == 50
    names = [s["name"] for s in steps_of(data, "hil")]
    assert names.index("Runner credential canary") < names.index("Sync environment")


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


MUTATIONS = [
    add_pull_request, add_pull_request_target, add_workflow_run, add_schedule, add_dispatch_inputs,
    add_paths_ignore, add_paths, change_branches, add_a_branch, add_workflow_concurrency,
    add_job_concurrency, widen_permissions, drop_permissions, widen_firmware_upload,
    add_a_third_firmware_file, drop_environment, other_environment, hosted_runner, drop_timeout,
    huge_timeout, step_without_timeout, teardown_without_own_timeout, teardown_timeout_too_short,
    job_timeout_below_the_step_sum, drop_canary, canary_behind_sync, canary_runs_something_else,
    third_party_action_in_hil_job, expression_in_hil_run, expression_in_build_run,
    teardown_without_always, teardown_only_on_failure, teardown_without_working_directory,
    run_check_without_working_directory, logs_only_on_failure, logs_only_on_failure_or_cancelled,
    logs_without_condition, logs_without_ignore, logs_error_on_empty, logs_upload_raw_reports,
    logs_before_teardown,
]


@pytest.mark.parametrize("mutation", MUTATIONS, ids=[m.__name__ for m in MUTATIONS])
def test_every_mutation_of_the_workflow_is_caught(mutation):
    mutated = mutation(copy.deepcopy(load_workflow()))
    assert violations(mutated), "policy test did not catch %s" % mutation.__name__


def test_the_release_version_job_is_the_only_one_allowed_an_expression_in_run():
    data = load_workflow()
    assert re.search(r"\$\{\{", str(steps_of(data, "release-version"))) is not None
    assert EXPRESSION_EXEMPT_JOBS == ("release-version",)
