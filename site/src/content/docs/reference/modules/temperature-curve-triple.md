---
title: Temperature Curve Triple
description: Three switchable fan profiles over one shared 5-point temperature axis
sidebar:
  order: 5
---

:::note[All Revisions]
Works with all hardware revisions (Rev 1.0 through Rev 3.3).
:::

## Purpose

The Temperature Curve Triple module holds three temperature-to-speed profiles and lets you pick between them from Home Assistant with a select entity. All three profiles share one set of five temperature points; only the speeds differ per profile.

Sharing the temperature axis is what makes the third profile free. Five shared temperature numbers plus three sets of five speed numbers is 20 entities, exactly the same as the two-curve module's 10 temperatures plus 10 speeds. You get a third profile without growing your Home Assistant entity list.

## When to Use

Choose Temperature Curve Triple when the temperatures you care about are fixed but how hard you want to react to them changes. A typical setup is Normal for everyday use, Quiet for the night, and Turbo for when the rack is under load. The temperature breakpoints stay the same; the aggressiveness changes.

If you need three profiles with genuinely different temperature breakpoints, use [Temperature Curve Triple Independent](/reference/modules/temperature-curve-triple-independent/), which gives each profile its own axis for ten more entities. For two profiles with separate axes, use [Temperature Curve Dual](/reference/modules/temperature-curve-dual/). For a single fixed curve, see [Temperature Curve](/reference/modules/temperature-curve/). The [modules overview](/reference/modules/) has a comparison table.

The module does not decide which profile is active. It reads no air-quality or occupancy sensor itself. Profile selection is just a select entity; the automation logic lives in Home Assistant.

:::caution[One temperature module at a time]
Temperature Curve Triple is a temperature control module. Do not enable it together with Temperature PID, Temperature Linear, Temperature Curve, Temperature Curve Dual, or Temperature Curve Triple Independent. They share the `auto_control_fan1`--`auto_control_fan4` switches and would fight over the fan outputs.
:::

:::tip[Works with Stall Guard]
This module cooperates with [Stall Guard](/reference/modules/stall-guard/) via the safety floor mechanism. If a fan stalls, Stall Guard sets a minimum speed that Temperature Curve Triple respects during recovery. No extra configuration needed, just include both modules.
:::

## Enter the temperature points in ascending order

The module never sorts your points at runtime. Point 1 must be the coldest and point 5 the warmest.

:::danger[An unordered axis forces the fans to 100%]
If any temperature point is not strictly greater than the one before it, the board treats it as a hard configuration fault. It logs a warning, raises the **Curve Configuration Warning** sensor, and drives every fan to 100% until you correct the points.

This is checked on every update cycle against the values actually in use, so it also catches an axis you put out of order by editing the **Temp 1**--**Temp 5** numbers in Home Assistant. Fixing the order restores normal control within a few seconds. No reboot needed.

That is deliberate. Interpolating over an unordered axis produces meaningless speeds, and a fan controller that fails loud is safe while one that fails silent is not.
:::

Speeds are a different matter. A profile whose speed dips as temperature rises is perfectly legitimate, and it is how you build a deliberate quiet band. The board logs an informational note and raises the warning sensor so you can see it was noticed, but the profile keeps operating normally. It never triggers the failsafe.

## Source Sensors

Each profile names the sensor it reads through `curve_a_sensor_id`, `curve_b_sensor_id` and `curve_c_sensor_id`. Leaving all three at the default gives the original behaviour: every profile follows the onboard HDC1080. Point one at any other sensor in your config, including a `platform: homeassistant` sensor pulled in from Home Assistant.

```yaml
sensor:
  - platform: homeassistant
    id: ambient_air_temperature
    entity_id: sensor.living_room_temperature

substitutions:
  curve_b_sensor_id: "ambient_air_temperature"
```

The module is evaluated on a fixed 10 second interval rather than from a sensor's `on_value` trigger. With three possible sources, an `on_value` trigger would only ever fire for one of them, so the interval is what keeps every profile responsive.

