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

:::tip[Included in standard firmware]
Standard firmware includes independent profiles and curves through `modules/default_fan_profiles.yaml` and the internal `modules/fan_profile.yaml` package. Each fan has Manual, Silent, Balanced, Aggressive, Server, and Custom options under Controls, with its own five temperature/speed pairs under Configuration. The shared module documented below remains available for direct imports with its original per-fan automatic switches.
:::

:::note[Updating an existing custom configuration]
If your YAML imports a full `fancontroller-rev*.yaml` configuration and also imports `modules/temperature_curve.yaml` separately, remove the separate curve import when updating: the full configuration now includes it. Saved shared values and existing curve substitutions seed the first per-fan migration. After migration, standard-firmware overrides target `fan1_curve_temp1` / `fan1_curve_speed1` through fan 4 and rule 5; legacy `curve_temp*` / `curve_speed*` overrides no longer adjust the independent curves. Configurations that import only `hardware-rev-*.yaml` should keep their explicit curve import.
:::

## When to Use

Choose Curve when you need more control points than the linear module's three zones but don't need PID's automatic target-chasing behavior. It's ideal when you know exactly how you want fans to respond at specific temperatures.

For simpler threshold-based control, see [Temperature Linear](/reference/modules/temperature-linear/). For automatic temperature targeting, see [Temperature PID](/reference/modules/temperature-pid/). The [modules overview](/reference/modules/) has a comparison table.

:::tip[Works with Stall Guard]
This module cooperates with [Stall Guard](/reference/modules/stall-guard/) via a safety floor mechanism. If a fan stalls, Stall Guard sets a minimum speed that Temperature Curve will respect during recovery. No extra configuration needed, just include both modules.
:::

:::tip[Works with USR Buttons with Auto/Manual Mode]
A fan put into manual mode, from Home Assistant or from the board, is skipped by this module until it is released. No extra configuration is needed: the manual speed holds instead of being overwritten on the next ten-second tick. See [USR Buttons with Auto/Manual Mode](/reference/modules/usr-buttons-mode/).
:::

## Configuration for Direct Module Imports

The variables below configure the shared module when imported directly. Standard firmware exposes its independent curve settings through Home Assistant.

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
| `curve_input_min`       | `"0"`                         | Lowest value the Curve Temperature sliders accept  |
| `curve_input_max`       | `"60"`                        | Highest value the sliders accept                   |
| `curve_input_step`      | `"0.5"`                       | Slider step                                        |
| `curve_input_unit`      | `"°C"`                        | Unit shown on the sliders                          |

## How It Works

The five temperature/speed pairs define a piecewise linear curve:

1. Each pair sets a "point" on the curve (e.g., 25 C = 25% speed)
2. Between any two adjacent points, the fan speed is linearly interpolated
3. Below the lowest temperature point, fans run at that point's speed
4. Above the highest temperature point, fans run at that point's speed

**Auto-sorting:** Temperature points are sorted at runtime. Keep each curve in ascending order for clarity. Standard firmware raises **Curve Configuration Warning** when an active fan's curve has unordered or invalid points. Direct module imports validate the configured default temperatures at boot and log a warning when they are unordered.

A curve point of 0% drives the PWM output to 0%. Whether the fan then stops or holds a minimum speed is a property of the fan, not of the module. See [Fan Compatibility](/reference/fan-compatibility/) if you need the fans to come to a complete stop.

## Home Assistant Entities

### Per-Fan Profiles in Standard Firmware

Standard firmware exposes **Fan 1 profile** through **Fan 4 profile**, each with **Manual**, **Silent**, **Balanced**, **Aggressive**, **Server**, and **Custom**:

