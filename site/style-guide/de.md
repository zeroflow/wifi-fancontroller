# Deutsche Regeln

Diese Datei listet die Regeln für deutsche Seiten der Dokumentation. Als Regelkatalog dient der tekom-Leitfaden "Regelbasiertes Schreiben: Deutsch für die Technische Kommunikation" (2. Auflage 2013). Die Regeln stehen mit ihren tekom-IDs in der Datei, die Texte der Regeln stehen nicht darin. Die Schwellenwerte wählt das Projekt selbst, weil der Leitfaden ein Katalog ist und keine Vorschrift.

Für den Aufbau von Anleitungen und Warnhinweisen dient IEC/IEEE 82079-1 als Quelle der Anregungen. Die Grundsätze von ISO 24495-1 leiten die Stufe FREE. Die Datei folgt ihren eigenen Regeln.

## So lesen Sie diese Datei

Jede Regel hat eine ID (DE-01 und folgende), einen Namen, ein Kürzel und eine Stufe je Seitentyp.

- Ein Name wie `DocsDE.Dashes` ist die Vale-Regel, die den Punkt prüft. Das Kürzel H steht für eine Regel ohne Vale-Regel. Eine Person prüft sie mit der Checkliste am Ende dieser Datei.
- Kürzel: M bedeutet maschinell geprüft. M? bedeutet Heuristik, nur auf der Ebene `suggestion`, weil das Muster auch gültigen Text trifft. H bedeutet menschliche Prüfung.
- Die Stufen stehen in der Reihenfolge strict, moderate, free. Eine Ebene ist `error`, `warning`, `suggestion` oder `NO` (die Regel ist für diesen Seitentyp aus).
- `err*` ist eine Kurzform. Sie bedeutet `warning` auf jeder Seite und zusätzlich `error` auf den Seiten, die in `blocking.yml` für diese Regel stehen.
- Schlechte Beispiele stehen in Code-Auszeichnung. So muss kein Text die Regel brechen, um sie zu zeigen.
- Die Buchstaben S, B, L und Z kennzeichnen die Gruppen des tekom-Katalogs: Satz, Benennung, Lexik und Zeichensetzung. Die Themen sind hier mit eigenen Worten beschrieben.

Der Seitentyp einer Seite steht in `page-tiers.yml`. Nummerierte Schritte sowie Caution- und Danger-Hinweise gelten auf jeder Seite als STRICT (siehe "Elementeskalation").

## Regeln für alle Stufen

Diese sechs Regeln gelten auf jeder Seite.

### DE-01 DocsDE.Dashes

- **Kürzel und Ebenen:** M. Strict `err*`, moderate `err*`, free `err*`.
- **Regel:** Setzen Sie keinen Gedankenstrich. Das gilt für den Geviertstrich (U+2014), den Halbgeviertstrich (U+2013) mit Leerzeichen, den doppelten Bindestrich und den Bindestrich mit Leerzeichen. Nutzen Sie ein Komma, einen Doppelpunkt, eine Klammer oder zwei Sätze. Schreiben Sie Bereiche als "20 bis 30".
- **Basis:** tekom Z 109, die Regel zum Verzicht auf Gedankenstriche. Sie deckt sich mit der Projektregel D-07.
- **Gut:** Schließen Sie zuerst den Lüfter an. Danach schließen Sie das Netzteil an.
- **Schlecht:** `Schließen Sie zuerst den Lüfter an -- dann das Netzteil.`

### DE-02 DocsDE.Units

- **Kürzel und Ebenen:** M. Strict `suggestion`, moderate `suggestion`, free `suggestion`.
- **Regel:** Schreiben Sie Zahl, Leerzeichen und Einheit, mit Dezimalkomma. Das gilt auch für das Prozentzeichen. Siehe "Zahlen und Einheiten".
- **Basis:** Projektentscheidung D-05, DIN 5008 und tekom B 303 (Zahlenformate festlegen). Die Regeln B 302a und B 302b betreffen Ziffer oder Wort bei kleinen Zahlen. Das Projekt prüft sie nicht.
- **Gut:** `12 V`, `2,5 A`, `50 %`
- **Schlecht:** `12V`, `2.5 A`, `50%`

