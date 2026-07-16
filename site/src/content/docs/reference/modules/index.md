---
title: Modules Overview
description: Optional add-on modules for temperature control, RPM regulation, and LED status
sidebar:
  label: Overview
  order: 0
---

The WiFi Fan Controller supports optional YAML modules that add advanced functionality beyond basic fan speed control. Modules handle temperature-based automation, closed-loop RPM regulation, and RGB status indicators -- all configurable from Home Assistant without reflashing.

If you haven't set up your board yet, start with the [getting started guide](/getting-started/) first, then come back here to add modules.

## How Modules Work

Modules use ESPHome's `packages:` feature to import additional YAML configuration on top of your base firmware. Each module is a single YAML file hosted in the repository that you reference by URL:

```yaml
packages:
  # Your hardware package (already in your config)
  wifi-fancontroller:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [hardware-rev-3.1.yaml]

  # Add a module
  temperature_control:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_pid.yaml
        vars:
          friendly_name: "My Fan Controller"
```

Modules define their configuration through `vars:` -- substitution variables that let you customize behavior without editing the module YAML directly. Each module page documents all available variables with their defaults.

### Customizing a module

Because you pull a module in as a remote package, you never edit its file. Everything you might want to do falls into one of three operations, in rough order of difficulty:

| I want to... | Mechanism | Example |
|--------------|-----------|---------|
| Add my own sensors or entities | Nothing special -- just write them. Lists merge. | A `dallas_temp` sensor with `one_wire_id: ow_bus` |
| Configure the module (names, intervals) | `vars:` on the package, or top-level `substitutions:` | `ow_prefix: "Aquarium"` |
| Change or remove an entity the module defines | `!extend <id>` / `!remove <id>` | `- id: !extend ow_device_count` |

**Adding your own entities** needs no special syntax. ESPHome merges same-named lists (`sensor:`, `switch:`, and so on) across all packages and your config. Just declare your entity and point it at the module's bus or components by their `id`.

**Configuring** a module is done through the substitution variables it exposes. Set them with `vars:` under the package's `files:` entry, or as top-level `substitutions:` in your own config. Each module page lists its variables and defaults.

**Changing or removing** a module's own entity uses ESPHome's `!extend` and `!remove` tags, which reach into the merged config by `id`:

```yaml
# Replace one key on a module entity (keeps everything else):
sensor:
  - id: !extend ow_device_count
    update_interval: 10s

# Remove a module entity entirely:
text_sensor:
  - id: !remove ow_device_list
```

:::caution[`!extend` is not for adding]
The single most common mistake: reaching for `!extend` to add something new. `!extend` only modifies an entity that **already exists** by `id`. To add a new entity you write it plainly and let the lists merge (row one above). Use `!extend` only to change an entity the module already defines.
:::

Two things to know about what `!extend` and `!remove` can reach:

- They target **top-level component list items by their `id:`** (an entry directly under `sensor:`, `switch:`, `one_wire:`, and so on). A **nested** sub-ID, such as the `temperature:` block inside a combined sensor, is not a top-level entry and cannot be targeted this way.
- They work against remote `github://` packages, not only local includes. The merge happens after the package is fetched, so the module's IDs are all reachable.

### Substitution names are global

Substitution names live in one shared namespace across every package. If two modules both defined a variable called `update_interval`, whichever loaded last would silently win, and you would get a value you did not choose with no error. To avoid this, module variables and IDs use a short module prefix: `ow_` for the DS2484 1-Wire module, `oled_` for the display, and so on. When you name your own substitutions, avoid those prefixes.

### Two small tips

- **The order of packages does not matter.** Merging is non-destructive, so listing the hardware package before or after a module makes no difference.
- **While developing, pin `refresh: 0s`** on a package so ESPHome always re-fetches it. The default caches a remote package for a day, and it is easy to spend an hour debugging a version of the file you already changed.

  ```yaml
  packages:
    ds2484:
      url: https://github.com/zeroflow/wifi-fancontroller
      ref: main
      refresh: 0s
      files: [modules/ds2484_onewire.yaml]
  ```

## Module Comparison

| Module | Complexity | Best Use Case | HA Entities Created | Revisions |
|--------|-----------|---------------|---------------------|-----------|
| [Temperature PID](/reference/modules/temperature-pid/) | Advanced | Precise temperature target with automatic adjustment | 20 (climate, numbers, sensors, switches, fan, button) | All |
| [Temperature Linear](/reference/modules/temperature-linear/) | Simple | Straightforward temperature-to-speed mapping | 10 (numbers, sensor, switches) | All |
| [Temperature Curve](/reference/modules/temperature-curve/) | Medium | Custom multi-point fan profiles | 16 (numbers, sensor, switches, binary sensor) | All |
| [Dual Curve](/reference/modules/dual-curve/) | Medium | Two switchable profiles (e.g. aggressive vs defensive) | 27 (numbers, sensor, switches, binary sensor) | All |
| [RPM PI Control](/reference/modules/rpm-pi-control/) | Advanced | Exact RPM targeting per fan | 31 (numbers, sensors, switches, button) | All |
| [RPM Status LEDs](/reference/modules/rpm-status-leds/) | Simple | Visual RPM feedback via board LEDs | 0 (writes to existing LED entities) | Rev 3.1+ |
| [Stall Guard](/reference/modules/stall-guard/) | Simple | Fan stall detection and automatic recovery | 9 (binary sensors, text sensors, button) | All |
| [USR Buttons](/reference/modules/usr-buttons/) | Simple | Physical button control of individual fan speeds | 5 (button, 4 switches) | Rev 3.1+ |

