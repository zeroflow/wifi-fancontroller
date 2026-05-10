---
title: Temperature PID
description: PID thermostat control module for precise temperature-based fan automation
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

| Variable | Default | Description |
|----------|---------|-------------|
| `friendly_name` | `"Fancontroller"` | Device name prefix for all entities |
| `kp` | `"3.0"` | Proportional gain (UI scale, x100) |
| `ki` | `"0.005"` | Integral gain (UI scale, x100) |
| `kd` | `"0.0"` | Derivative gain (UI scale, x100) |
| `max_integral` | `"0.0"` | Maximum integral term (0 = unlimited) |
| `output_averaging_samples` | `"1"` | Output smoothing samples |
| `derivative_averaging_samples` | `"5"` | Derivative smoothing samples |

## Home Assistant Entities

### Climate

| Entity | Description | Default |
|--------|-------------|---------|
| Thermostat | PID-controlled climate entity | Target 30 C, range 20-50 C |

### Number Entities

| Entity | Range | Step | Default | Description |
|--------|-------|------|---------|-------------|
| PID kp | 0 -- 50 | 0.1 | 3.0 | Proportional gain (UI scale) |
| PID ki | 0 -- 0.2 | 0.001 | 0.005 | Integral gain (UI scale) |
| PID kd | 0 -- 200 | 1 | 0.0 | Derivative gain (UI scale) |
| PID Deadband Threshold Low | 0 -- 5 C | 0.05 | 0.25 | How far below target before PID reacts |
| PID Deadband Threshold High | 0 -- 5 C | 0.05 | 0.25 | How far above target before PID reacts |
| PID Deadband ki Multiplier | 0 -- 0.2 | 0.01 | 0.04 | Ki scaling inside deadband (0.04 = 4% of normal Ki) |
| Fan Minimum Speed | 0 -- 30% | 1 | 0 | Minimum fan speed enforced by PID (0 = fans can stop) |

### Sensor Entities

| Entity | Unit | Description |
|--------|------|-------------|
| P term | % | Current proportional contribution |
| I term | % | Current integral contribution |
| D term | % | Current derivative contribution |
| Output value | % | Combined PID output (fan speed) |
| Error value | C | Difference between actual and target temperature |
| Is in deadband | 0/1 | Whether temperature is within deadband range |

### Switch Entities

| Entity | Default | Description |
|--------|---------|-------------|
| PID Control Fan 1 | ON | Enable PID control for fan 1 |
| PID Control Fan 2 | ON | Enable PID control for fan 2 |
| PID Control Fan 3 | ON | Enable PID control for fan 3 |
| PID Control Fan 4 | ON | Enable PID control for fan 4 |

### Fan Entity

| Entity | Description |
|--------|-------------|
| Fan Manual Override | Bypasses PID and sets fan speed directly. Turning off resets the PID integral term. |

### Button

| Entity | Description |
|--------|-------------|
| PID Climate Autotune | Starts ESPHome's automatic PID parameter calculation |

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
|-----------|--------------|----------------|----------|
| kp | 3.0 | 0.03 | 0 -- 50 |
| ki | 0.005 | 0.00005 | 0 -- 0.2 |
| kd | 0.0 | 0.0 | 0 -- 200 |

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
