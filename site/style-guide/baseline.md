# Prose lint baseline

Measured violations of the docs prose lint, handed to Phase 23 and the rewrite passes. Counts only: no page text is quoted, so the file does not change when a sentence is edited.

## How this file is made

- Command: `bash site/scripts/verify-prose.sh --baseline`
- Vale image: `jdkato/vale:v3.26.0`
- Commit: `4c0da92` (HEAD when the file was generated; a rerun on a later commit changes this line and no other)
- Mapped pages: 47 (see `page-tiers.yml`)
- Alerts counted: 1471

The command builds nothing. Run `npm --prefix site run build` first. It lints the mapped pages of `site/dist` with the same configuration as CI and does not fail on findings. The level columns are the levels Vale reports, which come from `rule-levels.yml` and `blocking.yml`.

## Totals by tier and rule

### English (DocsEN)

| Tier | Rule | Error | Warning | Suggestion | Total |
|---|---|---|---|---|---|
| strict | DocsEN.Contractions | 0 | 19 | 0 | 19 |
| strict | DocsEN.Dashes | 0 | 50 | 0 | 50 |
| strict | DocsEN.Headings | 0 | 0 | 13 | 13 |
| strict | DocsEN.Passive | 0 | 0 | 42 | 42 |
| strict | DocsEN.SafetyTitle | 0 | 7 | 0 | 7 |
| strict | DocsEN.Semicolons | 0 | 6 | 0 | 6 |
| strict | DocsEN.SentenceLength | 0 | 33 | 0 | 33 |
| strict | DocsEN.SentenceLengthSafety | 0 | 1 | 0 | 1 |
| strict | DocsEN.SentenceLengthSteps | 0 | 5 | 0 | 5 |
| strict | DocsEN.Spelling | 0 | 7 | 0 | 7 |
| strict | DocsEN.Terms | 0 | 8 | 0 | 8 |
| strict | DocsEN.Units | 0 | 0 | 29 | 29 |
| strict | DocsEN.Vague | 0 | 0 | 4 | 4 |
| moderate | DocsEN.Abbreviations | 0 | 7 | 0 | 7 |
| moderate | DocsEN.Brands | 0 | 8 | 0 | 8 |
| moderate | DocsEN.Contractions | 0 | 20 | 0 | 20 |
| moderate | DocsEN.Dashes | 0 | 168 | 0 | 168 |
| moderate | DocsEN.Headings | 0 | 0 | 160 | 160 |
| moderate | DocsEN.Passive | 0 | 0 | 165 | 165 |
| moderate | DocsEN.SafetyTitle | 0 | 45 | 0 | 45 |
| moderate | DocsEN.Semicolons | 0 | 61 | 0 | 61 |
| moderate | DocsEN.SentenceLength | 0 | 0 | 183 | 183 |
| moderate | DocsEN.SentenceLengthSafety | 0 | 51 | 0 | 51 |
| moderate | DocsEN.SentenceLengthSteps | 0 | 18 | 0 | 18 |
| moderate | DocsEN.Spelling | 0 | 30 | 0 | 30 |
| moderate | DocsEN.Terms | 0 | 10 | 0 | 10 |
| moderate | DocsEN.Units | 0 | 0 | 161 | 161 |
| moderate | DocsEN.Vague | 0 | 0 | 20 | 20 |
| free | DocsEN.Dashes | 0 | 23 | 0 | 23 |
| free | DocsEN.Headings | 0 | 0 | 22 | 22 |
| free | DocsEN.Spelling | 0 | 1 | 0 | 1 |
| free | DocsEN.Units | 0 | 0 | 24 | 24 |

English total: 1401 alerts (0 errors, 578 warnings, 823 suggestions).

### German (DocsDE)

| Tier | Rule | Error | Warning | Suggestion | Total |
|---|---|---|---|---|---|
| strict | DocsDE.Passive | 0 | 0 | 3 | 3 |
| strict | DocsDE.RoleNouns | 0 | 7 | 0 | 7 |
| strict | DocsDE.SafetyTitle | 0 | 3 | 0 | 3 |
| strict | DocsDE.Semicolons | 0 | 2 | 0 | 2 |
| strict | DocsDE.SentenceLength | 0 | 1 | 0 | 1 |
| strict | DocsDE.SentenceLengthSteps | 0 | 3 | 0 | 3 |
| strict | DocsDE.Subjunctive | 0 | 0 | 1 | 1 |
| moderate | DocsDE.Brands | 0 | 8 | 0 | 8 |
| moderate | DocsDE.Passive | 0 | 0 | 1 | 1 |
| moderate | DocsDE.RoleNouns | 0 | 4 | 0 | 4 |
| moderate | DocsDE.SafetyTitle | 0 | 7 | 0 | 7 |
| moderate | DocsDE.Semicolons | 0 | 8 | 0 | 8 |
| moderate | DocsDE.SentenceLength | 0 | 0 | 8 | 8 |
| moderate | DocsDE.Terms | 0 | 1 | 0 | 1 |
| moderate | DocsDE.Units | 0 | 0 | 11 | 11 |
| moderate | DocsDE.Vague | 0 | 0 | 2 | 2 |

