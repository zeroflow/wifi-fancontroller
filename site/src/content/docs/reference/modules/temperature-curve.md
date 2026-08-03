---
title: Temperature Curve
description: 5-point interpolated temperature curve module for custom fan profiles
sidebar:
  order: 3
---

:::note[All Revisions]
Works with all hardware revisions (Rev 1.0 through Rev 3.3).
:::

## Purpose

The Temperature Curve module lets you define a custom 5-point temperature-to-speed curve for granular control over fan behavior. Values between points are linearly interpolated, giving you a smooth speed transition across the entire temperature range.

## When to Use

Choose Curve when you need more control points than the linear module's three zones but don't need PID's automatic target-chasing behavior. It's ideal when you know exactly how you want fans to respond at specific temperatures.

For simpler threshold-based control, see [Temperature Linear](/reference/modules/temperature-linear/). For automatic temperature targeting, see [Temperature PID](/reference/modules/temperature-pid/). The [modules overview](/reference/modules/) has a comparison table.

:::tip[Works with Stall Guard]
This module cooperates with [Stall Guard](/reference/modules/stall-guard/) via a safety floor mechanism. If a fan stalls, Stall Guard sets a minimum speed that Temperature Curve will respect during recovery. No extra configuration needed, just include both modules.
:::

## Configuration

| Variable                | Default                       | Description                                        |
| ----------------------- | ----------------------------- | -------------------------------------------------- |
| `friendly_name`         | `"Fancontroller"`             | Device name prefix for all entities                |
| `curve_temp1`           | `"20.0"`                      | Temperature point 1 (C)                            |
| `curve_speed1`          | `"0.0"`                       | Fan speed at point 1 (%)                           |
| `curve_temp2`           | `"25.0"`                      | Temperature point 2 (C)                            |
| `curve_speed2`          | `"25.0"`                      | Fan speed at point 2 (%)                           |
| `curve_temp3`           | `"30.0"`                      | Temperature point 3 (C)                            |
| `curve_speed3`          | `"50.0"`                      | Fan speed at point 3 (%)                           |
| `curve_temp4`           | `"40.0"`                      | Temperature point 4 (C)                            |
| `curve_speed4`          | `"75.0"`                      | Fan speed at point 4 (%)                           |
| `curve_temp5`           | `"50.0"`                      | Temperature point 5 (C)                            |
| `curve_speed5`          | `"100.0"`                     | Fan speed at point 5 (%)                           |
| `temperature_sensor_id` | `"fancontroller_temperature"` | Id of the sensor supplying the control temperature |

## How It Works

The five temperature/speed pairs define a piecewise linear curve:

1. Each pair sets a "point" on the curve (e.g., 25 C = 25% speed)
2. Between any two adjacent points, the fan speed is linearly interpolated
3. Below the lowest temperature point, fans run at that point's speed
4. Above the highest temperature point, fans run at that point's speed

**Auto-sorting:** Temperature points are automatically sorted at runtime, so they work even if defined out of order. However, the module validates the curve at boot and logs a warning if points are not monotonically increasing.

## Home Assistant Entities

### Number Entities

| Entity              | Range    | Step | Unit | Default | Description          |
| ------------------- | -------- | ---- | ---- | ------- | -------------------- |
| Curve Temperature 1 | 0 -- 60  | 0.5  | C    | 20.0    | Temperature point 1  |
| Curve Speed 1       | 0 -- 100 | 1    | %    | 0       | Fan speed at point 1 |
| Curve Temperature 2 | 0 -- 60  | 0.5  | C    | 25.0    | Temperature point 2  |
| Curve Speed 2       | 0 -- 100 | 1    | %    | 25      | Fan speed at point 2 |
| Curve Temperature 3 | 0 -- 60  | 0.5  | C    | 30.0    | Temperature point 3  |
| Curve Speed 3       | 0 -- 100 | 1    | %    | 50      | Fan speed at point 3 |
| Curve Temperature 4 | 0 -- 60  | 0.5  | C    | 40.0    | Temperature point 4  |
| Curve Speed 4       | 0 -- 100 | 1    | %    | 75      | Fan speed at point 4 |
| Curve Temperature 5 | 0 -- 60  | 0.5  | C    | 50.0    | Temperature point 5  |
| Curve Speed 5       | 0 -- 100 | 1    | %    | 100     | Fan speed at point 5 |

### Sensor Entities

| Entity       | Unit | Description                                        |
| ------------ | ---- | -------------------------------------------------- |
| Curve Output | %    | Current interpolated fan speed (updated every 10s) |

### Switch Entities

| Entity             | Default | Description                    |
| ------------------ | ------- | ------------------------------ |
| Auto Control Fan 1 | ON      | Enable curve control for fan 1 |
| Auto Control Fan 2 | ON      | Enable curve control for fan 2 |
| Auto Control Fan 3 | ON      | Enable curve control for fan 3 |
| Auto Control Fan 4 | ON      | Enable curve control for fan 4 |

### Binary Sensor

| Entity                      | Category   | Description                                               |
| --------------------------- | ---------- | --------------------------------------------------------- |
| Curve Configuration Warning | Diagnostic | ON if temperature points are not monotonically increasing |

