---
title: Temperature Curve Per Fan
description: Optional independent temperature profiles and five-point curves for all four fans
sidebar:
  order: 7
---

## Purpose

This optional module gives each fan its own **Manual**, **Silent**, **Balanced**, **Aggressive**, **Server**, or **Custom** profile and five editable temperature/speed pairs. Fans can follow different curves at the same time. All four curves use the same temperature sensor, which defaults to the onboard HDC1080.

Standard and factory firmware are unchanged. Add this module to a custom ESPHome configuration, then flash that configuration. The selectors and rules appear on the device page in Home Assistant and in the device web UI if enabled; no separate dashboard is required.

:::caution[Choose one controller]
Do not combine this module with Temperature PID, Linear, Curve, Curve Dual, Curve Triple, Curve Triple Independent, or RPM PI Control. Two controllers writing the same fans would compete. The module works with Stall Guard, Fallback Mode, RPM Status LEDs, and either USR Buttons module. Physical manual overrides take precedence until cleared.
:::

## Installation

Use the hardware package for your board revision and the optional module from the same repository ref. For a local checkout, use local includes for both packages. A complete example is [with-temperature-curve-per-fan-rev-3.3.yaml](https://github.com/zeroflow/wifi-fancontroller/blob/main/examples/with-temperature-curve-per-fan-rev-3.3.yaml).

```yaml
packages:
  hardware:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [hardware-rev-3.3.yaml]
  per_fan:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [modules/temperature_curve_per_fan.yaml]
```

The module is standalone: it does not import the shared `temperature_curve.yaml`, modify native fan entities, or migrate settings from another module. Existing shared-curve users should remove the shared module before adding this one. Each fan starts in **Manual**, with Balanced values as its initial editable rules. Adding the module does not itself command a startup fan speed; the hardware package retains its own startup behavior.

## Controls

Open **Settings → Devices & services → ESPHome → your controller**. Under **Controls**, use **Fan 1 profile** through **Fan 4 profile** independently.

| What you want | What to do |
| --- | --- |
| A fixed speed | Select **Manual**, then set that fan's percentage |
| Keep a fan off | Select **Manual**, then switch that fan off |
| Temperature-based cooling | Select **Silent**, **Balanced**, **Aggressive**, or **Server** |
| Use your own rules | Select **Custom** and edit that fan's rules under Configuration |

Selecting an automatic profile applies it immediately, even if the fan was off. The module then updates each fan every 10 seconds. While a curve is active, an ordinary fan speed or off command is overwritten on the next tick; it does **not** select Manual. Startup speed writes and Stall Guard recovery bumps likewise leave the selected profile intact. A physical-button override pauses curve control until that override is cleared, without changing the profile selector.

The curve alone decides whether automatic output should be zero. A fan paused at 0% resumes automatically when temperature rises. Non-zero commands respect the hardware safety floor; a zero curve output still turns the fan off. The hardware's fan speed level count must remain **100**, so one level equals one percent.

### Presets

A preset replaces only the selected fan's ten curve values.

| Profile | Temperature / speed points | Speed at 30 C |
| --- | --- | --- |
| Silent | 20 C / 0%, 25 C / 20%, 35 C / 40%, 45 C / 60%, 55 C / 80% | 30% |
| Balanced | 20 C / 0%, 25 C / 25%, 30 C / 50%, 40 C / 75%, 50 C / 100% | 50% |
| Aggressive | 20 C / 0%, 22 C / 30%, 28 C / 60%, 35 C / 85%, 40 C / 100% | about 67% |
| Server | 15 C / 20%, 20 C / 30%, 25 C / 50%, 30 C / 75%, 35 C / 100% | 75% |

### Custom rules

Each fan exposes five pairs under **Configuration**, labeled **Fan 2: 1. At temperature** and **Fan 2: 1. Run at**, for example. There are **40** numeric settings across the four fans. **Run at** is the commanded percentage; RPM sensors report measured rotation speed separately.

To run Fan 2 at **60% at 30 C**:

1. Select **Balanced** in **Fan 2 profile** to load its standard rules.
2. Set **Fan 2: 3. At temperature** to **30 C** and **Fan 2: 3. Run at** to **60%**.
3. The selector changes to **Custom** and applies the edited curve. Fans 1, 3, and 4 keep their own settings.

Read each pair as “at this temperature, run this fan at this percentage.” Between adjacent points the speed changes smoothly: 22 C / 30% and 28 C / 60% give 45% at 25 C. Below the first temperature, the first speed applies; above the last temperature, the last speed applies.

Keep the five temperatures increasing. Runtime sorting handles out-of-order points, and each fan has a **Curve Configuration Warning** diagnostic. Invalid sensor readings or non-finite curve values hold that fan's previous command until valid readings return.

Editing an automatic curve selects **Custom** and applies the change immediately. Editing rules in **Manual** leaves the current speed alone; select **Custom** when ready to use them. Selecting a preset later replaces that fan's edited rules.

## Saved state and variables

Each fan's selector is its only persisted mode setting. The selector and all ten curve values restore after reboot, without reapplying presets over edited values. Allow the configured flash write interval before removing power. Native fan state and physical override behavior remain defined by their respective hardware and button modules.

| Variable | Default | Meaning |
| --- | --- | --- |
| `temperature_sensor_id` | `fancontroller_temperature` | Sensor used by all four curves |
| `fanN_curve_temp1` through `fanN_curve_temp5` | 20, 25, 30, 40, 50 | Initial temperatures in C, for fan N = 1–4 |
| `fanN_curve_speed1` through `fanN_curve_speed5` | 0, 25, 50, 75, 100 | Initial speeds in percent |

These substitutions set initial values only; restored number settings take precedence. A named preset overwrites those settings when selected. Temperature controls accept 0–60 C in 0.5 C steps, and speed controls accept 0–100% in 1% steps.

```yaml
substitutions:
  fan2_curve_speed3: "60"
  # Optional external temperature sensor already declared elsewhere:
  # temperature_sensor_id: cabinet_temperature
```

## Automations

Replace these entity IDs with those from your controller. Selectors are `fan1_profile` through `fan4_profile` in ESPHome; Home Assistant derives entity IDs from their display names.

```yaml
automation:
  - alias: "Fan profiles - quiet nights"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: select.select_option
        target:
          entity_id:
            - select.fan_controller_fan_1_profile
            - select.fan_controller_fan_2_profile
        data:
          option: "Silent"
```

Selecting a profile enables temperature control immediately unless a physical override is active. For a fixed-percentage automation, select **Manual** before calling `fan.set_percentage`. For a fixed stop, select **Manual** before calling `fan.turn_off`.
