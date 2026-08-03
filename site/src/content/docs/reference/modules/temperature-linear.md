---
title: Temperature Linear
description: Simple linear temperature-to-fan-speed mapping module
sidebar:
  order: 2
---

:::note[All Revisions]
Works with all hardware revisions (Rev 1.0 through Rev 3.3).
:::

## Purpose

The Temperature Linear module provides a simple three-zone mapping from temperature to fan speed. Define your temperature thresholds and fan speed percentages, and the controller handles the rest -- no complex tuning required.

## When to Use

Choose Linear when you want straightforward temperature-based fan control without the complexity of PID tuning or multi-point curves. It works well for most home and office setups where you just need fans to ramp up as temperature rises.

For more precise temperature targeting, consider [Temperature PID](/reference/modules/temperature-pid/). For finer control over the speed curve shape, see [Temperature Curve](/reference/modules/temperature-curve/). The [modules overview](/reference/modules/) has a comparison table.

:::tip[Works with Stall Guard]
This module cooperates with [Stall Guard](/reference/modules/stall-guard/) via a safety floor mechanism. If a fan stalls, Stall Guard sets a minimum speed that Temperature Linear will respect during recovery. No extra configuration needed, just include both modules.
:::

## Configuration

| Variable                | Default                       | Description                                        |
| ----------------------- | ----------------------------- | -------------------------------------------------- |
| `friendly_name`         | `"Fancontroller"`             | Device name prefix for all entities                |
| `t_off`                 | `"25.0"`                      | Temperature below which fans turn off (C)          |
| `t1`                    | `"30.0"`                      | Lower temperature setpoint (C)                     |
| `t2`                    | `"50.0"`                      | Upper temperature setpoint (C)                     |
| `fanpercent1`           | `"30.0"`                      | Fan speed at t1 (%)                                |
| `fanpercent2`           | `"100.0"`                     | Fan speed at t2 and above (%)                      |
| `temperature_sensor_id` | `"fancontroller_temperature"` | Id of the sensor supplying the control temperature |

## Zone Behavior

The module divides temperature into four zones:

| Zone          | Temperature Range | Fan Speed                      | Behavior                             |
| ------------- | ----------------- | ------------------------------ | ------------------------------------ |
| Off           | Below `t_off`     | 0%                             | Fans completely off                  |
| Constant low  | `t_off` to `t1`   | `fanpercent1`                  | Fans run at a fixed low speed        |
| Ramp          | `t1` to `t2`      | `fanpercent1` to `fanpercent2` | Linear ramp between the two speeds   |
| Constant high | Above `t2`        | `fanpercent2`                  | Fans run at maximum configured speed |

With the defaults (t_off=25, t1=30, t2=50, fanpercent1=30%, fanpercent2=100%):

- Below 25 C: fans off
- 25-30 C: fans at 30%
- 30-50 C: fans ramp linearly from 30% to 100%
- Above 50 C: fans at 100%

## Home Assistant Entities

### Number Entities

| Entity                 | Range    | Step | Unit | Default | Description                       |
| ---------------------- | -------- | ---- | ---- | ------- | --------------------------------- |
| Linear Off Temperature | 20 -- 50 | 0.5  | C    | 25.0    | Temperature below which fans stop |
| Linear T1              | 20 -- 50 | 0.5  | C    | 30.0    | Lower temperature setpoint        |
| Linear T2              | 20 -- 50 | 0.5  | C    | 50.0    | Upper temperature setpoint        |
| Linear Fan Percent 1   | 0 -- 100 | 1    | %    | 30      | Fan speed at T1                   |
| Linear Fan Percent 2   | 0 -- 100 | 1    | %    | 100     | Fan speed at T2 and above         |

### Sensor Entities

| Entity        | Unit | Description                                      |
| ------------- | ---- | ------------------------------------------------ |
| Linear Output | %    | Current calculated fan speed (updated every 10s) |

### Switch Entities