### DE-03 DocsDE.SafetyTitle

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `warning`, free `warning`.
- **Regel:** Der Titel eines Caution- oder Danger-Hinweises beginnt mit VORSICHT:, WARNUNG: oder GEFAHR:. Welches Wort zu welchem Typ passt, prüft ein Mensch. Siehe `safety.md`.
- **Basis:** Anregung aus IEC/IEEE 82079-1, mit geringer Sicherheit, weil der Text kostenpflichtig ist.
- **Gut:** `:::caution[VORSICHT: Ungeregeltes Netzteil]`
- **Schlecht:** `:::caution[Verwenden Sie ein geregeltes Netzteil]`

### DE-04 DocsDE.GenderCharacters

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `warning`, free `warning`.
- **Regel:** Verwenden Sie keine Gendersonderzeichen: weder Stern, Doppelpunkt oder Unterstrich noch das Binnen-I. Das ist Punkt (4) der Konvention aus dem Abschnitt "Ansprache und geschlechtergerechte Sprache".
- **Basis:** Projektentscheidung D-13. Der tekom-Katalog enthält laut Inhaltsverzeichnis keine Regel zum Gendern.
- **Gut:** Personen, die die Platine betreiben
- **Schlecht:** `Nutzer*innen`, `Nutzer:innen`, `Nutzer_innen`, `NutzerInnen`

### DE-05 DocsDE.Brands

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `warning`, free `warning`. Aktiv erst nach Freigabe des Glossars.
- **Regel:** Schreiben Sie Marken- und Produktnamen so, wie das Glossar es festlegt (Zeile G-15 und die Markenzeilen).
- **Basis:** tekom B 301 (einheitliche Benennungen), als Anregung für eine Schreibweise je Name.
- **Gut:** Der Qwiic-Anschluss führt I2C.
- **Schlecht:** `Der QWIIC-Anschluss führt I2C.`

### DE-06 DocsDE.RoleNouns

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `warning`, free `warning`. Aktiv erst nach Freigabe der Rollenzeilen im Glossar.
- **Regel:** Verwenden Sie für jede Rolle genau die Form aus dem Glossar. Das generische Maskulinum und Partizipformen sind ausgeschlossen. Das sind die Punkte (2) und (5) der Konvention.
- **Basis:** Projektentscheidung D-13 und Glossarzeilen G-10 bis G-14.
- **Gut:** die Elektrofachkraft, die Kundschaft
- **Schlecht:** `der Elektriker`, `die Nutzenden`

## Stufe STRICT

STRICT sind Anleitungen, Sicherheits- und Warnhinweise, Fehlersuche, Flashen, Ersteinrichtung, Standalone-Einrichtung und die Warnhinweise der Compliance-Seite. Die folgenden Regeln gelten für die ganze Seite. Die sechs Regeln oben gelten ebenfalls.

| Regel | Name | Kürzel | Ebene auf STRICT-Seiten |
|---|---|---|---|
| DE-07 | `DocsDE.SentenceLength` | M | `warning` (VORSCHLAG) |
| DE-08 | `DocsDE.Passive` | M? | `suggestion` |
| DE-09 | `DocsDE.Subjunctive` | M | `suggestion` |
| DE-10 | `DocsDE.Abbreviations` | M | `warning` |
| DE-11 | `DocsDE.Vague` | M | `suggestion` |
| DE-12 | `DocsDE.Pronouns` | M | `suggestion` |
| DE-13 | `DocsDE.Semicolons` | M | `warning` |
| DE-14 | `DocsDE.Exclamations` | M | `warning` |
| DE-15 | `DocsDE.Terms` | M | `warning` (nach Freigabe des Glossars) |

