---
title: Dual Curve
description: Two switchable 5-point temperature curves for aggressive vs defensive fan profiles
sidebar:
  order: 4
---

:::note[All Revisions]
Works with all hardware revisions (Rev 1.0 through Rev 3.3).
:::

## Purpose

The Dual Curve module holds two complete 5-point temperature-to-speed curves, A and B, and lets you switch between them from Home Assistant with a single switch. Curve A is meant to be an aggressive profile (cools hard, early) and curve B a defensive one (stays quiet longer, spins up later), but both are fully configurable.

## When to Use

Choose Dual Curve when you want two distinct fan profiles you can flip between, instead of constantly re-tuning a single curve. The classic case is pairing it with an air-quality automation: when the air is bad, a Home Assistant automation flips to the defensive curve so the fans stay quiet and ramp up later.

The module is sensor-agnostic. It does not read any air-quality sensor itself. Curve selection is just a switch; the automation logic lives in Home Assistant. For a single fixed curve, see [Temperature Curve](/reference/modules/temperature-curve/). The [modules overview](/reference/modules/) has a comparison table.

:::caution[One temperature module at a time]
Dual Curve is a temperature control module. Do not enable it together with Temperature PID, Temperature Linear, or Temperature Curve. They share the `auto_control_fan1`--`auto_control_fan4` switches and would fight over the fan outputs.
:::

:::tip[Works with Stall Guard]
This module cooperates with [Stall Guard](/reference/modules/stall-guard/) via the safety floor mechanism. If a fan stalls, Stall Guard sets a minimum speed that Dual Curve respects during recovery. No extra configuration needed, just include both modules.
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

See [`examples/with-dual-curve-rev-3.1.yaml`](https://github.com/zeroflow/wifi-fancontroller/blob/main/examples/with-dual-curve-rev-3.1.yaml) for a complete configuration.
