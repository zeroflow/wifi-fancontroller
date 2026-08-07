---
title: Temperature Curve Triple Independent
description: Three fully independent fan profiles, each with its own temperature axis and its own source sensor
sidebar:
  order: 6
---

:::note[All Revisions]
Works with all hardware revisions (Rev 1.0 through Rev 3.3).
:::

## Purpose

The Temperature Curve Triple Independent module holds three temperature-to-speed profiles and lets you pick between them from Home Assistant with a select entity. Nothing is shared between the profiles. Each one carries its own five temperature points, its own five speeds, and its own source sensor.

That last part is what separates it from every other temperature module on this board. One profile can follow a heat pump's flow temperature while another follows a room air sensor imported from Home Assistant, and a third can run inverted so the fans speed up as the temperature falls.

## When to Use

Choose this module when your profiles differ in more than aggressiveness. The typical case is one board serving several operating modes: a heat pump that heats in winter and cools in summer wants a rising curve on 28 to 50 C flow water, a falling curve on 8 to 20 C flow water, and a gentle circulation curve on room air for when the pump is idle. Three different bands and two different sensors is exactly what a shared axis cannot express.

If your three profiles use the same breakpoints and the same sensor and differ only in how hard they react, use [Temperature Curve Triple](/reference/modules/temperature-curve-triple/) instead. It does that job with 27 Home Assistant entities against this module's 37. For two profiles with separate axes, see [Temperature Curve Dual](/reference/modules/temperature-curve-dual/). For a single fixed curve, see [Temperature Curve](/reference/modules/temperature-curve/). The [modules overview](/reference/modules/) has a comparison table.

The module does not decide which profile is active. Profile selection is just a select entity; the automation logic lives in Home Assistant.

:::caution[One temperature module at a time]
Temperature Curve Triple Independent is a temperature control module. Do not enable it together with Temperature PID, Temperature Linear, Temperature Curve, Temperature Curve Dual, or Temperature Curve Triple. They share the `auto_control_fan1` to `auto_control_fan4` switches and would fight over the fan outputs.
:::

:::tip[Works with Stall Guard]
This module cooperates with [Stall Guard](/reference/modules/stall-guard/) via the safety floor mechanism. If a fan stalls, Stall Guard sets a minimum speed that this module respects during recovery. No extra configuration needed, just include both modules.
:::

## Source Sensors

Each profile names the sensor it reads through `curve_a_sensor_id`, `curve_b_sensor_id` and `curve_c_sensor_id`. Leaving all three at the default gives single-sensor behaviour: every profile follows the onboard HDC1080. Point one at any other sensor in your config, including a `platform: homeassistant` sensor pulled in from Home Assistant.

```yaml
sensor:
  - platform: homeassistant
    id: hp_flow_temperature
    entity_id: sensor.heat_pump_flow_temperature
  - platform: homeassistant
    id: ambient_air_temperature
    entity_id: sensor.living_room_temperature

substitutions:
  curve_a_sensor_id: "hp_flow_temperature"
  curve_b_sensor_id: "ambient_air_temperature"
  curve_c_sensor_id: "hp_flow_temperature"
```

Giving an imported sensor an `id` but no `name` keeps it internal. It is an input to the curve, not an entity worth publishing back to Home Assistant.

The module is evaluated on a fixed 10 second interval rather than from a sensor's `on_value` trigger. With three possible sources, an `on_value` trigger would only ever fire for one of them, so the interval is what keeps every profile responsive.

:::danger[A misspelled sensor id fails at compile time, not at validation]
`esphome config` will happily accept a `curve_*_sensor_id` that names an `id` which does not exist. The failure appears later, during compilation, as a C++ error along the lines of `'my_sensor' was not declared in this scope`, pointing at a line of generated code rather than at your YAML.

If you see that, check the spelling of your sensor ids first. The value must be the ESPHome `id:` of a sensor, not a Home Assistant `entity_id`.
:::

### When a source sensor goes unavailable

A sensor reads NAN whenever it has no value, which for a `platform: homeassistant` sensor happens while the Home Assistant entity is unavailable, while HA restarts, or simply before the first state arrives. A brief NAN is normal and must not disturb the fans.

