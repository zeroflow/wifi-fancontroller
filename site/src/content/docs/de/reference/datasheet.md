---
title: Datenblatt Rev 3.3
description: Produktdatenblatt der ESP32-S2 WiFi Lüftersteuerung Rev 3.3, mit elektrischen, mechanischen, umgebungsbezogenen und schnittstellenseitigen Spezifikationen
sidebar:
  label: Datenblatt (Rev 3.3)
---

WiFi Lüftersteuerung, Hardware-Revision 3.3. Eine CE-gekennzeichnete ESP32-S2-Platine, die bis zu
vier 4-polige PWM-Lüfter ansteuert, deren Tachosignal ausliest, Umgebungstemperatur und
Luftfeuchte misst und über ESPHome nativ mit Home Assistant zusammenarbeitet.

Rev 3.1, 3.2 und 3.3 sind elektrisch kompatibel und teilen sich diese Spezifikation. Unterschiede
zwischen den Unterrevisionen betreffen ausschließlich die Fertigung.

## Hauptmerkmale

- 4 unabhängige PWM-Lüfterausgänge mit 25 kHz und Signalpufferung
- 4 unabhängige Tachoeingänge, ausgegeben als Drehzahl in RPM
- Integrierter HDC1080-Sensor für Temperatur und Luftfeuchte
- 5 adressierbare RGB-Status-LEDs: eine für den Platinenstatus, eine je Lüfteranschluss
- WLAN 2,4 GHz, native Home-Assistant-Integration über ESPHome
- Qwiic- und 100-mil-I2C-Erweiterung, NeoPixel-Ausgang, SMD-Erweiterungsleiste
- Flashen über USB-C, zusätzlich UART0-Serial-Header als Rückfallebene
- 3 frei belegbare Benutzertasten

## Grenzwerte und elektrische Daten

| Parameter | Min. | Typ. | Max. | Einheit | Anmerkung |
|---|---|---|---|---|---|
| DC-Eingangsspannung | 11,4 | 12 | 12,6 | V | 12 V DC ±5 %, SELV, nur geregeltes Schaltnetzteil |
| DC-Eingangsspannung, nie zu überschreiten | | | 15 | V | Auch im Leerlauf und bei geringer Last |
| Gesamteingangsstrom | | | 2,5 | A | Festgelegt durch die DC-Hohlbuchse |
| Stromaufnahme der Platinenelektronik ohne Lüfter | | 50 | | mA | |
| PWM-Ausgangsfrequenz | | 25 | | kHz | Je Lüfter unabhängig steuerbar |
| PWM-Auflösung | | | 100 | Stufen | ESPHome `speed_count: 100` |
| Logikpegel aller Stiftleisten | | 3,3 | | V | Nicht 5-V-tolerant |
| NeoPixel-Port, Spannung | | 5 | | V | |
| NeoPixel-Port, Strom | | | 2 | A | |

Der Wert von 2,5 A ist der maximale Gesamteingangsstrom der Platine. Er gilt für die Summe aller
angeschlossenen Lüfter zuzüglich der Platinenelektronik. Dimensionieren Sie das Netzteil mit
Reserve für die kombinierte Leistungsaufnahme der angeschlossenen Lüfter. Den normativen Wortlaut
und die vollständigen Anforderungen an das externe Netzteil finden Sie unter
[Sicherheit und Konformität](/de/reference/compliance/).

Der USB-C-Anschluss versorgt ausschließlich den Mikrocontroller. Er kann keine Lüfter versorgen.

## Betriebs- und Lagerbedingungen

| Parameter | Wert | Referenz |
|---|---|---|
| Klimaklasse | 3K3 | IEC 60721-3-3, wettergeschützter Innenraum |
| Umgebungstemperatur im Betrieb | +5 bis +40 °C | Grenze der Klasse 3K3 |
| Relative Luftfeuchte | 5 bis 85 %, nicht kondensierend | Grenze der Klasse 3K3 |
| Verschmutzungsgrad | 2 | IEC 62368-1 |
| Einsatzhöhe | bis 2000 m | IEC 62368-1 |
| Schutzart | keine, nackte Leiterplatte | Gehäuse erforderlich, siehe unten |
| Aufstellung | ausschließlich trockene Innenräume | |

