---
title: Temperature PID
description: PID thermostat control module for precise temperature-based fan automation
sidebar:
  order: 1
---

:::note[All Revisions]
Works with all hardware revisions (Rev 1.0 through Rev 3.3).
:::

## Purpose

The Temperature PID module provides closed-loop PID thermostat control that automatically adjusts fan speed to maintain a target temperature. It creates a climate entity in Home Assistant that acts as a thermostat -- set your desired temperature and the controller handles the rest.

### How PID Works for Fan Control

PID stands for Proportional-Integral-Derivative, three terms that work together:

- **Proportional (P):** Reacts to the current temperature error. The further the temperature is from the target, the faster the fans spin. This is the primary driver of fan speed.
- **Integral (I):** Corrects for persistent offset over time. If the P term alone can't quite reach the target, the I term slowly increases fan speed to close the gap.
- **Derivative (D):** Dampens rapid temperature changes. If temperature is rising quickly, the D term increases fan speed preemptively. Usually left at 0 for fan control since temperature changes are slow.

## When to Use

Choose PID when you need precise temperature maintenance with automatic adjustment -- for example, keeping a server closet at exactly 25 C. PID is the most capable temperature module but requires more configuration than the alternatives.

For simpler setups, consider [Temperature Linear](/reference/modules/temperature-linear/) (three-zone mapping) or [Temperature Curve](/reference/modules/temperature-curve/) (custom multi-point profile). See the [modules overview](/reference/modules/) for a comparison table.

:::tip[Works with Stall Guard]
This module cooperates with [Stall Guard](/reference/modules/stall-guard/) via a safety floor mechanism. If a fan stalls, Stall Guard sets a minimum speed that Temperature PID will respect during recovery. The safety floor takes precedence over both PID output and the minimum fan speed setting. No extra configuration needed, just include both modules.
:::

## Configuration

| Variable                       | Default                       | Description                                        |
| ------------------------------ | ----------------------------- | -------------------------------------------------- |
| `friendly_name`                | `"Fancontroller"`             | Device name prefix for all entities                |
| `kp`                           | `"3.0"`                       | Proportional gain (UI scale, x100)                 |
| `ki`                           | `"0.005"`                     | Integral gain (UI scale, x100)                     |
| `kd`                           | `"0.0"`                       | Derivative gain (UI scale, x100)                   |
| `max_integral`                 | `"0.0"`                       | Maximum integral term (0 = unlimited)              |
| `output_averaging_samples`     | `"1"`                         | Output smoothing samples                           |
| `derivative_averaging_samples` | `"5"`                         | Derivative smoothing samples                       |
| `temperature_sensor_id`        | `"fancontroller_temperature"` | Id of the sensor supplying the control temperature |

## Home Assistant Entities

### Climate

| Entity     | Description                   | Default                    |
| ---------- | ----------------------------- | -------------------------- |
| Thermostat | PID-controlled climate entity | Target 30 C, range 20-50 C |

### Number Entities

| Entity                      | Range    | Step  | Default | Description                                           |
| --------------------------- | -------- | ----- | ------- | ----------------------------------------------------- |
| PID kp                      | 0 -- 50  | 0.1   | 3.0     | Proportional gain (UI scale)                          |
| PID ki                      | 0 -- 0.2 | 0.001 | 0.005   | Integral gain (UI scale)                              |
| PID kd                      | 0 -- 200 | 1     | 0.0     | Derivative gain (UI scale)                            |
| PID Deadband Threshold Low  | 0 -- 5 C | 0.05  | 0.25    | How far below target before PID reacts                |
| PID Deadband Threshold High | 0 -- 5 C | 0.05  | 0.25    | How far above target before PID reacts                |
| PID Deadband ki Multiplier  | 0 -- 0.2 | 0.01  | 0.04    | Ki scaling inside deadband (0.04 = 4% of normal Ki)   |
| Fan Minimum Speed           | 0 -- 30% | 1     | 0       | Minimum fan speed enforced by PID (0 = fans can stop) |

### Sensor Entities

| Entity         | Unit | Description                                      |
| -------------- | ---- | ------------------------------------------------ |
| P term         | %    | Current proportional contribution                |
| I term         | %    | Current integral contribution                    |
| D term         | %    | Current derivative contribution                  |
| Output value   | %    | Combined PID output (fan speed)                  |
| Error value    | C    | Difference between actual and target temperature |
| Is in deadband | 0/1  | Whether temperature is within deadband range     |

### Switch Entities

| Entity            | Default | Description                  |
| ----------------- | ------- | ---------------------------- |
| PID Control Fan 1 | ON      | Enable PID control for fan 1 |
| PID Control Fan 2 | ON      | Enable PID control for fan 2 |
| PID Control Fan 3 | ON      | Enable PID control for fan 3 |
| PID Control Fan 4 | ON      | Enable PID control for fan 4 |

### Fan Entity

| Entity              | Description                                                                         |
| ------------------- | ----------------------------------------------------------------------------------- |
| Fan Manual Override | Bypasses PID and sets fan speed directly. Turning off resets the PID integral term. |

### Button

| Entity               | Description                                          |
| -------------------- | ---------------------------------------------------- |
| PID Climate Autotune | Starts ESPHome's automatic PID parameter calculation |

## Web UI grouping

