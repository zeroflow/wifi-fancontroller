---
title: RPM Status LEDs
description: RGB LED status indicator module based on fan RPM readings
sidebar:
  order: 8
---

:::caution[Rev 3.1+ Only]
This module requires **Rev 3.1 or later** hardware (3.1, 3.2, or 3.3). Earlier revisions do not have per-fan RGB LEDs.
:::

## Purpose

The RPM Status LEDs module provides visual RPM feedback using the per-fan RGB LEDs on Rev 3.x boards. Each LED sweeps through a full HSV hue rotation from red (0 RPM) through orange, yellow, and chartreuse to green (full RPM), giving at-a-glance fan health status without checking Home Assistant.

## When to Use

Use this module when you want a quick visual indicator of whether your fans are running and at what relative speed. It pairs with any temperature module -- the temperature module controls the fan speed, and the LEDs show you the result.

See the [modules overview](/reference/modules/) for a comparison of all available modules.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `full_rpm` | `"2500"` | RPM value that maps to fully green LED |
| `brightness` | `"0.5"` | LED brightness 0.0–1.0 |
| `update_interval` | `"1s"` | LED update frequency |
| `fan1_led_enabled` | `"true"` | Enable Fan 1 LED |
| `fan2_led_enabled` | `"true"` | Enable Fan 2 LED |
| `fan3_led_enabled` | `"true"` | Enable Fan 3 LED |
| `fan4_led_enabled` | `"true"` | Enable Fan 4 LED |

## How It Works

The module reads the RPM sensor for each enabled fan at the configured `update_interval` (default: every second) and maps the value to a red-to-green HSV hue rotation:

- **0 RPM** -- fully red (hue 0°)
- **25% of full_rpm** -- orange (hue 30°)
- **50% of full_rpm** -- yellow (hue 60°)
- **75% of full_rpm** -- chartreuse (hue 90°)
- **full_rpm or above** -- fully green (hue 120°)

Because the HSV rotation always keeps at least one RGB channel at full output, the LED stays vivid at every point in the range -- unlike a linear red/green crossfade which dims to half brightness at midpoint.

LED brightness is configurable via the `brightness` variable. The module writes directly to the `fan1_led` through `fan4_led` partition light entities defined in the Rev 3.x hardware packages. Individual LEDs can be disabled via the `fanX_led_enabled` variables, leaving those LEDs free for other uses.

## Home Assistant Entities

This module creates **no additional Home Assistant entities**. It writes directly to the existing LED partition light entities (`fan1_led` through `fan4_led`) that are already exposed by the Rev 3.x hardware package.

## YAML Examples

### Basic Usage

```yaml
packages:
  rpm_status_leds:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/rpm_status_leds.yaml
        vars:
          full_rpm: "2500"
```

### Dimmed LEDs with Unused Channels Disabled

```yaml
packages:
  rpm_status_leds:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/rpm_status_leds.yaml
        vars:
          full_rpm: "2500"
          brightness: "0.2"
          fan3_led_enabled: "false"
          fan4_led_enabled: "false"
```

### Slower Update Rate

Reduce the update frequency to save resources if rapid LED changes aren't needed:

```yaml
packages:
  rpm_status_leds:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/rpm_status_leds.yaml
        vars:
          update_interval: "5s"
```

### Quieter Fans

For fans with a lower maximum RPM, set `full_rpm` to match so the color gradient scales correctly:

```yaml
packages:
  rpm_status_leds:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/rpm_status_leds.yaml
        vars:
          full_rpm: "1500"
```

## Tuning Tips

1. **Set full_rpm to your fans' actual maximum RPM** for accurate color representation. Check the fan datasheet or observe the maximum RPM reading in Home Assistant with fans set to 100% speed.
2. **If LEDs always show green**, your `full_rpm` value is set too low -- the fans are exceeding it. Increase `full_rpm` to match the actual top speed.
3. **If LEDs always show red or orange**, your `full_rpm` may be set too high, or the fans are running slowly. Check that the fans are receiving adequate power and that the PWM signal is set above 0%.
4. **Reduce brightness** in dark environments to avoid glare. Values around `0.1`-`0.2` work well for enclosed spaces.