## Compatibility

### Temperature modules are mutually exclusive

:::caution
You can only use **one** temperature control module at a time (PID, Linear, Curve, or Dual Curve). These modules define overlapping internal component IDs -- PID and Linear both define `proxy_output`, while Linear, Curve, and Dual Curve all define `auto_control_fan1`--`auto_control_fan4` switches. Even where IDs don't conflict, running two temperature controllers simultaneously would cause unpredictable fan behavior.
:::

:::caution
**Stall Guard** and **RPM PI Control** cannot be used together. RPM PI Control writes directly to PWM outputs, bypassing the fan entity that Stall Guard uses for recovery. RPM PI Control's feedback loop already handles stall-like scenarios through its closed-loop regulation.
:::

:::caution
**Temperature PID** and **RPM PI Control** can run side by side, but only when each fan is assigned to one or the other. PID exposes `PID Control Fan 1`--`Fan 4` switches (default ON), PI exposes `PI Control Fan 1`--`Fan 4` switches (default OFF). If both are enabled for the same fan, the two loops fight over the PWM output. See [`examples/with-pid-and-pi.yaml`](https://github.com/zeroflow/wifi-fancontroller/blob/main/examples/with-pid-and-pi.yaml) for a working split configuration.
:::

### Compatibility matrix

Most modules can be combined freely. The two exceptions are: temperature modules are mutually exclusive (see above), and Stall Guard conflicts with RPM PI Control (both write to PWM outputs). The full compatibility matrix:

| | Temp PID | Temp Linear | Temp Curve | Dual Curve | RPM PI Control | RPM Status LEDs | Stall Guard | USR Buttons |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Temperature PID** | -- | ❌ | ❌ | ❌ | ⚠️ | ✅ | ✅ | ✅ |
| **Temperature Linear** | ❌ | -- | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| **Temperature Curve** | ❌ | ❌ | -- | ❌ | ✅ | ✅ | ✅ | ✅ |
| **Dual Curve** | ❌ | ❌ | ❌ | -- | ✅ | ✅ | ✅ | ✅ |
| **RPM PI Control** | ⚠️ | ✅ | ✅ | ✅ | -- | ✅ | ❌ | ✅ |
| **RPM Status LEDs** | ✅ | ✅ | ✅ | ✅ | ✅ | -- | ✅ | ✅ |
| **Stall Guard** | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | -- | ✅ |
| **USR Buttons** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | -- |

## Module List

### Temperature Control

- **[Temperature PID](/reference/modules/temperature-pid/)** -- Advanced PID thermostat that automatically adjusts fan speed to maintain a target temperature. Includes live tuning via Home Assistant, autotune, and deadband control.

- **[Temperature Linear](/reference/modules/temperature-linear/)** -- Simple three-zone mapping from temperature to fan speed. No complex tuning required -- set your thresholds and you're done.

- **[Temperature Curve](/reference/modules/temperature-curve/)** -- Define a custom 5-point temperature-to-speed curve for precise control over how fans respond at different temperatures. Includes preset profiles for common scenarios.

- **[Dual Curve](/reference/modules/dual-curve/)** -- Two complete 5-point curves (for example aggressive and defensive) switchable from Home Assistant with a single switch. Sensor-agnostic; pair the switch with an automation, such as flipping to the defensive curve on poor air quality.

### RPM Control

- **[RPM PI Control](/reference/modules/rpm-pi-control/)** -- Closed-loop RPM regulation that maintains exact fan speeds regardless of load changes. Useful when you need consistent, precise airflow.

- **[RPM Status LEDs](/reference/modules/rpm-status-leds/)** -- Colors the per-fan RGB LEDs based on RPM (red at 0, green at full speed). Requires Rev 3.1+ hardware with per-fan RGB LEDs.

### Fan Safety

- **[Stall Guard](/reference/modules/stall-guard/)** -- Detects fan stalls (0 RPM when commanded on) and automatically raises fan speed to attempt recovery. Works cooperatively with temperature modules via a safety floor mechanism. Flags persistent warnings in Home Assistant so you know to investigate.

### Physical Controls

- **[USR Buttons](/reference/modules/usr-buttons/)** -- Direct fan speed control via the three on-board USR buttons with per-fan RGB LED feedback. Manual overrides persist until cleared through Home Assistant. Requires Rev 3.1+ hardware.
