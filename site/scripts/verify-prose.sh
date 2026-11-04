#!/usr/bin/env bash
# verify-prose.sh - docs prose lint harness (Phase 22)
#
# Lints the BUILT site (site/dist) with a pinned Vale image and checks the
# lint's own data files. Run from anywhere inside the repository:
#   npm --prefix site run build
#   bash site/scripts/verify-prose.sh [flags]
#
# Flags (no flag runs --test --lint --selftest --map --pin):
#   --test          vale test cases of the own styles, with coverage
#   --lint          lint the built pages, ratchet report, exit code
#   --selftest      plant a dash in a clean page and prove the exit code flips
#   --map           page to tier map, generated config and ratchet list checks
#   --pin           supply chain checks (single pinned image, no packages)
#   --write-config  regenerate the per-tier sections of site/.vale.ini and exit
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# The only place the Vale version is written down (decision D-11).
VALE_IMAGE="jdkato/vale:v3.26.0"

PY=(python3 -I site/scripts/prose-lint.py)
PASS_COUNT=0
FAIL_COUNT=0

pass() {
  echo "PASS: $1"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  echo "FAIL: $1"
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

usage() {
  cat >&2 <<'USAGE'
Usage: bash site/scripts/verify-prose.sh [--test] [--lint] [--selftest] [--map] [--pin] [--write-config]
  No flag runs --test --lint --selftest --map --pin.
USAGE
}

# Run the pinned Vale image against the repository (read-only, current user).
# Extra docker arguments, for example a mount, come from the VALE_EXTRA array.
# No time-limit wrapper around docker: it leaks containers. The CI job limit
# bounds the run.
VALE_EXTRA=()
vale() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/repo:ro \
    ${VALE_EXTRA[@]+"${VALE_EXTRA[@]}"} -w /repo/site "$VALE_IMAGE" "$@"
}

need_dist() {
  if [[ ! -d site/dist ]]; then
    echo "FAIL: site/dist not found - run \`npm --prefix site run build\` first"
    exit 1
  fi
}

# ─── Argument parsing ────────────────────────────────────────────────────────

RUN_TEST=false
RUN_LINT=false
RUN_SELFTEST=false
RUN_MAP=false
RUN_PIN=false
RUN_WRITE=false
ANY=false

for arg in "$@"; do
  case "$arg" in
    --test) RUN_TEST=true ;;
    --lint) RUN_LINT=true ;;
    --selftest) RUN_SELFTEST=true ;;
    --map) RUN_MAP=true ;;
    --pin) RUN_PIN=true ;;
    --write-config) RUN_WRITE=true ;;
    *)
      echo "Unknown flag: $arg" >&2
      usage
      exit 2
      ;;
  esac
  ANY=true
done

if [[ "$ANY" == "false" ]]; then
  RUN_TEST=true
  RUN_LINT=true
  RUN_SELFTEST=true
  RUN_MAP=true
  RUN_PIN=true
fi

if [[ "$RUN_WRITE" == "true" ]]; then
  "${PY[@]}" config --write
  exit 0
fi

echo "=== Docs prose lint ($VALE_IMAGE) ==="
echo ""

# ─── --test ──────────────────────────────────────────────────────────────────

run_test() {
  local out rc=0
  out=$(vale test --coverage .vale/styles/DocsEN .vale/styles/DocsDE 2>&1) || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    pass "test: $(echo "$out" | tail -n 1 | sed "s/^ *//; s/ $(printf '\342\200\224') /, /")"
  else
    echo "$out"
    fail "test: vale test reported failing or uncovered cases (exit $rc)"
  fi
}

# ─── --lint ──────────────────────────────────────────────────────────────────

# Lint the given dist pages (paths relative to site/) and print the report.
# Usage: lint_pages <dist-root-for-snippets> <report-extra-args...> -- <pages...>
lint_pages() {
  local snippet_root="$1"
  shift
  local -a extra=()
  while [[ "$1" != "--" ]]; do
    extra+=("$1")
    shift
  done
  shift
  local json err vale_rc=0 report_rc=0
  json=$(mktemp)
  err=$(mktemp)
  # Vale's own exit code is informational: the report decides pass or fail.
  vale --output=JSON "$@" >"$json" 2>"$err" || vale_rc=$?
  "${PY[@]}" report "$json" --dist "$snippet_root" ${extra[@]+"${extra[@]}"} || report_rc=$?
  if [[ "$report_rc" -ne 0 && -s "$err" ]]; then
    echo "--- Vale stderr ---"
    cat "$err"
  fi
  rm -f "$json" "$err"
  return "$report_rc"
}