German total: 70 alerts (0 errors, 44 warnings, 26 suggestions).

## Pages

One row per mapped page. The last column lists the rules with at least one alert on the page and their counts.

| Page | Tier | Alerts | Rules |
|---|---|---|---|
| blog/server-rack-cooling-esp32-home-assistant.md | free | 28 | DocsEN.Dashes 17, DocsEN.Headings 6, DocsEN.Units 5 |
| de/getting-started/first-setup.mdx | strict | 11 | DocsDE.Passive 1, DocsDE.RoleNouns 3, DocsDE.SafetyTitle 3, DocsDE.SentenceLength 1, DocsDE.SentenceLengthSteps 3 |
| de/index.mdx | free | 0 | none |
| de/reference/compliance.md | strict | 9 | DocsDE.Passive 2, DocsDE.RoleNouns 4, DocsDE.Semicolons 2, DocsDE.Subjunctive 1 |
| de/reference/datasheet.md | moderate | 7 | DocsDE.Passive 1, DocsDE.SentenceLength 4, DocsDE.Terms 1, DocsDE.Vague 1 |
| de/reference/hardware/index.md | moderate | 4 | DocsDE.Brands 4 |
| de/reference/hardware/rev-1-0.mdx | moderate | 4 | DocsDE.RoleNouns 1, DocsDE.Semicolons 2, DocsDE.SentenceLength 1 |
| de/reference/hardware/rev-2-0.mdx | moderate | 6 | DocsDE.RoleNouns 1, DocsDE.SafetyTitle 2, DocsDE.Semicolons 2, DocsDE.SentenceLength 1 |
| de/reference/hardware/rev-3-0.mdx | moderate | 11 | DocsDE.Brands 2, DocsDE.RoleNouns 1, DocsDE.SafetyTitle 2, DocsDE.Semicolons 2, DocsDE.SentenceLength 1, DocsDE.Units 3 |
| de/reference/hardware/rev-3-x.mdx | moderate | 18 | DocsDE.Brands 2, DocsDE.RoleNouns 1, DocsDE.SafetyTitle 3, DocsDE.Semicolons 2, DocsDE.SentenceLength 1, DocsDE.Units 8, DocsDE.Vague 1 |
| getting-started/firmware-updates.mdx | strict | 22 | DocsEN.Contractions 2, DocsEN.Dashes 6, DocsEN.Headings 3, DocsEN.Passive 4, DocsEN.SafetyTitle 1, DocsEN.Terms 5, DocsEN.Units 1 |
| getting-started/first-setup.mdx | strict | 35 | DocsEN.Contractions 4, DocsEN.Headings 2, DocsEN.Passive 3, DocsEN.SafetyTitle 4, DocsEN.SentenceLength 2, DocsEN.SentenceLengthSafety 1, DocsEN.SentenceLengthSteps 3, DocsEN.Spelling 2, DocsEN.Terms 1, DocsEN.Units 13 |
| getting-started/home-assistant.mdx | strict | 17 | DocsEN.Contractions 1, DocsEN.Dashes 4, DocsEN.Headings 8, DocsEN.Passive 2, DocsEN.SentenceLength 1, DocsEN.Units 1 |
| getting-started/index.mdx | moderate | 4 | DocsEN.Contractions 1, DocsEN.Headings 2, DocsEN.Terms 1 |
| getting-started/troubleshooting.md | strict | 79 | DocsEN.Contractions 11, DocsEN.Dashes 36, DocsEN.Passive 13, DocsEN.SentenceLength 3, DocsEN.Terms 2, DocsEN.Units 12, DocsEN.Vague 2 |
| index.mdx | free | 42 | DocsEN.Dashes 6, DocsEN.Headings 16, DocsEN.Spelling 1, DocsEN.Units 19 |
| reference/compliance.md | strict | 16 | DocsEN.Passive 8, DocsEN.Semicolons 1, DocsEN.SentenceLength 2, DocsEN.Spelling 5 |
| reference/datasheet.md | moderate | 18 | DocsEN.Passive 8, DocsEN.SentenceLength 6, DocsEN.Spelling 4 |
| reference/fan-compatibility.md | moderate | 38 | DocsEN.Abbreviations 1, DocsEN.Dashes 1, DocsEN.Headings 6, DocsEN.Passive 4, DocsEN.Semicolons 1, DocsEN.SentenceLength 8, DocsEN.Units 16, DocsEN.Vague 1 |
| reference/hardware/index.md | moderate | 11 | DocsEN.Brands 4, DocsEN.Dashes 5, DocsEN.Headings 1, DocsEN.Passive 1 |
| reference/hardware/rev-1-0.mdx | moderate | 19 | DocsEN.Abbreviations 1, DocsEN.Dashes 3, DocsEN.Headings 6, DocsEN.Semicolons 1, DocsEN.SentenceLength 1, DocsEN.Spelling 1, DocsEN.Units 6 |
| reference/hardware/rev-2-0.mdx | moderate | 20 | DocsEN.Contractions 1, DocsEN.Dashes 2, DocsEN.Headings 5, DocsEN.SafetyTitle 2, DocsEN.Semicolons 1, DocsEN.SentenceLength 1, DocsEN.Spelling 1, DocsEN.Units 7 |
| reference/hardware/rev-3-0.mdx | moderate | 26 | DocsEN.Brands 2, DocsEN.Contractions 1, DocsEN.Dashes 2, DocsEN.Headings 6, DocsEN.SafetyTitle 2, DocsEN.Semicolons 1, DocsEN.SentenceLength 1, DocsEN.Spelling 1, DocsEN.Units 10 |
| reference/hardware/rev-3-x.mdx | moderate | 58 | DocsEN.Brands 2, DocsEN.Contractions 1, DocsEN.Dashes 9, DocsEN.Headings 13, DocsEN.Passive 3, DocsEN.SafetyTitle 5, DocsEN.Semicolons 1, DocsEN.SentenceLength 3, DocsEN.SentenceLengthSafety 1, DocsEN.Spelling 1, DocsEN.Units 19 |
| reference/index.md | moderate | 4 | DocsEN.Headings 2, DocsEN.Passive 1, DocsEN.Semicolons 1 |
| reference/modules/fallback-mode.md | moderate | 27 | DocsEN.Headings 1, DocsEN.Passive 8, DocsEN.SafetyTitle 1, DocsEN.Semicolons 1, DocsEN.SentenceLength 11, DocsEN.SentenceLengthSafety 1, DocsEN.SentenceLengthSteps 3, DocsEN.Vague 1 |
| reference/modules/index.md | moderate | 53 | DocsEN.Contractions 4, DocsEN.Dashes 16, DocsEN.Headings 7, DocsEN.Passive 9, DocsEN.SafetyTitle 2, DocsEN.Semicolons 3, DocsEN.SentenceLength 5, DocsEN.SentenceLengthSafety 5, DocsEN.Terms 1, DocsEN.Vague 1 |
| reference/modules/rpm-pi-control.md | moderate | 60 | DocsEN.Dashes 32, DocsEN.Headings 13, DocsEN.Passive 5, DocsEN.SafetyTitle 1, DocsEN.Semicolons 1, DocsEN.SentenceLength 5, DocsEN.SentenceLengthSteps 2, DocsEN.Terms 1 |
| reference/modules/rpm-status-leds.md | moderate | 31 | DocsEN.Contractions 1, DocsEN.Dashes 8, DocsEN.Headings 9, DocsEN.Passive 4, DocsEN.SafetyTitle 1, DocsEN.SentenceLength 3, DocsEN.Units 5 |
| reference/modules/stall-guard.md | moderate | 66 | DocsEN.Abbreviations 3, DocsEN.Contractions 3, DocsEN.Dashes 16, DocsEN.Headings 15, DocsEN.Passive 9, DocsEN.SafetyTitle 1, DocsEN.Semicolons 1, DocsEN.SentenceLength 4, DocsEN.SentenceLengthSteps 5, DocsEN.Terms 2, DocsEN.Units 7 |
| reference/modules/temperature-curve-dual.md | moderate | 32 | DocsEN.Dashes 7, DocsEN.Headings 4, DocsEN.Passive 2, DocsEN.SafetyTitle 2, DocsEN.Semicolons 6, DocsEN.SentenceLength 7, DocsEN.SentenceLengthSafety 3, DocsEN.Units 1 |
| reference/modules/temperature-curve-triple-independent.md | moderate | 58 | DocsEN.Headings 5, DocsEN.Passive 15, DocsEN.SafetyTitle 4, DocsEN.Semicolons 6, DocsEN.SentenceLength 11, DocsEN.SentenceLengthSafety 7, DocsEN.SentenceLengthSteps 2, DocsEN.Spelling 3, DocsEN.Units 3, DocsEN.Vague 2 |
| reference/modules/temperature-curve-triple.md | moderate | 54 | DocsEN.Dashes 7, DocsEN.Headings 4, DocsEN.Passive 9, DocsEN.SafetyTitle 4, DocsEN.Semicolons 9, DocsEN.SentenceLength 9, DocsEN.SentenceLengthSafety 5, DocsEN.Spelling 2, DocsEN.Units 3, DocsEN.Vague 2 |
| reference/modules/temperature-curve.md | moderate | 99 | DocsEN.Abbreviations 1, DocsEN.Contractions 3, DocsEN.Dashes 18, DocsEN.Headings 17, DocsEN.Passive 10, DocsEN.SafetyTitle 1, DocsEN.Semicolons 4, DocsEN.SentenceLength 5, DocsEN.SentenceLengthSafety 3, DocsEN.Terms 3, DocsEN.Units 34 |
| reference/modules/temperature-linear.md | moderate | 47 | DocsEN.Dashes 10, DocsEN.Headings 11, DocsEN.Passive 1, DocsEN.SafetyTitle 1, DocsEN.Semicolons 2, DocsEN.SentenceLength 3, DocsEN.SentenceLengthSafety 3, DocsEN.Terms 1, DocsEN.Units 14, DocsEN.Vague 1 |
| reference/modules/temperature-pid.md | moderate | 58 | DocsEN.Contractions 3, DocsEN.Dashes 18, DocsEN.Headings 14, DocsEN.Passive 3, DocsEN.SafetyTitle 2, DocsEN.Semicolons 3, DocsEN.SentenceLength 5, DocsEN.SentenceLengthSafety 2, DocsEN.Units 5, DocsEN.Vague 3 |
| reference/modules/usr-buttons-mode.md | moderate | 121 | DocsEN.Headings 8, DocsEN.Passive 28, DocsEN.SafetyTitle 5, DocsEN.Semicolons 7, DocsEN.SentenceLength 37, DocsEN.SentenceLengthSafety 12, DocsEN.SentenceLengthSteps 3, DocsEN.Spelling 16, DocsEN.Units 3, DocsEN.Vague 2 |
| reference/modules/usr-buttons.md | moderate | 51 | DocsEN.Contractions 2, DocsEN.Dashes 13, DocsEN.Headings 7, DocsEN.Passive 7, DocsEN.SafetyTitle 2, DocsEN.Semicolons 6, DocsEN.SentenceLength 6, DocsEN.SentenceLengthSafety 2, DocsEN.SentenceLengthSteps 2, DocsEN.Spelling 1, DocsEN.Units 2, DocsEN.Vague 1 |
| reference/qwiic/combining.md | moderate | 65 | DocsEN.Dashes 1, DocsEN.Headings 1, DocsEN.Passive 6, DocsEN.SafetyTitle 1, DocsEN.Semicolons 1, DocsEN.SentenceLength 31, DocsEN.SentenceLengthSafety 1, DocsEN.Units 22, DocsEN.Vague 1 |
| reference/qwiic/examples/bme680-bsec2.md | moderate | 15 | DocsEN.Passive 4, DocsEN.SafetyTitle 3, DocsEN.SentenceLength 4, DocsEN.SentenceLengthSafety 2, DocsEN.Units 2 |
| reference/qwiic/examples/bme680.md | moderate | 4 | DocsEN.Passive 2, DocsEN.SentenceLength 1, DocsEN.Vague 1 |
| reference/qwiic/examples/ds2484.md | moderate | 19 | DocsEN.Passive 11, DocsEN.Semicolons 1, DocsEN.SentenceLength 5, DocsEN.Vague 2 |
| reference/qwiic/examples/scd41.md | moderate | 32 | DocsEN.Headings 3, DocsEN.Passive 9, DocsEN.SafetyTitle 3, DocsEN.Semicolons 4, DocsEN.SentenceLength 7, DocsEN.SentenceLengthSafety 2, DocsEN.SentenceLengthSteps 1, DocsEN.Terms 1, DocsEN.Vague 2 |
| reference/qwiic/examples/ssd1306.md | moderate | 5 | DocsEN.Passive 2, DocsEN.SafetyTitle 1, DocsEN.SentenceLength 1, DocsEN.SentenceLengthSafety 1 |
| reference/qwiic/index.md | moderate | 12 | DocsEN.Abbreviations 1, DocsEN.Passive 4, DocsEN.SafetyTitle 1, DocsEN.SentenceLength 3, DocsEN.SentenceLengthSafety 1, DocsEN.Units 2 |
| reference/standalone.mdx | strict | 44 | DocsEN.Passive 9, DocsEN.SafetyTitle 1, DocsEN.Semicolons 3, DocsEN.SentenceLength 25, DocsEN.SentenceLengthSteps 2, DocsEN.Units 2, DocsEN.Vague 2 |
| reference/web-server.mdx | strict | 11 | DocsEN.Contractions 1, DocsEN.Dashes 4, DocsEN.Passive 3, DocsEN.SafetyTitle 1, DocsEN.Semicolons 2 |

