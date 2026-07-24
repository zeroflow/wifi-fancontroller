#!/usr/bin/env bash
# verify-manual.sh - Phase 19.1 German legal manual verification harness (Wave 0)
#
# Usage:
#   bash site/scripts/verify-manual.sh                 # run all checks
#   bash site/scripts/verify-manual.sh --r4 --r9       # run only selected checks
#
# Flags: --sections --lang --r4 --r5 --r6 --r7 --r9 --typography --footer --umlaut
# Running with no flag runs every check group.
#
# Reads site/dist/de/manual-print/index.html (built HTML, pre-PDF) for the
# grep-able section/content checks (R1/R2/R4/R5/R6/R7/R9), and site/manual.pdf
# (via pdftotext, when present) for the PDF-only checks (--footer/R3,
# --umlaut). The manual is a fixed, versioned snapshot artifact, never a live
# website (P3/P1 in 19.1-SPEC.md) - so there is no --live mode here, unlike
# verify-seo.sh.
#
# This is the Wave 0 test scaffold (19.1-VALIDATION.md): the print route
# (plan 03) and the curated DE content (plan 02) do not exist yet, so this
# script is EXPECTED TO FAIL until those plans land - that is the intended
# Wave-0-first ordering (19.1-01 must-have).
set -euo pipefail

PASS_COUNT=0
FAIL_COUNT=0

MANUAL_HTML_PATH="site/dist/de/manual-print/index.html"
MANUAL_PDF_PATH="site/manual.pdf"

# ─── Helpers ─────────────────────────────────────────────────────────────────

pass() {
  echo "PASS: $1"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  echo "FAIL: $1"
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

# Read the built (pre-PDF) print-route HTML, or empty string if not built yet.
get_manual_html() {
  if [[ ! -f "$MANUAL_HTML_PATH" ]]; then
    echo ""
    return
  fi
  cat "$MANUAL_HTML_PATH"
}

# ─── Argument parsing ────────────────────────────────────────────────────────

RUN_SECTIONS=false
RUN_LANG=false
RUN_R4=false
RUN_R5=false
RUN_R6=false
RUN_R7=false
RUN_R9=false
RUN_TYPOGRAPHY=false
RUN_FOOTER=false
RUN_UMLAUT=false
ANY_FLAG=false

for arg in "$@"; do
  case "$arg" in
    --sections) RUN_SECTIONS=true; ANY_FLAG=true ;;
    --lang) RUN_LANG=true; ANY_FLAG=true ;;
    --r4) RUN_R4=true; ANY_FLAG=true ;;
    --r5) RUN_R5=true; ANY_FLAG=true ;;
    --r6) RUN_R6=true; ANY_FLAG=true ;;
    --r7) RUN_R7=true; ANY_FLAG=true ;;
    --r9) RUN_R9=true; ANY_FLAG=true ;;
    --typography) RUN_TYPOGRAPHY=true; ANY_FLAG=true ;;
    --footer) RUN_FOOTER=true; ANY_FLAG=true ;;
    --umlaut) RUN_UMLAUT=true; ANY_FLAG=true ;;
    *)
      echo "Unknown flag: $arg (supported: --sections --lang --r4 --r5 --r6 --r7 --r9 --typography --footer --umlaut)" >&2
      exit 2
      ;;
  esac
done

if [[ "$ANY_FLAG" == "false" ]]; then
  RUN_SECTIONS=true
  RUN_LANG=true
  RUN_R4=true
  RUN_R5=true
  RUN_R6=true
  RUN_R7=true
  RUN_R9=true
  RUN_TYPOGRAPHY=true
  RUN_FOOTER=true
  RUN_UMLAUT=true
fi

NEEDS_HTML=false
if [[ "$RUN_SECTIONS" == "true" || "$RUN_LANG" == "true" || "$RUN_R4" == "true" || \
      "$RUN_R5" == "true" || "$RUN_R6" == "true" || "$RUN_R7" == "true" || "$RUN_R9" == "true" || \
      "$RUN_TYPOGRAPHY" == "true" ]]; then
  NEEDS_HTML=true
fi

# ─── Pre-flight: dist/ existence ─────────────────────────────────────────────

if [[ "$NEEDS_HTML" == "true" && ! -d "site/dist" ]]; then
  echo "FAIL: site/dist/ not found - run \`cd site && npm run build\` first"
  exit 1
