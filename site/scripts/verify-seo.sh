#!/usr/bin/env bash
# verify-seo.sh - Phase 14 Technical SEO validation script
# Usage:
#   bash site/scripts/verify-seo.sh          # local mode (reads site/dist/)
#   SEO_BASE=https://fancontroller.arthofer.dev bash site/scripts/verify-seo.sh --live
set -euo pipefail

PASS_COUNT=0
FAIL_COUNT=0
LIVE_MODE=false

for arg in "$@"; do
  if [[ "$arg" == "--live" ]]; then
    LIVE_MODE=true
  fi
done

LIVE_BASE="https://fancontroller.arthofer.dev"
: "${SEO_BASE:=$LIVE_BASE}"

# ─── Helpers ─────────────────────────────────────────────────────────────────

pass() {
  echo "PASS: $1"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  echo "FAIL: $1"
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

# Fetch page content - curl in live mode, cat from dist/ in local mode
get_page() {
  local path="$1"  # e.g. "" for root, "de/" for DE root, "getting-started/first-setup/" for docs
  if [[ "$LIVE_MODE" == "true" ]]; then
    curl -fsS "$LIVE_BASE/$path"
  else
    local file="site/dist/${path}index.html"
    if [[ ! -f "$file" ]]; then
      echo ""
      return
    fi
    cat "$file"
  fi
}

# ─── Pre-flight: dist/ existence (local mode only) ───────────────────────────

if [[ "$LIVE_MODE" == "false" ]]; then
  if [[ ! -d "site/dist" ]]; then
    echo "FAIL: site/dist/ not found - run \`cd site && npm run build\` first"
    exit 1
  fi
fi

echo "=== Phase 14 SEO Verification ==="
echo "Mode: $([ "$LIVE_MODE" == "true" ] && echo 'live' || echo 'local dist/')"
echo ""

# ─── Fetch pages (cache) ──────────────────────────────────────────────────────

EN_HOME=$(get_page "")
DE_HOME=$(get_page "de/")
FIRST_SETUP=$(get_page "getting-started/first-setup/")

# ─── T-06: OG Image + og:type ─────────────────────────────────────────────────

# Check 1: T-06 og:image present on EN homepage
if echo "$EN_HOME" | grep -q 'og:image'; then
  pass "T-06 og:image present on EN homepage"
else
  fail "T-06 og:image missing on EN homepage"
fi

# Check 2: T-06 og:type=product on EN homepage
if echo "$EN_HOME" | grep -Eq 'property="og:type"[^>]*content="product"'; then
  pass "T-06 og:type=product on EN homepage"
else
  fail "T-06 og:type=product missing on EN homepage (got 'article' or absent)"
fi

# Check 3: T-06 og:type=article NOT present on EN homepage (replaced, not duplicated)
if ! echo "$EN_HOME" | grep -Eq 'property="og:type"[^>]*content="article"'; then
  pass "T-06 og:type=article NOT present on EN homepage (fully replaced)"
else
  fail "T-06 og:type=article still present on EN homepage (duplicate or not replaced)"
fi

# Check 4: T-06 og:image on DE homepage
if echo "$DE_HOME" | grep -q 'og:image'; then
  pass "T-06 og:image present on DE homepage"
else
  fail "T-06 og:image missing on DE homepage"
fi

# ─── T-04: Title deduplication ────────────────────────────────────────────────

# Check 5: T-04 EN title deduplicated
EN_TITLE=$(echo "$EN_HOME" | grep -oP '(?<=<title>)[^<]*' || true)
EXPECTED_EN_TITLE="ESP32 WiFi Fan Controller - 4-Channel PWM for Home Assistant | ESPHome"
if [[ "$EN_TITLE" == "$EXPECTED_EN_TITLE" ]]; then
  pass "T-04 EN title deduplicated: '$EN_TITLE'"
else
  fail "T-04 EN title mismatch - got: '$EN_TITLE' | expected: '$EXPECTED_EN_TITLE'"
fi

# Check 6: T-04 DE title deduplicated
DE_TITLE=$(echo "$DE_HOME" | grep -oP '(?<=<title>)[^<]*' || true)
EXPECTED_DE_TITLE="ESP32 WiFi Lüftersteuerung - 4-Kanal PWM für Home Assistant | ESPHome"
if [[ "$DE_TITLE" == "$EXPECTED_DE_TITLE" ]]; then
  pass "T-04 DE title deduplicated: '$DE_TITLE'"
else
  fail "T-04 DE title mismatch - got: '$DE_TITLE' | expected: '$EXPECTED_DE_TITLE'"
fi

# ─── T-05: "smart home" keyword ───────────────────────────────────────────────

# Check 7: T-05 EN "smart home" >=3 occurrences
EN_SMART_HOME_COUNT=$(echo "$EN_HOME" | { grep -oi 'smart home' || true; } | wc -l | tr -d ' ')
if [[ "$EN_SMART_HOME_COUNT" -ge 3 ]]; then
  pass "T-05 EN 'smart home' >= 3 occurrences ($EN_SMART_HOME_COUNT found)"
else
  fail "T-05 EN 'smart home' < 3 occurrences ($EN_SMART_HOME_COUNT found, need >=3)"
fi

# Check 8: T-05 DE "smart home"/"Smart-Home"/"Smart Home" >=3 occurrences
DE_SMART_HOME_COUNT=$(echo "$DE_HOME" | { grep -oEi 'smart[ -]home' || true; } | wc -l | tr -d ' ')
if [[ "$DE_SMART_HOME_COUNT" -ge 3 ]]; then
  pass "T-05 DE 'smart home/Smart-Home' >= 3 occurrences ($DE_SMART_HOME_COUNT found)"
else
  fail "T-05 DE 'smart home/Smart-Home' < 3 occurrences ($DE_SMART_HOME_COUNT found, need >=3)"
fi

# ─── T-01: Review visibility ──────────────────────────────────────────────────

# Check 9: T-01 review visible on EN homepage
if echo "$EN_HOME" | grep -q 'verified Tindie buyer'; then
  pass "T-01 review visible on EN homepage ('verified Tindie buyer' found)"
else
  fail "T-01 review missing on EN homepage ('verified Tindie buyer' not found)"
fi

# Check 10: T-01 review visible on DE homepage
if echo "$DE_HOME" | grep -q 'verified Tindie buyer'; then
  pass "T-01 review visible on DE homepage ('verified Tindie buyer' found)"
else
  fail "T-01 review missing on DE homepage ('verified Tindie buyer' not found)"
fi

# ─── T-01/T-03: Product JSON-LD (DE parity) ───────────────────────────────────

# Check 11: T-01/T-03 DE homepage has Product JSON-LD
if echo "$DE_HOME" | grep -q 'WIFIFC-REV33'; then
  pass "T-01/T-03 DE homepage has Product JSON-LD (WIFIFC-REV33 SKU found)"
else
  fail "T-01/T-03 DE homepage missing Product JSON-LD (WIFIFC-REV33 SKU not found)"
fi

# ─── T-02: BreadcrumbList ─────────────────────────────────────────────────────

# Check 12: T-02 BreadcrumbList on docs page
if echo "$FIRST_SETUP" | grep -q 'BreadcrumbList'; then
  pass "T-02 BreadcrumbList present on docs page (getting-started/first-setup)"
else
  fail "T-02 BreadcrumbList missing on docs page (getting-started/first-setup)"
fi

# Check 13: T-02 BreadcrumbList NOT on EN splash
if ! echo "$EN_HOME" | grep -q 'BreadcrumbList'; then
  pass "T-02 BreadcrumbList correctly absent from EN splash homepage"
else
  fail "T-02 BreadcrumbList found on EN splash homepage (should not be there)"
fi

# Check 14: T-02 BreadcrumbList NOT on DE splash
if ! echo "$DE_HOME" | grep -q 'BreadcrumbList'; then
  pass "T-02 BreadcrumbList correctly absent from DE splash homepage"
else
  fail "T-02 BreadcrumbList found on DE splash homepage (should not be there)"
fi

# Check 15: T-02 fully-qualified URLs in BreadcrumbList
if echo "$FIRST_SETUP" | grep -q 'https://fancontroller.arthofer.dev/'; then
  pass "T-02 BreadcrumbList uses fully-qualified URLs (https://fancontroller.arthofer.dev/ found)"
else
  fail "T-02 BreadcrumbList URLs not fully-qualified (https://fancontroller.arthofer.dev/ not found in first-setup page)"
fi

# ─── T-07: Sitemap (live mode only) ───────────────────────────────────────────

# Check 16: T-07 sitemap HTTP 200
if [[ "$LIVE_MODE" == "true" ]]; then
  SITEMAP_STATUS=$(curl -fsS -o /dev/null -w '%{http_code}' "$LIVE_BASE/sitemap-index.xml" || echo "000")
  if [[ "$SITEMAP_STATUS" == "200" ]]; then
    pass "T-07 sitemap HTTP 200 ($LIVE_BASE/sitemap-index.xml)"
  else
    fail "T-07 sitemap HTTP $SITEMAP_STATUS ($LIVE_BASE/sitemap-index.xml - expected 200)"
  fi

  # Check 17: T-07 sitemap URL count
  # Note: Starlight emits sitemap-0.xml as a single line; grep -c counts lines, not occurrences.
  # Use grep -o to count each <loc> occurrence individually.
  SITEMAP_URL_COUNT=$(curl -s "$LIVE_BASE/sitemap-0.xml" | grep -o '<loc>' | wc -l | tr -d ' ' || echo 0)
  if [[ "$SITEMAP_URL_COUNT" -ge 22 ]]; then
    pass "T-07 sitemap URL count >= 22 ($SITEMAP_URL_COUNT URLs found in sitemap-0.xml)"
  else
    fail "T-07 sitemap URL count < 22 ($SITEMAP_URL_COUNT found, need >=22)"
  fi
else
  echo "SKIP: T-07 sitemap HTTP check (local mode - use --live flag for live URL checks)"
  echo "SKIP: T-07 sitemap URL count check (local mode)"
fi

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