## YAML Examples

### Basic Usage (Default Balanced Curve)

```yaml
packages:
  temperature_curve:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_curve.yaml
        vars:
          friendly_name: "My Fan Controller"
```

### Silent Profile

Prioritizes low noise. Fans stay off until 25 C and ramp slowly, reaching only 80% at 55 C. Best for quiet home office environments where some temperature rise is acceptable.

```yaml
packages:
  temperature_curve:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_curve.yaml
        vars:
          friendly_name: "Silent Cooler"
          curve_temp1: "20.0"
          curve_speed1: "0.0"
          curve_temp2: "25.0"
          curve_speed2: "20.0"
          curve_temp3: "35.0"
          curve_speed3: "40.0"
          curve_temp4: "45.0"
          curve_speed4: "60.0"
          curve_temp5: "55.0"
          curve_speed5: "80.0"
```

### Balanced Profile

Good all-around curve that balances noise and cooling. This is the default configuration.

```yaml
packages:
  temperature_curve:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_curve.yaml
        vars:
          friendly_name: "Balanced Cooler"
          curve_temp1: "20.0"
          curve_speed1: "0.0"
          curve_temp2: "25.0"
          curve_speed2: "25.0"
          curve_temp3: "30.0"
          curve_speed3: "50.0"
          curve_temp4: "40.0"
          curve_speed4: "75.0"
          curve_temp5: "50.0"
          curve_speed5: "100.0"
```

### Aggressive Profile

Reacts quickly to temperature increases with steep ramp. Reaches full speed at 40 C. Best for high-performance setups where cooling takes priority over noise.

```yaml
packages:
  temperature_curve:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_curve.yaml
        vars:
          friendly_name: "Aggressive Cooler"
          curve_temp1: "20.0"
          curve_speed1: "0.0"
          curve_temp2: "22.0"
          curve_speed2: "30.0"
          curve_temp3: "28.0"
          curve_speed3: "60.0"
          curve_temp4: "35.0"
          curve_speed4: "85.0"
          curve_temp5: "40.0"
          curve_speed5: "100.0"
```

### Server Profile

Always-on baseline cooling with rapid ramp. Fans never fully stop (20% minimum at 15 C), reaching full speed at just 35 C. Designed for server racks and network closets.

```yaml
packages:
  temperature_curve:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_curve.yaml
        vars:
          friendly_name: "Server Rack"
          curve_temp1: "15.0"
          curve_speed1: "20.0"
          curve_temp2: "20.0"
          curve_speed2: "30.0"
          curve_temp3: "25.0"
          curve_speed3: "50.0"
          curve_temp4: "30.0"
          curve_speed4: "75.0"
          curve_temp5: "35.0"
          curve_speed5: "100.0"
```

## Tuning Tips

:::tip[Use the HA Number Entities]
All 10 curve parameters can be adjusted live from Home Assistant without reflashing. Experiment with different values and watch the Curve Output sensor to see the effect in real time.
:::

- **Watch the Configuration Warning sensor** -- if it shows ON in Home Assistant, your temperature points are not in ascending order. The module still works (points are auto-sorted at runtime), but it's best practice to define them in order for clarity.
- **Define temperatures in ascending order** -- while auto-sorting handles out-of-order points, having them in order makes your configuration easier to read and debug.
- **Start with the Balanced preset** -- the default curve works well for most scenarios. Adjust individual points based on your environment.
- **Consider your fans' minimum speed** -- if your fans need at least 20% PWM to spin reliably, make sure your lowest non-zero speed point is at or above that threshold.
- **Use the Curve Output sensor for debugging** -- it updates every 10 seconds and shows the current interpolated fan speed, making it easy to verify your curve behaves as expected at different temperatures.

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
  temperature_curve:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_curve.yaml
        vars:
          temperature_sensor_id: "bme680_temperature"
```

Omit the variable and it falls back to `fancontroller_temperature`, so existing configurations keep working unchanged. A misspelled id fails the build rather than quietly falling back to the onboard sensor.

The Qwiic modules build their sensor ids from an id-prefix substitution, so [BME680](/reference/qwiic/examples/bme680/) gives you `bme680_temperature`, [SCD41](/reference/qwiic/examples/scd41/) gives `scd41_temperature`, and [DS2484](/reference/qwiic/examples/ds2484/) gives whatever ids you assign your own `dallas_temp` sensors.

If you also run the [SSD1306 OLED](/reference/qwiic/examples/ssd1306/) module, note that it displays the onboard sensor regardless of this setting, so the screen and the fan control can show different temperatures.

The module names the sensor it is reading in its boot log, so you can confirm from a log dump that the override took effect.

:::caution[External sensors and startup]
A sensor that needs time before its first reading -- an SCD41 warming up, a BME680 on a long update interval, a Dallas probe -- reports no value for a while after boot. During that window this module commands the fans **off**. Keep the sensor's `update_interval` short if that matters to you, and expect the fans not to spin until the first reading lands. The onboard HDC1080 polls every 10 seconds and needs no warm-up, so the window is normally too short to notice; `modules/bme680.yaml` defaults to a 60 second interval, which stretches it considerably.
:::
