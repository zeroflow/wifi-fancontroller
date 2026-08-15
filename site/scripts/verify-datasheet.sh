#!/usr/bin/env bash
# verify-datasheet.sh - Rev 3.3 datasheet verification harness
#
# Usage:
#   bash site/scripts/verify-datasheet.sh              # run all checks
#   bash site/scripts/verify-datasheet.sh --specs      # run only selected checks
#
# Flags: --routes --lang --specs --contradiction --typography --pdf
# Running with no flag runs every check group.
#
# Reads the built print-route HTML for the grep-able content checks, and the
# rendered PDFs (via pdftotext, when present) for the PDF-only checks. The PDF
# checks SKIP rather than fail when no render exists, so the script is useful
# after a plain `npm run build` on a dev machine.
set -euo pipefail

PASS_COUNT=0
FAIL_COUNT=0

EN_HTML_PATH="site/dist/datasheet-print/index.html"
DE_HTML_PATH="site/dist/de/datasheet-print/index.html"
EN_PDF_PATH="site/fancontroller-rev3.3-datasheet-en.pdf"
DE_PDF_PATH="site/fancontroller-rev3.3-datasheet-de.pdf"

pass() { echo "PASS: $1"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "FAIL: $1"; FAIL_COUNT=$((FAIL_COUNT + 1)); }

read_html() { [[ -f "$1" ]] && cat "$1" || echo ""; }

# ─── Argument parsing ────────────────────────────────────────────────────────

RUN_ROUTES=false
RUN_LANG=false
RUN_SPECS=false
RUN_CONTRADICTION=false
RUN_TYPOGRAPHY=false
RUN_PDF=false
ANY_FLAG=false

for arg in "$@"; do
  case "$arg" in
    --routes) RUN_ROUTES=true; ANY_FLAG=true ;;
    --lang) RUN_LANG=true; ANY_FLAG=true ;;
    --specs) RUN_SPECS=true; ANY_FLAG=true ;;
    --contradiction) RUN_CONTRADICTION=true; ANY_FLAG=true ;;
    --typography) RUN_TYPOGRAPHY=true; ANY_FLAG=true ;;
    --pdf) RUN_PDF=true; ANY_FLAG=true ;;
    *)
      echo "Unknown flag: $arg (supported: --routes --lang --specs --contradiction --typography --pdf)" >&2
      exit 2
      ;;
  esac
done

if [[ "$ANY_FLAG" == "false" ]]; then
  RUN_ROUTES=true
  RUN_LANG=true
  RUN_SPECS=true
  RUN_CONTRADICTION=true
  RUN_TYPOGRAPHY=true
  RUN_PDF=true
fi

if [[ ! -d "site/dist" ]]; then
  echo "FAIL: site/dist/ not found - run \`cd site && npm run build\` first"
  exit 1
fi

EN_HTML=$(read_html "$EN_HTML_PATH")
DE_HTML=$(read_html "$DE_HTML_PATH")

echo "=== Rev 3.3 Datasheet Verification ==="
echo "EN HTML: $EN_HTML_PATH"
echo "DE HTML: $DE_HTML_PATH"
echo ""

PDFTOTEXT_AVAILABLE=false
command -v pdftotext >/dev/null 2>&1 && PDFTOTEXT_AVAILABLE=true

extract_pdf() {
  [[ -f "$1" && "$PDFTOTEXT_AVAILABLE" == "true" ]] && pdftotext "$1" - 2>/dev/null || true
}

# ─── Both print routes exist and are non-empty ───────────────────────────────

