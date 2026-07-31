---
title: Temperature Curve Dual
description: Two switchable 5-point temperature curves for aggressive vs defensive fan profiles
sidebar:
  order: 4
---

:::note[All Revisions]
Works with all hardware revisions (Rev 1.0 through Rev 3.3).
:::

## Purpose

The Temperature Curve Dual module holds two complete 5-point temperature-to-speed curves, A and B, and lets you switch between them from Home Assistant with a single switch. Curve A is meant to be an aggressive profile (cools hard, early) and curve B a defensive one (stays quiet longer, spins up later), but both are fully configurable.

## When to Use

Choose Temperature Curve Dual when you want two distinct fan profiles you can flip between, instead of constantly re-tuning a single curve. The classic case is pairing it with an air-quality automation: when the air is bad, a Home Assistant automation flips to the defensive curve so the fans stay quiet and ramp up later.

The module is sensor-agnostic. It does not read any air-quality sensor itself. Curve selection is just a switch; the automation logic lives in Home Assistant. For a single fixed curve, see [Temperature Curve](/reference/modules/temperature-curve/). The [modules overview](/reference/modules/) has a comparison table.

:::caution[One temperature module at a time]
Temperature Curve Dual is a temperature control module. Do not enable it together with Temperature PID, Temperature Linear, or Temperature Curve. They share the `auto_control_fan1`--`auto_control_fan4` switches and would fight over the fan outputs.
:::

:::tip[Works with Stall Guard]
This module cooperates with [Stall Guard](/reference/modules/stall-guard/) via the safety floor mechanism. If a fan stalls, Stall Guard sets a minimum speed that Temperature Curve Dual respects during recovery. No extra configuration needed, just include both modules.
:::

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `friendly_name` | `"Fancontroller"` | Device name prefix for the output sensor |
| `curveA_temp1` | `"20.0"` | Curve A temperature point 1 (C) |
| `curveA_speed1` | `"0.0"` | Curve A fan speed at point 1 (%) |
| `curveA_temp2` | `"22.0"` | Curve A temperature point 2 (C) |
| `curveA_speed2` | `"30.0"` | Curve A fan speed at point 2 (%) |
| `curveA_temp3` | `"28.0"` | Curve A temperature point 3 (C) |
| `curveA_speed3` | `"60.0"` | Curve A fan speed at point 3 (%) |
| `curveA_temp4` | `"35.0"` | Curve A temperature point 4 (C) |
| `curveA_speed4` | `"85.0"` | Curve A fan speed at point 4 (%) |
| `curveA_temp5` | `"40.0"` | Curve A temperature point 5 (C) |
| `curveA_speed5` | `"100.0"` | Curve A fan speed at point 5 (%) |
| `curveB_temp1` | `"25.0"` | Curve B temperature point 1 (C) |
| `curveB_speed1` | `"0.0"` | Curve B fan speed at point 1 (%) |
| `curveB_temp2` | `"35.0"` | Curve B temperature point 2 (C) |
| `curveB_speed2` | `"25.0"` | Curve B fan speed at point 2 (%) |
| `curveB_temp3` | `"45.0"` | Curve B temperature point 3 (C) |
| `curveB_speed3` | `"50.0"` | Curve B fan speed at point 3 (%) |
| `curveB_temp4` | `"50.0"` | Curve B temperature point 4 (C) |
| `curveB_speed4` | `"65.0"` | Curve B fan speed at point 4 (%) |
| `curveB_temp5` | `"55.0"` | Curve B temperature point 5 (C) |
| `curveB_speed5` | `"80.0"` | Curve B fan speed at point 5 (%) |
| `temperature_sensor_id` | `"fancontroller_temperature"` | Id of the sensor supplying the control temperature |

## How It Works

Every 10 seconds the module reads the board temperature, picks the active curve based on the **Curve Selection** switch (off = A, on = B), sorts that curve's five points by temperature, and linearly interpolates the fan speed. Below the lowest point it holds the first speed; above the highest point it holds the last speed.

The result drives all four fans, gated per fan by the **Auto Control Fan 1**--**Fan 4** switches and by any active user override, and clamped by each fan's safety floor (the floor only applies to non-zero speeds; a commanded 0% always turns the fan off).

## Entities

| Entity | Type | Purpose |
|--------|------|---------|
| Curve Selection | switch | Selects curve A (off) or B (on). Remembers its last state across reboots. |
| Curve A/B Temperature 1--5, Speed 1--5 | number (20) | The two curves' points, editable live |
| Auto Control Fan 1--4 | switch (4) | Per-fan enable for automatic control |
| `$friendly_name` Curve Output | sensor | The active curve's computed fan speed (%) |
| Curve Configuration Warning | binary_sensor | Flags a non-monotonic curve at boot |

## Switching Automatically

Pair the **Curve Selection** switch with a Home Assistant automation. For example, switch to the defensive curve when an air-quality sensor reports poor air:

```yaml
automation:
  - alias: "Defensive fan curve on poor air quality"
    trigger:
      - platform: numeric_state
        entity_id: sensor.living_room_pm2_5
        above: 35
    action:
      - service: switch.turn_on
        target: { entity_id: switch.my_fancontroller_curve_selection }
```

See [`examples/with-temperature-curve-dual-rev-3.1.yaml`](https://github.com/zeroflow/wifi-fancontroller/blob/main/examples/with-temperature-curve-dual-rev-3.1.yaml) for a complete configuration.

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
  temperature_curve_dual:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_curve_dual.yaml
        vars:
          temperature_sensor_id: "bme680_temperature"
```

Both curves read the same sensor; the A/B switch selects which curve is applied, not which sensor is used.

Omit the variable and it falls back to `fancontroller_temperature`, so existing configurations keep working unchanged. A misspelled id fails the build rather than quietly falling back to the onboard sensor.

The Qwiic modules build their sensor ids from an id-prefix substitution, so [BME680](/reference/qwiic/examples/bme680/) gives you `bme680_temperature`, [SCD41](/reference/qwiic/examples/scd41/) gives `scd41_temperature`, and [DS2484](/reference/qwiic/examples/ds2484/) gives whatever ids you assign your own `dallas_temp` sensors.

If you also run the [SSD1306 OLED](/reference/qwiic/examples/ssd1306/) module, note that it displays the onboard sensor regardless of this setting, so the screen and the fan control can show different temperatures.

:::caution[External sensors and startup]
A sensor that needs time before its first reading -- an SCD41 warming up, a BME680 on a long update interval, a Dallas probe -- reports no value for a while after boot. During that window this module commands the fans **off**. Keep the sensor's `update_interval` short if that matters to you, and expect the fans not to spin until the first reading lands. The onboard HDC1080 polls every 10 seconds and needs no warm-up, so the window is normally too short to notice; `modules/bme680.yaml` defaults to a 60 second interval, which stretches it considerably.
:::