| Entity             | Default | Description                     |
| ------------------ | ------- | ------------------------------- |
| Auto Control Fan 1 | ON      | Enable linear control for fan 1 |
| Auto Control Fan 2 | ON      | Enable linear control for fan 2 |
| Auto Control Fan 3 | ON      | Enable linear control for fan 3 |
| Auto Control Fan 4 | ON      | Enable linear control for fan 4 |

## YAML Examples

### Basic Usage (Default Settings)

```yaml
packages:
  temperature_linear:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_linear.yaml
        vars:
          friendly_name: "My Fan Controller"
```

### Quiet Desktop Profile

```yaml
packages:
  temperature_linear:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_linear.yaml
        vars:
          friendly_name: "Desktop Cooler"
          t_off: "28.0"
          t1: "32.0"
          t2: "45.0"
          fanpercent1: "20.0"
          fanpercent2: "80.0"
```

This profile keeps fans off until 28 C, starts at a quiet 20%, and caps at 80% for reduced noise.

## Tuning Tips

:::tip[Start with the Defaults]
The defaults work for a wide range of setups. Adjust only after observing behavior for a few hours.
:::

- **Adjust `t_off` based on ambient temperature** -- if your room is normally 24 C, setting `t_off` to 25 C means fans only spin when something is actively generating heat
- **Set `fanpercent1` to your fans' minimum reliable speed** -- most fans need at least 20-30% PWM to start spinning consistently. Check the [troubleshooting guide](/getting-started/troubleshooting/) if fans stutter at low speeds.
- **Use the HA number entities to fine-tune** -- all five parameters can be adjusted live from Home Assistant without reflashing
- **Watch the Linear Output sensor** -- it shows the current calculated fan speed percentage, helpful for verifying your thresholds behave as expected

## Controlling From a Different Sensor

By default the module reads `fancontroller_temperature`, the onboard HDC1080 that every hardware package declares. Set `temperature_sensor_id` to the id of any other temperature sensor in your configuration to control from that instead:

```yaml
packages:
  # modules/bme680.yaml is not standalone - it needs the shared I2C bus (bus_a)
  # that your hardware package declares. Use your own board revision here.
  hardware:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [hardware-rev-3.1.yaml]
  bme680:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [modules/bme680.yaml]
  temperature_linear:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_linear.yaml
        vars:
          temperature_sensor_id: "bme680_temperature"
```

Remember that `t_off`, `t1`, and `t2` are absolute temperatures. An external sensor measuring room or intake air reads lower than the board does, so thresholds tuned for the onboard sensor will usually need lowering.

Omit the variable and it falls back to `fancontroller_temperature`, so existing configurations keep working unchanged. A misspelled id fails the build rather than quietly falling back to the onboard sensor.

The Qwiic modules build their sensor ids from an id-prefix substitution, so [BME680](/reference/qwiic/examples/bme680/) gives you `bme680_temperature`, [SCD41](/reference/qwiic/examples/scd41/) gives `scd41_temperature`, and [DS2484](/reference/qwiic/examples/ds2484/) gives whatever ids you assign your own `dallas_temp` sensors.

If you also run the [SSD1306 OLED](/reference/qwiic/examples/ssd1306/) module, note that it displays the onboard sensor regardless of this setting, so the screen and the fan control can show different temperatures.

The module names the sensor it is reading in its boot log, so you can confirm from a log dump that the override took effect.

:::caution[External sensors and startup]
A sensor that needs time before its first reading -- an SCD41 warming up, a BME680 on a long update interval, a Dallas probe -- reports no value for a while after boot. During that window this module commands the fans **off**. Keep the sensor's `update_interval` short if that matters to you, and expect the fans not to spin until the first reading lands. The onboard HDC1080 polls every 10 seconds and needs no warm-up, so the window is normally too short to notice; `modules/bme680.yaml` defaults to a 60 second interval, which stretches it considerably.
:::