fi

echo "=== Phase 19.1 Manual Verification ==="
echo "HTML target: $MANUAL_HTML_PATH"
echo "PDF target:  $MANUAL_PDF_PATH"
echo ""

# ─── PDF pre-flight (footer / umlaut only) ───────────────────────────────────

PDFTOTEXT_AVAILABLE=false
if command -v pdftotext >/dev/null 2>&1; then
  PDFTOTEXT_AVAILABLE=true
fi

PDF_AVAILABLE=false
if [[ -f "$MANUAL_PDF_PATH" ]]; then
  PDF_AVAILABLE=true
fi

MANUAL_PDF_TEXT=""
if [[ "$PDF_AVAILABLE" == "true" && "$PDFTOTEXT_AVAILABLE" == "true" ]]; then
  MANUAL_PDF_TEXT=$(pdftotext "$MANUAL_PDF_PATH" - 2>/dev/null || true)
fi

# ─── R1: curated sections, fixed order, no excluded surfaces ─────────────────

check_sections() {
  local html
  html=$(get_manual_html)

  if [[ -z "$html" ]]; then
    fail "R1 section order: $MANUAL_HTML_PATH not found or empty (print route not built yet - plan 03)"
    fail "R1 excluded content: cannot check ($MANUAL_HTML_PATH missing)"
    return
  fi

  # Fixed table of contents (R1/D-10): print route imports these 6 curated
  # entries, in this order, each wrapped in
  # <section class="manual-section" data-section-index="N">. See
  # 19.1-RESEARCH.md Pattern 1 for the sectionIds array this mirrors:
  #   0 compliance, 1 first-setup, 2 rev-1-0, 3 rev-2-0, 4 rev-3-0, 5 rev-3-x
  local expected_order="0 1 2 3 4 5"
  local actual_order
  actual_order=$(echo "$html" | grep -oE 'data-section-index="[0-9]+"' | grep -oE '[0-9]+' | tr '\n' ' ' | sed 's/ *$//')

  if [[ "$actual_order" == "$expected_order" ]]; then
    pass "R1 section order: all 6 curated sections present in fixed order (0..5)"
  else
    fail "R1 section order: expected '$expected_order', got '$actual_order' - print route must render compliance, first-setup, rev-1-0, rev-2-0, rev-3-0, rev-3-x in that order (D-10)"
  fi

  # Excluded surfaces (R1 boundary) must never appear in the curated print route.
  # NOTE: a blanket "Qwiic" marker was replaced with "STEMMA QT" (plan 03,
  # Rule 1 fix) - the curated hardware rev-3-0/rev-3-x pages legitimately
  # mention the board's own Qwiic connector as an included hardware-spec
  # detail (R1's in-scope "hardware-spec ratings"), which is a different
  # thing from the excluded "Qwiic examples" documentation section
  # (reference/qwiic/*). "STEMMA QT" appears in all 7 files under
  # reference/qwiic/ but in none of the 6 curated DE sections, so it is a
  # precise signal for "the excluded Qwiic section leaked into the PDF"
  # without false-positiving on the in-scope hardware connector mention.
  local excluded_markers=(
    "Blog"
    "Vergleichstabelle"
    "Comparison Matrix"
    "PID Simulator"
    "PID-Simulator"
    "STEMMA QT"
    "Modulreferenz"
    "Module Reference"
  )
  local excluded_found=false
  for marker in "${excluded_markers[@]}"; do
    if echo "$html" | grep -qF "$marker"; then
      fail "R1 excluded content: found forbidden marker '$marker' in manual-print HTML"
      excluded_found=true
    fi
  done
  if [[ "$excluded_found" == "false" ]]; then
    pass "R1 excluded content: none of the excluded surfaces (blog, comparison matrix, PID simulator, module reference, Qwiic) found"
  fi
}

# ─── R2: cover-to-cover German (backstop sanity, primary gate is the build-time throw) ──

