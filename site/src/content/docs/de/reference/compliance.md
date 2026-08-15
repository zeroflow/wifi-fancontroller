---
title: Sicherheit und Konformität
description: Anforderungen an die Stromversorgung, Sicherheitsabstand für HF-Exposition und Umfang der Benutzertasten für die WiFi Lüftersteuerung
---

Diese Seite enthält den normativen Wortlaut für die WiFi Lüftersteuerung. Wo eine andere Seite, ein Produktlisting oder eine gedruckte Beilage etwas anderes angibt, gilt der Text dieser Seite.

## Stromversorgung

Die Lüftersteuerung benötigt ein externes 12 V DC SELV-Netzteil, das nicht im Lieferumfang enthalten ist.

- **Steckverbinder:** Hohlstecker 5,5 × 2,1 mm, Mittelpin positiv
- **Spannung:** 12 V DC ±5 %
- **Strom:** mindestens 2,5 A empfohlen, abhängig von der Lüfterlast

Das Netzteil ist nicht Teil des Produkts. Nutzerinnen und Nutzer müssen eine Stromquelle bereitstellen, die für ihre Region zertifiziert ist.

Der Wert von 2,5 A ist der maximale Gesamteingangsstrom der Platine, festgelegt durch die DC-Hohlbuchse. Er gilt für die Summe aller angeschlossenen Lüfter zuzüglich der Elektronik der Platine und beschreibt keinen Grenzwert für einen einzelnen Lüfteranschluss. Dimensionieren Sie das Netzteil mit Reserve für die kombinierte Leistungsaufnahme der angeschlossenen Lüfter.

Der USB-C-Anschluss (Rev 2.0 und neuer) versorgt ausschließlich den Mikrocontroller mit Strom. Er kann keine Lüfter mit Strom versorgen.

Das Netzteil muss ein geregeltes Schaltnetzteil (SMPS) mit 12 V DC sein. Die Eingangsspannung darf 15 V unter keinen Umständen überschreiten, auch nicht im Leerlauf oder bei geringer Last. Die Platine selbst nimmt weniger als 50 mA auf. Ein ungeregeltes, transformatorbasiertes Netzteil ohne Rückkopplungsregelung kann daher bei geringer Last deutlich über seine Nennspannung ansteigen.

**Warnung:** Verwenden Sie keine alten, transformatorbasierten Netzteile ("schwere Klötze"). Diese sind häufig ungeregelt und können bei geringer Last 15 bis 18 V ausgeben, was die Platine dauerhaft beschädigt.

Schäden durch Überspannung aus einem ungeeigneten Netzteil sind kein Fabrikationsfehler der Platine und nicht von der Gewährleistung gedeckt.

So erkennen Sie ein ungeeignetes Netzteil:

- Schwer im Verhältnis zur Größe
- Hörbares Brummen
- Lüftungsschlitze am Gehäuse
- Kennzeichnung, die nur "50 Hz" ohne Schaltfrequenz angibt
- Sehr alt

Messen Sie im Zweifel die Ausgangsspannung ohne angeschlossene Last. Verwenden Sie das Netzteil nicht, wenn es mehr als etwa 13 V anzeigt.

Geeignete Netzteile sind moderne geregelte Schalt-Steckernetzteile sowie MeanWell-Hutschienennetzteile (zum Beispiel die Serien HDR oder MDR) für den Einbau im Schaltschrank.

Hinweis: Verbinden Sie zuerst den Hohlstecker mit der Platine und stecken Sie erst danach das Netzteil in die Steckdose.

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
- **Regelung:** geregeltes Schaltnetzteil (SMPS), kein ungeregeltes transformatorbasiertes Netzteil
- **Maximale Spannung:** darf 15 V unter keinen Umständen überschreiten, auch nicht im Leerlauf
- **Kennzeichnung:** CE-gekennzeichnet
- **Strombegrenzung:** das Netzteil muss den Ausgangsstrom begrenzen
- **Polarität:** korrekte Polarität, Mittelpin positiv (Hohlstecker 5,5 × 2,1 mm)

## Firmware-Warnhinweis

Der Fancontroller wird mit werkseitig getesteter Firmware ausgeliefert. Die Konformitätserklärung bezieht sich auf das Produkt in diesem Zustand. Eigene ESPHome-YAML-Konfigurationen, eigene Module oder Firmware von Dritten können die CE-Konformität berühren. Ob sie das tun, hängt davon ab, was die Änderung verändert.

Konfigurationen, die sich im dokumentierten Rahmen bewegen, verändern weder das funktechnische noch das elektrische Verhalten, auf dem die Bewertung beruht. Dazu zählen etwa ein geänderter Gerätename, geänderte Aktualisierungsintervalle, eine ergänzte Temperaturkurve oder ein Steuerungsmodul aus diesem Repository sowie das vom Hersteller bereitgestellte Firmware-Update.

Die CE-Konformität des Produkts in der ausgelieferten Form erlischt dagegen bei Änderungen, die den dokumentierten Rahmen verlassen. Dazu zählen insbesondere:

- Veränderung der Funkparameter, etwa der Sendeleistung über `wifi: output_power:`
- Verstellen der PWM-Ausgangsfrequenz von 25 kHz
- Betrieb der Ausgänge außerhalb der spezifizierten Grenzen
- Betrieb außerhalb der bestimmungsgemäßen Verwendung nach diesem Dokument

Nicht jede mögliche Konfiguration lässt sich vorab bewerten. Für veränderte Firmware wird daher keine generelle Freigabe erteilt, und die Verantwortung für eine veränderte Konfiguration liegt bei der Person, die sie betreibt.

Der Garantieanspruch entfällt für Schäden, die auf eine solche Änderung zurückzuführen sind. Eine Änderung, die den dokumentierten Rahmen verlässt, stellt eine bestimmungswidrige Verwendung dar (Instruktionswidrigkeit) und kann im Schadensfall als Mitverschulden der Nutzerin oder des Nutzers berücksichtigt werden.

Dieser Hinweis schränkt die Produkthaftung nach dem Produkthaftungsgesetz nicht vollständig aus; ein solcher genereller Ausschluss wäre nach § 9 ProdHG gegenüber Verbraucherinnen und Verbrauchern unwirksam. Er weist lediglich darauf hin, dass eine Änderung der Firmware außerhalb der bestimmungsgemäßen Verwendung erfolgt und entsprechende Folgen für Konformität, Garantie und die Berücksichtigung eines Mitverschuldens haben kann.