### DE-07 DocsDE.SentenceLength

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `suggestion`, free `NO`.
- **Regel:** Ein Satz im Fließtext hat höchstens M Wörter. Steht der Wert M noch nicht fest, ist die Regel nicht geschrieben (siehe "Satzlänge").
- **Basis:** tekom S 302, die Regel gegen zu lange Sätze. Der Leitfaden nennt dafür keine Zahl.
- **Gut:** Die Platine liest die Temperatur und sendet sie an Home Assistant. Home Assistant wählt die Drehzahl und sendet sie zurück.
- **Schlecht:** Ein Satz mit mehr als 25 Wörtern, der Messung, Übertragung und Reaktion in einer Kette verbindet.

### DE-08 DocsDE.Passive

- **Kürzel und Ebenen:** M?. Strict `suggestion`, moderate `suggestion`, free `NO`.
- **Regel:** Schreiben Sie aktiv. Die Prüfung sucht die Formen von "werden" mit Partizip. Viele Treffer sind gültig, zum Beispiel, wenn unklar ist, wer handelt. Lesen Sie einen Treffer als Frage und nicht als Fehler.
- **Basis:** tekom S 501 bis S 504, die Regeln gegen Passiv in verschiedenen Formen.
- **Gut:** Der Regler stellt die Drehzahl ein.
- **Schlecht:** `Die Drehzahl wird vom Regler eingestellt.`

### DE-09 DocsDE.Subjunctive

- **Kürzel und Ebenen:** M. Strict `suggestion`, moderate `suggestion`, free `NO`.
- **Regel:** Schreiben Sie im Präsens und vermeiden Sie den Konjunktiv. Die Prüfung sucht Formen wie `würde`, `könnte`, `sollte`, `wäre` und `hätte`.
- **Basis:** tekom S 507 (Präsens) und S 508 (Konjunktiv).
- **Gut:** Wenn die LED aus ist, prüfen Sie das Netzteil.
- **Schlecht:** `Sie könnten das Netzteil prüfen.`

### DE-10 DocsDE.Abbreviations

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `warning`, free `NO`. Tabellen sind ausgenommen.
- **Regel:** Schreiben Sie Abkürzungen ohne Zahlenwert aus. Die Liste steht im Abschnitt "Abkürzungen".
- **Basis:** tekom B 201. Die Regel schützt außerdem die Satzlängenprüfung, weil Vale Sätze an einem Punkt nach einer Abkürzung trennt.
- **Gut:** Wählen Sie einen Lüfter mit vier Adern, zum Beispiel einen PWM-Lüfter.
- **Schlecht:** `Wählen Sie einen Lüfter mit vier Adern, z. B. einen PWM-Lüfter.`

### DE-11 DocsDE.Vague

- **Kürzel und Ebenen:** M. Strict `suggestion`, moderate `suggestion`, free `NO`.
- **Regel:** Vermeiden Sie ungenaue und wertende Angaben sowie Weichmacher, zum Beispiel `eventuell`, `vielleicht`, `relativ`, `einfach` und `schnell`. Nennen Sie die Bedingung oder die Zahl.
- **Basis:** tekom L 102 (ungenaue Angaben), L 105 (wertende Angaben) und L 110 (Weichmacher).
- **Gut:** Manche Lüfter laufen bei 0 Prozent mit ihrer Mindestdrehzahl weiter.
- **Schlecht:** `Der Lüfter stoppt meistens bei 0 %.`

### DE-12 DocsDE.Pronouns

- **Kürzel und Ebenen:** M. Strict `suggestion`, moderate `suggestion`, free `NO`.
- **Regel:** Vermeiden Sie unpersönliche Pronomen. Die Prüfung sucht das Wort "man". Der Platzhalter "es" bleibt eine Aufgabe der menschlichen Prüfung.
- **Basis:** tekom L 104 (unpersönliche Pronomen). Für S 308 sind die Titel im Inhaltsverzeichnis der Leseprobe nicht lesbar. Deshalb ist die Zuordnung zum Platzhalter "es" unbestätigt.
- **Gut:** Drücken Sie die Reset-Taste.
- **Schlecht:** `Man drückt die Reset-Taste.`