Der Betrieb ohne Gehäuse ist eine ausgeschlossene Anwendung. Die Platine wird als bestückte,
nackte Leiterplatte geliefert und muss in ein schützendes Gehäuse eingebaut werden.

## Mechanische Daten

| Parameter | Wert |
|---|---|
| Platinenumriss | 70,0 × 45,0 mm |
| Platinendicke | 1,6 mm |
| Befestigungsbohrungen | 4 Stück, Durchmesser 3,2 mm |
| Bohrbild | Rechteck 60,0 × 35,0 mm, symmetrisch zur Platinenmitte |
| Abstand der Bohrungen zur Kante | 5,0 mm an allen vier Seiten |
| Maximale Bauhöhe über der Platine | 11,0 mm |
| Maximale Bauhöhe unter der Platine | 2,5 mm |
| Gesamtabmessungen | 70,0 × 45,0 × 15,1 mm |

Ein STEP-Modell der bestückten Platine liegt im Verzeichnis [`hardware/`](https://github.com/zeroflow/wifi-fancontroller/tree/main/hardware)
des Repositorys bereit, für Gehäusekonstruktion und die Prüfung von Einbaufreiräumen.

## Rechenkern und Funk

| Parameter | Wert |
|---|---|
| Modul | ESP32-S2-MINI-2 |
| Kern | Xtensa LX7, Single-Core, bis 240 MHz |
| Flash | 4 MB |
| Antenne | integrierte Leiterbahnantenne auf dem Modul |
| WLAN | 802.11 b/g/n, 2,4 GHz |
| Bluetooth | auf dem ESP32-S2 nicht verfügbar |
| ESPHome-Board | `esp32-s2-saola-1` |
| Framework | `arduino` |

Das Framework `arduino` ist erforderlich: Der NeoPixel-Ausgang an GPIO42 nutzt die Plattform
`esp32_rmt_led_strip`, die auf dem ESP32-S2 mit `esp-idf` nicht zuverlässig arbeitet.

## Sensorik und Anzeigen

| Element | Spezifikation |
|---|---|
| Temperatur- und Feuchtesensor | HDC1080, am gemeinsamen I2C-Bus |
| Standard-Aktualisierungsintervall des Sensors | 10 s |
| Tachoeingang | Impulszähler mit internem Pull-up, 2 Impulse je Umdrehung |
| Standard-Aktualisierungsintervall der Drehzahl | 1 s |
| Status-LEDs | 5 Stück SK6805 adressierbar RGB an GPIO1, WS2812-Protokoll, Farbreihenfolge GRB |
| LED-Zuordnung | LED 0 Platinenstatus, LED 1 bis 4 Lüfter 1 bis 4 |

## Anschlüsse

| Anschluss | Typ | Anmerkung |
|---|---|---|
| DC-Eingang | Hohlbuchse 5,5 × 2,1 mm, Mittelpin positiv | 12 V DC, externes Netzteil nicht im Lieferumfang |
| USB-C | USB 2.0 Device | Flashen und Logs, versorgt nur den Mikrocontroller |
| Lüfter 1 bis 4 | 4-polige Lüfterstiftleiste, Raster 2,54 mm | Übliche 4-adrige PWM-Lüfter |
| I2C-Erweiterung | 5-polig, Raster 100 mil | GND, INT, SCL, SDA, +3V3 |
| Qwiic / STEMMA QT | JST-SH 4-polig, Raster 1 mm | Teilt sich den I2C-Bus |
| NeoPixel | 3-polig | 5 V, maximal 2 A, GPIO42 |
| Serial | 4-polig | 3V3, TX, RX, GND, UART0 mit 3,3 V Logikpegel |
| Erweiterung | SMD-Leiste, Platinenunterseite | GPIO2 bis GPIO11 |

Der Qwiic-Anschluss, der 100-mil-I2C-Anschluss und der integrierte HDC1080 liegen alle am
selben I2C-Bus (GPIO33 SDA, GPIO34 SCL, 4,7 k Pull-ups). Die Adressen dürfen sich über diese
Anschlüsse hinweg nicht überschneiden.

## Pinbelegung

| Pin | Verwendung |
|---|---|
| GPIO0 | Boot-Taste, zum Aktivieren des Flash-Modus drücken |
| GPIO1 | RGB-Status-LEDs, SK6805, 5 LEDs |
| GPIO2 bis GPIO11 | Erweiterungsleiste, Platinenunterseite |
| GPIO12 | Lüfter 1 PWM |
| GPIO13 | Lüfter 2 PWM |
| GPIO14 | Lüfter 3 PWM |
| GPIO15 | Lüfter 4 PWM |
| GPIO16 | Lüfter 1 Drehzahlerfassung |
| GPIO17 | Lüfter 2 Drehzahlerfassung |
| GPIO18 | Lüfter 3 Drehzahlerfassung |
| GPIO21 | Lüfter 4 Drehzahlerfassung |
| GPIO26 | unbenutzt |
| GPIO33 | I2C SDA |
| GPIO34 | I2C SCL |
| GPIO35 | I2C INT |
| GPIO36 | Taste USR3 |
| GPIO37 | Taste USR2 |
| GPIO38 | Taste USR1 |
| GPIO42 | NeoPixel-Erweiterungsanschluss |
| GPIO43 | UART0 TX, Serial-Header |
| GPIO44 | UART0 RX, Serial-Header |
| GPIO45, GPIO46 | unbenutzt, Strapping-Pins |

## Firmware und Integration

| Element | Wert |
|---|---|
| Firmware | ESPHome |
| Integration | Home Assistant, native API |
| Inbetriebnahme | Improv Serial, zusätzlich WLAN-Captive-Portal als Rückfallebene |
| Aktualisierung | OTA über ESPHome sowie HTTP-Update über das unten genannte Manifest |
| Werksfirmware | `fancontroller-r3-3-esp32s2.factory.bin` |
| Update-Manifest | `https://fancontroller.arthofer.dev/firmware/fancontroller-r3-3.manifest.json` |

Optionale Steuerungsmodule für Temperaturkurven, PID-Regelung, geschlossene Drehzahlregelung und
LED-Verhalten sind unter [Modules](/reference/modules/) dokumentiert.

## Konformität

| Element | Status |
|---|---|
| CE-Kennzeichnung | ja |
| RoHS | konform |
| HF-Exposition | Sicherheitsabstand von mindestens 20 cm zwischen Antenne und Personen einhalten |
| Funk | enthält einen Funksender im 2,4-GHz-Band |

### Bestimmungsgemäße Verwendung

Versorgung über ein externes 12 V DC SELV-Netzteil, Betrieb ausschließlich in trockenen
Innenräumen, Anschluss ausschließlich 4-poliger PWM-Lüfter, maximaler Gesamteingangsstrom 2,5 A.

### Ausdrückliche Ausschlüsse

Das Produkt ist nicht geeignet für und darf nicht eingesetzt werden in sicherheitskritischen
Anwendungen, explosionsgefährdeten Bereichen, medizinischen Anwendungen, im Betrieb ohne Gehäuse,
im unbeaufsichtigten Dauerbetrieb ohne regelmäßige Kontrolle sowie in Kraftfahrzeugen und anderen
Fahrzeugen.

### Firmware-Warnhinweis

Die Platine wird mit werkseitig getesteter Firmware ausgeliefert. Wird die Firmware verändert,
etwa durch eigene ESPHome-YAML-Konfigurationen, eigene Module oder Firmware von Dritten, erlischt
die CE-Konformität des Produkts in der ausgelieferten Form, und der Garantieanspruch entfällt für
Schäden, die auf diese Änderung zurückzuführen sind.

Den vollständigen normativen Wortlaut finden Sie auf der Seite
[Sicherheit und Konformität](/de/reference/compliance/). Wo dieses Datenblatt und jene Seite
voneinander abweichen, gilt jene Seite.

## Bestellangaben

| Element | Wert |
|---|---|
| Produkt | ESP32 WiFi Fancontroller |
| Hardware-Revision | 3.3 |
| Lieferumfang | bestückte Platine mit Werksfirmware |
| Nicht im Lieferumfang | 12-V-DC-Netzteil, Lüfter, Gehäuse |
| Shop | [Tindie](https://www.tindie.com/products/zeroflow/esp32-fancontroller/) |
| Dokumentation | [fancontroller.arthofer.dev](https://fancontroller.arthofer.dev) |
| Quellcode und Hardware-Dateien | [github.com/zeroflow/wifi-fancontroller](https://github.com/zeroflow/wifi-fancontroller) |