The module holds the last good reading for 60 seconds and keeps controlling from it. If the sensor has still not recovered by then, it forces every fan to 100% until it does. Entry into the hold, expiry into the failsafe, and recovery are each logged at warning level.

Switching profiles discards the held value. Holding one profile's flow temperature and feeding it into another profile's ambient curve would produce a plausible looking but wrong speed.

## Enter each axis in ascending order

The module never sorts your points at runtime. For every profile, point 1 must be the coldest and point 5 the warmest.

:::danger[An unordered axis forces the fans to 100%, but only while that profile is active]
If any temperature point is not strictly greater than the one before it, the board logs a warning naming the offending profile and raises the **Curve Configuration Warning** sensor. All three axes are checked every cycle, so you find out about a profile you have misconfigured but not yet selected.

The failsafe is narrower than the warning. The fans are forced to 100% only while the broken profile is the **active** one. A misconfigured profile sitting idle must not run your fans flat out, but the profile actually in control has to fail loud, because interpolating over an unordered axis produces meaningless speeds.

This is checked against the values actually in use, so it also catches an axis you put out of order by editing the number entities in Home Assistant. Fixing the order restores normal control within a few seconds. No reboot needed.
:::

### Building an inverted curve

Speeds are a different matter from the axis. A profile whose speed falls as temperature rises is exactly how you drive fans harder as water gets colder in cooling mode. The board logs an informational note and raises the warning sensor so you can see it was noticed, but the profile keeps operating normally. It never triggers the failsafe.

Never invert the temperature axis to get an inverted curve. Enter the temperatures ascending and let the speeds descend:

```yaml
substitutions:
  # Cooling: the AXIS ascends 8 to 20, the SPEEDS descend 100 to 0
  curve_c_temp1: "8.0"
  curve_c_temp2: "11.0"
  curve_c_temp3: "14.0"
  curve_c_temp4: "17.0"
  curve_c_temp5: "20.0"
  curve_c_speed1: "100.0"
  curve_c_speed2: "80.0"
  curve_c_speed3: "55.0"
  curve_c_speed4: "30.0"
  curve_c_speed5: "0.0"
```

## Migrating from Temperature Curve Triple

The five shared `axis_temp1` to `axis_temp5` substitutions are replaced by three separate axes. To keep the behaviour you had, copy each `axis_tempN` value into all three of `curve_a_tempN`, `curve_b_tempN` and `curve_c_tempN`, then change the ones you actually want to differ.

Everything else keeps its name and meaning. The speed substitutions, the profile names, the select entity, the per-fan Auto Control switches and the output sensor are all unchanged, so nothing else in your config has to move.

The number entities do change. The shared module exposes one **Temp 1** to **Temp 5** block plus speeds named `<profile> 1` to `<profile> 5`. Here every number is profile-scoped and qualified, giving `<profile> Temp 1` to `<profile> Temp 5` and `<profile> Speed 1` to `<profile> Speed 5`. Home Assistant derives `entity_id` from the entity name, so the old entities do not carry over. Any dashboard card, automation or history that referenced them has to be repointed once.

## Renaming a profile renames its Home Assistant entities

The module's internal component IDs are fixed literals and are never built from the name variables, so renaming a profile cannot break curve selection or any lambda inside the firmware.

Home Assistant is the part that does not follow along. HA derives each `entity_id` from the entity name, not from the ESPHome ID, so changing `curve_c_name` from `Turbo` to `Cooling` renames that profile's ten number entities in Home Assistant. Any dashboard card, automation, or history that referenced the old names will break.

