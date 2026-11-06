# English rules

This file lists the rules for English docs pages. The rules are adapted from the principles of ASD-STE100 Issue 9. They are the project's own set, called "Docs style", and they do not use the approved word list of that specification. This file follows its own rules.

## How to read this file

Every rule has an ID (EN-01 onward), a name, a tag and a level per tier.

- A name such as `DocsEN.Dashes` is the Vale rule that checks it. The tag H means no Vale rule exists and a person checks the rule with the checklist at the end of this file.
- Tags: M is machine-checked. M? is a heuristic at suggestion level only, because the pattern also matches valid text. H is human-reviewed.
- Levels are written strict, moderate, free. A level is `error`, `warning`, `suggestion` or `NO` (the rule is off for that tier).
- `err*` is a shorthand. It means `warning` on every page, plus `error` on the pages listed for that rule in `blocking.yml`.
- Bad examples are shown inside inline code. A rule never has to be broken in running text to show it.
- A basis names the topic of the standard that inspired the rule. Section numbers appear only when a secondary source gave one, and they are marked unconfirmed.

The tier of a page comes from `page-tiers.yml`. Steps and caution or danger asides count as STRICT on every page (see "Element escalation").

## Rules for every tier

These six rules apply on every page, whatever its tier.

### EN-01 DocsEN.Dashes

- **Tag and levels:** M. Strict `err*`, moderate `err*`, free `err*`.
- **Rule:** Do not use a dash as punctuation. This covers an em dash (U+2014), an en dash (U+2013) with spaces around it, a double hyphen and a spaced single hyphen. Use a comma, a colon, brackets or two sentences. Write ranges as "20 to 30".
- **Basis:** Project rule. The German tekom catalogue has a matching rule (Z 109).
- **Good:** Connect the fan first. Then connect the power supply.
- **Bad:** `Connect the fan -- then the power supply.`

### EN-02 DocsEN.Headings

- **Tag and levels:** M. Strict `suggestion`, moderate `suggestion`, free `suggestion`.
- **Rule:** Write headings in sentence case. Only the first word and proper names start with a capital letter. Product names keep their own casing, such as Home Assistant and ESPHome.
- **Basis:** Project choice. Today the docs mix sentence case and title case, so this rule is a direction and not a description.
- **Good:** Check the fan connector
- **Bad:** `Check The Fan Connector`

### EN-03 DocsEN.Spelling

- **Tag and levels:** M. Strict `warning`, moderate `warning`, free `warning`.
- **Rule:** Use American spelling. The ASD specification is based on American English, and the docs mix both forms today. The table after this list shows the forms found in the docs.
- **Basis:** Adapted from the ASD-STE100 spelling principle (per a secondary source, rule 1.14, unconfirmed).
- **Good:** The color of the LED shows the fan speed.
- **Bad:** `The colour of the LED shows the fan speed.`

Spelling list, with the number of uses in the docs today:

| Use | Avoid | Count today (avoid / use) |
|---|---|---|
| color | colour | 12 / 15 |
| behavior | behaviour | 14 / 19 |
| center | centre | 10 / 0 |
| license | licence | 0 / 7 |
| analyze | analyse | 1 / 0 |
| recognize | recognise | 1 / 0 |

### EN-04 DocsEN.Units

- **Tag and levels:** M. Strict `suggestion`, moderate `suggestion`, free `suggestion`.
- **Rule:** Write a number, a space and the unit symbol, including the percent sign. See "Units and numbers".
- **Basis:** Project decision D-05, with the BIPM SI Brochure for the percent sign.
- **Good:** The board needs 12 V.
- **Bad:** `The board needs 12V.`

### EN-05 DocsEN.Brands

- **Tag and levels:** M. Strict `warning`, moderate `warning`, free `warning`. Active after glossary approval.
- **Rule:** Write brand and product names with the casing in the glossary (row G-15 and the brand rows).
- **Basis:** Project choice, one form per name.
- **Good:** The Qwiic connector carries I2C.
- **Bad:** `The QWIIC connector carries I2C.`