run_lint() {
  need_dist
  local stale_rc=0
  "${PY[@]}" config --check || stale_rc=$?
  if [[ "$stale_rc" -ne 0 ]]; then
    fail "lint: generated .vale.ini block is stale (run --write-config)"
    return
  fi
  local -a pages
  mapfile -t pages < <("${PY[@]}" pages)
  local rc=0
  lint_pages "site/dist" -- "${pages[@]}" || rc=$?
  if [[ "$rc" -eq 0 ]]; then
    pass "lint: ${#pages[@]} pages, no error alert, ratchet list complete"
  else
    fail "lint: error alert or ratchet gap (see ERROR and RATCHET lines above)"
  fi
}

# ─── --selftest ──────────────────────────────────────────────────────────────

# First page listed under a rule header of site/style-guide/blocking.yml.
first_blocking_page() {
  awk -v header="$1:" '
    $0 == header { found = 1; next }
    found && /^  - / { sub(/^  - /, ""); print; exit }
    found && /^[^ #]/ { exit }
  ' site/style-guide/blocking.yml
}

selftest_case() {
  local label="$1" style="$2" source="$3" kind="$4"
  local dist rel work out rc=0 errors
  dist=$("${PY[@]}" dist "$source")
  rel="${dist#dist/}"
  work="$SELFTEST_DIR/$label"
  mkdir -p "$work/$(dirname "$rel")"
  if [[ "$kind" == "unchanged" ]]; then
    cp "site/dist/$rel" "$work/$rel"
  else
    "${PY[@]}" inject "site/dist/$rel" "$work/$rel" "$kind"
  fi
  VALE_EXTRA=(-v "$work":/repo/site/dist:ro)
  out=$(lint_pages "$work" --only "$dist" -- "$dist") || rc=$?
  VALE_EXTRA=()
  errors=$(echo "$out" | grep -c '^ERROR ' || true)
  if [[ "$kind" == "unchanged" ]]; then
    if [[ "$rc" -eq 0 && "$errors" -eq 0 ]]; then
      pass "selftest $label: unchanged clean page gives exit 0 and no ERROR line"
    else
      echo "$out"
      fail "selftest $label: unchanged clean page must give exit 0 and no ERROR line (exit $rc, $errors errors)"
    fi
  else
    if [[ "$rc" -eq 1 ]] && echo "$out" | grep -q "^ERROR $style\.Dashes "; then
      pass "selftest $label: planted dash gives exit 1 and an ERROR line from $style.Dashes"
    else
      echo "$out"
      fail "selftest $label: planted dash must give exit 1 and an ERROR line from $style.Dashes (exit $rc)"
    fi
  fi
}

run_selftest() {
  need_dist
  SELFTEST_DIR=$(mktemp -d)
  trap 'rm -rf "$SELFTEST_DIR"' EXIT
  local style lang page
  for style in DocsEN DocsDE; do
    lang="${style#Docs}"
    page=$(first_blocking_page "$style.Dashes")
    if [[ -z "$page" ]]; then
      fail "selftest $lang: no page listed under $style.Dashes in blocking.yml"
      continue
    fi
    selftest_case "$lang-unchanged" "$style" "$page" unchanged
    selftest_case "$lang-em-dash" "$style" "$page" em-dash
    selftest_case "$lang-hyphens" "$style" "$page" hyphens
  done
}

# ─── Run ─────────────────────────────────────────────────────────────────────

[[ "$RUN_TEST" == "true" ]] && run_test
[[ "$RUN_LINT" == "true" ]] && run_lint
[[ "$RUN_SELFTEST" == "true" ]] && run_selftest

# ─── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "=== Results ==="
TOTAL=$((PASS_COUNT + FAIL_COUNT))
echo "Passed: $PASS_COUNT / $TOTAL"
if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo "Failed: $FAIL_COUNT / $TOTAL"
  echo ""
  echo "Some checks failed - see FAIL lines above."
  exit 1
else
  echo "All $TOTAL checks passed."
  exit 0
fi
