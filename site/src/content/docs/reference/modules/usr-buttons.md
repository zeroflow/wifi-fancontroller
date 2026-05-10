---
title: USR Buttons
description: Physical button control for fan speed with per-fan RGB LED feedback
---

:::caution[Rev 3.1+ Only]
This module requires **Rev 3.1 or later** hardware (3.1, 3.2, or 3.3). Earlier revisions do not have per-fan RGB LEDs required by this module.
:::

## Purpose

The USR Buttons module gives you direct physical control over fan speeds using the three USR buttons on the board. Press a button to select a fan, then step its speed up or down without touching Home Assistant. The selected fan's LED lights up in a configurable color so you always know which fan you're adjusting.

## When to Use

Use this module when you want hands-on control of individual fan speeds - useful during initial setup, when tuning noise levels by ear, or in any situation where reaching for a phone or computer is inconvenient. Manual overrides take priority over all temperature modules, so you can temporarily lock a fan at a specific speed while leaving the others under automatic control.

If you also use RPM Status LEDs, the two modules coordinate automatically: entering button selection mode temporarily takes over the LEDs, then returns control to RPM Status LEDs when the timeout expires.

See the [modules overview](/reference/modules/) for a comparison of all available modules.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `friendly_name` | `"Fan Controller"` | Device name prefix for HA entities |
| `speed_step` | `"10"` | Percentage to increase or decrease fan speed per button press |
| `override_timeout` | `"30s"` | Time after the last button press before selection mode auto-deactivates |
| `selection_color_r` | `"0"` | Red component (0–255) of the selection indicator LED color |
| `selection_color_g` | `"0"` | Green component (0–255) of the selection indicator LED color |
| `selection_color_b` | `"255"` | Blue component (0–255) of the selection indicator LED color |

## How It Works

The three USR buttons (labeled top to bottom on the board) each have a fixed function:

- **USR1 (speed up)** -- Increases the selected fan's speed by `speed_step`%. If the fan is off, it turns on at `speed_step`%. If Stall Guard is active and has set a safety floor for that fan, the speed is clamped to at least that floor value.
- **USR2 (select)** -- Cycles through fans in order (1 → 2 → 3 → 4 → 1). The first press enters selection mode; subsequent presses advance to the next fan. The selected fan's LED lights up in the configured selection color; all other fan LEDs turn off.
- **USR3 (speed down)** -- Decreases the selected fan's speed by `speed_step`%. If the speed would drop to 0%, the fan turns off instead.

**Override persistence:** A manual override sticks until you clear it -- either via the **Clear Fan Overrides** button in Home Assistant, or by toggling the individual **Fan X Manual Override** switch for that fan. Temperature modules skip automatic control for any fan with an active override, so a manually set speed holds indefinitely regardless of temperature.

**Selection mode timeout:** If no button is pressed for `override_timeout`, selection mode deactivates automatically. Fan overrides already set remain in effect -- only the visual selection mode ends.

**LED coordination:** When selection mode is active, this module sets the `auto_led_override` global to pause RPM Status LEDs updates and takes direct control of the fan LEDs. When selection mode times out or is cleared, the global is released and RPM Status LEDs resumes its normal updates.

**Temperature module coordination:** When a fan has an active override, the `usr_override_fanN` global for that fan is set. All temperature modules check this global on every update cycle and skip writing a new speed to any fan that has it set.

## Home Assistant Entities

### Button (1)

| Entity | Description |
|--------|-------------|
| `${friendly_name} Clear Fan Overrides` | Resets all four manual override flags. Does **not** change fan speed -- fans continue at their current speed, but temperature modules can now resume automatic control for all fans. |

### Switch Entities (4)

| Entity | Description |
|--------|-------------|
| Fan 1 Manual Override | Shows whether fan 1 has an active manual speed override. Turn off to release that fan back to automatic temperature control. |
| Fan 2 Manual Override | Same as above for fan 2. |
| Fan 3 Manual Override | Same as above for fan 3. |
| Fan 4 Manual Override | Same as above for fan 4. |

The override switches let you release individual fans from manual control without affecting the others. You can also turn them on from Home Assistant to lock a fan at its current speed without pressing any physical buttons.

## YAML Examples

### Basic Usage

```yaml
packages:
  hardware:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [hardware-rev-3.1.yaml]
  usr_buttons:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/usr_buttons.yaml
        vars:
          friendly_name: "My Fan Controller"
```

### Combined with RPM Status LEDs

The USR Buttons and RPM Status LEDs modules coordinate automatically. Include both to get visual speed feedback at all times, with button selection mode temporarily taking over the LEDs while you make adjustments:

```yaml
packages:
  hardware:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [hardware-rev-3.1.yaml]
  rpm_status_leds:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/rpm_status_leds.yaml
        vars:
          full_rpm: "2500"
  usr_buttons:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/usr_buttons.yaml
        vars:
          friendly_name: "My Fan Controller"
          speed_step: "10"
          override_timeout: "30s"
```

During normal operation the LEDs show fan speed as a red-to-green gradient. Press USR2 to enter selection mode -- the selected fan LED switches to blue and the others go dark. After `override_timeout` with no button activity, the LEDs return to their normal gradient display.

### Custom Selection Color

Change the selection indicator to amber (useful if you find blue hard to distinguish from the RPM gradient):

```yaml
packages:
  usr_buttons:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/usr_buttons.yaml
        vars:
          friendly_name: "My Fan Controller"
          selection_color_r: "255"
          selection_color_g: "100"
          selection_color_b: "0"
```

## Tips

1. **Set `speed_step` to match your use case** -- `"10"` (10% per press) gives 10 steps across the full speed range. For coarser control, try `"25"`; for finer tuning, `"5"`.
2. **Increase `override_timeout` for slow adjustments** -- if you find selection mode timing out before you finish tuning, set `override_timeout: "60s"` or higher.
3. **Use the Clear Fan Overrides button in HA after manual tuning** -- once you've found a good speed through physical buttons, you can either leave the override in place permanently or clear it and let the temperature module take over using your tuning as a reference.
4. **Check the override switches in HA** -- if temperature control stops responding for a fan, check that its Manual Override switch is off. A switch left on after manual tuning is the most common reason a fan stops following the temperature curve.
5. **Combine with Stall Guard** -- when Stall Guard sets a safety floor during recovery, USR1 (speed up) respects it. You cannot accidentally set a stalled fan below its recovery floor using the physical buttons.
6. **Release individual fans selectively** -- you don't have to clear all overrides at once. Toggle individual Manual Override switches in Home Assistant to release only the fans you want back under automatic control.