Bear in mind that the temperature axis is still shared. Two profiles reading sensors that live in different temperature bands will not both fit one set of breakpoints; that is what [Temperature Curve Triple Independent](/reference/modules/temperature-curve-triple-independent/) is for.

:::danger[A misspelled sensor id fails at compile time, not at validation]
`esphome config` will happily accept a `curve_*_sensor_id` that names an `id` which does not exist. The failure appears later, during compilation, as a C++ error along the lines of `'my_sensor' was not declared in this scope`, pointing at a line of generated code rather than at your YAML.

If you see that, check the spelling of your sensor ids first. The value must be the ESPHome `id:` of a sensor, not a Home Assistant `entity_id`.
:::

### When a source sensor goes unavailable

A sensor reads NAN whenever it has no value, which for a `platform: homeassistant` sensor happens while the Home Assistant entity is unavailable, while HA restarts, or simply before the first state arrives. A brief NAN is normal and must not disturb the fans.

The module holds the last good reading for 60 seconds and keeps controlling from it. If the sensor has still not recovered by then, it forces every fan to 100% until it does. Entry into the hold, expiry into the failsafe, and recovery are each logged at warning level.

Switching profiles discards the held value. Holding one profile's flow temperature and feeding it into another profile's ambient curve would produce a plausible looking but wrong speed.

## Renaming a profile renames its Home Assistant entities

The module's internal component IDs are fixed literals and are never built from the name variables, so renaming a profile cannot break curve selection or any lambda inside the firmware.

Home Assistant is the part that does not follow along. HA derives each `entity_id` from the entity name, not from the ESPHome ID, so changing `curve_b_name` from `Heating` to `Quiet` renames that profile's five number entities in Home Assistant. Any dashboard card, automation, or history that referenced the old names will break.

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
| `axis_temp1` | `"20.0"` | Shared temperature point 1 (C) |
| `axis_temp2` | `"25.0"` | Shared temperature point 2 (C) |
| `axis_temp3` | `"30.0"` | Shared temperature point 3 (C) |
| `axis_temp4` | `"35.0"` | Shared temperature point 4 (C) |
| `axis_temp5` | `"40.0"` | Shared temperature point 5 (C) |
| `curve_a_speed1` | `"0.0"` | Profile A fan speed at point 1 (%) |
| `curve_a_speed2` | `"30.0"` | Profile A fan speed at point 2 (%) |
| `curve_a_speed3` | `"55.0"` | Profile A fan speed at point 3 (%) |
| `curve_a_speed4` | `"80.0"` | Profile A fan speed at point 4 (%) |
| `curve_a_speed5` | `"100.0"` | Profile A fan speed at point 5 (%) |
| `curve_b_speed1` | `"0.0"` | Profile B fan speed at point 1 (%) |
| `curve_b_speed2` | `"10.0"` | Profile B fan speed at point 2 (%) |
| `curve_b_speed3` | `"30.0"` | Profile B fan speed at point 3 (%) |
| `curve_b_speed4` | `"60.0"` | Profile B fan speed at point 4 (%) |
| `curve_b_speed5` | `"90.0"` | Profile B fan speed at point 5 (%) |
| `curve_c_speed1` | `"40.0"` | Profile C fan speed at point 1 (%) |
| `curve_c_speed2` | `"60.0"` | Profile C fan speed at point 2 (%) |
| `curve_c_speed3` | `"80.0"` | Profile C fan speed at point 3 (%) |
| `curve_c_speed4` | `"95.0"` | Profile C fan speed at point 4 (%) |
| `curve_c_speed5` | `"100.0"` | Profile C fan speed at point 5 (%) |

## How It Works

At boot the module validates the shared temperature axis and all three speed sets, then reports the result to the log.

Every 10 seconds it resolves the active profile, reads that profile's source sensor, and computes a fan speed. It first re-checks that the five shared temperature points are still in ascending order, since you can edit them from Home Assistant at any time. If they are not, it returns 100% and stops there. Otherwise it picks the active profile's five speeds and linearly interpolates. Below the lowest point it holds the first speed; above the highest point it holds the last speed.