### DE-13 DocsDE.Semicolons

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `warning`, free `NO`.
- **Regel:** Setzen Sie kein Semikolon. Schreiben Sie zwei Sätze.
- **Basis:** tekom Z 116.
- **Gut:** Schließen Sie den Lüfter an. Danach schließen Sie das Netzteil an.
- **Schlecht:** `Schließen Sie den Lüfter an; danach schließen Sie das Netzteil an.`

### DE-14 DocsDE.Exclamations

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `warning`, free `NO`.
- **Regel:** Beenden Sie keinen Satz mit einem Ausrufezeichen. Die Signalwörter der Sicherheitshinweise tragen die Dringlichkeit.
- **Basis:** tekom Z 108.
- **Gut:** Trennen Sie das Netzteil vom Netz.
- **Schlecht:** `Trennen Sie das Netzteil vom Netz!`

### DE-15 DocsDE.Terms

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `warning`, free `NO`. Aktiv erst nach Freigabe des Glossars.
- **Regel:** Nennen Sie jedes Konzept mit dem bevorzugten Begriff des Glossars. Die Spalte "DE meiden" listet die Formen, die die Regel meldet.
- **Basis:** tekom B 301 (einheitliche Benennung von Bedien- und Anzeigeelementen) und L 107 (gebräuchliche Benennungen).
- **Gut:** Schließen Sie den Lüfter an die Platine an.
- **Schlecht:** `Schließen Sie den Lüfter an das Board an.` (wenn "Board" die Platine meint)

## Stufe MODERATE

MODERATE sind Modulreferenz, Hardware-Revisionsseiten, das Datenblatt und die Qwiic-Beispiele. Die sechs Regeln für alle Stufen gelten. Die Regeln der Stufe STRICT gelten mit diesen Änderungen.

| Regel | Ebene auf MODERATE-Seiten |
|---|---|
| `DocsDE.SentenceLength` | `suggestion` (STRICT: `warning`) |
| `DocsDE.Passive` | `suggestion` (wie STRICT) |
| `DocsDE.Subjunctive` | `suggestion` (wie STRICT) |
| `DocsDE.Abbreviations` | `warning` (wie STRICT) |
| `DocsDE.Vague` | `suggestion` (wie STRICT) |
| `DocsDE.Pronouns` | `suggestion` (wie STRICT) |
| `DocsDE.Semicolons` | `warning` (wie STRICT) |
| `DocsDE.Exclamations` | `warning` (wie STRICT) |
| `DocsDE.Terms` | `warning` (wie STRICT) |

Referenztext darf etwas länger laufen, behält aber Wortschatz und Zeichensetzung der Anleitungen. Nummerierte Schritte und Caution- oder Danger-Hinweise auf MODERATE-Seiten folgen durch die Elementeskalation den strengen Grenzen.

## Stufe FREE

FREE sind Blogbeiträge und die Startseiten. Es gelten nur die Regeln für alle Stufen: kein Gedankenstrich, Einheiten, Sicherheitstitel, keine Gendersonderzeichen, Markennamen und Rollenformen aus dem Glossar.

Längere Sätze, Passiv und Konjunktiv sind hier erlaubt. Die Grundsätze von ISO 24495-1 leiten diese Seiten: Der Text soll relevant, auffindbar, verständlich und nutzbar sein. Ein Linter kann sie nicht prüfen.

## Elementeskalation

Ein nummerierter Schritt sowie ein Caution- oder Danger-Hinweis gilt auf jeder Seite als STRICT. Fünf Regeln tragen diese Strenge auf MODERATE- und FREE-Seiten.

### DE-16 DocsDE.SentenceLengthSteps

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `warning`, free `warning`.
- **Regel:** Ein Satz in einem nummerierten Schritt hat höchstens N Wörter (VORSCHLAG: N = 20). Die Regel entsteht erst nach der Entscheidung zu "Satzlänge".
- **Basis:** tekom S 302.
- **Gut:** Öffnen Sie die Improv-Seite in Chrome oder Edge.
- **Schlecht:** Ein Schritt mit mehr als 20 Wörtern, der drei Handlungen verbindet.