### EN-06 DocsEN.SafetyTitle

- **Tag and levels:** M. Strict `warning`, moderate `warning`, free `warning`.
- **Rule:** The title of a caution or danger aside starts with CAUTION:, WARNING: or DANGER:. See `safety.md`.
- **Basis:** Adapted from the ASD-STE100 principle on warning words, and informed by IEC/IEEE 82079-1 (low confidence).
- **Good:** `:::caution[CAUTION: Unregulated power supply]`
- **Bad:** `:::caution[Use a regulated power supply]`

## Strict tier

STRICT pages are procedures, safety and warning notices, troubleshooting, flashing, first setup, standalone setup and compliance warnings. The rules below apply to the whole page. The six rules above apply too.

| Rule | Name | Tag | Level on strict pages |
|---|---|---|---|
| EN-07 | `DocsEN.SentenceLength` | M | `warning` |
| EN-08 | `DocsEN.ParagraphLength` | M | `suggestion` |
| EN-09 | `DocsEN.Passive` | M? | `suggestion` |
| EN-10 | `DocsEN.Contractions` | M | `warning` |
| EN-11 | `DocsEN.Semicolons` | M | `warning` |
| EN-12 | `DocsEN.Abbreviations` | M | `warning` |
| EN-13 | `DocsEN.Vague` | M | `suggestion` |
| EN-14 | `DocsEN.Terms` | M | `warning` (after glossary approval) |

### EN-07 DocsEN.SentenceLength

- **Tag and levels:** M. Strict `warning`, moderate `suggestion`, free `NO`.
- **Rule:** A sentence in running text has at most 25 words. The rule skips steps, safety asides and tables, which have their own limit or none.
- **Basis:** Adapted from the ASD-STE100 principle on short sentences (per a secondary source, rule 5.1, unconfirmed). The number 25 is a project choice (see "Thresholds and their sources").
- **Good:** The board reads the temperature and sends it to Home Assistant. Home Assistant decides the fan speed and sends it back.
- **Bad:** `The board reads the temperature from the sensor and sends the value to Home Assistant, which then decides on the fan speed and tells the board to apply it to all four fans at once.`

### EN-08 DocsEN.ParagraphLength

- **Tag and levels:** M. Strict `suggestion`, moderate `NO`, free `NO`.
- **Rule:** A paragraph has at most 6 sentences. Start a new paragraph for a new topic.
- **Basis:** Adapted from the ASD-STE100 principle on paragraph size. The number 6 comes from one secondary source and is a project choice.
- **Good:** Two paragraphs of three sentences, one about wiring and one about software.
- **Bad:** `One paragraph of nine sentences that mixes wiring and software.`

### EN-09 DocsEN.Passive

- **Tag and levels:** M?. Strict `suggestion`, moderate `suggestion`, free `NO`.
- **Rule:** Prefer the active voice. The passive is fine when the agent is unknown or does not matter. The check is a pattern heuristic, so many of its hits are valid. Treat a hit as a question, not as an error.
- **Basis:** Adapted from the ASD-STE100 principle on active voice (per a secondary source, rule 3.6, unconfirmed).
- **Good:** The module sets the fan speed.
- **Bad:** `The fan speed is set by the module.`

### EN-10 DocsEN.Contractions

- **Tag and levels:** M. Strict `warning`, moderate `warning`, free `NO`.
- **Rule:** Write out contractions. A contraction hides a negation that matters in instructions.
- **Basis:** Adapted from the ASD-STE100 principle on plain, unambiguous verb forms.
- **Good:** Do not connect the fan while the power is on.
- **Bad:** `Don't connect the fan while the power is on.`

### EN-11 DocsEN.Semicolons