Profile selection is resolved by the select entity's index position, not by matching the option string, so renaming a profile in your substitutions cannot break which curve is active.

The result drives all four fans, gated per fan by the **Auto Control Fan 1**--**Fan 4** switches and by any active user override, and clamped by each fan's safety floor (the floor only applies to non-zero speeds; a commanded 0% always turns the fan off).

## Entities

| Entity | Type | Purpose |
|--------|------|---------|
| Curve Selection | select | Picks the active profile by name. Remembers its last choice across reboots. |
| Temp 1--5 | number (5) | The shared temperature axis, editable live |
| `$curve_a_name` 1--5, `$curve_b_name` 1--5, `$curve_c_name` 1--5 | number (15) | Each profile's five speeds, editable live |
| Auto Control Fan 1--4 | switch (4) | Per-fan enable for automatic control |
| `$friendly_name` Curve Output | sensor | The active profile's computed fan speed (%) |
| Curve Configuration Warning | binary_sensor | Flags an unordered axis (live) or a dipping speed (at boot) |

27 entities in total, the same count as Temperature Curve Dual.

Entity names are laid out profile-major, so with the default names Home Assistant sorts them as `Heating 1..5`, `Normal 1..5`, `Temp 1..5`, `Turbo 1..5`. Each profile is one contiguous block, which makes tuning a profile a straight read down the list. Where the shared `Temp` block lands depends on the profile names you chose, since it sorts alphabetically among them.

## Web UI grouping

This block goes in **your own configuration**, not in the module. See [why the assignment lives in the consuming config](/reference/standalone/#grouping-module-entities-in-the-web-ui) for the reason. `version: 3` is what makes entity grouping work at all; without it, entity grouping has no effect.

```yaml
web_server:
  version: 3
  sorting_groups:
    - id: grp_temp_curve_triple
      name: "Temperature Curve Triple"
      sorting_weight: 130

number:
  - id: !extend axis_temp1
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 10
  - id: !extend axis_temp2
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 20
  - id: !extend axis_temp3
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 30
  - id: !extend axis_temp4
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 40
  - id: !extend axis_temp5
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 50
  - id: !extend curve_a_speed1
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 60
  - id: !extend curve_a_speed2
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 70
  - id: !extend curve_a_speed3
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 80
  - id: !extend curve_a_speed4
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 90
  - id: !extend curve_a_speed5
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 100
  - id: !extend curve_b_speed1
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 110
  - id: !extend curve_b_speed2
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 120
  - id: !extend curve_b_speed3
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 130
  - id: !extend curve_b_speed4
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 140
  - id: !extend curve_b_speed5
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 150
  - id: !extend curve_c_speed1
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 160
  - id: !extend curve_c_speed2
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 170
  - id: !extend curve_c_speed3
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 180
  - id: !extend curve_c_speed4
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 190
  - id: !extend curve_c_speed5
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 200

select:
  - id: !extend curve_select
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 210

switch:
  - id: !extend auto_control_fan1
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 220
  - id: !extend auto_control_fan2
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 230
  - id: !extend auto_control_fan3
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 240
  - id: !extend auto_control_fan4
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 250

sensor:
  - id: !extend curve_output_value
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 260

binary_sensor:
  - id: !extend curve_config_warning_sensor
    web_server:
      sorting_group_id: grp_temp_curve_triple
      sorting_weight: 900
```

## Switching Automatically

Pair the **Curve Selection** select with a Home Assistant automation. Note that this uses `select.select_option` rather than `switch.turn_on`, and that the `option` value must match the profile name you configured.

```yaml
automation:
  - alias: "Quiet fan profile at night"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: select.select_option
        target: { entity_id: select.my_fancontroller_curve_selection }
        data:
          option: "Quiet"
```

See [`examples/with-temperature-curve-triple-rev-3.1.yaml`](https://github.com/zeroflow/wifi-fancontroller/blob/main/examples/with-temperature-curve-triple-rev-3.1.yaml) for a complete configuration.