### DE-17 DocsDE.SentenceLengthSafety

- **Kürzel und Ebenen:** M. Strict `warning`, moderate `warning`, free `warning`.
- **Regel:** Ein Satz in einem Caution- oder Danger-Hinweis hat höchstens N Wörter (VORSCHLAG: N = 20). Die Regel entsteht erst nach der Entscheidung zu "Satzlänge".
- **Basis:** tekom S 302. Kurze Sätze zählen dort am meisten, wo Menschen unter Risiko handeln.
- **Gut:** Diese Spannung beschädigt die Platine dauerhaft. Verwenden Sie ein geregeltes 12-V-Netzteil.
- **Schlecht:** Ein Satz mit mehr als 20 Wörtern, der Folge, Ursache und Maßnahme zusammenzieht.

### DE-18 DocsDE.StrictElements

- **Kürzel und Ebenen:** M. Strict `NO`, moderate `NO`, free `warning`.
- **Regel:** In Schritten und Sicherheitshinweisen gelten die Prüfungen von DE-10, DE-13 und DE-14 (Abkürzungen, Semikolons, Ausrufezeichen). Auf STRICT- und MODERATE-Seiten gelten sie ohnehin für die ganze Seite. Auf FREE-Seiten sind sie aus, deshalb schaltet diese Regel sie für die beiden Elemente ein.
- **Basis:** wie DE-10, DE-13 und DE-14.

### DE-19 DocsDE.StrictElementsHints

- **Kürzel und Ebenen:** M. Strict `NO`, moderate `NO`, free `suggestion`.
- **Regel:** In Schritten und Sicherheitshinweisen gelten die Hinweise von DE-08, DE-09, DE-11 und DE-12 (Passiv, Konjunktiv, Ungenaues, Pronomen). Die Begründung ist dieselbe wie bei DE-18.
- **Basis:** wie DE-08, DE-09, DE-11 und DE-12.

### DE-20 DocsDE.TermsStrictElements

- **Kürzel und Ebenen:** M. Strict `NO`, moderate `NO`, free `warning`. Aktiv erst nach Freigabe des Glossars.
- **Regel:** In Schritten und Sicherheitshinweisen gelten die Begriffstausche von DE-15. Auf FREE-Seiten ist DE-15 aus, deshalb braucht es diese Regel.
- **Basis:** wie DE-15.

## Ansprache und geschlechtergerechte Sprache

Die Konvention ist eine feste Entscheidung des Projekts (D-13). Die Absicht: inklusiv und mehrsprachig denkend, aber schlicht und ohne Zwang. Die Reihenfolge der Vorlieben lautet:

1. **Direkte Anrede mit "Sie" und Imperativ.** In STRICT ist das Pflicht, in Sicherheitshinweisen ebenso. Das deckt sich mit tekom S 506a. Der imperativische Infinitiv (S 506b) kommt im Projekt nicht zum Einsatz.
2. **Neutrale Nomen, wo sie natürlich klingen.** Beispiele: "Personen", "wer die Platine betreibt", "Elektrofachkraft", "Kundschaft". Partizipformen wie "Nutzende" sind ausgeschlossen.
3. **Paarform nur, wenn Sie eine Rolle benennen müssen.** Das betrifft vor allem Compliance- und Rechtstexte. Schreiben Sie die Paarform einmal je Absatz aus.
4. **Keine Gendersonderzeichen.** Kein Stern, kein Doppelpunkt, kein Unterstrich, kein Binnen-I. Das prüft `DocsDE.GenderCharacters`.
5. **Kein generisches Maskulinum.** Die verbotenen Rollenbezeichnungen prüft `DocsDE.RoleNouns` aus den freigegebenen Rollenzeilen des Glossars.