- **Tag and levels:** M. Strict `warning`, moderate `warning`, free `NO`.
- **Rule:** Do not use semicolons. Write two sentences.
- **Basis:** Adapted from the ASD-STE100 punctuation topic (per a secondary source, rule 8.1, unconfirmed).
- **Good:** Connect the fan. Then connect the power supply.
- **Bad:** `Connect the fan; then connect the power supply.`

### EN-12 DocsEN.Abbreviations

- **Tag and levels:** M. Strict `warning`, moderate `warning`, free `NO`. Tables are excluded.
- **Rule:** Do not use Latin or shortened words that end in a period. See "Abbreviations" for the list.
- **Basis:** Project choice. It also protects the sentence-length checks, because Vale's sentence splitter ends a sentence at the period (see "Thresholds and their sources").
- **Good:** Use a fan with four wires, for example a PWM fan.
- **Bad:** `Use a fan with four wires, e.g. a PWM fan.`

### EN-13 DocsEN.Vague

- **Tag and levels:** M. Strict `suggestion`, moderate `suggestion`, free `NO`.
- **Rule:** Avoid vague words such as usually, typically, probably, simply, various and might. Give the condition or the number. If the uncertainty is real, state it once and say why.
- **Basis:** Adapted from the ASD-STE100 principle on precise words.
- **Good:** Some fans keep a minimum speed at 0 percent.
- **Bad:** `The fan usually stops at 0 percent.`

### EN-14 DocsEN.Terms

- **Tag and levels:** M. Strict `warning`, moderate `warning`, free `NO`. Active after glossary approval.
- **Rule:** Use the preferred term of the glossary for each concept. The avoid column lists the forms that the rule flags.
- **Basis:** Adapted from the ASD-STE100 principle of one word per meaning.
- **Good:** Connect the fan to the board.
- **Bad:** `Connect the fan to the unit.` (when "unit" means the board)

## Moderate tier

MODERATE pages are module reference, hardware revision pages, the datasheet and Qwiic examples. The six cross-tier rules apply. The rules of the strict tier apply with these changes.

| Rule | Level on moderate pages |
|---|---|
| `DocsEN.SentenceLength` | `suggestion` (strict: `warning`) |
| `DocsEN.ParagraphLength` | `NO` (strict: `suggestion`) |
| `DocsEN.Passive` | `suggestion` (same as strict) |
| `DocsEN.Contractions` | `warning` (same as strict) |
| `DocsEN.Semicolons` | `warning` (same as strict) |
| `DocsEN.Abbreviations` | `warning` (same as strict) |
| `DocsEN.Vague` | `suggestion` (same as strict) |
| `DocsEN.Terms` | `warning` (same as strict) |

The idea: reference text may run a little longer, but it keeps the same vocabulary and punctuation habits as procedures. Numbered steps and caution or danger asides on a moderate page follow the strict limits through element escalation.

## Free tier

FREE pages are blog posts and the landing pages. Only the cross-tier rules apply: no dash punctuation, sentence-case headings, American spelling, units, brand names from the glossary and the safety title pattern.

Contractions, first person plural and longer sentences are allowed. The guidance for these pages is the set of principles in ISO 24495-1: text should be relevant, findable, understandable and usable. A linter cannot check them.

## Element escalation

A numbered step or a caution or danger aside is STRICT on every page. Six rules carry this wording onto MODERATE and FREE pages. Each one limits itself to the steps scope (`ol > li`) or to the safety scope (caution and danger asides).

### EN-15 DocsEN.SentenceLengthSteps

- **Tag and levels:** M. Strict `warning`, moderate `warning`, free `warning`.
- **Rule:** A sentence in a numbered step has at most 20 words.
- **Basis:** Adapted from the ASD-STE100 principle on short sentences in procedures. The number 20 is the figure that both secondary sources give.
- **Good:** Open the Improv Serial page in Chrome or Edge.
- **Bad:** `Open a tool that speaks Improv Serial, such as the browser page for it in Chrome or Edge, or use any other client that you already trust and can reach.`

