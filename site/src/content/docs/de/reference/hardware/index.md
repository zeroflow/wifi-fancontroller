---
title: Hardware-Revisionen
description: Übersicht und Vergleich der WiFi Lüftersteuerung Hardware-Revisionen
sidebar:
  label: Übersicht
  order: 0
---

:::caution[Entwurf (rechtliche Prüfung ausstehend)]
Dieser Text ist ein Entwurf und wurde noch nicht rechtlich geprüft oder freigegeben. Er ist nicht als endgültige oder rechtsverbindliche Gebrauchsanleitung zu verstehen, bis die rechtliche Freigabe erfolgt ist.
:::

Die WiFi Lüftersteuerung hat mehrere Hardware-Revisionen durchlaufen, wobei jede die vorherige Generation abgelöst hat. Alle Revisionen teilen sich die gleichen Kernfunktionen: 4 PWM-Lüfteranschlüsse, einen HDC1080 Temperatur- und Luftfeuchtigkeitssensor sowie ESPHome-basierte Firmware mit Home Assistant-Integration.

Die **aktuelle Revision ist Rev 3.3**. Frühere Revisionen sind hier für bestehende Besitzerinnen und Besitzer dokumentiert.

## Revisionsvergleich

| Merkmal | Rev 1.0 | Rev 2.0 | Rev 3.0 | Rev 3.x (3.1/3.2/3.3) |
|---------|---------|---------|---------|------------------------|
| MCU | ESP32 | ESP32-S2 | ESP32-S2 | ESP32-S2 |
| Board | esp32dev | esp32-s2-saola-1 | esp32-s2-saola-1 | esp32-s2-saola-1 |
| Flashen | Serieller Header | USB-C | USB-C | USB-C |
| Status-LED | Rot (einzeln) | Rot (einzeln) | Rot (einzeln) | RGB (SK6805) x5 |
| Erweiterung | I2C + 2x ext. Eingang | I2C | QWIIC + I2C + NeoPixel | QWIIC + I2C + NeoPixel |
| PWM-Pufferung | Nein | Nein | Ja | Ja |
| Lüfteranschlüsse | 4x PWM | 4x PWM | 4x PWM | 4x PWM |
| Sensor | HDC1080 | HDC1080 | HDC1080 | HDC1080 |

## Revisionen

- **[Rev 3.x (3.1 / 3.2 / 3.3)](/de/reference/hardware/rev-3-x/)**: Aktuelle Generation mit RGB-Status-LEDs, QWIIC-Erweiterung und NeoPixel-Ausgang. Alle drei Unterrevisionen teilen sich identische Firmware und Pin-Belegung.
- **[Rev 3.0](/de/reference/hardware/rev-3-0/)**: Ergänzte QWIIC I2C, NeoPixel-Erweiterung und PWM-Pufferung. Keine RGB-Status-LEDs. Abgelöst durch Rev 3.1.
- **[Rev 2.0](/de/reference/hardware/rev-2-0/)**: Führte USB-C-Flashing mit ESP32-S2 ein. Abgelöst durch Rev 3.0.
- **[Rev 1.0](/de/reference/hardware/rev-1-0/)**: Ursprüngliches ESP32-Design mit seriellem Flashen. Abgelöst durch Rev 2.0.