- Manual holds that fan's current speed. Adjusting its native running-speed percentage selects Manual for that fan alone.
- A preset replaces only that fan's ten curve values and enables temperature control for a running/curve-paused fan. A fan explicitly switched off remains off until switched on.
- Custom uses that fan's currently displayed rules for editing. Choosing a preset replaces them. Its own five temperature/speed pairs are labeled **Fan 1: 1. At temperature**, **Fan 1: 1. Run at**, and so on, under Configuration (40 settings total).
- Editing active rules changes the displayed label to Custom when they no longer match a preset. Explicitly choosing Custom keeps that label even if its rules match a preset. Edits in Manual do not change fixed fan speed.
- New installs start in Manual. On the first upgrade, existing automatic fans copy the saved shared curve; other fans remain Manual. Each fan's mode, curve, and participation restore independently on subsequent reboots.

The old shared profile, curve numbers/output sensor, automatic switches, and preset buttons are internal in standard firmware. Native fan IDs remain unchanged; automations using the old shared selector should target a per-fan profile instead. No separate dashboard is required.

When importing `modules/temperature_curve.yaml` directly, **Fan Profile** retains its original shared **Silent**, **Balanced**, **Aggressive**, **Server**, and **Custom** selector. It never changes the public **Auto Control Fan** switches. The following entity tables describe that direct-module setup. Its selector reflects saved curve points, and explicit Custom keeps the current points for editing. Values restore without reapplying a preset at boot.

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

