// site/scripts/render-manual-pdf.mjs
//
// D-09: renders the D-10 concatenated print route (src/pages/de/manual-print/)
// into a single, versioned/dated PDF via headless Chromium. Plain `playwright`
// (not `@playwright/test` - there is nothing to assert here beyond "did a
// non-empty PDF get produced", matching the project's existing one-shot
// scripts/*.mjs convention, e.g. build-og-homepage.mjs).
//
// This script only runs from the release-triggered publish-manual.yml
// workflow (plan 04). SPEC R8: there is no off-release build path, so both
// RELEASE_TAG and RELEASE_DATE must already be set by that workflow - if
// either is missing, this throws rather than falling back to a placeholder
// version/date.
//
// Expects site/dist to already be built (`npm run build`, which itself fails
// loudly per R2 if a curated DE section is missing) and served at
// http://localhost:4321 (e.g. `npm run preview -- --port 4321`) before this
// script runs - never point Playwright at a file:// URL (Astro's root-relative
// asset paths do not resolve under file://, silently dropping CSS/images).
import { chromium } from 'playwright';

const RELEASE_TAG = process.env.RELEASE_TAG;
const RELEASE_DATE = process.env.RELEASE_DATE; // ISO string, e.g. github.event.release.published_at

if (!RELEASE_TAG || !RELEASE_DATE) {
  throw new Error(
    'RELEASE_TAG and RELEASE_DATE must be set - this script only runs from ' +
      'the release-triggered publish-manual.yml workflow (SPEC R8: no ' +
      'off-release build path).'
  );
}

// R3: every page footer must show a non-empty version + date sourced from
// the triggering release. Built as a Playwright footerTemplate string, NOT
// CSS @page margin boxes / position:fixed - neither repeats reliably across
// printed pages in Chromium's print engine (19.1-RESEARCH.md Don't Hand-Roll).
const formattedDate = new Date(RELEASE_DATE).toLocaleDateString('de-AT');
const footerTemplate = `
  <div style="font-size:9px; width:100%; text-align:center; color:#555; padding:0 15mm;">
    Version ${RELEASE_TAG} &middot; ${formattedDate} &middot;
    Seite <span class="pageNumber"></span> / <span class="totalPages"></span>
  </div>
`;

const browser = await chromium.launch(); // headless by default - page.pdf() requires this
try {
  const page = await browser.newPage();
  await page.goto('http://localhost:4321/de/manual-print/', {
    waitUntil: 'networkidle',
  });

  await page.pdf({
    path: 'manual.pdf',
    format: 'A4',
    printBackground: true,
    displayHeaderFooter: true,
    headerTemplate: '<span></span>', // empty - footer carries the required info (R3)
    footerTemplate,
    // Sized to comfortably fit the footer's font size (Pitfall 3: a small
    // default margin.bottom clips/overlaps footer text with body content).
    margin: { top: '20mm', bottom: '20mm', left: '15mm', right: '15mm' },
  });

  console.log(
    `[render-manual-pdf] Wrote site/manual.pdf (version ${RELEASE_TAG}, ${formattedDate})`
  );
} finally {
  await browser.close();
}
