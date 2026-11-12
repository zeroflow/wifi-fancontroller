# Safety notices

This file defines how the docs warn readers. It maps the Starlight aside types to hazard levels, fixes the signal words in English and German, and describes the title pattern and the structure of a notice.

The mapping is a design choice of this project. It is informed by IEC/IEEE 82079-1:2019, but the standard is paywalled and only secondary sources were read, so confidence is low. Read the standard before treating the signal word rules as final.

## Aside types and hazard levels

Starlight offers four aside types and no "warning" type. The docs use them as follows.

| Starlight type | Meaning | Use |
|---|---|---|
| `danger` | Risk of injury or death | Reserved. Zero uses are correct for a 12 V product that stays in the safety extra-low voltage range. The RF separation distance is the nearest candidate. |
| `caution` | Risk of damage to the product, connected equipment or data, or minor injury | Overvoltage from an unregulated supply, wrong polarity, a flash that overwrites stored WiFi credentials |
| `note` | Information that is not an instruction | Context and scope statements |
| `tip` | Optional advice | Never safety-relevant |

A notice that tells the reader to do something belongs in the text or in a step. A `note` carries information only.

## Signal words

| Language | Signal words, from highest to lowest hazard |
|---|---|
| English | DANGER, WARNING, CAUTION, NOTICE |
| German | GEFAHR, WARNUNG, VORSICHT, HINWEIS |

The type decides which words are allowed in a title:

- `danger`: DANGER or WARNING in English, GEFAHR or WARNUNG in German.
- `caution`: CAUTION in English, VORSICHT in German.
- `note` and `tip`: no signal word.

The words NOTICE and HINWEIS exist in the word set for property damage. This project covers property damage with `caution`, so it does not use them in titles.

Starlight prints a default label when an aside has no custom title. The English labels are Note, Tip, Caution and Danger. The German labels are Hinweis, Tipp, Achtung and Gefahr. "Achtung" is not a signal word of this guide. Almost every aside in the docs sets a custom title, so the type shows only as a CSS class and an icon, and the reader sees no signal word.

## Title pattern

The title of a `caution` or `danger` aside starts with the signal word in capitals, followed by a colon. The rest of the title is a short phrase that names the hazard.

- English: `CAUTION:`, `WARNING:` or `DANGER:`
- German: `VORSICHT:`, `WARNUNG:` or `GEFAHR:`

A good title: `:::caution[CAUTION: Unregulated power supply]`. A title that fails: `:::caution[Use a regulated power supply]`.

`DocsEN.SafetyTitle` and `DocsDE.SafetyTitle` check the pattern on every page, at warning level. They check only the shape of the title. A person checks which word fits which type, using the table above.

An aside without a custom title shows the Starlight default label, which does not match the pattern. Give every `caution` and `danger` aside a title.

## Notice structure

A notice has four parts. This is a human-reviewed rule (tag H).

1. The signal word.
2. The type and the source of the hazard.
3. The consequence if the reader ignores it.
4. How to avoid the hazard.

An example for the English docs:

```markdown
:::caution[CAUTION: Unregulated power supply]
A transformer supply without regulation can output 15 to 18 V at low load. This voltage damages the board permanently. Use a regulated 12 V supply.
:::
```

Keep the notice short. One notice names one hazard. Put the notice before the step where the hazard arises, not after it.

## Wording

In English, write instructions in the imperative. Start with the condition when there is one: "If the fan does not spin, check the connector." Keep each sentence within the 20 word limit that applies to safety notices.

In German, address the reader with "Sie" and use the imperative: "Verwenden Sie ein geregeltes Netzteil." This is mandatory because safety notices are STRICT (see decision 1 of the gender convention in `de.md`). Do not write instructions as a bare infinitive. State the condition first, as in English.

Do not soften a warning with words such as "usually" or "should". If a risk is real, state it. If it is only possible under a condition, state the condition.

## Findings for the rewrite passes

The measurements below describe the docs as they stand. Each one is a finding for the rewrite passes that follow the fact review. None of them is fixed in this phase, and no page was changed.

**No caution or danger title starts with a signal word.** The docs have 63 caution asides and 6 danger asides, and none of the 69 titles starts with CAUTION, WARNING, DANGER or the German equivalents. The `SafetyTitle` rules will report all of them.

**`danger` is used for configuration faults and licensing, not for harm to people.** Six uses on four pages:

- `reference/modules/temperature-curve-triple-independent.md`: a misspelled sensor id, and an unordered axis
- `reference/modules/temperature-curve-triple.md`: an unordered axis, and a misspelled sensor id
- `reference/qwiic/examples/bme680-bsec2.md`: accepting the Bosch BSEC2 license
- `reference/qwiic/examples/scd41.md`: a calibration setting that is probably wrong for a fan controller

Under the mapping above, none of them describes a risk of injury or death. Each is a candidate for `caution` or `note`. List the current uses again with `grep -rn ':::danger' site/src/content/docs`.

**`caution` is used for troubleshooting blocks.** The titles are questions about a symptom, and the blocks hold step lists. English: "USB not detected? (ESP32-S2)" in `getting-started/first-setup.mdx` and `getting-started/firmware-updates.mdx`, and "USB not working?" in `reference/hardware/rev-2-0.mdx`, `rev-3-0.mdx` and `rev-3-x.mdx`. German: "USB nicht erkannt? (ESP32-S2)" in `de/getting-started/first-setup.mdx`, and "USB funktioniert nicht?" in the three German hardware pages of the same names. A troubleshooting aid is not a hazard. These blocks are candidates for `note`, or for a plain subsection with steps.

**Twelve `caution` asides have no custom title.** They show the Starlight default label. They sit in `reference/modules/index.md` (6), `reference/modules/rpm-pi-control.md` (2), `reference/qwiic/combining.md` (2), `reference/modules/stall-guard.md` (1) and `reference/qwiic/index.md` (1).

**The German compliance page does not use asides for its warning.** `de/reference/compliance.md` uses inline paragraphs that start with "Warnung:" and "Hinweis:". The warning about old transformer supplies is the main case. It should become a `caution` aside with a `VORSICHT:` title, written as a four-part notice.
