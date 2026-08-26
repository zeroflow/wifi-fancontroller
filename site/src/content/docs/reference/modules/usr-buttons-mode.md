---
title: USR Buttons with Auto/Manual Mode
description: Assign the three USR buttons to fan selection, speed stepping, and a per-fan auto/manual mode toggle
sidebar:
  order: 12
---

:::caution[Rev 3.1+ Only]
This module requires **Rev 3.1 or later** hardware (3.1, 3.2, or 3.3). Earlier revisions do not have per-fan RGB LEDs required by this module.
:::

:::caution[Mutually exclusive with USR Buttons]
This module is a superset of **USR Buttons** and defines the same component ids. Load one or the other, never both. A configuration that loads both fails to validate with a duplicate entity error.
:::

## Purpose

A temperature curve, or any of this project's temperature modules, keeps every fan under automatic control. Sometimes a person wants one fan to hold a speed and stay there: a hand-tuned value during commissioning, a quiet setting during a call, a fan a particular workload needs pinned. Without a mode, the curve overwrites a hand-set speed again within ten seconds, on its next update tick. This module makes that per-fan choice explicit, and reachable both from the board's own buttons and from Home Assistant.

## When to Use

Assign the buttons this way when you want a local override available at the board, and you also want an explicit auto or manual mode for each fan rather than an override that ages out on its own. It suits setup and commissioning, tuning noise levels by ear, or a fan that needs to hold a hand-set speed indefinitely. Manual overrides take priority over all temperature modules, so you can pin one fan at a specific speed while leaving the others under automatic control.

Regular operation of the controller runs over the network interface through Home Assistant. The buttons complement that; they are not meant to replace it as the day-to-day control surface.

:::caution[Keep 20 cm separation]
This product contains a radio transmitter and must be installed so that at least 20 cm separation is maintained between the antenna and any person during normal operation. Assigning the buttons does not change that. Reach the board for setup or an occasional override, then step away; do not plan an installation around standing at the board. See [Safety and Compliance](/reference/compliance/).
:::

A configuration already using [USR Buttons](/reference/modules/usr-buttons/) swaps the package path from `usr_buttons.yaml` to `usr_buttons_mode.yaml` and keeps every Home Assistant entity, because the switch ids and display names are identical between the two modules.

