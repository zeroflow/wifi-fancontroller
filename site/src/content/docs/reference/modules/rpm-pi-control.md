---
title: RPM PI Control
description: Closed-loop RPM regulation module for precise fan speed control
sidebar:
  order: 6
---

:::note[All Revisions]
Works with all hardware revisions (Rev 1.0 through Rev 3.3).
:::

## Purpose

The RPM PI Control module provides closed-loop RPM regulation that maintains exact fan speeds regardless of load changes, backpressure, or voltage variation. While [temperature modules](/reference/modules/) set fan speed based on heat, RPM PI control ensures fans actually reach and hold the commanded speed by continuously adjusting the PWM duty cycle.

## When to Use

Use RPM PI control when precise RPM targets matter -- server cooling with specific airflow requirements, noise management at exact speed limits, or testing fans at defined operating points. This module can be combined with any temperature module: the temperature module sets the desired speed, and RPM PI ensures the fans actually reach it.

See the [modules overview](/reference/modules/) for a comparison of all available modules.

## Configuration

The module accepts these substitution variables in the `packages:` block:

| Variable | Default | Description |
|----------|---------|-------------|
| `friendly_name` | `"Fancontroller"` | Device name prefix for all HA entities |
| `kp` | `"50"` | Proportional gain (UI-scaled, see [scaling section](#scaling-convention-x100000)) |
| `ki` | `"10"` | Integral gain (UI-scaled, see [scaling section](#scaling-convention-x100000)) |
| `update_interval` | `"1s"` | Control loop interval (ESPHome time literal, e.g. `"1s"`, `"500ms"`) |

Parameters like integral limit, deadband, PWM minimum, and setpoint change threshold are **not** YAML substitution variables. They are runtime-adjustable through Home Assistant number entities (see below).

## Home Assistant Entities

### Numbers (10)

These number entities are adjustable at runtime through Home Assistant -- no reflashing needed. The first six control the PI algorithm behavior, while the last four set per-fan target speeds.

| Entity | Range | Step | Unit | Description |
|--------|-------|------|------|-------------|
| PI Kp | 0--1000 | 1 | -- | Proportional gain (UI-scaled) |
| PI Ki | 0--100 | 1 | -- | Integral gain (UI-scaled) |
| PI Integral Limit | 0.1--1.0 | 0.1 | -- | Anti-windup clamp for I-term |
| PWM Minimum | 0--50 | 1 | % | Minimum PWM when target RPM > 0 |
| PI Deadband | 0--100 | 1 | RPM | Error tolerance (no correction inside this range) |
| PI Setpoint Change Threshold | 0--1000 | 50 | RPM | RPM change that resets I-term |
| Fan 1 Target RPM | 0--4000 | 10 | RPM | Target speed for fan 1 |
| Fan 2 Target RPM | 0--4000 | 10 | RPM | Target speed for fan 2 |
| Fan 3 Target RPM | 0--4000 | 10 | RPM | Target speed for fan 3 |
| Fan 4 Target RPM | 0--4000 | 10 | RPM | Target speed for fan 4 |

### Sensors (16)

Each fan exposes four diagnostic sensors for monitoring the control loop in real time:

| Entity | Unit | Description |
|--------|------|-------------|
| Fan 1--4 Error | RPM | Difference between target and actual RPM |
| Fan 1--4 P-Term | % | Proportional contribution to output |
| Fan 1--4 I-Term | % | Integral contribution to output |
| Fan 1--4 PWM Output | % | Final PWM duty cycle sent to fan |

### Switches (4)

:::caution
PI control switches default to **OFF**. You must enable each fan individually before the PI controller will regulate its speed.
:::

| Entity | Default | Description |
|--------|---------|-------------|
| PI Control Fan 1 | OFF | Enable/disable PI control for fan 1 |
| PI Control Fan 2 | OFF | Enable/disable PI control for fan 2 |
| PI Control Fan 3 | OFF | Enable/disable PI control for fan 3 |
| PI Control Fan 4 | OFF | Enable/disable PI control for fan 4 |

### Button (1)

| Entity | Description |
|--------|-------------|
| Reset PI Integrators | Resets all four integral terms to zero (useful when tuning) |

## YAML Examples

### Basic Usage

```yaml
packages:
  rpm_pi_control:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/rpm_pi_control.yaml
        vars:
          friendly_name: "My Fan Controller"
```

### High-Performance Server

Higher gains for fast, precise RPM tracking:

```yaml
packages:
  rpm_pi_control:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/rpm_pi_control.yaml
        vars:
          friendly_name: "Server Rack"
          kp: "80"
          ki: "15"
```

After flashing, adjust deadband and PWM minimum via the Home Assistant number entities for fine-tuning.

## Scaling Convention (x100000)

:::caution
The PI gains displayed in Home Assistant are scaled by **100,000** relative to the internal control values. This makes the sliders easier to use but means the numbers look very different from textbook PI values.
:::

### Conversion Table

| UI Value (HA slider) | Internal Value | Calculation |
|----------------------|----------------|-------------|
| kp = 50 | 0.0005 | 50 / 100,000 |
| kp = 100 | 0.001 | 100 / 100,000 |
| ki = 10 | 0.0001 | 10 / 100,000 |
| ki = 50 | 0.0005 | 50 / 100,000 |

### UI Ranges

| Parameter | UI Range | Internal Range |
|-----------|----------|----------------|
| Kp | 0--1000 | 0--0.01 |
| Ki | 0--100 | 0--0.001 |

**Recommended starting values:** kp 30--50, ki 5--10 (UI-scaled).

## Control Loop Features

### Anti-Windup

The integral term is clamped to a configurable limit (default 0.5), preventing the I-term from accumulating excessively when the fan cannot reach the target RPM. This avoids large overshoot when conditions change.

### Deadband

A configurable RPM tolerance (default 5 RPM) where no correction is applied. When the actual RPM is within the deadband of the target, the error is treated as zero. This prevents constant small adjustments and reduces oscillation around the setpoint.

### Setpoint Change Detection

When the target RPM changes by more than the configured threshold (default 200 RPM), the I-term is automatically reset to zero. This prevents overshoot that would occur if a large accumulated I-term from the previous setpoint carried over to a very different target speed.

### Update Interval

The control loop runs at a configurable interval (default 1 second), which matches the hardware fan speed sensor update rate. Faster intervals provide no benefit since the RPM reading only updates once per second.

## Advanced: Noisy Tachometers

:::tip
This section is **optional**. The default sensor configuration works well for most fans. Only apply filtering if you observe oscillating PI output in the debug sensors.
:::

Some fans produce unstable tachometer signals that cause the RPM reading to jump around, making the PI controller oscillate. You can smooth these readings by adding a sliding window filter using the `!extend` pattern:

```yaml
sensor:
  - id: !extend fan1_speed
    filters:
      - sliding_window_moving_average:
          window_size: 3
          send_every: 1
```

Repeat for `fan2_speed`, `fan3_speed`, and `fan4_speed` as needed. A window size of 3 provides good smoothing without adding significant delay.

## Tuning Tips

1. **Start with defaults** -- kp=50, ki=10 (UI-scaled) work well for most 4-pin PWM fans
2. **Monitor the debug sensors** -- the 16 diagnostic sensors in Home Assistant show exactly what the control loop is doing (error, P-term, I-term, PWM output per fan)
3. **Adjust kp for response speed** -- increase kp for faster response to RPM changes, decrease if you see oscillation
4. **Adjust ki for steady-state accuracy** -- increase ki to eliminate persistent RPM offset, decrease if you see overshoot or slow oscillation
5. **Use the Reset PI Integrators button** if the control loop gets stuck or after making large parameter changes
6. **Set a sensible deadband** -- 5--20 RPM prevents unnecessary micro-adjustments without sacrificing accuracy
7. **Enable one fan at a time** when first tuning -- this lets you isolate behavior without all four fans interacting
