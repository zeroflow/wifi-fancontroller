---
title: Fallback Mode
description: Home Assistant link supervision with a PWM floor
sidebar:
  order: 11
---

:::note[All Revisions]
Works with all hardware revisions (Rev 1.0 through Rev 3.3).
:::

## Scope and limits

This module is an availability feature, not a protective function. It reduces the likelihood that fans remain stuck at a stale value after the Home Assistant control loop dies. It does not ensure that cooling occurs.

It has not been developed as a safety function. There is no FMEA, no FMEDA, no fault tree, no hazard analysis, no defined safety goal or fault tolerant time interval, no diagnostic coverage figure, no independence or diversity argument, and no claim against ISO 26262, IEC 61508 or IEC 60730. In IEC 60730 terms this is a control function, not a Type 2 protective action, the established category for thermostats and fan controllers.

Failure modes explicitly not covered:

- **Fan failure.** Engaging the fallback writes a PWM value. It does not verify that any fan responds. A dead, stalled or unplugged fan produces the same PWM output and no error. See [The fan failure question](#the-fan-failure-question) below.
- **Output stage failure.** A stuck or shorted PWM output is not detected.
- **Board hang.** If the firmware wedges in a state that stops the supervision interval, the PWM output holds its last value indefinitely. There is no independent hardware watchdog on the actuation path.
- **Loss of supply.** Single 12 V input, no redundancy. No power, no fans, no fallback.
- **Common cause failure.** The pet, the setpoint and the diagnostics all travel the same WiFi link and the same API connection. A single fault removes supervision and control simultaneously.
- **A single implementation of the fallback path.** One implementation, one MCU, one task, no diversity.
- **Thermal adequacy of an open loop guess.** `fallback_pwm` is an open loop guess. Nothing verifies it is sufficient for the actual thermal load.
- **Sensor plausibility.** The Home Assistant side freshness check verifies age, not correctness. A sensor stuck at a plausible wrong value passes.
- **Detection latency.** Roughly 80 seconds from the last pet to fallback with the shipped preset, plus the thermal time constant of the cooled device. No fault tolerant time interval is defined or verified.

For the originating use case (external fans supporting a hybrid inverter), the actual protective function is the cooled device's own thermal management: its internal fans, its derating and its shutdown behavior. This module makes that device quieter and its temperature more stable. It does not protect it. An installation that depends on external fans to avoid damage is undersized, and this board is the wrong answer to that problem.

Nothing on this page is a safety case.

## The problem

Users drive the fan controller from Home Assistant: HA computes the PWM value from an external temperature source (for example a hybrid inverter's internal temperature via Modbus) and writes it to the board. If that control loop dies, the board keeps the last value forever.

Three failure modes, all covered by this module together with its blueprint:

1. HA is down, or the network is down. API disconnects.
2. HA is up, the board's entity is `unavailable`.
3. HA is up and the API is connected, but the upstream data source is dead (Modbus integration lost the device, template broke, automation disabled). The board sees a healthy API and a stale setpoint.

Case 3 is the dominant one in practice, and it is invisible to any connection status check. That is the reason a source freshness condition is a required input on the blueprint, not an optional extra.

## The single validated preset

Ship only this preset. Free reparameterization is not documented here; mis-sizing is the most likely route to fans spuriously sitting at 80 percent, and that statement is deliberate, not a hedge.

| Variable | Value |
|-|-|
| `sup_cycle` | `5s` |
| `sup_alive_init` | `20` |
| `sup_thr_margin` | `12` |
| `sup_thr_fallback` | `4` |
| `sup_release` | `12` |
| `fallback_pwm` | `80` |

Sized for a 30 second pet interval:

- Steady state margin: 14, above the margin threshold, no false positives.
- One pet missed: margin drops to 8, a Margin Low state, no action taken.
- Two pets missed: margin drops to 2, fallback engages roughly 80 seconds after the last pet.

## The `api: reboot_timeout: 0s` requirement

:::caution[Required firmware setting]
The consuming firmware config must set `api: reboot_timeout: 0s`. ESPHome's default is 15 minutes: with no client connected, the board reboots, which kills the fallback exactly when it is needed. `wifi: reboot_timeout` stays at its default on purpose, so a wedged WiFi stack is still caught.
:::

## Home Assistant entities

| Entity | Type | Category | Notes |
|-|-|-|-|
| Supervision Pet | `button` | diagnostic | Pressed by the paired blueprint automation. |
| Reset Supervision Latches | `button` | diagnostic | Clears both latches, both counters, and the Supervision Margin Min low water mark. Does not touch the live counter or an active fallback. |
| Fallback Active | `binary_sensor` | none | `device_class: problem`. The only non diagnostic entity. The natural automation trigger. |
| Fallback Triggered | `binary_sensor` | diagnostic | Latched: it engaged since boot. |
| Margin Low | `binary_sensor` | diagnostic | Latched. Not `device_class: problem`, a hint rather than a problem. |
| Supervision State | `text_sensor` | diagnostic | `OK`, `MARGIN_LOW` or `FALLBACK`. |
| Supervision Margin | `sensor` | diagnostic | Live alive counter, in supervision cycles. `state_class: measurement`. |
| Supervision Margin Min | `sensor` | diagnostic | Low water mark since boot or last latch reset, in supervision cycles. `state_class: measurement`. See below. |
| Margin Low Events | `sensor` | diagnostic | Count of episodes that reached Margin Low without escalating. `state_class: total_increasing`. |
| Fallback Events | `sensor` | diagnostic | Count of episodes that reached Fallback. `state_class: total_increasing`. |

## Graphing the diagnostics

All four numeric diagnostics carry a `unit_of_measurement` and a `state_class`, so Home Assistant treats them as numeric and draws them as line charts.

This matters because Home Assistant sorts an entity into its line chart set only when it has a unit or a state class. An entity with neither falls through to the timeline strip, which renders each value as a discrete state label. That is why an earlier version of this module showed the margin as a text state such as `12.0`.

The two margin sensors, Supervision Margin and Supervision Margin Min, use `state_class: measurement` in `cycles`, the class for a level that rises and falls. Home Assistant records min, mean and max statistics for them.

The two event counters, Margin Low Events and Fallback Events, use `state_class: total_increasing` in `events`, the class for a counter that only climbs and occasionally returns to zero. Both a reboot and a Reset Supervision Latches press send the counter back to 0, and Home Assistant reads that drop as a meter reset rather than as a negative jump, so the accumulated total survives in long term statistics.

Supervision State stays a `text_sensor`. Its three values, `OK`, `MARGIN_LOW` and `FALLBACK`, are categorical, and the timeline strip is the right rendering for them.

## Reading Supervision Margin Min

Supervision Margin Min is the most useful number in the set. Against the shipped thresholds of 12 and 4:

- A minimum of 11 is noise.
- A minimum of 5 means the pet interval is running on almost no margin, and should be halved before it bites.

Read the event counters the same way: a board with 40 fallback or margin low events in a week has a WiFi problem, not a Home Assistant problem. With `total_increasing` set, Home Assistant's own statistics answer that question directly: put either counter on a Statistics graph card and read the weekly sum.

## The boot episode

`sup_alive` starts at 0, so a cold boot with no Home Assistant present runs the fans at the fallback value rather than not at all. The first pet after that boot counts one fallback episode, because the fallback did engage. That is truthful, not a bug. Do not file a board that just came back from a power cut as broken because it logged one fallback event.

## Non-latching actuation, latching diagnostics

The floor releases automatically on the first valid pet after an engagement. Holding it would leave the fans loud after a 3 a.m. WiFi blip until a human notices, which is not acceptable for a device in a living space. The latches and the two event counters persist until reboot or until Reset Supervision Latches is pressed.

## Module interactions

- **Arbitration is not instantaneous.** A later writer, Home Assistant, a temperature module, can still command a speed below the floor after the fallback engaged. The supervision interval re-asserts the floor on the next cycle, so worst case exposure to a below-floor speed is one `sup_cycle`, 5 seconds with the shipped preset. This is a bounded latency, not an instant override.
- **Not supported together with [RPM PI Control](/reference/modules/rpm-pi-control/).** RPM PI Control writes the `pwm_fanN` outputs directly, bypassing the fan entity this module writes through, so a fan entity floor cannot reach it. This mirrors the existing Stall Guard and RPM PI Control incompatibility.
- **With [Stall Guard](/reference/modules/stall-guard/) also loaded**, both features raise floors and neither lowers one, so the effective floor is simply the higher of the two. They use separate globals: this module owns `fallback_floor`, Stall Guard owns the `fanN_safety_floor` set, so Stall Guard's Clear Stall Warnings button cannot wipe an active fallback floor.

## The fan failure question

Users will ask why the fallback ignores the RPM data the board already has. The documented answer:

> Fan failure would be detected, not compensated, and detection belongs in a separate module because it watches a different error domain: this module supervises the control source (network, Home Assistant), a fan monitor would supervise the actuator. Neither can substitute for the other. Compensating for a dead fan requires redundancy, not software.

A minimum PWM clamp, this module's floor included, is prevention, not detection: it stops the commanded speed from falling below a fan's start threshold, but a dead, blocked or unplugged fan is invisible to it at any PWM value. "Covered by Stall Guard" is the wrong answer to the fan failure question for the same reason.

A planned follow-up module, `fan_health`, would add reporting on a calibrated PWM to RPM curve, without promising a date and without writing to any output.

## Test matrix

The following are the checks a user or a hardware session runs against a real board and a real Home Assistant instance. They are not results. None of them has been run or claimed to pass in this documentation.

1. Steady state over 24 hours: no events, Supervision Margin Min equals the steady state value for the configured preset.
2. One pet dropped: Margin Low latched, count 1, floor never engages, PWM untouched.
3. Home Assistant stopped: fallback engages roughly 80 seconds after the last pet, floor at `fallback_pwm`.
4. Home Assistant resumes: floor releases on the first pet, output returns to the controller's value, the fallback latch stays set.
5. Source sensor `unavailable`, Home Assistant and the API both healthy: pet stops via the blueprint condition, fallback engages. If this case fails, the module does not do its job.
6. Cold boot, no Home Assistant present: fans reach `fallback_pwm` within one supervision cycle.
7. No API client for more than 15 minutes: the board does not reboot, verifying the `reboot_timeout: 0s` requirement.
8. Controller commands 90 percent while fallback is active: output stays at 90 percent, not 80 percent.
9. Controller commands 30 percent while fallback is active: output is 80 percent.
10. Latch reset button: clears the latches, the counters and Supervision Margin Min, and does not disturb the live counter or an active fallback.

## Web UI grouping

This block goes in your own configuration, not in the module. See [why the assignment lives in the consuming config](/reference/standalone/#grouping-module-entities-in-the-web-ui) for the reason.

```yaml
web_server:
  version: 3
  sorting_groups:
    - id: grp_fallback_mode
      name: "Fallback Mode"
      sorting_weight: 210

binary_sensor:
  - id: !extend fallback_active_sensor
    web_server:
      sorting_group_id: grp_fallback_mode
      sorting_weight: 10
  - id: !extend fallback_triggered_sensor
    web_server:
      sorting_group_id: grp_fallback_mode
      sorting_weight: 900
  - id: !extend fallback_margin_low_sensor
    web_server:
      sorting_group_id: grp_fallback_mode
      sorting_weight: 910

text_sensor:
  - id: !extend fallback_state_text
    web_server:
      sorting_group_id: grp_fallback_mode
      sorting_weight: 920

sensor:
  - id: !extend fallback_margin
    web_server:
      sorting_group_id: grp_fallback_mode
      sorting_weight: 930
  - id: !extend fallback_margin_min
    web_server:
      sorting_group_id: grp_fallback_mode
      sorting_weight: 940
  - id: !extend fallback_margin_events
    web_server:
      sorting_group_id: grp_fallback_mode
      sorting_weight: 950
  - id: !extend fallback_events
    web_server:
      sorting_group_id: grp_fallback_mode
      sorting_weight: 960

button:
  - id: !extend fallback_pet_button
    web_server:
      sorting_group_id: grp_fallback_mode
      sorting_weight: 970
  - id: !extend fallback_reset_button
    web_server:
      sorting_group_id: grp_fallback_mode
      sorting_weight: 980
```

Fallback Active is the only non diagnostic entity and takes weight 10. Every other entity in the module is diagnostic and takes weights 900 upward.

## YAML usage

```yaml
packages:
  fallback_mode:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/fallback_mode.yaml
        vars:
          friendly_name: "My Fan Controller"
          sup_cycle: "5s"
          sup_alive_init: "20"
          sup_thr_margin: "12"
          sup_thr_fallback: "4"
          sup_release: "12"
          fallback_pwm: "80"
```

See [`examples/with-fallback-mode-rev-3.3.yaml`](https://github.com/zeroflow/wifi-fancontroller/blob/main/examples/with-fallback-mode-rev-3.3.yaml) for a complete, compiling starting point, and [`blueprints/automation/zeroflow_fancontroller/fancontroller_supervision_pet.yaml`](https://github.com/zeroflow/wifi-fancontroller/blob/main/blueprints/automation/zeroflow_fancontroller/fancontroller_supervision_pet.yaml) for the Home Assistant side.
