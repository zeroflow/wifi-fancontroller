---
title: Sicherheit und Konformität
description: Anforderungen an die Stromversorgung, Sicherheitsabstand für HF-Exposition und Umfang der Benutzertasten für die WiFi Lüftersteuerung
---

:::caution[Entwurf (rechtliche Prüfung ausstehend)]
Dieser Text ist ein Entwurf und wurde noch nicht rechtlich geprüft oder freigegeben. Er ist nicht als endgültige oder rechtsverbindliche Gebrauchsanleitung zu verstehen, bis die rechtliche Freigabe erfolgt ist.
:::

Diese Seite enthält den normativen Wortlaut für die WiFi Lüftersteuerung. Wo eine andere Seite, ein Produktlisting oder eine gedruckte Beilage etwas anderes angibt, gilt der Text dieser Seite.

## Stromversorgung

Die Lüftersteuerung benötigt ein externes 12 V DC SELV-Netzteil, das nicht im Lieferumfang enthalten ist.

- **Steckverbinder:** Hohlstecker 5,5 × 2,1 mm, Mittelpin positiv
- **Spannung:** 12 V DC ±5 %
- **Strom:** mindestens 2,5 A empfohlen, abhängig von der Lüfterlast

Das Netzteil ist nicht Teil des Produkts. Nutzerinnen und Nutzer müssen eine Stromquelle bereitstellen, die für ihre Region zertifiziert ist.

Der Wert von 2,5 A ist der maximale Gesamteingangsstrom der Platine, festgelegt durch die DC-Hohlbuchse. Er gilt für die Summe aller angeschlossenen Lüfter zuzüglich der Elektronik der Platine und beschreibt keinen Grenzwert für einen einzelnen Lüfteranschluss. Dimensionieren Sie das Netzteil mit Reserve für die kombinierte Leistungsaufnahme der angeschlossenen Lüfter.

Der USB-C-Anschluss (Rev 2.0 und neuer) versorgt ausschließlich den Mikrocontroller mit Strom. Er kann keine Lüfter mit Strom versorgen.

## HF-Exposition

Dieses Produkt enthält einen Funksender. Installieren Sie das Produkt so, dass während des normalen Betriebs ein Mindestabstand von 20 cm zwischen der Antenne und Personen eingehalten wird. Dieses Produkt ist nicht dafür vorgesehen, am Körper getragen oder in unmittelbarer Nähe der Nutzerin oder des Nutzers betrieben zu werden.

## Benutzertasten

Die Platine verfügt über drei frei belegbare Taster, die mit GPIO verbunden sind. In der Standardkonfiguration haben sie keine Funktion. Jedes Verhalten wird durch die ESPHome-Konfiguration der Nutzerin oder des Nutzers festgelegt. Typische Verwendung ist Einrichtung, Inbetriebnahme oder gelegentliche manuelle Übersteuerung; der reguläre Betrieb erfolgt über die Netzwerkschnittstelle.

In der Werksfirmware werden die Taster Home Assistant als binäre Sensoren gemeldet, die ihren Tastendruck-Status anzeigen. Sie lösen von sich aus keine Aktion auf der Platine aus, sofern keine konfiguriert wird.

Siehe [USR Buttons](/reference/modules/usr-buttons/) für eine fertige Möglichkeit, ihnen eine Funktion zuzuweisen.

## Bestimmungsgemäße Verwendung

Die WiFi Lüftersteuerung ist für den folgenden Einsatzbereich bestimmt:

- Versorgung über ein externes 12 V DC SELV-Netzteil (nicht im Lieferumfang enthalten)
- Betrieb ausschließlich in trockenen Innenräumen
- Anschluss ausschließlich 4-poliger PWM-Lüfter
- Maximaler Gesamteingangsstrom von 2,5 A

Der Wert von 2,5 A ist der maximale Gesamteingangsstrom der Platine, festgelegt durch die DC-Hohlbuchse. Er gilt für die Summe aller angeschlossenen Lüfter zuzüglich der Elektronik der Platine und beschreibt keinen Grenzwert für einen einzelnen Lüfteranschluss. Dimensionieren Sie das Netzteil mit Reserve für die kombinierte Leistungsaufnahme der angeschlossenen Lüfter.

## Ausdrückliche Ausschlüsse

Die WiFi Lüftersteuerung ist NICHT für folgende Anwendungen geeignet und darf dafür nicht eingesetzt werden:

- Sicherheitskritische Anwendungen (zum Beispiel Personen- oder Brandschutz, Notabschaltungen)
- Einsatz in explosionsgefährdeten Bereichen (Ex-Bereiche)
- Medizinische Anwendungen
- Betrieb ohne Gehäuse (offener Aufbau ohne schützende Abdeckung)
- Unbeaufsichtigter Dauerbetrieb ohne regelmäßige Kontrolle
- Einsatz in Kraftfahrzeugen oder anderen Fahrzeugen

Für keinen dieser Anwendungsfälle wird eine Eignung des Produkts zugesichert.

## Anforderungen an das externe Netzteil

Das von Ihnen bereitgestellte externe Netzteil muss folgende Anforderungen erfüllen:

- **Spannung:** 12 V DC
- **Kennzeichnung:** CE-gekennzeichnet
- **Strombegrenzung:** das Netzteil muss den Ausgangsstrom begrenzen
- **Polarität:** korrekte Polarität, Mittelpin positiv (Hohlstecker 5,5 × 2,1 mm)

## Firmware-Warnhinweis

Der Fancontroller wird mit werkseitig getesteter Firmware ausgeliefert. Wird die Firmware verändert, etwa durch eigene ESPHome-YAML-Konfigurationen, eigene Module oder Firmware von Dritten, erlischt die CE-Konformität des Produkts in der ausgelieferten Form, und der Garantieanspruch entfällt für Schäden, die auf diese Änderung zurückzuführen sind. Eine solche Änderung stellt eine bestimmungswidrige Verwendung dar (Instruktionswidrigkeit) und kann im Schadensfall als Mitverschulden der Nutzerin oder des Nutzers berücksichtigt werden.

Dieser Hinweis schränkt die Produkthaftung nach dem Produkthaftungsgesetz nicht vollständig aus; ein solcher genereller Ausschluss wäre nach § 9 ProdHG gegenüber Verbraucherinnen und Verbrauchern unwirksam. Er weist lediglich darauf hin, dass eine Änderung der Firmware außerhalb der bestimmungsgemäßen Verwendung erfolgt und entsprechende Folgen für Konformität, Garantie und die Berücksichtigung eines Mitverschuldens haben kann.
