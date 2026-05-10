---
title: Modules Overview
description: Optional add-on modules for temperature control, RPM regulation, and LED status
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

## Module Comparison

| Module | Complexity | Best Use Case | HA Entities Created | Revisions |
|--------|-----------|---------------|---------------------|-----------|
| [Temperature PID](/reference/modules/temperature-pid/) | Advanced | Precise temperature target with automatic adjustment | 20 (climate, numbers, sensors, switches, fan, button) | All |
| [Temperature Linear](/reference/modules/temperature-linear/) | Simple | Straightforward temperature-to-speed mapping | 10 (numbers, sensor, switches) | All |
| [Temperature Curve](/reference/modules/temperature-curve/) | Medium | Custom multi-point fan profiles | 16 (numbers, sensor, switches, binary sensor) | All |
| [RPM PI Control](/reference/modules/rpm-pi-control/) | Advanced | Exact RPM targeting per fan | 31 (numbers, sensors, switches, button) | All |
| [RPM Status LEDs](/reference/modules/rpm-status-leds/) | Simple | Visual RPM feedback via board LEDs | 0 (writes to existing LED entities) | Rev 3.1+ |
| [Stall Guard](/reference/modules/stall-guard/) | Simple | Fan stall detection and automatic recovery | 9 (binary sensors, text sensors, button) | All |
| [USR Buttons](/reference/modules/usr-buttons/) | Simple | Physical button control of individual fan speeds | 5 (button, 4 switches) | Rev 3.1+ |

## Compatibility

### Temperature modules are mutually exclusive

:::caution
You can only use **one** temperature control module at a time. These modules define overlapping internal component IDs -- PID and Linear both define `proxy_output`, while Linear and Curve both define `auto_control_fan1`--`auto_control_fan4` switches. Even where IDs don't conflict, running two temperature controllers simultaneously would cause unpredictable fan behavior.
:::

:::caution
**Stall Guard** and **RPM PI Control** cannot be used together. RPM PI Control writes directly to PWM outputs, bypassing the fan entity that Stall Guard uses for recovery. RPM PI Control's feedback loop already handles stall-like scenarios through its closed-loop regulation.
:::

### Compatibility matrix

Most modules can be combined freely. The two exceptions are: temperature modules are mutually exclusive (see above), and Stall Guard conflicts with RPM PI Control (both write to PWM outputs). The full compatibility matrix:

| | Temp PID | Temp Linear | Temp Curve | RPM PI Control | RPM Status LEDs | Stall Guard | USR Buttons |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Temperature PID** | -- | No | No | Yes | Yes | Yes | Yes |
| **Temperature Linear** | No | -- | No | Yes | Yes | Yes | Yes |
| **Temperature Curve** | No | No | -- | Yes | Yes | Yes | Yes |
| **RPM PI Control** | Yes | Yes | Yes | -- | Yes | No | Yes |
| **RPM Status LEDs** | Yes | Yes | Yes | Yes | -- | Yes | Yes |
| **Stall Guard** | Yes | Yes | Yes | No | Yes | -- | Yes |
| **USR Buttons** | Yes | Yes | Yes | Yes | Yes | Yes | -- |

## Module List

### Temperature Control

- **[Temperature PID](/reference/modules/temperature-pid/)** -- Advanced PID thermostat that automatically adjusts fan speed to maintain a target temperature. Includes live tuning via Home Assistant, autotune, and deadband control.

- **[Temperature Linear](/reference/modules/temperature-linear/)** -- Simple three-zone mapping from temperature to fan speed. No complex tuning required -- set your thresholds and you're done.

- **[Temperature Curve](/reference/modules/temperature-curve/)** -- Define a custom 5-point temperature-to-speed curve for precise control over how fans respond at different temperatures. Includes preset profiles for common scenarios.

### RPM Control

- **[RPM PI Control](/reference/modules/rpm-pi-control/)** -- Closed-loop RPM regulation that maintains exact fan speeds regardless of load changes. Useful when you need consistent, precise airflow.

- **[RPM Status LEDs](/reference/modules/rpm-status-leds/)** -- Colors the per-fan RGB LEDs based on RPM (red at 0, green at full speed). Requires Rev 3.1+ hardware with per-fan RGB LEDs.

### Fan Safety

- **[Stall Guard](/reference/modules/stall-guard/)** -- Detects fan stalls (0 RPM when commanded on) and automatically raises fan speed to attempt recovery. Works cooperatively with temperature modules via a safety floor mechanism. Flags persistent warnings in Home Assistant so you know to investigate.

### Physical Controls

- **[USR Buttons](/reference/modules/usr-buttons/)** -- Direct fan speed control via the three on-board USR buttons with per-fan RGB LED feedback. Manual overrides persist until cleared through Home Assistant. Requires Rev 3.1+ hardware.
