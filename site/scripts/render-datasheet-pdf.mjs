// site/scripts/render-datasheet-pdf.mjs
//
// Renders the Rev 3.3 datasheet print routes (src/pages/datasheet-print/ and
// src/pages/de/datasheet-print/) into two versioned/dated PDFs via headless
// Chromium. Same shape as render-manual-pdf.mjs, extended to loop over both
// language variants; plain `playwright` rather than `@playwright/test`,
// matching the project's one-shot scripts/*.mjs convention.
//
// This runs from the release-triggered publish-datasheet.yml workflow, so
// both RELEASE_TAG and RELEASE_DATE must already be set by that workflow. If
// either is missing this throws rather than stamping a placeholder version
// into a customer-facing document.
//
// Expects site/dist to already be built (`npm run build`, which itself fails
// loudly if a datasheet source is missing) and served at http://localhost:4321
// (e.g. `npm run preview -- --port 4321`) before this script runs. Never point
// Playwright at a file:// URL: Astro's root-relative asset paths do not
// resolve under file://, silently dropping CSS.
import { chromium } from 'playwright';

const RELEASE_TAG = process.env.RELEASE_TAG;
const RELEASE_DATE = process.env.RELEASE_DATE; // ISO string, e.g. github.event.release.published_at
const BASE_URL = process.env.BASE_URL ?? 'http://localhost:4321';

if (!RELEASE_TAG || !RELEASE_DATE) {
  throw new Error(
    'RELEASE_TAG and RELEASE_DATE must be set - this script only runs from ' +
      'the release-triggered publish-datasheet.yml workflow.'
  );
}

// Asset names carry the revision explicitly: these land next to the firmware
// binaries on the release, and a future revision's datasheet must not be
// mistakable for this one.
const VARIANTS = [
  {
    lang: 'en',
    path: '/datasheet-print/',
    out: 'fancontroller-rev3.3-datasheet-en.pdf',
    locale: 'en-GB',
    pageLabel: 'Page',
  },
  {
    lang: 'de',
    path: '/de/datasheet-print/',
    out: 'fancontroller-rev3.3-datasheet-de.pdf',
    locale: 'de-AT',
    pageLabel: 'Seite',
  },
];

// Every page footer shows a non-empty version and date sourced from the
// triggering release. Built as a Playwright footerTemplate string, NOT CSS
// @page margin boxes or position:fixed: neither repeats reliably across
// printed pages in Chromium's print engine.
const buildFooter = (variant) => {
  const formattedDate = new Date(RELEASE_DATE).toLocaleDateString(variant.locale);
  return `
    <div style="font-size:9px; width:100%; text-align:center; color:#555; padding:0 15mm;">
      Rev 3.3 &middot; Version ${RELEASE_TAG} &middot; ${formattedDate} &middot;
      ${variant.pageLabel} <span class="pageNumber"></span> / <span class="totalPages"></span>
    </div>
  `;
};

const browser = await chromium.launch(); // headless by default - page.pdf() requires this
try {
  for (const variant of VARIANTS) {
    const page = await browser.newPage();
    await page.goto(`${BASE_URL}${variant.path}`, { waitUntil: 'networkidle' });

    await page.pdf({
      path: variant.out,
      format: 'A4',
      printBackground: true,
      displayHeaderFooter: true,
      headerTemplate: '<span></span>', // empty - the footer carries the required info
      footerTemplate: buildFooter(variant),
      // Sized to comfortably fit the footer's font size: a small default
      // margin.bottom clips or overlaps footer text with body content.
      margin: { top: '15mm', bottom: '18mm', left: '15mm', right: '15mm' },
    });

    await page.close();
    console.log(
      `[render-datasheet-pdf] Wrote site/${variant.out} (${variant.lang}, version ${RELEASE_TAG})`
    );
  }
} finally {
  await browser.close();
}
