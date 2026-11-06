# Documentation style guide

This folder holds the written contract for the docs site in `site/src/content/docs`. The project style is called "Docs style". It covers English and German, three tiers of strictness, a glossary, safety notice rules and the prose lint that checks part of it.

## Purpose and audience

The audience is contributors and Claude. Anyone who writes or edits a docs page reads this guide first, then runs the lint before opening a pull request.

The guide has two goals. Readers of the docs should find short, consistent, unambiguous text, especially in procedures and warnings. Contributors should get the same answer to a style question every time, whoever answers it.

The guide adapts published standards and does not copy them. See "Sources and license" below.

## Where this guide lives

The guide is repo-only and is not published on the docs site. Anything placed under `site/src/content/docs` becomes a page, a sidebar entry, a sitemap entry and a search result, and it would itself fall under the tiers it describes. The folders `.planning/` and the file `CLAUDE.md` are gitignored, so they cannot carry a contract that every contributor must see.

Keep all guide files in `site/style-guide/`. Never move them into `site/src/content/docs`, `site/src/pages` or `site/public`.

## Tiers

Every content page belongs to one tier. The tier decides which rules apply and how strictly.

| Tier | Pages |
|---|---|
| STRICT | Procedures, safety and warning notices, troubleshooting, flashing, first setup, standalone setup, compliance warnings |
| MODERATE | Module reference, hardware revision pages, the datasheet, Qwiic examples |
| FREE | Blog posts and the landing pages |

Two kinds of element are STRICT on every page, whatever the page tier. These are numbered steps (`ol > li`) and caution or danger asides. This is called element escalation. The rule catalogue in [en.md](en.md) and [de.md](de.md) names the rules that carry it, for example `SentenceLengthSteps` and `StrictElements`.

The map from page to tier lives in `page-tiers.yml`. It is the single source: the lint config is generated from it. A new content file needs an entry there, or `bash site/scripts/verify-prose.sh --map` fails.

Some built pages are not content files and are never linted: print routes, blog tag and author pages, redirect stubs, the 404 page, the PID simulator, and the English fallback copies that appear under `/de/` when no German page exists. The map check keeps German rules away from those copies.

## Rule files

| File | Content |
|---|---|
| [en.md](en.md) | English rules per tier, with examples and the human review checklist |
| [de.md](de.md) | German rules per tier (written in German), with the tekom rule IDs they rest on |
| [safety.md](safety.md) | Safety notices: aside types, hazard levels, signal words, title pattern, structure |
| [glossary.md](glossary.md) | One preferred term per concept in English and German, with a status per row |

Three data files drive the tooling. `page-tiers.yml` maps pages to tiers. `blocking.yml` lists the pages where a rule blocks CI. `rule-levels.yml` maps every rule to a level per tier. The last file arrives together with the remaining Vale rules.

## Machine-checked and human-reviewed rules

Every rule carries a tag. M means a Vale rule checks it. M? means a Vale heuristic checks it at suggestion level only, because the pattern also matches valid text. H means a person checks it with the checklist at the end of `en.md` or `de.md`.

Vale cannot check what the H rules cover. A linter finds words and patterns. It does not know whether a step holds one instruction or whether a warning explains the risk. The lint is a safety net for the cheap checks, and the checklist does the rest.

## Running the lint

The lint reads the built site, not the Markdown source. Vale runs on the HTML in `site/dist` because smartypants and the Starlight components only exist after the build. Docker must be installed.

```bash
npm --prefix site run build
bash site/scripts/verify-prose.sh
```

Without a flag the script runs every check except `--write-config` and `--baseline`. Each flag runs one part.

| Flag | What it does |
|---|---|
| `--test` | Runs the Vale test cases of the own styles, with coverage. |
| `--lint` | Lints the mapped pages, prints the report and sets the exit code. |
| `--selftest` | Plants a dash in a clean page and proves the exit code flips. |
| `--write-config` | Regenerates the per-tier sections of `site/.vale.ini` and exits. |
| `--map` | Checks the page map, the generated config and the ratchet list. |
| `--pin` | Checks that one exact Vale tag is used and no style packages are fetched. |
| `--glossary` | Checks that glossary terms and swap rules agree. |
| `--guide` | Checks the guide files for dashes, forbidden claims and rule names. |
| `--baseline` | Regenerates `baseline.md`, the measured violations per tier and rule. |

The flags `--glossary`, `--guide` and `--baseline` arrive with the remaining Phase 22 work. Until then the script rejects them as unknown flags.

## CI and the ratchet