## Ratchet candidates

A candidate is a page with zero alerts for a rule that is not yet blocking there, where the rule is on in the page's tier. Promoting a candidate means adding the page to `blocking.yml`, which is a decision for later and not an action of this file. The lint itself already fails when a page is clean for a rule that has a `blocking.yml` header and is not listed.

### English (DocsEN)

- `DocsEN.SentenceLength`: 5 of 36 pages are clean: `getting-started/firmware-updates.mdx`, `getting-started/index.mdx`, `reference/hardware/index.md`, `reference/index.md`, `reference/web-server.mdx`
- `DocsEN.SentenceLengthSteps`: 29 of 38 pages are clean: `blog/server-rack-cooling-esp32-home-assistant.md`, `getting-started/firmware-updates.mdx`, `getting-started/home-assistant.mdx`, `getting-started/index.mdx`, `getting-started/troubleshooting.md`, `index.mdx`, `reference/compliance.md`, `reference/datasheet.md`, `reference/fan-compatibility.md`, `reference/hardware/index.md`, `reference/hardware/rev-1-0.mdx`, `reference/hardware/rev-2-0.mdx`, `reference/hardware/rev-3-0.mdx`, `reference/hardware/rev-3-x.mdx`, `reference/index.md`, `reference/modules/index.md`, `reference/modules/rpm-status-leds.md`, `reference/modules/temperature-curve-dual.md`, `reference/modules/temperature-curve-triple.md`, `reference/modules/temperature-curve.md`, `reference/modules/temperature-linear.md`, `reference/modules/temperature-pid.md`, `reference/qwiic/combining.md`, `reference/qwiic/examples/bme680-bsec2.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ds2484.md`, `reference/qwiic/examples/ssd1306.md`, `reference/qwiic/index.md`, `reference/web-server.mdx`
- `DocsEN.SentenceLengthSafety`: 21 of 38 pages are clean: `blog/server-rack-cooling-esp32-home-assistant.md`, `getting-started/firmware-updates.mdx`, `getting-started/home-assistant.mdx`, `getting-started/index.mdx`, `getting-started/troubleshooting.md`, `index.mdx`, `reference/compliance.md`, `reference/datasheet.md`, `reference/fan-compatibility.md`, `reference/hardware/index.md`, `reference/hardware/rev-1-0.mdx`, `reference/hardware/rev-2-0.mdx`, `reference/hardware/rev-3-0.mdx`, `reference/index.md`, `reference/modules/rpm-pi-control.md`, `reference/modules/rpm-status-leds.md`, `reference/modules/stall-guard.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ds2484.md`, `reference/standalone.mdx`, `reference/web-server.mdx`
- `DocsEN.ParagraphLength`: all 7 pages where the rule is on are clean.
- `DocsEN.ParagraphLengthStrictElements`: all 31 pages where the rule is on are clean.
- `DocsEN.Headings`: 10 of 38 pages are clean: `getting-started/troubleshooting.md`, `reference/compliance.md`, `reference/datasheet.md`, `reference/qwiic/examples/bme680-bsec2.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ds2484.md`, `reference/qwiic/examples/ssd1306.md`, `reference/qwiic/index.md`, `reference/standalone.mdx`, `reference/web-server.mdx`
- `DocsEN.SafetyTitle`: 13 of 38 pages are clean: `blog/server-rack-cooling-esp32-home-assistant.md`, `getting-started/home-assistant.mdx`, `getting-started/index.mdx`, `getting-started/troubleshooting.md`, `index.mdx`, `reference/compliance.md`, `reference/datasheet.md`, `reference/fan-compatibility.md`, `reference/hardware/index.md`, `reference/hardware/rev-1-0.mdx`, `reference/index.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ds2484.md`
- `DocsEN.Passive`: 4 of 36 pages are clean: `getting-started/index.mdx`, `reference/hardware/rev-1-0.mdx`, `reference/hardware/rev-2-0.mdx`, `reference/hardware/rev-3-0.mdx`
- `DocsEN.Contractions`: 21 of 36 pages are clean: `reference/compliance.md`, `reference/datasheet.md`, `reference/fan-compatibility.md`, `reference/hardware/index.md`, `reference/hardware/rev-1-0.mdx`, `reference/index.md`, `reference/modules/fallback-mode.md`, `reference/modules/rpm-pi-control.md`, `reference/modules/temperature-curve-dual.md`, `reference/modules/temperature-curve-triple-independent.md`, `reference/modules/temperature-curve-triple.md`, `reference/modules/temperature-linear.md`, `reference/modules/usr-buttons-mode.md`, `reference/qwiic/combining.md`, `reference/qwiic/examples/bme680-bsec2.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ds2484.md`, `reference/qwiic/examples/scd41.md`, `reference/qwiic/examples/ssd1306.md`, `reference/qwiic/index.md`, `reference/standalone.mdx`
- `DocsEN.Semicolons`: 12 of 36 pages are clean: `getting-started/firmware-updates.mdx`, `getting-started/first-setup.mdx`, `getting-started/home-assistant.mdx`, `getting-started/index.mdx`, `getting-started/troubleshooting.md`, `reference/datasheet.md`, `reference/hardware/index.md`, `reference/modules/rpm-status-leds.md`, `reference/qwiic/examples/bme680-bsec2.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ssd1306.md`, `reference/qwiic/index.md`
- `DocsEN.Abbreviations`: 31 of 36 pages are clean: `getting-started/firmware-updates.mdx`, `getting-started/first-setup.mdx`, `getting-started/home-assistant.mdx`, `getting-started/index.mdx`, `getting-started/troubleshooting.md`, `reference/compliance.md`, `reference/datasheet.md`, `reference/hardware/index.md`, `reference/hardware/rev-2-0.mdx`, `reference/hardware/rev-3-0.mdx`, `reference/hardware/rev-3-x.mdx`, `reference/index.md`, `reference/modules/fallback-mode.md`, `reference/modules/index.md`, `reference/modules/rpm-pi-control.md`, `reference/modules/rpm-status-leds.md`, `reference/modules/temperature-curve-dual.md`, `reference/modules/temperature-curve-triple-independent.md`, `reference/modules/temperature-curve-triple.md`, `reference/modules/temperature-linear.md`, `reference/modules/temperature-pid.md`, `reference/modules/usr-buttons-mode.md`, `reference/modules/usr-buttons.md`, `reference/qwiic/combining.md`, `reference/qwiic/examples/bme680-bsec2.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ds2484.md`, `reference/qwiic/examples/scd41.md`, `reference/qwiic/examples/ssd1306.md`, `reference/standalone.mdx`, `reference/web-server.mdx`
- `DocsEN.Vague`: 21 of 36 pages are clean: `getting-started/firmware-updates.mdx`, `getting-started/first-setup.mdx`, `getting-started/home-assistant.mdx`, `getting-started/index.mdx`, `reference/compliance.md`, `reference/datasheet.md`, `reference/hardware/index.md`, `reference/hardware/rev-1-0.mdx`, `reference/hardware/rev-2-0.mdx`, `reference/hardware/rev-3-0.mdx`, `reference/hardware/rev-3-x.mdx`, `reference/index.md`, `reference/modules/rpm-pi-control.md`, `reference/modules/rpm-status-leds.md`, `reference/modules/stall-guard.md`, `reference/modules/temperature-curve-dual.md`, `reference/modules/temperature-curve.md`, `reference/qwiic/examples/bme680-bsec2.md`, `reference/qwiic/examples/ssd1306.md`, `reference/qwiic/index.md`, `reference/web-server.mdx`
- `DocsEN.Spelling`: 26 of 38 pages are clean: `blog/server-rack-cooling-esp32-home-assistant.md`, `getting-started/firmware-updates.mdx`, `getting-started/home-assistant.mdx`, `getting-started/index.mdx`, `getting-started/troubleshooting.md`, `reference/fan-compatibility.md`, `reference/hardware/index.md`, `reference/index.md`, `reference/modules/fallback-mode.md`, `reference/modules/index.md`, `reference/modules/rpm-pi-control.md`, `reference/modules/rpm-status-leds.md`, `reference/modules/stall-guard.md`, `reference/modules/temperature-curve-dual.md`, `reference/modules/temperature-curve.md`, `reference/modules/temperature-linear.md`, `reference/modules/temperature-pid.md`, `reference/qwiic/combining.md`, `reference/qwiic/examples/bme680-bsec2.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ds2484.md`, `reference/qwiic/examples/scd41.md`, `reference/qwiic/examples/ssd1306.md`, `reference/qwiic/index.md`, `reference/standalone.mdx`, `reference/web-server.mdx`
- `DocsEN.Units`: 13 of 38 pages are clean: `getting-started/index.mdx`, `reference/compliance.md`, `reference/datasheet.md`, `reference/hardware/index.md`, `reference/index.md`, `reference/modules/fallback-mode.md`, `reference/modules/index.md`, `reference/modules/rpm-pi-control.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ds2484.md`, `reference/qwiic/examples/scd41.md`, `reference/qwiic/examples/ssd1306.md`, `reference/web-server.mdx`
- `DocsEN.StrictElements`: all 2 pages where the rule is on are clean.
- `DocsEN.StrictElementsHints`: all 2 pages where the rule is on are clean.
- `DocsEN.Terms`: 26 of 36 pages are clean: `getting-started/home-assistant.mdx`, `reference/compliance.md`, `reference/datasheet.md`, `reference/fan-compatibility.md`, `reference/hardware/index.md`, `reference/hardware/rev-1-0.mdx`, `reference/hardware/rev-2-0.mdx`, `reference/hardware/rev-3-0.mdx`, `reference/hardware/rev-3-x.mdx`, `reference/index.md`, `reference/modules/fallback-mode.md`, `reference/modules/rpm-status-leds.md`, `reference/modules/temperature-curve-dual.md`, `reference/modules/temperature-curve-triple-independent.md`, `reference/modules/temperature-curve-triple.md`, `reference/modules/temperature-pid.md`, `reference/modules/usr-buttons-mode.md`, `reference/modules/usr-buttons.md`, `reference/qwiic/combining.md`, `reference/qwiic/examples/bme680-bsec2.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ds2484.md`, `reference/qwiic/examples/ssd1306.md`, `reference/qwiic/index.md`, `reference/standalone.mdx`, `reference/web-server.mdx`
- `DocsEN.TermsStrictElements`: all 2 pages where the rule is on are clean.
- `DocsEN.Brands`: 35 of 38 pages are clean: `blog/server-rack-cooling-esp32-home-assistant.md`, `getting-started/firmware-updates.mdx`, `getting-started/first-setup.mdx`, `getting-started/home-assistant.mdx`, `getting-started/index.mdx`, `getting-started/troubleshooting.md`, `index.mdx`, `reference/compliance.md`, `reference/datasheet.md`, `reference/fan-compatibility.md`, `reference/hardware/rev-1-0.mdx`, `reference/hardware/rev-2-0.mdx`, `reference/index.md`, `reference/modules/fallback-mode.md`, `reference/modules/index.md`, `reference/modules/rpm-pi-control.md`, `reference/modules/rpm-status-leds.md`, `reference/modules/stall-guard.md`, `reference/modules/temperature-curve-dual.md`, `reference/modules/temperature-curve-triple-independent.md`, `reference/modules/temperature-curve-triple.md`, `reference/modules/temperature-curve.md`, `reference/modules/temperature-linear.md`, `reference/modules/temperature-pid.md`, `reference/modules/usr-buttons-mode.md`, `reference/modules/usr-buttons.md`, `reference/qwiic/combining.md`, `reference/qwiic/examples/bme680-bsec2.md`, `reference/qwiic/examples/bme680.md`, `reference/qwiic/examples/ds2484.md`, `reference/qwiic/examples/scd41.md`, `reference/qwiic/examples/ssd1306.md`, `reference/qwiic/index.md`, `reference/standalone.mdx`, `reference/web-server.mdx`