### EN-16 DocsEN.SentenceLengthSafety

- **Tag and levels:** M. Strict `warning`, moderate `warning`, free `warning`.
- **Rule:** A sentence in a caution or danger aside has at most 20 words.
- **Basis:** Same as EN-15. Short sentences matter most where a reader acts under risk.
- **Good:** This voltage damages the board permanently. Use a regulated 12 V supply.
- **Bad:** `This voltage can damage the board permanently, so you need to make sure that the supply you use is a regulated one before you connect anything.`

### EN-17 DocsEN.ParagraphLengthStrictElements

- **Tag and levels:** M. Strict `NO`, moderate `suggestion`, free `suggestion`.
- **Rule:** A paragraph inside a step or a safety aside has at most 6 sentences. On strict pages EN-08 already covers the whole page, so this rule is off there.
- **Basis:** Same as EN-08.

### EN-18 DocsEN.StrictElements

- **Tag and levels:** M. Strict `NO`, moderate `NO`, free `warning`.
- **Rule:** Inside steps and safety asides, the contraction, semicolon and abbreviation checks of EN-10, EN-11 and EN-12 apply. On strict and moderate pages those rules already cover the whole page. On free pages they are off, so this rule turns them on for the two elements.
- **Basis:** Same as EN-10, EN-11 and EN-12.

### EN-19 DocsEN.StrictElementsHints

- **Tag and levels:** M. Strict `NO`, moderate `NO`, free `suggestion`.
- **Rule:** Inside steps and safety asides, the passive and vague-word hints of EN-09 and EN-13 apply. The same reasoning as EN-18 explains why only free pages need it.
- **Basis:** Same as EN-09 and EN-13.

### EN-20 DocsEN.TermsStrictElements

- **Tag and levels:** M. Strict `NO`, moderate `NO`, free `warning`. Active after glossary approval.
- **Rule:** Inside steps and safety asides, the glossary term swaps of EN-14 apply. Free pages need the rule because EN-14 is off there.
- **Basis:** Same as EN-14.

## Thresholds and their sources

The numbers in the rules are project choices. The table says how far each one is backed.

| Threshold | Value | Source | Status |
|---|---|---|---|
| Words per sentence in steps and safety notices | 20 | A Wikipedia summary of STE gives 20. A second secondary source confirms 20 for the short-sentence rule. | Project choice, partly confirmed |
| Words per sentence in running text | 25 | The Wikipedia summary only | Project choice, unconfirmed |
| Sentences per paragraph | 6 | The Wikipedia summary only | Project choice, unconfirmed |
| Nouns in a noun cluster | 3 | The Wikipedia summary only | Human rule EN-25, unconfirmed |

Reading the official ASD-STE100 PDF (free on request) would confirm or correct these numbers. Until then, treat them as this project's choices.

Vale's sentence splitter ends a sentence at a period after an abbreviation. A sentence with `approx.` or `Fig.` in it is counted as two sentences, so its length is wrong. This is one reason EN-12 bans abbreviations. Vale also counts a hyphenated compound such as "PWM-Signal" as two words, so counts run slightly high.

## Abbreviations

Do not use these forms outside tables and code:

- `e.g.`, `i.e.` and `etc.`
- `approx.`, `vs.`, `Fig.`, `incl.` and `resp.`
- `max.` or `min.` before a number

Write the full words instead: "for example", "that is", "and so on", "about", "against", "see the figure", "including", "or", "at most" and "at least".

These are allowed:

- Unit symbols such as V, A, kHz and mm.
- Established acronyms written without periods: USB, PWM, RPM, I2C, ESP32.
- HA for Home Assistant, but only in tables and only after the full name has been written on the page.
- Any abbreviation inside a table cell.

Write every other abbreviation out at its first use on a page (see EN-28).

## Units and numbers