check_routes() {
  local label path html
  for pair in "EN:$EN_HTML_PATH" "DE:$DE_HTML_PATH"; do
    label="${pair%%:*}"
    path="${pair#*:}"
    html=$(read_html "$path")
    if [[ -z "$html" ]]; then
      fail "routes: $label print route not built or empty ($path)"
    else
      pass "routes: $label print route built ($path)"
    fi
  done

  # <title> is an HTML raw-text element: two adjacent Astro expressions inside
  # it get split, and everything after the first one is pushed into the body
  # where it prints as stray text above the page header. Asserting the full
  # title string catches that regression.
  if echo "$EN_HTML" | grep -qF "<title>Datasheet: ESP32 WiFi Fan Controller</title>"; then
    pass "routes: EN title renders as a single complete string"
  else
    fail "routes: EN <title> is incomplete - a split expression leaks into the body as stray text"
  fi

  if echo "$DE_HTML" | grep -qF "<title>Datenblatt: ESP32 WiFi Lüftersteuerung</title>"; then
    pass "routes: DE title renders as a single complete string"
  else
    fail "routes: DE <title> is incomplete - a split expression leaks into the body as stray text"
  fi

  # The print routes are render targets, not reader-facing pages. Astro's
  # sitemap integration picks up every src/pages route, so without an explicit
  # noindex they compete with /reference/datasheet/ as duplicate content.
  for pair in "EN:$EN_HTML_PATH" "DE:$DE_HTML_PATH"; do
    label="${pair%%:*}"
    html=$(read_html "${pair#*:}")
    if echo "$html" | grep -qE '<meta name="robots" content="noindex'; then
      pass "routes: $label print route is noindex"
    else
      fail "routes: $label print route is missing its noindex meta tag"
    fi
  done

  # The print routes must carry none of Starlight's chrome. A sidebar or search
  # element leaking in means the layout accidentally got wrapped in a Starlight
  # page, which would put navigation furniture into a customer-facing PDF.
  local marker
  for marker in "sidebar" "site-search" "starlight-menu"; do
    if echo "$EN_HTML$DE_HTML" | grep -qiF "$marker"; then
      fail "routes: Starlight chrome marker '$marker' found in a print route"
    else
      pass "routes: no Starlight chrome marker '$marker' in print routes"
    fi
  done
}

# ─── Correct language declared per route ─────────────────────────────────────

check_lang() {
  if echo "$EN_HTML" | grep -qE '<html[^>]*lang="en"'; then
    pass "lang: <html lang=\"en\"> present on the EN print route"
  else
    fail "lang: <html lang=\"en\"> missing on the EN print route"
  fi

  if echo "$DE_HTML" | grep -qE '<html[^>]*lang="de"'; then
    pass "lang: <html lang=\"de\"> present on the DE print route"
  else
    fail "lang: <html lang=\"de\"> missing on the DE print route"
  fi

  # Cross-contamination guard: the DE route must not fall back to the English
  # source, and vice versa.
  if echo "$DE_HTML" | grep -qF "Ordering information"; then
    fail "lang: English heading 'Ordering information' found in the DE route (i18n fallback leak)"
  else
    pass "lang: no English fallback leak in the DE route"
  fi

  if echo "$EN_HTML" | grep -qF "Bestellangaben"; then
    fail "lang: German heading 'Bestellangaben' found in the EN route"
  else
    pass "lang: no German content leak in the EN route"
  fi
}

# ─── Mandatory spec values present in both languages ─────────────────────────

