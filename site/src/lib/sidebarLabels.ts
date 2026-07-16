// IMPORTANT: Keep in sync with astro.config.mjs sidebar config.
//
// This module provides breadcrumb-label lookup for StarlightHead.astro.
// Acronym preservation: the titleCase fallback honors the ACRONYMS list so
// slugs like "esp32" render as "ESP32" instead of "Esp32" (Gemini review
// 14-REVIEWS.md Suggestion 2 - 2026-04-18).

/**
 * Project-standard acronyms that must retain canonical casing when a slug
 * segment falls through the sidebar-label lookup into titleCase.
 *
 * All entries stored in UPPERCASE; membership check compares the segment's
 * uppercase form. Matched segments return this canonical uppercase form.
 *
 * If a future acronym needs MIXED case (e.g. IoT), convert this Set to a
 * Map<uppercase, canonical> and use the map's value as the output.
 */
export const ACRONYMS: ReadonlySet<string> = new Set([
  'ESP32', 'HA', 'PID', 'RPM', 'PWM', 'RGB', 'MCU', 'LED',
  'SEO', 'JSON', 'LD', 'HTML', 'CSS', 'URL', 'API', 'OG', 'SKU',
]);

const segmentLabels: Record<string, string> = {
  // Top-level groups
  'getting-started': 'Getting Started',
  'reference': 'Reference',

  // Getting Started items
  'first-setup': 'First Setup',
  'home-assistant': 'Home Assistant',
  'firmware-updates': 'Firmware Updates',
  'troubleshooting': 'Troubleshooting',

  // Reference groups
  'hardware': 'Hardware',
  'modules': 'Modules',

  // Hardware items
  'rev-3-x': 'Rev 3.x (3.1/3.2/3.3)',
  'rev-3-0': 'Rev 3.0',
  'rev-2-0': 'Rev 2.0',
  'rev-1-0': 'Rev 1.0',

  // Module items
  'temperature-pid': 'Temperature PID',
  'temperature-linear': 'Temperature Linear',
  'temperature-curve': 'Temperature Curve',
  'rpm-pi-control': 'RPM PI Control',
  'rpm-status-leds': 'RPM Status LEDs',
  'stall-guard': 'Stall Guard',

  // Other reference items
  'fan-compatibility': 'Fan Compatibility',
};

/**
 * Title-case a hyphen-delimited segment, preserving project acronyms.
 *
 * Examples:
 *   titleCase('getting-started') -> 'Getting Started'
 *   titleCase('esp32')           -> 'ESP32'   (via ACRONYMS)
 *   titleCase('esp32-modules')   -> 'ESP32 Modules'
 *   titleCase('ha-config')       -> 'HA Config'
 *   titleCase('unknown-segment') -> 'Unknown Segment'
 */
function titleCase(segment: string): string {
  return segment
    .split('-')
    .map((word) => {
      const upper = word.toUpperCase();
      if (ACRONYMS.has(upper)) {
        return upper;
      }
      if (word.length === 0) {
        return '';
      }
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(' ');
}

export function getSegmentLabel(segment: string): string {
  return segmentLabels[segment] ?? titleCase(segment);
}

export function getHomeLabel(): string {
  return 'Home';
}