Die Wahl zwischen (2) und (3) prüft ein Mensch. Das Glossar legt für jede Rolle genau eine Form fest.

Der Bestand: Die vier Vorkommen von "Benutzer" stehen in der Tasterzeile der vier Hardwareseiten. Die Überarbeitung formuliert sie um, nicht diese Phase. Die Paarform "Nutzerin oder Nutzer" steht auf der Ersteinrichtungsseite und auf der Compliance-Seite. Die Überarbeitung gleicht sie mit dem Glossar ab.

## Satzlänge

Die Grenzen sind ein VORSCHLAG und warten auf die Entscheidung der Betreuung:

- 20 Wörter in Schritten und Sicherheitshinweisen.
- 25 Wörter in allem anderen Text.

Die Gründe: tekom S 302 nennt in der Leseprobe keine Zahl. Die englischen Regeln verwenden 20 und 25, und die deutschen Werte spiegeln sie. Vale zählt einen Bindestrich-Begriff wie "PWM-Signal" als zwei Wörter. Deutsche Komposita treiben die Zählung darum nach oben. Planen Sie ein bis zwei Wörter Spielraum ein. Als lockerere Alternative stehen 22 und 28 Wörter zur Wahl.

Die Dateien `DocsDE.SentenceLength*` entstehen erst nach dieser Entscheidung. Bis dahin sind DE-07, DE-16 und DE-17 nur beschrieben und nicht geprüft.

## Abkürzungen

Verwenden Sie diese Formen nicht, weder mit noch ohne Leerzeichen, außer in Tabellen und Code:

- `z. B.` und `z.B.`, `d. h.` und `d.h.`, `u. a.` und `u.a.`
- `usw.`, `bzw.`, `ca.`, `ggf.`, `evtl.`, `inkl.`, `vgl.`
- `Nr.` und `Abb.`
- `s. o.` und `s.o.`, `s. u.` und `s.u.`
- `max.` oder `min.` vor einer Zahl

Schreiben Sie stattdessen: zum Beispiel, das heißt, unter anderem, und so weiter, beziehungsweise, etwa, wenn nötig, einschließlich, vergleiche, Nummer, Abbildung, siehe oben, siehe unten, höchstens und mindestens.

Erlaubt sind Einheitenzeichen und gängige Akronyme ohne Punkt, zum Beispiel USB, PWM, RPM und I2C. Jede weitere Abkürzung schreiben Sie bei der ersten Nennung auf der Seite aus (siehe DE-27).

## Zahlen und Einheiten

Schreiben Sie Zahl, Leerzeichen und Einheit: `12 V`, `25 kHz`, `2,5 A`. Das Dezimalzeichen ist das Komma. Das Prozentzeichen steht nach einem Leerzeichen: `50 %`. Das entspricht DIN 5008.

Verwenden Sie ein geschütztes Leerzeichen (`&nbsp;`), wo das Format es erlaubt. In Markdown und MDX schreiben Sie die Entität, zum Beispiel `12&nbsp;V`. In Code, Codeblöcken und Frontmatter schreiben Sie ein gewöhnliches Leerzeichen. Eine Prüfung mit `@mdx-js/mdx` zeigt, dass MDX das Zeichen U+00A0 erhält (Ergebnis in `en.md`).

Im Bestand folgen die deutschen Seiten dieser Regel bereits: `12 V` steht 25-mal, `12V` kein einziges Mal, und `50 %` steht 9-mal, `50%` kein einziges Mal.

## Anführungszeichen

Das Projekt prüft Anführungszeichen nicht. Der tekom-Katalog rät mit Z 103a von typografischen Anführungszeichen ab und mit Z 103b zu geraden Zeichen für zitierte Oberflächentexte. Der Build ändert aber alle geraden Zeichen in typografische Zeichen nach englischer Art, auch auf deutschen Seiten. Deutsche Anführungszeichen sind deshalb zurückgestellt, bis die Einstellung je Sprache entschieden ist.

