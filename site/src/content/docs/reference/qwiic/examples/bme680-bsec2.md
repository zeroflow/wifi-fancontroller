---
title: BME680 Environmental Sensor (BSEC2)
description: BME680 with the Bosch BSEC2 library for IAQ, CO2 equivalent, and VOC (license note applies)
sidebar:
  order: 3
---

![WiFi Fan Controller with an Adafruit BME680 environmental sensor connected over Qwiic / STEMMA QT](/images/qwiic/qwiic_bme680.jpg)

This is the same [Adafruit BME680](https://www.adafruit.com/product/3660) as the [plain BME680 example](/reference/qwiic/examples/bme680/), but run through the Bosch **BSEC2** library. BSEC2 processes the raw gas reading into an air-quality index (IAQ), a CO2 equivalent, and a breath VOC equivalent, which the open driver cannot produce.

It comes with two strings attached: a **license** you accept by importing it, and a **framework** requirement. Those two sections below are the ones you actually have to read. The rest is copy-paste.

The BSEC2 module and the [open BME680 module](/reference/qwiic/examples/bme680/) are **mutually exclusive**. Pick one, never import both.

## License

:::danger[Importing this module accepts the Bosch BSEC2 license]
BSEC2 is proprietary Bosch software. Adding this module to your config **is** your acceptance of the [Bosch BSEC license](https://www.bosch-sensortec.com/software-tools/software/bsec/). There is no prompt and no separate click.

- **Non-commercial / personal use** is covered by the license as bundled.
- **Commercial use** requires a separate agreement with Bosch.
- You **must not redistribute** compiled firmware binaries that contain the BSEC library.

This is exactly why BSEC is not part of the standard [BME680 module](/reference/qwiic/examples/bme680/): nobody should agree to a proprietary license without knowing it.
:::

## Framework: Arduino only

BSEC2 ships as a **precompiled Arduino library**, so it only builds on the `arduino` framework.

**In the normal case you do not have to do anything.** The shipped fancontroller firmware already pins `arduino`:

```yaml
esp32:
  board: esp32-s2-saola-1
  framework:
    type: arduino      # already set in every production config
```

So if you build on the stock config (or on the full example at the bottom of this page), you are done.

:::caution[Only an issue if you switch to esp-idf]
ESPHome's default framework moved to **esp-idf** in 2026.1. That matters only if you write a config from scratch and leave the framework out, or set it to esp-idf on purpose. The config still validates, but the build then fails to link the BSEC library. If that happens, set the framework back to `arduino`.
:::

## Add it to your config

Plug the sensor into the Qwiic connector, then include the module as a package and give it a role name. As with the open module, the BME680 hangs on a cable and measures wherever you put it, so name it for its role (`Air`, `Intake`, `Room`), not for the chip:

```yaml
packages:
  hardware: ...      # your hardware-rev-*.yaml
  bme680:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/bme680_bsec2.yaml
        vars:
          bme680_name: "Air"
```

## Burn-in: the first readings are garbage

:::caution[Fresh from flashing, the sensor shows nonsense. That is normal.]
The BSEC2 algorithm learns its own baseline over **hours to days**. Until it has, the air-quality numbers are meaningless. The **IAQ Accuracy** entity tells you where it stands:

| IAQ Accuracy | Meaning |
|--------------|---------|
| 0 | Stabilizing, no baseline yet |
| 1 | Still calibrating, values unreliable |
| 2 | Calibrating, values usable with care |
| 3 | Calibrated, values trustworthy |

Watch **IAQ Accuracy** before you trust IAQ, CO2, or VOC. A reading of 3 is the goal.
:::

The learned state is written to flash every 6 hours (`state_save_interval`), so a reboot does not send the sensor back to accuracy 0. **Do not shorten that interval** to speed things up: it does not speed up learning, and frequent flash writes wear the chip out.

## What you get

| Entity | Unit | Notes |
|--------|------|-------|
| **IAQ** | 0 to 500 index | 0 = clean, 500 = heavily polluted. Only meaningful once IAQ Accuracy is 3 |
| **CO2 Equivalent** | ppm | Estimated, not measured (see below) |
| **Breath VOC Equivalent** | ppm | Estimated VOC load |
| **Pressure** | hPa | Barometric pressure |
| **IAQ Accuracy** | 0 to 3 text sensor | The calibration state, tagged as a diagnostic |

Temperature and humidity are also produced but set **internal** by default, because they duplicate the onboard HDC1080. Expose them with `!extend` if you want them (see below).

:::note["Equivalent" is not a typo]
The BME680 does not measure CO2. It measures a gas resistance and BSEC2 **computes** a CO2-equivalent number from it. The same goes for VOC. Treat both as trend indicators. If you need a real CO2 value, you need an NDIR sensor such as the [SCD41](/reference/qwiic/examples/scd41/).
:::

## Sample rate: LP or ULP

`bme680_sample_rate` sets how hard the sensor works:

- **`LP`** (low power): a reading every 3 seconds. The default.
- **`ULP`** (ultra low power): a reading every 300 seconds.

For a fixed rack sensor, **`ULP` is the better choice**: 5-minute resolution is plenty for air quality, it runs the gas heater far less, and it draws less current. The tradeoff is a longer burn-in, since the algorithm sees fewer samples.

```yaml
files:
  - path: modules/bme680_bsec2.yaml
    vars:
      bme680_sample_rate: "ULP"
```

## Configuration variables

Set these under the package's `files:` entry with `vars:`, or as top-level `substitutions:` in your config.

| Variable | Default | Purpose |
|----------|---------|---------|
| `bme680_name` | `Air` | Role name and entity prefix, for example `Intake` or `Room` |
| `bme680_address` | `0x77` | I2C address. Set `0x76` if you moved the solder jumper |
| `bme680_temp_offset` | `0` | °C subtracted from the temperature to correct self-heating |
| `bme680_sample_rate` | `LP` | `LP` (every 3s) or `ULP` (every 300s) |

## IDs you can override

These are the component ids the module defines. They are the surface you can reach with `!extend` and `!remove` from your own config.

| ID | Type | Notes |
|----|------|-------|
| `bme_bsec` | bme68x_bsec2_i2c | The BSEC2 device |
| `bme_iaq` | sensor | IAQ index |
| `bme_co2eq` | sensor | CO2 equivalent |
| `bme_voceq` | sensor | Breath VOC equivalent |
| `bme_pressure` | sensor | Pressure |
| `bme_temperature` | sensor | Temperature, **internal** by default |
| `bme_humidity` | sensor | Humidity, **internal** by default |
| `bme_iaq_accuracy` | text_sensor | Calibration state |

:::note[No Web UI group for this module]
This module's 7 named entities do not get their own [Web UI group](/reference/standalone/#grouping-module-entities-in-the-web-ui). The module declares them as nested sub-keys of a single `platform: bme68x_bsec2` sensor entry rather than as top-level list items each with their own `id:`, so `!extend` cannot reach them (the same top-level-only limitation the [modules overview](/reference/modules/#customizing-a-module) already documents). Instead they fall back to ESPHome's documented default: grouping by `entity_category`. That works, but it is not per-module grouping.
:::

To publish the temperature and humidity after all, extend them and drop `internal`:

```yaml
sensor:
  - id: !extend bme_temperature
    name: "Air Temperature"
    internal: false
  - id: !extend bme_humidity
    name: "Air Humidity"
    internal: false
```

:::tip[New to the module system?]
Adding your own entities, changing module variables, and overriding module entities are three different operations. If any of that is unfamiliar, read [How modules work](/reference/modules/#how-modules-work) once. It applies to every module, not just this one.
:::

## Bus and prerequisites

- **Requires** the hardware package (it provides the shared I2C bus `bus_a`). This module is not standalone.
- **I2C address:** `0x77` by default, `0x76` with the solder jumper. Neither collides with the onboard HDC1080 at `0x40`.
- **Bus speed:** this module does **not** change the shared bus speed. If you combine several modules, mind the shared clock speed and the added pull-up load. See [Combining Expansion Modules](/reference/qwiic/combining/).

## Full example

A complete, compilable config: the hardware package and one BSEC2 sensor named "Air", set to ultra-low-power. **Note the `arduino` framework.**

```yaml
substitutions:
  wifi_ssid: "YourNetwork"
  wifi_password: "YourPassword"

packages:
  hardware:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [hardware-rev-3.1.yaml]
  bme680:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/bme680_bsec2.yaml
        vars:
          bme680_name: "Air"
          bme680_sample_rate: "ULP"

esphome:
  name: my-fancontroller
  friendly_name: My Fan Controller

esp32:
  board: esp32-s2-saola-1
  framework:
    type: arduino      # required by BSEC2

logger:
api:
ota:
  - platform: esphome
wifi:
  ssid: ${wifi_ssid}
  password: ${wifi_password}
  ap:
    ssid: "Fancontroller Fallback"
captive_portal:
```

:::note[ESP32-S2 support is verified, but not long-term tested]
BSEC2 runs and produces values on the Rev 3.x ESP32-S2 boards. It has not been through a long-term stability test on this platform. If you hit trouble, report it.
:::

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Compile error mentioning BSEC | The config runs on `esp-idf`. BSEC2 only builds on `arduino` |
| IAQ jumps around or sticks near 25 | Burn-in. IAQ Accuracy is still below 3. Wait it out |
| IAQ, CO2, VOC look wrong right after flashing | Same thing: the algorithm has no baseline yet |
| Temperature reads 1 to 2 °C high | Self-heating from the gas heater. Raise `bme680_temp_offset` |
| Sensor missing from the I2C scan log | Cable not seated, or the jumper is on `0x76` while `bme680_address` still says `0x77` |
| You want real CO2, not an estimate | The BME680 cannot measure it. Use an NDIR sensor like the [SCD41](/reference/qwiic/examples/scd41/) |