The workflow `.github/workflows/lint-docs.yml` runs on pull requests and on pushes to main that touch `site/**`. It builds the site and runs the same script as a local run.

Warnings and suggestions never fail the job. Errors come only from rules listed for a page in `blocking.yml`. A page that is clean for a listed rule can never get dirty again unnoticed. This is the ratchet.

The ratchet works in both directions. When a page becomes clean for a rule, add it to `blocking.yml` in the same commit. The script prints a line starting with `RATCHET:` that shows the exact YAML line to add, and the job fails until you add it. Promoting a further rule into `blocking.yml` is a later decision, after the fact review and the rewrite passes.

The checks `vale test` and the map check always block, because they test the tooling and not the prose. After you edit `page-tiers.yml` or `blocking.yml`, run `bash site/scripts/verify-prose.sh --write-config`.

## Bumping Vale

The Vale version is pinned to one image tag. The script defines it once as `VALE_IMAGE` in `site/scripts/verify-prose.sh`, and this guide quotes it once: `jdkato/vale:v3.26.0` is the current pin.

Dependabot does not track image tags inside workflow run steps. This is an assumption that was not verified, so a bump is a manual task. Vale ships about once a month, and a new release can change how a rule behaves. Bump on purpose, not by accident.

1. Read the Vale changelog between the old and the new tag.
2. Change the tag in both places: `VALE_IMAGE` in `site/scripts/verify-prose.sh` and the quoted tag in this section.
3. Run `bash site/scripts/verify-prose.sh --pin`. It fails if the two places disagree or if more than one tag exists.
4. Run `--test`, then the full script after a fresh build.
5. Fix rule tests that changed behavior, and commit the bump on its own.

## Typography decisions

The docs use no dash punctuation in English or German. An em dash (U+2014), an en dash (U+2013) used as punctuation, a double hyphen and a spaced single hyphen all count as the same violation. Use a comma, a colon, brackets or two sentences instead. Write number ranges as "20 to 30".

The lint reads built output because the build changes the text. The smartypants step of the site build used to turn a double hyphen in the source into an em dash, so a grep over the source passed while the page failed. The site build now has smartypants dashes switched off. A double hyphen therefore renders literally, and the `Dashes` rule in both languages catches it.

That setting reaches Markdown pages only. The MDX integration ignores it, so ten MDX pages and one frontmatter value on the home page still render a dash character from a double hyphen in their source. The `Dashes` rule flags the character as well, so the lint still sees them. They are fixed during the rewrite passes that follow the fact review, and until then they warn and do not block.

Quotation marks are not linted. German quotation marks are deferred (see "Open items").

## Sources and license

ASD-STE100 Simplified Technical English, Issue 9 (2025-01-15), is the basis for the English rules. The specification is free as a PDF on request. It is copyright and trademark of ASD. The guide adapts its principles and rule topics, such as short sentences, one instruction per sentence and active voice. It copies no rule text and no dictionary entry. It uses no ASD or STE name in rule names or messages. Rule numbers that come from a secondary source are unconfirmed until someone reads the official PDF.

tekom, "Regelbasiertes Schreiben: Deutsch für die Technische Kommunikation", 2nd edition 2013, ISBN 978-3-9814055-9-0 (softcover) and 978-3-944449-55-5 (PDF), is the rule catalogue for the German rules. Rules are cited by ID. The rule titles come from the free sample's table of contents, the guide paraphrases the topics, and the thresholds are the project's own choice, because the guideline is a catalogue and not a mandate.

IEC/IEEE 82079-1:2019 informs the structure of instructions and warnings. The text is paywalled, so the signal word mapping in `safety.md` relies on secondary sources and has low confidence.

ISO 24495-1:2023, plain language, supplies the principles for the FREE tier: text should be relevant, findable, understandable and usable. A linter cannot check them.

DIN SPEC 33429:2025-03 was considered and rejected. It describes Leichte Sprache, which serves a different audience than people configuring ESPHome.

DIN 5008 gives the German rule for spacing numbers, units and the percent sign. The BIPM SI Brochure, 9th edition, section 5.4.7, says that a space separates a number from the percent symbol, which the guide also uses for English.

The guide adapts ideas from these sources and makes no claim beyond that.

## Open items

These ideas are deferred and not part of the current work:

- German quotation marks through a per-locale smartypants setting.
- Buying IEC/IEEE 82079-1 and the tekom book to harden the safety rules and read the rule bodies.
- Requesting the ASD-STE100 Issue 9 PDF to confirm the sentence and paragraph limits.
- Closing the MDX dash gap described under "Typography decisions", either in the rewrite passes or with direct MDX dependencies.