The range, step and unit shown for the five Curve Temperature rows are the defaults. The four `curve_input` variables change them, which is how the module is used for humidity. See [Controlling From Humidity](#controlling-from-humidity).

### Preset Buttons

In standard firmware, select a preset from **Fan 1 profile** through **Fan 4 profile**. When importing this module directly, you can also apply a complete temperature curve with **Curve Preset Silent**, **Curve Preset Balanced**, **Curve Preset Aggressive**, or **Curve Preset Server** in Home Assistant or the device web UI (when enabled).

| Preset | Temperature / speed points | Speed at 30 C |
| ------ | -------------------------- | ------------- |
| Silent | 20 C / 0%, 25 C / 20%, 35 C / 40%, 45 C / 60%, 55 C / 80% | 30% |
| Balanced | 20 C / 0%, 25 C / 25%, 30 C / 50%, 40 C / 75%, 50 C / 100% | 50% |
| Aggressive | 20 C / 0%, 22 C / 30%, 28 C / 60%, 35 C / 85%, 40 C / 100% | about 67% |
| Server | 15 C / 20%, 20 C / 30%, 25 C / 50%, 30 C / 75%, 35 C / 100% | 75% |

For example, selecting **Server** in **Fan 2 profile** makes a running Fan 2 use 75% at 30 C while the other fans retain their profiles. Set **Fan 2: 4. At temperature** to **30 C** and **Fan 2: 4. Run at** to your desired percentage to customize that rule.

With a direct shared-module import, press **Curve Preset Server** and edit **Curve Temperature 4** / **Curve Speed 4** instead; all automatically controlled fans share those values. Keep the other temperature points in ascending order. Intermediate temperatures use smooth interpolation.

For a direct shared-module import, each button replaces all ten curve values and immediately recalculates the output. You can then fine-tune the number entities; no reflashing is needed. Values are saved using the existing number entities' restore behavior (allow the configured flash write interval before cutting power). Restarting does not reapply a preset over your saved edits.

Presets only affect fans whose **Auto Control Fan** switch is on and which are not in manual override. Safety floors still apply. Preset buttons are included with `modules/temperature_curve.yaml`; the dual and triple curve modules have separate controls.

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

These defaults apply when importing `modules/temperature_curve.yaml` directly. Standard firmware keeps these switches internal and defaults them OFF. Each per-fan selector controls its own automatic participation, preserving explicit Off commands and allowing curve-paused fans to restart.

### Binary Sensor

| Entity                      | Category   | Description                                               |
| --------------------------- | ---------- | --------------------------------------------------------- |
| Curve Configuration Warning | Diagnostic | ON if temperature points are not monotonically increasing |

## Web UI grouping

This block goes in **your own configuration**, not in the module. See [why the assignment lives in the consuming config](/reference/standalone/#grouping-module-entities-in-the-web-ui) for the reason. `version: 3` is what makes entity grouping work at all; without it, entity grouping has no effect.

```yaml
web_server:
  version: 3
  sorting_groups:
    - id: grp_temp_curve
      name: "Temperature Curve"
      sorting_weight: 110

number:
  - id: !extend curve_temp1
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 10
  - id: !extend curve_speed1
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 20
  - id: !extend curve_temp2
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 30
  - id: !extend curve_speed2
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 40
  - id: !extend curve_temp3
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 50
  - id: !extend curve_speed3
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 60
  - id: !extend curve_temp4
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 70
  - id: !extend curve_speed4
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 80
  - id: !extend curve_temp5
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 90
  - id: !extend curve_speed5
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 100

sensor:
  - id: !extend curve_output_value
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 110

switch:
  - id: !extend auto_control_fan1
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 120
  - id: !extend auto_control_fan2
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 130
  - id: !extend auto_control_fan3
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 140
  - id: !extend auto_control_fan4
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 150

binary_sensor:
  - id: !extend curve_config_warning_sensor
    web_server:
      sorting_group_id: grp_temp_curve
      sorting_weight: 900
```

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
- **Check whether your fans stop at 0%** - a 0% curve point does not guarantee a stopped fan. [Fan Compatibility](/reference/fan-compatibility/) lists tested fans and explains how to check yours.
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

## Controlling From Humidity

The onboard HDC1080 also measures relative humidity. It is declared as `fancontroller_humidity` in every hardware package, so humidity control needs no extra hardware. The module does not care what its input measures.

```yaml
# Your hardware package stays in the config as usual.
packages:
  temperature_curve:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_curve.yaml
        vars:
          friendly_name: "Humidity"
          temperature_sensor_id: "fancontroller_humidity"
          curve_input_min: "0"
          curve_input_max: "100"
          curve_input_step: "1"
          curve_input_unit: "%"
          curve_temp1: "50.0"
          curve_speed1: "0.0"
          curve_temp2: "60.0"
          curve_speed2: "25.0"
          curve_temp3: "70.0"
          curve_speed3: "50.0"
          curve_temp4: "75.0"
          curve_speed4: "75.0"
          curve_temp5: "80.0"
          curve_speed5: "100.0"
```

The four `curve_input` variables set the range, step and unit of the five Curve Temperature sliders. Their defaults (0, 60, 0.5, °C) are the previous fixed values, so configurations that do not set them behave exactly as before. Keep every curve point inside the chosen range.

:::note[The names still say temperature]
The sliders keep the names Curve Temperature 1 to 5, and the boot log still says "Temperature point". This is on purpose: renaming them would change the Home Assistant entities and break existing dashboards and automations. In a humidity config, read them as humidity points. Setting `friendly_name` to "Humidity" makes the output sensor read "Humidity Curve Output".
:::

The sliders keep their values across reboots and reflashes, so a board that ran the temperature curve before keeps the old temperature points. Set the five sliders once after switching.

The [preset buttons](#preset-buttons) are temperature presets. They load fixed temperature points between 15 and 55, so in a humidity config one press would replace your humidity curve with temperature values. Remove them in your own config:

```yaml
button:
  - id: !remove curve_preset_silent
  - id: !remove curve_preset_balanced
  - id: !remove curve_preset_aggressive
  - id: !remove curve_preset_server
```

The example below already does this.

The board's own warmth makes the onboard sensor read humidity a few percent low. Shift the curve points down a little, or add a humidity offset as shown in [Sensor offset](/reference/modules/usr-buttons-mode/#sensor-offset). The board is rated for 5 to 85 % relative humidity, non-condensing (see the [datasheet](/reference/datasheet/)), which is why the example reaches full speed at 80 %.

A complete config is in [examples/standalone-humidity-curve-rev-3.3.yaml](https://github.com/zeroflow/wifi-fancontroller/blob/main/examples/standalone-humidity-curve-rev-3.3.yaml). It runs without Home Assistant and groups the curve in the built-in web UI. For the walkthrough behind that setup, see [Standalone usage](/reference/standalone/).