check_lang() {
  local html
  html=$(get_manual_html)

  if [[ -z "$html" ]]; then
    fail "R2 lang: $MANUAL_HTML_PATH not found or empty"
    return
  fi

  if echo "$html" | grep -qE '<html[^>]*lang="de"'; then
    pass "R2 lang: <html lang=\"de\"> present on manual-print route"
  else
    fail "R2 lang: <html lang=\"de\"> missing on manual-print route"
  fi

  # Non-blocking secondary signal (RESEARCH.md "Don't Hand-Roll": the primary
  # gate is the build-time throw-on-missing-DE-entry in the print route, not
  # this word-list check).
  local de_markers=("Gebrauchsanleitung" "Sicherheit" "Lüfter")
  local all_present=true
  for marker in "${de_markers[@]}"; do
    if ! echo "$html" | grep -qF "$marker"; then
      all_present=false
      fail "R2 lang sanity: expected German word '$marker' not found in manual-print body"
    fi
  done
  if [[ "$all_present" == "true" ]]; then
    pass "R2 lang sanity: expected German vocabulary present (non-blocking secondary signal)"
  fi
}

# ─── R4: bestimmungsgemäße Verwendung + P2 (no per-port current limit) ───────

check_r4() {
  local html
  html=$(get_manual_html)

  if [[ -z "$html" ]]; then
    fail "R4: $MANUAL_HTML_PATH not found or empty"
    return
  fi

  if echo "$html" | grep -qE '12[[:space:]]?V'; then
    pass "R4: 12 V stated"
  else
    fail "R4: 12 V not found"
  fi

  if echo "$html" | grep -qi 'SELV'; then
    pass "R4: SELV stated"
  else
    fail "R4: SELV not found"
  fi

  if echo "$html" | grep -qiE 'trocken|Innenraum'; then
    pass "R4: indoor/dry-use constraint stated"
  else
    fail "R4: indoor/dry-use constraint not found"
  fi

  if echo "$html" | grep -qiE '4[- ]?(Pin|polig)'; then
    pass "R4: 4-pin PWM constraint stated"
  else
    fail "R4: 4-pin PWM constraint not found"
  fi

  if echo "$html" | grep -qE '2,5[[:space:]]?A'; then
    pass "R4: 2,5 A total current stated (German decimal comma)"
  else
    fail "R4: 2,5 A total current not found"
  fi

  # P2: MUST NOT state a per-fan-header / per-port current limit, in German
  # or English - no allowlist, no exception (19.1-01-PLAN.md Task 3, verbatim
  # instruction). This is intentionally a blanket phrase match, not a
  # proximity/negation-aware one: even a negating clause like "nicht pro
  # Anschluss" / "not per fan header" trips this check. That is deliberate -
  # it forces the curated DE legal text (plan 02) to state the 2.5 A total
  # constraint without ever invoking per-port framing at all, rather than
  # asserting-then-negating it. Any hit here is a hard violation.
  local forbidden=(
    "pro Anschluss"
    "pro Lüfteranschluss"
    "pro Port"
    "je Anschluss"
    "je Lüfteranschluss"
    "per port"
    "per fan header"
    "per-fan-header"
    "per fan-header"
  )
  local violation=false
  for phrase in "${forbidden[@]}"; do
    if echo "$html" | grep -qi "$phrase"; then
      fail "R4/P2 VIOLATION: forbidden per-port/per-fan-header phrase found: '$phrase'"
      violation=true
    fi
  done
  if [[ "$violation" == "false" ]]; then
    pass "R4/P2: no per-fan-header / per-port current-limit phrasing found (German or English)"
  fi
}

# ─── R5: six exclusion classes ────────────────────────────────────────────────

check_r5() {
  local html
  html=$(get_manual_html)

  if [[ -z "$html" ]]; then
    fail "R5: $MANUAL_HTML_PATH not found or empty"
    return
  fi

  local -A classes=(
    ["safety-critical"]="sicherheitskritisch"
    ["Ex-explosive-atmosphere"]="[Ee]xplosionsgefährdet|Ex-Bereich|explosionsfähig"
    ["medical"]="medizinisch"
    ["no-enclosure"]="ohne Gehäuse"
    ["unattended-continuous"]="unbeaufsichtigt.*Dauerbetrieb|Dauerbetrieb.*unbeaufsichtigt"
    ["automotive"]="Kraftfahrzeug|Automobil|Fahrzeug"
  )
  local order=("safety-critical" "Ex-explosive-atmosphere" "medical" "no-enclosure" "unattended-continuous" "automotive")

  local class pattern
  for class in "${order[@]}"; do
    pattern="${classes[$class]}"
    if echo "$html" | grep -qiE "$pattern"; then
      pass "R5: exclusion class '$class' present"
    else
      fail "R5: exclusion class '$class' not found (expected pattern: $pattern)"
    fi
  done
}