There is no workaround today; it is tracked upstream as [esphome/feature-requests#2119](https://github.com/esphome/feature-requests/issues/2119). Pick your profile names when you first set the board up.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `friendly_name` | `"Fancontroller"` | Device name prefix for the output sensor |
| `curve_a_name` | `"Normal"` | Display name for profile A |
| `curve_b_name` | `"Heating"` | Display name for profile B |
| `curve_c_name` | `"Turbo"` | Display name for profile C |
| `curve_a_sensor_id` | `"fancontroller_temperature"` | ESPHome `id` of the sensor profile A reads |
| `curve_b_sensor_id` | `"fancontroller_temperature"` | ESPHome `id` of the sensor profile B reads |
| `curve_c_sensor_id` | `"fancontroller_temperature"` | ESPHome `id` of the sensor profile C reads |
| `curve_a_temp1` | `"20.0"` | Profile A temperature point 1 (C) |
| `curve_a_temp2` | `"25.0"` | Profile A temperature point 2 (C) |
| `curve_a_temp3` | `"30.0"` | Profile A temperature point 3 (C) |
| `curve_a_temp4` | `"35.0"` | Profile A temperature point 4 (C) |
| `curve_a_temp5` | `"40.0"` | Profile A temperature point 5 (C) |
| `curve_a_speed1` | `"0.0"` | Profile A fan speed at point 1 (%) |
| `curve_a_speed2` | `"30.0"` | Profile A fan speed at point 2 (%) |
| `curve_a_speed3` | `"55.0"` | Profile A fan speed at point 3 (%) |
| `curve_a_speed4` | `"80.0"` | Profile A fan speed at point 4 (%) |
| `curve_a_speed5` | `"100.0"` | Profile A fan speed at point 5 (%) |
| `curve_b_temp1` | `"20.0"` | Profile B temperature point 1 (C) |
| `curve_b_temp2` | `"25.0"` | Profile B temperature point 2 (C) |
| `curve_b_temp3` | `"30.0"` | Profile B temperature point 3 (C) |
| `curve_b_temp4` | `"35.0"` | Profile B temperature point 4 (C) |
| `curve_b_temp5` | `"40.0"` | Profile B temperature point 5 (C) |
| `curve_b_speed1` | `"0.0"` | Profile B fan speed at point 1 (%) |
| `curve_b_speed2` | `"10.0"` | Profile B fan speed at point 2 (%) |
| `curve_b_speed3` | `"30.0"` | Profile B fan speed at point 3 (%) |
| `curve_b_speed4` | `"60.0"` | Profile B fan speed at point 4 (%) |
| `curve_b_speed5` | `"90.0"` | Profile B fan speed at point 5 (%) |
| `curve_c_temp1` | `"20.0"` | Profile C temperature point 1 (C) |
| `curve_c_temp2` | `"25.0"` | Profile C temperature point 2 (C) |
| `curve_c_temp3` | `"30.0"` | Profile C temperature point 3 (C) |
| `curve_c_temp4` | `"35.0"` | Profile C temperature point 4 (C) |
| `curve_c_temp5` | `"40.0"` | Profile C temperature point 5 (C) |
| `curve_c_speed1` | `"40.0"` | Profile C fan speed at point 1 (%) |
| `curve_c_speed2` | `"60.0"` | Profile C fan speed at point 2 (%) |
| `curve_c_speed3` | `"80.0"` | Profile C fan speed at point 3 (%) |
| `curve_c_speed4` | `"95.0"` | Profile C fan speed at point 4 (%) |
| `curve_c_speed5` | `"100.0"` | Profile C fan speed at point 5 (%) |

All three axes default to the same 20 to 40 C band, so a config that sets nothing but the speeds behaves like the shared-axis module.

## How It Works

At boot the module validates all three speed sets and reports the result to the log. The temperature axes are deliberately not checked at boot, only live, because the axis numbers are restorable and editable from Home Assistant, so the configured defaults stop being the values in use after the first boot.

Every 10 seconds it resolves the active profile from the select entity's index position, not by matching the option string, so renaming a profile in your substitutions cannot break which curve is active. Then it:

1. Scans all three live temperature axes, raising the warning sensor and logging the offending profile by name if any is unordered. The logging is edge triggered, so a persistent misconfiguration is logged once when it appears and once when it clears, not every 10 seconds.
2. Reads the active profile's source sensor, applying the 60 second hold if it is unavailable.
3. Returns 100% if the active profile's axis is unordered or the hold has expired.
4. Otherwise linearly interpolates the active profile's speeds over its own axis. Below the lowest point it holds the first speed; above the highest point it holds the last speed.

The result drives all four fans, gated per fan by the **Auto Control Fan 1** to **Fan 4** switches and by any active user override, and clamped by each fan's safety floor. The floor only applies to non-zero speeds; a commanded 0% always turns the fan off.

## Entities

| Entity | Type | Purpose |
|--------|------|---------|
| Curve Selection | select | Picks the active profile by name. Remembers its last choice across reboots. |
| `$curve_a_name` Temp 1 to 5, `$curve_b_name` Temp 1 to 5, `$curve_c_name` Temp 1 to 5 | number (15) | Each profile's own temperature axis, editable live |
| `$curve_a_name` Speed 1 to 5, `$curve_b_name` Speed 1 to 5, `$curve_c_name` Speed 1 to 5 | number (15) | Each profile's own speeds, editable live |
| Auto Control Fan 1 to 4 | switch (4) | Per-fan enable for automatic control |
| `$friendly_name` Curve Output | sensor | The active profile's computed fan speed (%) |
| Curve Configuration Warning | binary_sensor | Flags an unordered axis on any profile (live) or a dipping speed (at boot) |

37 entities in total, ten more than Temperature Curve Triple. That is the price of independent axes, and it is expected.

Entity names are laid out profile-major, so with the names from the example Home Assistant sorts them as `Cooling Speed 1..5`, `Cooling Temp 1..5`, `Heating Speed 1..5`, `Heating Temp 1..5`, and so on. Each profile is one contiguous block, which makes tuning a profile a straight read down the list.

## Web UI grouping

This block goes in **your own configuration**, not in the module. See [why the assignment lives in the consuming config](/reference/standalone/#grouping-module-entities-in-the-web-ui) for the reason. `version: 3` is what makes entity grouping work at all; without it, entity grouping has no effect.

```yaml
web_server:
  version: 3
  sorting_groups:
    - id: grp_temp_curve_triple_ind
      name: "Temperature Curve Triple Independent"
      sorting_weight: 140

number:
  - id: !extend curve_a_temp1
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 10
  - id: !extend curve_a_temp2
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 20
  - id: !extend curve_a_temp3
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 30
  - id: !extend curve_a_temp4
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 40
  - id: !extend curve_a_temp5
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 50
  - id: !extend curve_a_speed1
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 60
  - id: !extend curve_a_speed2
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 70
  - id: !extend curve_a_speed3
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 80
  - id: !extend curve_a_speed4
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 90
  - id: !extend curve_a_speed5
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 100
  - id: !extend curve_b_temp1
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 110
  - id: !extend curve_b_temp2
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 120
  - id: !extend curve_b_temp3
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 130
  - id: !extend curve_b_temp4
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 140
  - id: !extend curve_b_temp5
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 150
  - id: !extend curve_b_speed1
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 160
  - id: !extend curve_b_speed2
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 170
  - id: !extend curve_b_speed3
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 180
  - id: !extend curve_b_speed4
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 190
  - id: !extend curve_b_speed5
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 200
  - id: !extend curve_c_temp1
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 210
  - id: !extend curve_c_temp2
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 220
  - id: !extend curve_c_temp3
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 230
  - id: !extend curve_c_temp4
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 240
  - id: !extend curve_c_temp5
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 250
  - id: !extend curve_c_speed1
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 260
  - id: !extend curve_c_speed2
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 270
  - id: !extend curve_c_speed3
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 280
  - id: !extend curve_c_speed4
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 290
  - id: !extend curve_c_speed5
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 300

select:
  - id: !extend curve_select
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 310

switch:
  - id: !extend auto_control_fan1
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 320
  - id: !extend auto_control_fan2
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 330
  - id: !extend auto_control_fan3
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 340
  - id: !extend auto_control_fan4
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 350

sensor:
  - id: !extend curve_output_value
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 360

binary_sensor:
  - id: !extend curve_config_warning_sensor
    web_server:
      sorting_group_id: grp_temp_curve_triple_ind
      sorting_weight: 900
```

## Switching Automatically

Pair the **Curve Selection** select with a Home Assistant automation driven by your heat pump's operating mode. Note that this uses `select.select_option` rather than `switch.turn_on`, and that the `option` value must match the profile name you configured.

```yaml
automation:
  - alias: "Radiator fans follow the heat pump into cooling mode"
    trigger:
      - platform: state
        entity_id: sensor.heat_pump_operating_mode
        to: "cooling"
    action:
      - service: select.select_option
        target: { entity_id: select.my_fancontroller_curve_selection }
        data:
          option: "Cooling"
```

See [`examples/with-temperature-curve-triple-independent-rev-3.1.yaml`](https://github.com/zeroflow/wifi-fancontroller/blob/main/examples/with-temperature-curve-triple-independent-rev-3.1.yaml) for a complete configuration.