Write a number, a space and the unit: `12 V`, `25 kHz`, `3 A`. Use a decimal point, as in `2.5 A`. Write the percent sign the same way, with a space: `50 %`.

Use a non-breaking space between number and unit where the source format allows it. In Markdown and MDX write the entity `&nbsp;`, for example `12&nbsp;V`. Inside inline code, code blocks and frontmatter write a plain space, because those places do not decode entities.

The entity was checked once. A one-off `node` run against `@mdx-js/mdx` 3.1.1 under `site/node_modules` compiled `12&nbsp;V` and the output held the character U+00A0, not the text `&nbsp;`. MDX therefore keeps a non-breaking space.

The percent sign with a space is a project choice for English. The BIPM SI Brochure (9th edition, section 5.4.7) says that a space separates the number from the symbol %. Many English style guides write `50%` without a space, so the choice is a convention and not a fact. It keeps one rule for English and German, because DIN 5008 spaces the percent sign in German.

Today the docs write `12V` 29 times and `12 V` 10 times, and `50%` 105 times and `50 %` 5 times. The rule starts at suggestion level for that reason.

## Human review checklist

Check these rules by reading. No Vale rule covers them. Use the list on every STRICT page and on every step and safety aside elsewhere.

### EN-21 One instruction per step

- **Tag:** H. **Basis:** adapted from the ASD-STE100 principle of one instruction per sentence unless actions happen at the same time (per a secondary source, rule 5.2, unconfirmed).
- **Good:** Disconnect the power supply. In the next step, remove the fan.
- **Bad:** `Disconnect the power supply and remove the fan, then reconnect the cable.`

### EN-22 Imperative in steps

- **Tag:** H. **Basis:** adapted from the ASD-STE100 principle on commands (per a secondary source, rule 5.3, unconfirmed).
- **Good:** Press the reset button.
- **Bad:** `The reset button should be pressed.`

### EN-23 Condition first

- **Tag:** H. **Basis:** adapted from the ASD-STE100 principle on warnings that start with a command or a condition.
- **Good:** If the LED is off, check the power supply.
- **Bad:** `Check the power supply if the LED is off.`

### EN-24 No -ing forms as verbs

- **Tag:** H. A pattern check is too noisy, because it matches 909 words in the docs. **Basis:** adapted from the ASD-STE100 principle on the -ing form (per a secondary source, rule 3.5, unconfirmed).
- **Good:** The board reads the sensor every second.
- **Bad:** `The board is reading the sensor every second.`

### EN-25 Noun clusters of at most three nouns

- **Tag:** H. **Basis:** adapted from the ASD-STE100 principle on noun clusters (per a secondary source, rule 2.1, unconfirmed).
- **Good:** the gain of the fan speed loop
- **Bad:** `fan speed control loop gain value`

### EN-26 Do not omit articles

- **Tag:** H. **Basis:** adapted from the ASD-STE100 principle on complete sentences.
- **Good:** Connect the fan to the header.
- **Bad:** `Connect fan to header.`

### EN-27 Notes give information only

- **Tag:** H. **Basis:** adapted from the ASD-STE100 principle that notes carry no commands.
- **Good:** Note: The board keeps the last speed after a reboot.
- **Bad:** `Note: Disconnect the power first.` (move this into a step)

### EN-28 Write out an abbreviation at first use

- **Tag:** H. **Basis:** adapted from the ASD-STE100 principle on defined terms. Applies to HA, SELV, OTA and similar short forms.
- **Good:** The over-the-air (OTA) update needs a working WiFi link.
- **Bad:** `The OTA update needs a working WiFi link.` (on the first use on the page)

### EN-29 Safety notices have four parts

- **Tag:** H. **Basis:** adapted from the ASD-STE100 principle on warnings, informed by IEC/IEEE 82079-1 (low confidence).
- **Rule:** Signal word, type and source of the hazard, consequence, how to avoid it. See `safety.md` for the structure and an example.