# ─── R6: external PSU requirements ────────────────────────────────────────────

check_r6() {
  local html
  html=$(get_manual_html)

  if [[ -z "$html" ]]; then
    fail "R6: $MANUAL_HTML_PATH not found or empty"
    return
  fi

  if echo "$html" | grep -qE '12[[:space:]]?V'; then
    pass "R6: 12 V PSU requirement stated"
  else
    fail "R6: 12 V PSU requirement not found"
  fi

  if echo "$html" | grep -qi 'CE'; then
    pass "R6: CE marking requirement stated"
  else
    fail "R6: CE marking requirement not found"
  fi

  if echo "$html" | grep -qiE 'Strombegrenzung|strombegrenzt|current[- ]limit'; then
    pass "R6: current-limiting requirement stated"
  else
    fail "R6: current-limiting requirement not found"
  fi

  if echo "$html" | grep -qiE 'Polarität|Polung'; then
    pass "R6: correct-polarity requirement stated"
  else
    fail "R6: correct-polarity requirement not found"
  fi
}

# ─── R7: firmware Warnhinweis + P1 (no full liability exclusion) ─────────────

check_r7() {
  local html
  html=$(get_manual_html)

  if [[ -z "$html" ]]; then
    fail "R7: $MANUAL_HTML_PATH not found or empty"
    return
  fi

  if echo "$html" | grep -qi 'Konformität'; then
    pass "R7: Konformität-voiding language present"
  else
    fail "R7: Konformität-voiding language not found"
  fi

  if echo "$html" | grep -qi 'Garantie'; then
    pass "R7: Garantie-voiding language present"
  else
    fail "R7: Garantie-voiding language not found"
  fi

  if echo "$html" | grep -qiE '[Ii]nstruktionswidrig'; then
    pass "R7: Instruktionswidrigkeit language present"
  else
    fail "R7: Instruktionswidrigkeit language not found"
  fi

  # P1: MUST NOT claim a full/blanket exclusion of product liability - § 9
  # ProdHG makes such exclusions ineffective against consumers. No allowlist.
  local forbidden=(
    "jede Haftung aus"
    "jegliche Haftung"
    "vollständiger Haftungsausschluss"
    "keine Haftung"
    "full liability exclusion"
    "excludes all liability"
    "no liability whatsoever"
  )
  local violation=false
  for phrase in "${forbidden[@]}"; do
    if echo "$html" | grep -qiE "$phrase"; then
      fail "R7/P1 VIOLATION: forbidden full-liability-exclusion phrase found: '$phrase'"
      violation=true
    fi
  done
  if [[ "$violation" == "false" ]]; then
    pass "R7/P1: no full/blanket liability-exclusion wording found"
  fi
}

# ─── R9: review-pending marker ────────────────────────────────────────────────

check_r9() {
  local html
  html=$(get_manual_html)

  if [[ -z "$html" ]]; then
    fail "R9: $MANUAL_HTML_PATH not found or empty"
    return
  fi

  if echo "$html" | grep -qi 'rechtliche Prüfung ausstehend'; then
    pass "R9: review-pending marker present ('rechtliche Prüfung ausstehend')"
  else
    fail "R9: review-pending marker not found ('rechtliche Prüfung ausstehend')"
  fi
}

# ─── Typography: no em-dash in the rendered manual (SPEC constraint) ─────────
#
# Astro's default `smartypants: true` rewrites a source `--` into a real em-dash
# (—, U+2014) at BUILD time, so a source-only grep passes while the rendered PDF
# still carries em-dashes. This check reads the BUILT HTML (and the PDF text when
# available) so the regression cannot slip through the source again.