This block goes in **your own configuration**, not in the module. See [why the assignment lives in the consuming config](/reference/standalone/#grouping-module-entities-in-the-web-ui) for the reason. `version: 3` is what makes entity grouping work at all; without it, entity grouping has no effect.

```yaml
web_server:
  version: 3
  sorting_groups:
    - id: grp_temp_pid
      name: "PID Temperature Control"
      sorting_weight: 160

number:
  - id: !extend pid_kp_number
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 10
  - id: !extend pid_ki_number
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 20
  - id: !extend pid_kd_number
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 30
  - id: !extend pid_threshold_low
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 40
  - id: !extend pid_threshold_high
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 50
  - id: !extend pid_ki_multiplier
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 60
  - id: !extend pwm_minimum_pid
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 70

fan:
  - id: !extend manual_fan_control
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 80

switch:
  - id: !extend pid_control_fan1
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 90
  - id: !extend pid_control_fan2
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 100
  - id: !extend pid_control_fan3
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 110
  - id: !extend pid_control_fan4
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 120

sensor:
  - id: !extend p_term
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 130
  - id: !extend i_term
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 140
  - id: !extend d_term
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 150
  - id: !extend o_term
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 160
  - id: !extend e_term
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 170
  - id: !extend in_deadband_term
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 180

climate:
  - id: !extend pid_thermostat
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 190

button:
  - id: !extend pid_autotune
    web_server:
      sorting_group_id: grp_temp_pid
      sorting_weight: 200
```

## YAML Examples

### Basic Usage (Default Settings)

```yaml
packages:
  temperature_pid:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_pid.yaml
        vars:
          friendly_name: "My Fan Controller"
```

### Custom Tuning Values

```yaml
packages:
  temperature_pid:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_pid.yaml
        vars:
          friendly_name: "Server Rack"
          kp: "5.0"
          ki: "0.01"
          kd: "0.0"
```

## Scaling Convention (x100)

:::caution[UI Values Are Scaled]
The PID number entities in Home Assistant display values that are **100 times larger** than the internal PID values. This makes the numbers easier to read and adjust in the UI.

When you set `kp = 3.0` in the HA interface, the controller internally uses `0.03`.
:::

### Conversion Table

| Parameter | UI Value (HA) | Internal Value | UI Range |
| --------- | ------------- | -------------- | -------- |
| kp        | 3.0           | 0.03           | 0 -- 50  |
| ki        | 0.005         | 0.00005        | 0 -- 0.2 |
| kd        | 0.0           | 0.0            | 0 -- 200 |

To convert: **Internal = UI / 100**

:::tip[PID Simulator Uses the Same Scale]
The [PID simulator](/pid-simulator/) uses the same UI-scale values as Home Assistant. You can enter simulator values directly into HA number entities without any conversion.
:::

## Tuning Tips

:::tip[Start with the Defaults]
The default values (`kp = 3.0`, `ki = 0.005`, `kd = 0.0`) work well for most setups. Try them before changing anything.
:::

**Getting started:**

- Set your target temperature in the thermostat entity and observe the behavior for 10-15 minutes
- Watch the **P term** sensor in HA -- it should react proportionally to temperature changes
- Watch the **I term** sensor -- it should slowly climb if the P term alone can't reach the target
- The **output value** sensor shows the combined fan speed percentage

**When to use Autotune:**

- Press the **PID Climate Autotune** button to let the controller calculate parameters automatically
- Autotune works best when the system is at a steady state (fans running, temperature stable)
- After autotune completes, the new parameters are saved to flash and persist across reboots

**Manual tuning:**

- Increase `kp` if fans react too slowly to temperature changes
- Increase `ki` if the temperature settles slightly above or below the target
- Leave `kd` at 0 unless you see oscillation -- temperature changes are usually slow enough that derivative control isn't needed

**Deadband:**

- The default deadband is +/- 0.25 C around the target temperature
- Inside the deadband, Ki is scaled to 4% of its normal value (`ki_multiplier = 0.04`), which prevents integral windup while allowing slow drift correction
- Increase the deadband thresholds if fans cycle on/off too frequently near the target

---

Based on work by [patrickcollins12/esphome-fan-controller](https://github.com/patrickcollins12/esphome-fan-controller).

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
  temperature_pid:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_pid.yaml
        vars:
          temperature_sensor_id: "bme680_temperature"
```

This becomes the climate component's process variable, so the thermostat's current temperature is the external sensor's reading.

Retune after switching sensors. A sensor at the end of a cable responds more slowly to fan changes than the onboard sensor does, and that added lag changes the gains that behave well -- start by reducing `kp` and re-checking for oscillation.

Omit the variable and it falls back to `fancontroller_temperature`, so existing configurations keep working unchanged. A misspelled id fails the build rather than quietly falling back to the onboard sensor.

The Qwiic modules build their sensor ids from an id-prefix substitution, so [BME680](/reference/qwiic/examples/bme680/) gives you `bme680_temperature`, [SCD41](/reference/qwiic/examples/scd41/) gives `scd41_temperature`, and [DS2484](/reference/qwiic/examples/ds2484/) gives whatever ids you assign your own `dallas_temp` sensors.

If you also run the [SSD1306 OLED](/reference/qwiic/examples/ssd1306/) module, note that it displays the onboard sensor regardless of this setting, so the screen and the fan control can show different temperatures.

The module names the sensor it is reading in its boot log, so you can confirm from a log dump that the override took effect.

:::caution[External sensors and startup]
A sensor that needs time before its first reading -- an SCD41 warming up, a BME680 on a long update interval, a Dallas probe -- reports no value for a while after boot. The PID controller has no process variable during that window. Keep the sensor's `update_interval` short if that matters to you. The onboard HDC1080 polls every 10 seconds and needs no warm-up, so the window is normally too short to notice; `modules/bme680.yaml` defaults to a 60 second interval, which stretches it considerably.
:::