See the [modules overview](/reference/modules/) for a comparison of all available modules.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `friendly_name` | `"Fan Controller"` | Device name prefix for HA entities |
| `speed_step` | `"10"` | Speed change per button press, in percent at the hardware default of 100 speed levels. See [Speed steps](#speed-steps) |
| `override_timeout` | `"30s"` | Time after the last button press before selection mode auto-deactivates |
| `selection_color_r` | `"0"` | Red component (0 to 255) of the LED color shown for a fan under automatic control |
| `selection_color_g` | `"0"` | Green component (0 to 255) of the LED color shown for a fan under automatic control |
| `selection_color_b` | `"255"` | Blue component (0 to 255) of the LED color shown for a fan under automatic control |

A fan already in manual shows magenta instead, regardless of these three variables: the magenta is not configurable. See [Selection colours](#selection-colours) below.

The long-press threshold is not one of these variables. It is a fixed one second (1000 milliseconds) in the module's lambda, by design: `speed_step` and `override_timeout` are values a person reasonably wants to tune per installation, while the point at which a press becomes a hold is a gesture-recognition detail rather than a per-installation choice, and keeping it fixed avoids a variable nobody but the module itself needs.

## How It Works

The three USR buttons (labeled top to bottom on the board) each have a function:

- **USR1 (speed up):** Increases the selected fan's speed by `speed_step`%. If the fan is off, it turns on at `speed_step`%. If Stall Guard is active and has set a safety floor for that fan, the speed is clamped to at least that floor value.
- **USR3 (speed down):** Decreases the selected fan's speed by `speed_step`%. If the speed would drop to 0%, the fan turns off instead.
- **USR2 (select, then hold to toggle):** A short press cycles the fan selection forward, 1, 2, 3, 4, then back to 1. The short press is recognised on release rather than on press, because a press is only known to be short once the button comes back up; the difference is not perceptible, and nothing repeats while the button is held. The selected fan's LED shows that fan's current mode while it is selected. Holding USR2 down for about one second toggles the currently selected fan between automatic and manual. The toggle fires the instant the one-second threshold is crossed, while the button is still held, so the confirmation is immediate, and the release that follows does nothing further. The fan stays selected through the toggle, and the selection window restarts at that moment, so USR1 and USR3 immediately adjust that same fan's speed with no need to press USR2 again. With no fan selected, a long press does nothing while held, and the release that follows simply performs an ordinary selection press, choosing fan 1. In practice this means press to select, then hold to toggle: the first touch of USR2 in a session always selects a fan, and only a subsequent hold on an already-selected fan toggles its mode.

### Selection colours

Only the selected fan's LED is lit while a fan is selected: the other three go dark. That is unchanged.

Magenta means the selected fan is in manual. The selection colour, blue by default, means it is under automatic control. So one look at the board tells you both which fan you have selected and what mode it is in, before you decide whether to hold USR2.

Brightness still tracks the fan's commanded speed in either colour: a dim LED is a slow fan, a bright one a fast fan.

Magenta carries one meaning across both indicators: it is the same magenta the toggle confirmation flash uses for a fan going to manual. The flash uses white for a fan going to automatic rather than the selection blue, because the flash is a transient confirmation painted on all four LEDs while the selection colour is a steady state on one. The flash finishes by repainting the selection LED in the colour matching the mode the fan just landed in, magenta for manual or the selection colour for automatic, which is also why that final colour always agrees with what the selection LED already meant.

### LED confirmation

When the toggle fires, all four fan LEDs flash twice: magenta for a fan going to manual, white for a fan going to automatic, roughly 150 milliseconds on and 150 milliseconds off per flash, about 600 milliseconds total. Once the flash finishes, the LEDs return to the selection display, with the just-toggled fan lit alone in its new colour, magenta for manual or the selection colour for automatic, so the result of the toggle is visible as a steady state and not only as a blink. The toggle also restarts the selection window, so there is a fresh full `override_timeout` available from the moment of the toggle in which to set that fan's speed with USR1 or USR3, with no need to select it again. Live RPM returns to all four LEDs once the selection window finally expires, the same rule every other USR2 press already follows. The flash itself stays transient rather than persistent: pinning all four LEDs to a mode colour indefinitely was considered and rejected, because it would suppress RPM feedback for as long as someone stands at the board watching the fans, which is exactly when RPM feedback matters most. RPM feedback still comes back on its own, just later than before, once the selection window times out.

### What manual actually means

Manual mode sets that fan's manual override flag, the same flag the four Home Assistant Manual Override switches set, and the same flag every temperature module in this project checks before writing a fan's speed. Manual mode does not change the fan's speed. It only stops the temperature module from changing it: a fan that was cooling at 60% when it enters manual keeps cooling at 60% until a person or an automation sets a different value.

### Reboot behaviour

:::caution[Mode survives a reboot]
The mode survives a power cut. A board that loses power at three in the morning while a fan is in manual comes back with that fan still in manual, the temperature curve idle for it, and the fan running at whatever speed its `restore_mode: RESTORE_DEFAULT_ON` setting gives it. This is a deliberate choice: the alternative was to force every fan back to automatic on every boot, and that was rejected because it would silently throw away a deliberate hand setting the moment the board restarts. If you want a fan to come back under automatic control after a reboot, release it from manual first, or use Clear Fan Overrides once the board is back online.
:::

### Stall Guard interaction

The example on this page does not include Stall Guard, but the two work together when both are loaded. USR1 already respects the safety floor Stall Guard sets for a stalled fan, clamping a speed-up press to at least that floor, and a fan in manual mode still respects that same floor: leaving a fan in manual does not defeat stall recovery. See [Stall Guard](/reference/modules/stall-guard/).

## Home Assistant Entities

### Button (1)

| Entity | Description |
|--------|-------------|
| `${friendly_name} Clear Fan Overrides` | Resets all four manual override flags. Does **not** change fan speed: fans continue at their current speed, but temperature modules can now resume automatic control for all fans. |

### Switch Entities (4)

| Entity | Description |
|--------|-------------|
| Fan 1 Manual Override | Shows whether fan 1 is currently in manual. Turn off to release that fan back to automatic temperature control. |
| Fan 2 Manual Override | Same as above for fan 2. |
| Fan 3 Manual Override | Same as above for fan 3. |
| Fan 4 Manual Override | Same as above for fan 4. |

These four switches are the mode. There is no separate mode entity, by design: a global mode plus four per-fan flags could disagree with each other, and keeping the mode entirely inside these four switches makes that contradictory state impossible.

The override switches let you release individual fans from manual control without affecting the others, and you can turn one on from Home Assistant to lock a fan at its current speed without touching any physical button. These four switch ids and display names are byte-identical to the ones [USR Buttons](/reference/modules/usr-buttons/) defines, so a customer migrating from USR Buttons to this module keeps every entity id, every automation, and every dashboard card unchanged.

## One switch per fan, not two

A config loading a temperature module alongside this one gets two switches per fan: the temperature module's own "Auto Control Fan N" and this module's "Fan N Manual Override". They approach the same decision from opposite directions, and having both on a dashboard invites a fan sitting off the curve for a reason that is not obvious.

The fix is to hide the temperature module's switches in your own configuration:

```yaml
switch:
  - id: !extend auto_control_fan1
    internal: true
  - id: !extend auto_control_fan2
    internal: true
  - id: !extend auto_control_fan3
    internal: true
  - id: !extend auto_control_fan4
    internal: true
```

`internal: true` hides the entity from Home Assistant and from the API without removing it. The switch keeps its `RESTORE_DEFAULT_ON` state and the curve's own lambda keeps reading it, so automatic control keeps running and the Manual Override switch is the only remaining gate.

This belongs in the consuming config, not in this module, because `usr_buttons_mode` deliberately does not know which temperature module is loaded. `temperature_curve` names its switches `auto_control_fanN`, while `temperature_pid` names its own `pid_control_fanN`, so a module that hid another module's entity would have to hard-code that other module's ids. The shared `usr_override_fanN` flag is the module-neutral interface, which is why every temperature module in this project checks it.

Loading `temperature_pid` instead, extend `pid_control_fan1` through `pid_control_fan4` the same way.

`!extend` reaches these four because they are top-level ids in the temperature module's own `switch:` list, the same reason it reaches `temperature_sensor` in [Sensor offset](#sensor-offset) below.

[`examples/with-auto-manual-mode-rev-3.3.yaml`](https://github.com/zeroflow/wifi-fancontroller/blob/main/examples/with-auto-manual-mode-rev-3.3.yaml) ships with this block.

## Going fully manual, and building presets

Going fully manual is four switches, not one, because the mode is tracked per fan by design (see above). A single action that sets all four fans at once has to be built from those four switches plus the four fan speeds, so this section shows the working YAML rather than just describing it.

### A script to go fully manual

A script has a defined order, and the order matters here: turn the four override switches on first, then set the four fan speeds, so the temperature curve cannot get a write in between the two.

```yaml
script:
  fancontroller_manual_all:
    alias: "Fan Controller: Go Fully Manual"
    sequence:
      - service: switch.turn_on
        target:
          entity_id:
            - switch.my_fancontroller_fan_1_manual_override
            - switch.my_fancontroller_fan_2_manual_override
            - switch.my_fancontroller_fan_3_manual_override
            - switch.my_fancontroller_fan_4_manual_override
      - service: fan.set_percentage
        target:
          entity_id: fan.my_fancontroller_fan_1
        data:
          percentage: 60
      - service: fan.set_percentage
        target:
          entity_id: fan.my_fancontroller_fan_2
        data:
          percentage: 60
      - service: fan.set_percentage
        target:
          entity_id: fan.my_fancontroller_fan_3
        data:
          percentage: 40
      - service: fan.set_percentage
        target:
          entity_id: fan.my_fancontroller_fan_4
        data:
          percentage: 40
```

### A script to hand all four fans back to the curve

```yaml
script:
  fancontroller_release_all:
    alias: "Fan Controller: Release to Auto"
    sequence:
      - service: switch.turn_off
        target:
          entity_id:
            - switch.my_fancontroller_fan_1_manual_override
            - switch.my_fancontroller_fan_2_manual_override
            - switch.my_fancontroller_fan_3_manual_override
            - switch.my_fancontroller_fan_4_manual_override
```

Turning the switches off is the entire action: the temperature curve resumes writing that fan's speed on its next tick, so no fan speed needs to be set here.

### The scene form, and its ordering caveat

A scene is the shape most Home Assistant documentation reaches for, so it is worth showing too:

```yaml
scene:
  - name: "Fan Controller Quiet Preset"
    entities:
      switch.my_fancontroller_fan_1_manual_override: "on"
      switch.my_fancontroller_fan_2_manual_override: "on"
      switch.my_fancontroller_fan_3_manual_override: "on"
      switch.my_fancontroller_fan_4_manual_override: "on"
      fan.my_fancontroller_fan_1:
        state: "on"
        percentage: 60
      fan.my_fancontroller_fan_2:
        state: "on"
        percentage: 60
      fan.my_fancontroller_fan_3:
        state: "on"
        percentage: 40
      fan.my_fancontroller_fan_4:
        state: "on"
        percentage: 40
```

State the caveat honestly rather than leaving it out: a scene applies its entities without a guaranteed order, so there is a narrow window in which the temperature curve's ten-second tick could land between the switch and the speed, writing a value the scene did not intend. The script form above has a defined order and is not exposed to that window, which is why it is the form to reach for first. The scene form is shown because it is what most Home Assistant guides point you toward.

### Building more than one preset

The pattern for more than one preset is one script per preset, each turning the four override switches on first and then setting its own four speeds, exactly like the first script above. Give each script a name that identifies the preset, for example `fancontroller_manual_quiet` and `fancontroller_manual_loud`, and call whichever one matches the situation from an automation or a dashboard button.

Write your own entity ids in the `switch.my_fancontroller_...` and `fan.my_fancontroller_...` style used on this page, but confirm the exact ids for your own board in Home Assistant under **Developer Tools > States**, since they are derived from the device name you chose when you flashed it.

## Speed steps

:::caution[Leave the speed level count at its default]
The fan speed level count is a count of discrete LEVELS the fan entity accepts. It is not a percentage and it is not a slider widget setting.

The hardware packages set it to 100. At 100, one level is exactly one percent, which is the coincidence every module in this project is written against.

Lowering it silently redefines the unit for every module that speaks in percentages. A `speed_step` of `"5"` at a level count of 20 moves five levels, which is 25 percent per press, not 5. A temperature module that computes a percentage and then writes it as a level has its output multiplied by five and clamped, so a curve value of 20 or more commands full speed. This module's own selected-fan LED brightness is derived from the speed against a 100 scale too, so it saturates the same way.

Leave the level count at the hardware default. You already get one percent resolution on the Home Assistant slider and whatever `speed_step` you choose meaning exactly that many percent, at the same time. They were never in conflict.
:::

One combination that caution does not cover: a Home Assistant slider that snaps in 5 percent steps is the one thing this setup cannot give you today. The slider's own step size comes from the fan's speed level count, not from `speed_step`. A 5 percent snap needs `speed_count: 20`, which is exactly the value the caution above says to avoid, because it is the value that breaks every module's percentage math. `speed_step` only governs how far a button press moves the fan; it has no effect on the slider's granularity in the Home Assistant UI.

Lifting this would mean every module that calls `set_speed` reading the fan's actual level count at runtime, `get_traits().supported_speed_count()`, and converting a percentage to a level before writing it, rather than assuming the level count is 100. At the hardware default that conversion is a no-op, so nothing about an existing configuration would change. It touches all ten speed-setting modules and every example that loads one, which is why it has not been done yet. It is deferred, not overlooked: a known limitation, not a bug waiting to be found on a bench.

## Sensor offset

```yaml
sensor:
  - id: !extend temperature_sensor
    temperature:
      filters:
        - offset: -2.0
    humidity:
      filters:
        - offset: 3.0
```

The target here is `temperature_sensor`, the top-level id the HDC1080 platform uses in the hardware package. A nested id, `fancontroller_temperature` or `fancontroller_humidity`, two levels further down, is not a top-level entry, and `!extend` cannot reach it.

The two values shown, `-2.0` and `3.0`, are placeholders, not a calibration to copy. The onboard sensor reads warm from the board's own self heating, typically by one to three kelvin, and how much depends on your enclosure and load. Measure your own board against a reference instrument rather than reusing these two numbers.

## Web UI grouping

This block goes in **your own configuration**, not in the module. See [why the assignment lives in the consuming config](/reference/standalone/#grouping-module-entities-in-the-web-ui) for the reason. `version: 3` is what makes entity grouping work at all; without it, entity grouping has no effect.

```yaml
web_server:
  version: 3
  sorting_groups:
    - id: grp_usr_buttons_mode
      name: "USR Buttons with Auto/Manual Mode"
      sorting_weight: 410

button:
  - id: !extend usr_clear_overrides
    web_server:
      sorting_group_id: grp_usr_buttons_mode
      sorting_weight: 10

switch:
  - id: !extend usr_override_sw_fan1
    web_server:
      sorting_group_id: grp_usr_buttons_mode
      sorting_weight: 20
  - id: !extend usr_override_sw_fan2
    web_server:
      sorting_group_id: grp_usr_buttons_mode
      sorting_weight: 30
  - id: !extend usr_override_sw_fan3
    web_server:
      sorting_group_id: grp_usr_buttons_mode
      sorting_weight: 40
  - id: !extend usr_override_sw_fan4
    web_server:
      sorting_group_id: grp_usr_buttons_mode
      sorting_weight: 50
```

None of this module's 5 entities are diagnostic, so all of them fall in the 10-50 range.

## YAML Examples

### Basic Usage

```yaml
packages:
  hardware:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [hardware-rev-3.1.yaml]
  usr_buttons_mode:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/usr_buttons_mode.yaml
        vars:
          friendly_name: "My Fan Controller"
```

### Combined with a Temperature Curve and RPM Status LEDs

```yaml
packages:
  hardware:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [hardware-rev-3.3.yaml]
  temperature_curve:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_curve.yaml
        vars:
          friendly_name: "My Fan Controller"
  usr_buttons_mode:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/usr_buttons_mode.yaml
        vars:
          friendly_name: "My Fan Controller"
          speed_step: "5"
          override_timeout: "30s"
  rpm_status_leds:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/rpm_status_leds.yaml
        vars:
          full_rpm: "2500"
```

### The complete example

This is the shape [`examples/with-auto-manual-mode-rev-3.3.yaml`](https://github.com/zeroflow/wifi-fancontroller/blob/main/examples/with-auto-manual-mode-rev-3.3.yaml) uses. That file also adds the sensor offset `!extend` override described above, and is a complete, compiling starting point you can flash directly.

## Tips

1. **Leave the speed level count at its default.** It is a count of discrete levels the fan accepts, not a percentage, and lowering it rescales `speed_step` along with every other percentage this project computes. See [Speed steps](#speed-steps).
2. **Use the Clear Fan Overrides button when a fan stops responding to temperature.** A forgotten manual override, left on from an earlier test or press, is the most common reason a fan appears stuck at one speed.
3. **Remember that the mode survives a reboot.** A fan you left in manual is still in manual after a power cycle. See Reboot behaviour above.
4. **Do not load both button modules.** `usr_buttons` and `usr_buttons_mode` define the same component ids; load one or the other, never both.
5. **Increase `override_timeout` for slow adjustments.** If selection mode times out before you finish tuning, set `override_timeout: "60s"` or higher.
6. **Combine with Stall Guard.** When Stall Guard sets a safety floor during recovery, both USR1 and manual mode respect it. You cannot accidentally hold a stalled fan below its recovery floor.
7. **Read the selection colour before holding USR2.** Magenta means the fan is already in manual, so a hold sends it back to automatic. Blue means it is on the curve.
8. **Toggle then adjust in one motion.** Hold USR2 to flip a fan's mode, then press USR1 or USR3 right away to set its speed. The fan stays selected through the toggle, so there is no need to press USR2 again.