check_typography() {
  local html
  html=$(get_manual_html)

  if [[ -z "$html" ]]; then
    fail "typography: $MANUAL_HTML_PATH not found or empty"
    return
  fi

  if echo "$html" | grep -qF "—"; then
    local n
    n=$(echo "$html" | grep -oF "—" | wc -l | tr -d ' ')
    fail "typography: $n em-dash (—, U+2014) character(s) found in built manual HTML - source '--' likely rewritten by smartypants; use ':' / '.' / ',' instead"
  else
    pass "typography: no em-dash (—) in built manual HTML"
  fi

  # PDF backstop when a render is available (mirrors --footer/--umlaut gating).
  if [[ "$PDF_AVAILABLE" == "true" && "$PDFTOTEXT_AVAILABLE" == "true" && -n "$MANUAL_PDF_TEXT" ]]; then
    if echo "$MANUAL_PDF_TEXT" | grep -qF "—"; then
      local np
      np=$(echo "$MANUAL_PDF_TEXT" | grep -oF "—" | wc -l | tr -d ' ')
      fail "typography: $np em-dash (—) character(s) found in extracted PDF text"
    else
      pass "typography: no em-dash (—) in extracted PDF text"
    fi
  fi
}

# ─── R3: version + date footer (PDF only) ────────────────────────────────────

check_footer() {
  if [[ "$PDF_AVAILABLE" != "true" ]]; then
    echo "SKIP: R3 footer check - $MANUAL_PDF_PATH not found (no render yet; local dev without a release-triggered build)"
    return
  fi
  if [[ "$PDFTOTEXT_AVAILABLE" != "true" ]]; then
    echo "SKIP: R3 footer check - pdftotext not available on this machine"
    return
  fi
  if [[ -z "$MANUAL_PDF_TEXT" ]]; then
    fail "R3: pdftotext extraction produced no text from $MANUAL_PDF_PATH"
    return
  fi

  # Footer must show a non-empty version string (release tag, e.g. v3.2.0)
  # and a date, matching the triggering release (D-06).
  if echo "$MANUAL_PDF_TEXT" | grep -qE 'v?[0-9]+\.[0-9]+(\.[0-9]+)?'; then
    pass "R3: version string found in extracted PDF text"
  else
    fail "R3: no version string found in extracted PDF text"
  fi

  if echo "$MANUAL_PDF_TEXT" | grep -qE '[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2}'; then
    pass "R3: date found in extracted PDF text"
  else
    fail "R3: no date found in extracted PDF text"
  fi
}

# ─── Encoding backstop: ä/ö/ü/ß render correctly (PDF only) ──────────────────

check_umlaut() {
  if [[ "$PDF_AVAILABLE" != "true" ]]; then
    echo "SKIP: umlaut check - $MANUAL_PDF_PATH not found (no render yet; local dev without a release-triggered build)"
    return
  fi
  if [[ "$PDFTOTEXT_AVAILABLE" != "true" ]]; then
    echo "SKIP: umlaut check - pdftotext not available on this machine"
    return
  fi
  if [[ -z "$MANUAL_PDF_TEXT" ]]; then
    fail "umlaut: pdftotext extraction produced no text from $MANUAL_PDF_PATH"
    return
  fi

  local found_all=true
  local ch
  for ch in "ä" "ö" "ü" "ß"; do
    if ! echo "$MANUAL_PDF_TEXT" | grep -qF "$ch"; then
      found_all=false
      fail "umlaut: character '$ch' not found in extracted PDF text (mojibake or missing glyph? see RESEARCH.md Pitfall 4)"
    fi
  done
  if [[ "$found_all" == "true" ]]; then
    pass "umlaut: ä/ö/ü/ß all render correctly in extracted PDF text"
  fi

  # Backstop: a literal U+FFFD replacement character is a strong mojibake signal.
  if echo "$MANUAL_PDF_TEXT" | grep -qF $'\xef\xbf\xbd'; then
    fail "umlaut: replacement character (U+FFFD) found in extracted PDF text - mojibake"
  else
    pass "umlaut: no replacement-character mojibake found"
  fi
}

# ─── Run selected checks ──────────────────────────────────────────────────────

[[ "$RUN_SECTIONS" == "true" ]] && check_sections
[[ "$RUN_LANG" == "true" ]] && check_lang
[[ "$RUN_R4" == "true" ]] && check_r4
[[ "$RUN_R5" == "true" ]] && check_r5
[[ "$RUN_R6" == "true" ]] && check_r6
[[ "$RUN_R7" == "true" ]] && check_r7
[[ "$RUN_R9" == "true" ]] && check_r9
[[ "$RUN_TYPOGRAPHY" == "true" ]] && check_typography
[[ "$RUN_FOOTER" == "true" ]] && check_footer
[[ "$RUN_UMLAUT" == "true" ]] && check_umlaut

# ─── Summary ──────────────────────────────────────────────────────────────────

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