check_specs() {
  # Locale-independent values: identical in both documents.
  local shared=(
    "70"      # PCB length, mm
    "45"      # PCB width, mm
    "60"      # mounting hole pattern, mm
    "35"      # mounting hole pattern, mm
    "3K3"     # climatic class
    "60721"   # IEC 60721-3-3
    "62368"   # IEC 62368-1
    "2000"    # operating altitude, m
    "GPIO12"  # pin table rendered
    "GPIO44"  # pin table rendered through to the end
    "ESP32-S2-MINI-2"
    "HDC1080"
    "802.11"
    "20 cm"   # RF exposure separation distance
  )
  local value
  for value in "${shared[@]}"; do
    if echo "$EN_HTML" | grep -qF "$value"; then
      pass "specs EN: '$value' present"
    else
      fail "specs EN: '$value' missing"
    fi
    if echo "$DE_HTML" | grep -qF "$value"; then
      pass "specs DE: '$value' present"
    else
      fail "specs DE: '$value' missing"
    fi
  done

  # Decimal separators are locale specific: the EN document uses points, the DE
  # document uses commas. A comma in the EN document (or a point in the DE one)
  # means a translation slipped a number through unconverted.
  local en_only=("2.5 A" "1.6 mm" "3.2 mm" "12.6" "11.4" "±5 %")
  for value in "${en_only[@]}"; do
    if echo "$EN_HTML" | grep -qF "$value"; then
      pass "specs EN: '$value' present"
    else
      fail "specs EN: '$value' missing"
    fi
  done

  local de_only=("2,5 A" "1,6 mm" "3,2 mm" "12,6" "11,4" "±5 %")
  for value in "${de_only[@]}"; do
    if echo "$DE_HTML" | grep -qF "$value"; then
      pass "specs DE: '$value' present"
    else
      fail "specs DE: '$value' missing"
    fi
  done

  if echo "$DE_HTML" | grep -qF "2.5 A"; then
    fail "specs DE: English decimal point found in '2.5 A' - use the German comma"
  else
    pass "specs DE: no English decimal point in the total-current figure"
  fi
}

# ─── No contradiction with the compliance page ───────────────────────────────

check_contradiction() {
  # compliance.md excludes operation without an enclosure, so the datasheet
  # must not advertise an IP rating that implies the bare board is protected.
  local marker
  for marker in "IP20" "IP 20" "IP65" "IP54"; do
    if echo "$EN_HTML$DE_HTML" | grep -qF "$marker"; then
      fail "contradiction: ingress-protection claim '$marker' found - the bare PCB has no IP rating and requires an enclosure"
    else
      pass "contradiction: no '$marker' ingress-protection claim"
    fi
  done

  # The board must never be described as able to power fans from USB.
  if echo "$EN_HTML" | grep -qiE 'USB[^.]{0,60}power[s]? (the )?fans'; then
    fail "contradiction: EN datasheet suggests USB can power fans"
  else
    pass "contradiction: EN datasheet does not claim USB powers fans"
  fi

  # Enclosure requirement must be stated in both languages.
  if echo "$EN_HTML" | grep -qiF "enclosure is required"; then
    pass "contradiction: EN datasheet states the enclosure requirement"
  else
    fail "contradiction: EN datasheet does not state the enclosure requirement"
  fi

  if echo "$DE_HTML" | grep -qiF "Gehäuse erforderlich"; then
    pass "contradiction: DE datasheet states the enclosure requirement"
  else
    fail "contradiction: DE datasheet does not state the enclosure requirement"
  fi
}

# ─── Typography: no em-dash anywhere ─────────────────────────────────────────
#
# Astro's default `smartypants: true` rewrites a source `--` into a real
# em-dash (U+2014) at BUILD time, so a source-only grep passes while the
# rendered PDF still carries em-dashes. This reads the BUILT output.

check_typography() {
  local label html n
  for pair in "EN:$EN_HTML_PATH" "DE:$DE_HTML_PATH"; do
    label="${pair%%:*}"
    html=$(read_html "${pair#*:}")
    if [[ -z "$html" ]]; then
      fail "typography: $label print route not built, cannot check"
      continue
    fi
    if echo "$html" | grep -qF "—"; then
      n=$(echo "$html" | grep -oF "—" | wc -l | tr -d ' ')
      fail "typography: $n em-dash (—, U+2014) character(s) in built $label HTML - source '--' rewritten by smartypants; use ':' / '.' / ',' instead"
    else
      pass "typography: no em-dash in built $label HTML"
    fi
  done
}

# ─── PDF checks: footer stamp, umlauts, em-dash backstop ─────────────────────