### German (DocsDE)

- `DocsDE.SentenceLength`: 2 of 8 pages are clean: `de/reference/compliance.md`, `de/reference/hardware/index.md`
- `DocsDE.SentenceLengthSteps`: 8 of 9 pages are clean: `de/index.mdx`, `de/reference/compliance.md`, `de/reference/datasheet.md`, `de/reference/hardware/index.md`, `de/reference/hardware/rev-1-0.mdx`, `de/reference/hardware/rev-2-0.mdx`, `de/reference/hardware/rev-3-0.mdx`, `de/reference/hardware/rev-3-x.mdx`
- `DocsDE.SentenceLengthSafety`: all 9 pages where the rule is on are clean.
- `DocsDE.Passive`: 5 of 8 pages are clean: `de/reference/hardware/index.md`, `de/reference/hardware/rev-1-0.mdx`, `de/reference/hardware/rev-2-0.mdx`, `de/reference/hardware/rev-3-0.mdx`, `de/reference/hardware/rev-3-x.mdx`
- `DocsDE.Subjunctive`: 7 of 8 pages are clean: `de/getting-started/first-setup.mdx`, `de/reference/datasheet.md`, `de/reference/hardware/index.md`, `de/reference/hardware/rev-1-0.mdx`, `de/reference/hardware/rev-2-0.mdx`, `de/reference/hardware/rev-3-0.mdx`, `de/reference/hardware/rev-3-x.mdx`
- `DocsDE.Abbreviations`: all 8 pages where the rule is on are clean.
- `DocsDE.Vague`: 6 of 8 pages are clean: `de/getting-started/first-setup.mdx`, `de/reference/compliance.md`, `de/reference/hardware/index.md`, `de/reference/hardware/rev-1-0.mdx`, `de/reference/hardware/rev-2-0.mdx`, `de/reference/hardware/rev-3-0.mdx`
- `DocsDE.Pronouns`: all 8 pages where the rule is on are clean.
- `DocsDE.Semicolons`: 3 of 8 pages are clean: `de/getting-started/first-setup.mdx`, `de/reference/datasheet.md`, `de/reference/hardware/index.md`
- `DocsDE.Exclamations`: all 8 pages where the rule is on are clean.
- `DocsDE.Units`: 7 of 9 pages are clean: `de/getting-started/first-setup.mdx`, `de/index.mdx`, `de/reference/compliance.md`, `de/reference/datasheet.md`, `de/reference/hardware/index.md`, `de/reference/hardware/rev-1-0.mdx`, `de/reference/hardware/rev-2-0.mdx`
- `DocsDE.SafetyTitle`: 5 of 9 pages are clean: `de/index.mdx`, `de/reference/compliance.md`, `de/reference/datasheet.md`, `de/reference/hardware/index.md`, `de/reference/hardware/rev-1-0.mdx`
- `DocsDE.GenderCharacters`: all 9 pages where the rule is on are clean.
- `DocsDE.StrictElements`: the one page where the rule is on is clean.
- `DocsDE.StrictElementsHints`: the one page where the rule is on is clean.
- `DocsDE.Terms`: 7 of 8 pages are clean: `de/getting-started/first-setup.mdx`, `de/reference/compliance.md`, `de/reference/hardware/index.md`, `de/reference/hardware/rev-1-0.mdx`, `de/reference/hardware/rev-2-0.mdx`, `de/reference/hardware/rev-3-0.mdx`, `de/reference/hardware/rev-3-x.mdx`
- `DocsDE.TermsStrictElements`: the one page where the rule is on is clean.
- `DocsDE.Brands`: 6 of 9 pages are clean: `de/getting-started/first-setup.mdx`, `de/index.mdx`, `de/reference/compliance.md`, `de/reference/datasheet.md`, `de/reference/hardware/rev-1-0.mdx`, `de/reference/hardware/rev-2-0.mdx`
- `DocsDE.RoleNouns`: 3 of 9 pages are clean: `de/index.mdx`, `de/reference/datasheet.md`, `de/reference/hardware/index.md`

## Notes for Phase 23

- The research phase counted violations with draft rules. This file supersedes those numbers: it uses the final rule set, the per-tier levels and the approved glossary.
- The rewrite passes after Phase 23 work from the Pages and Totals tables. A page leaves the table when its row shows zero alerts for the rules it is meant to pass.
- Accepted deferral (maintainer decision during Phase 22): ten MDX pages still carry a double hyphen and `index.mdx` still emits U+2014, because the MDX integration ignores the smartypants setting. They stay as they are, count in the dash rows above, and are fixed in the Phase 23 rewrite passes. This is not a failure of the lint.
- Pages with at least one dash finding today: 23 English, 0 German.
- Regenerate this file with `bash site/scripts/verify-prose.sh --baseline` after `npm --prefix site run build`. The command prints a PASS line when the table totals equal the alert count in the Vale output.