## Checkliste für die menschliche Prüfung

Prüfen Sie diese Regeln beim Lesen. Keine Vale-Regel deckt sie ab. Wenden Sie die Liste auf jede STRICT-Seite an und auf jeden Schritt und jeden Sicherheitshinweis auf anderen Seiten.

### DE-21 Direkte Anrede mit Sie

- **Kürzel:** H. **Basis:** tekom S 506a und Konvention D-13 (1). In STRICT Pflicht.
- **Gut:** Öffnen Sie die Einstellungen.
- **Schlecht:** `Die Einstellungen sind zu öffnen.`

### DE-22 Imperativ statt Infinitiv

- **Kürzel:** H. **Basis:** Das Projekt wählt die Anrede mit Sie und lässt den imperativischen Infinitiv (tekom S 506b) weg.
- **Gut:** Trennen Sie das Netzteil.
- **Schlecht:** `Netzteil trennen.`

### DE-23 Eine Handlung je Schritt

- **Kürzel:** H. **Basis:** tekom S 313 (höchstens zwei gleichzeitige Handlungen in einem Satz). Das Projekt geht strenger vor und verlangt eine Handlung je Schritt.
- **Gut:** Trennen Sie das Netzteil. Entfernen Sie im nächsten Schritt den Lüfter.
- **Schlecht:** `Trennen Sie das Netzteil, entfernen Sie den Lüfter und stecken Sie das Kabel wieder an.`

### DE-24 Bedingung zuerst

- **Kürzel:** H. **Basis:** Projektregel, wie EN-23.
- **Gut:** Wenn die LED aus ist, prüfen Sie das Netzteil.
- **Schlecht:** `Prüfen Sie das Netzteil, wenn die LED aus ist.`

### DE-25 Modalverben sparsam

- **Kürzel:** H. **Basis:** tekom S 509. Pflicht ("müssen") und Verbot ("dürfen nicht") bleiben in Sicherheitshinweisen erlaubt.
- **Gut:** Der Lüfter braucht ein PWM-Signal.
- **Schlecht:** `Der Lüfter kann ein PWM-Signal benötigen.`

### DE-26 Gleiche Benennung für Bedienelemente

- **Kürzel:** H, ergänzt durch die Glossarprüfung. **Basis:** tekom B 301.
- **Regel:** Nennen Sie jede Taste, Anzeige und Oberflächenfläche überall gleich, so wie sie beschriftet ist.

### DE-27 Abkürzung bei der ersten Nennung ausschreiben

- **Kürzel:** H. **Basis:** tekom B 201 als Ausgangspunkt. Gilt für HA, SELV, OTA und ähnliche Kurzformen.
- **Gut:** Das Update per Funk (Over-the-Air, kurz OTA) braucht eine WiFi-Verbindung.
- **Schlecht:** `Das OTA-Update braucht eine WiFi-Verbindung.` (bei der ersten Nennung auf der Seite)

### DE-28 Hinweise informieren nur

- **Kürzel:** H. **Basis:** Projektregel, wie EN-27.
- **Gut:** Hinweis: Die Platine behält nach einem Neustart die letzte Drehzahl.
- **Schlecht:** `Hinweis: Trennen Sie zuerst die Stromversorgung.` (gehört in einen Schritt)

### DE-29 Sicherheitshinweise mit vier Teilen

- **Kürzel:** H. **Basis:** Anregung aus IEC/IEEE 82079-1 (geringe Sicherheit).
- **Regel:** Signalwort, Art und Quelle der Gefahr, Folge, Maßnahme zur Vermeidung. Siehe `safety.md`.

### DE-30 Wahl zwischen neutraler Form und Paarform

- **Kürzel:** H. **Basis:** Konvention D-13, Punkte (2) und (3).
- **Regel:** Nehmen Sie die neutrale Form, wo sie natürlich klingt. Nehmen Sie die Paarform nur, wenn Sie eine Rolle benennen müssen, und schreiben Sie sie einmal je Absatz aus.