check_pdf() {
  if [[ "$PDFTOTEXT_AVAILABLE" != "true" ]]; then
    echo "SKIP: PDF checks - pdftotext not available on this machine"
    return
  fi

  local label path text
  for pair in "EN:$EN_PDF_PATH" "DE:$DE_PDF_PATH"; do
    label="${pair%%:*}"
    path="${pair#*:}"

    if [[ ! -f "$path" ]]; then
      echo "SKIP: PDF checks ($label) - $path not found (no render yet)"
      continue
    fi

    text=$(extract_pdf "$path")
    if [[ -z "$text" ]]; then
      fail "pdf $label: pdftotext extraction produced no text from $path"
      continue
    fi

    # Footer must carry the revision, a version string and a date.
    if echo "$text" | grep -qF "Rev 3.3"; then
      pass "pdf $label: revision stamp present in footer"
    else
      fail "pdf $label: revision stamp 'Rev 3.3' not found"
    fi

    if echo "$text" | grep -qE 'v?[0-9]+\.[0-9]+(\.[0-9]+)?'; then
      pass "pdf $label: version string found"
    else
      fail "pdf $label: no version string found"
    fi

    if echo "$text" | grep -qE '[0-9]{1,2}[./][0-9]{1,2}[./][0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2}'; then
      pass "pdf $label: date found"
    else
      fail "pdf $label: no date found"
    fi

    if echo "$text" | grep -qF "—"; then
      fail "pdf $label: em-dash (—) found in extracted PDF text"
    else
      pass "pdf $label: no em-dash in extracted PDF text"
    fi

    # Starlight's heading autolink label is only visually hidden by Starlight's
    # own stylesheet, which these standalone routes do not load. If the print
    # layout stops hiding .sl-anchor-link, "Section titled ..." prints under
    # every heading; it shows up here rather than in the HTML.
    if echo "$text" | grep -qiE 'Section titled|Abschnitt mit dem Titel'; then
      fail "pdf $label: heading autolink label printed - .sl-anchor-link is not hidden in the print layout"
    else
      pass "pdf $label: no heading autolink label in the printed output"
    fi

    # A downloaded PDF has no origin, so a root-relative href is a dead link.
    # The print layout rewrites them to absolute production URLs; this reads the
    # PDF's actual link annotations to confirm the rewrite ran.
    if command -v pdftohtml >/dev/null 2>&1; then
      local links relative
      links=$(pdftohtml -i -stdout -xml "$path" 2>/dev/null | grep -oE 'href="[^"]*"' | sort -u)
      relative=$(echo "$links" | grep -E 'href="/' || true)
      if [[ -n "$relative" ]]; then
        fail "pdf $label: root-relative link(s) survived into the PDF: $(echo "$relative" | tr '\n' ' ')"
      else
        pass "pdf $label: all link annotations are absolute URLs"
      fi
    else
      echo "SKIP: pdf $label link check - pdftohtml not available"
    fi
  done

  # Encoding backstop on the German PDF: Chromium needs the OS font packages
  # (`playwright install --with-deps`) to render umlauts, and a missing glyph
  # shows up here rather than in the HTML.
  if [[ -f "$DE_PDF_PATH" ]]; then
    text=$(extract_pdf "$DE_PDF_PATH")
    local ch found_all=true
    for ch in "ä" "ö" "ü" "ß"; do
      if ! echo "$text" | grep -qF "$ch"; then
        found_all=false
        fail "pdf DE: character '$ch' not found in extracted text (missing glyph or mojibake)"
      fi
    done
    [[ "$found_all" == "true" ]] && pass "pdf DE: ä/ö/ü/ß all render correctly"

    if echo "$text" | grep -qF $'\xef\xbf\xbd'; then
      fail "pdf DE: replacement character (U+FFFD) found - mojibake"
    else
      pass "pdf DE: no replacement-character mojibake"
    fi
  fi
}

# ─── Run selected checks ─────────────────────────────────────────────────────

[[ "$RUN_ROUTES" == "true" ]] && check_routes
[[ "$RUN_LANG" == "true" ]] && check_lang
[[ "$RUN_SPECS" == "true" ]] && check_specs
[[ "$RUN_CONTRADICTION" == "true" ]] && check_contradiction
[[ "$RUN_TYPOGRAPHY" == "true" ]] && check_typography
[[ "$RUN_PDF" == "true" ]] && check_pdf

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
