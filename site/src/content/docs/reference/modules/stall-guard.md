---
title: Stall Guard
description: Fan stall detection and automatic recovery module
---

:::note[All Revisions]
Works with all hardware revisions (Rev 1.0 through Rev 3.3).
:::

## Purpose

The Stall Guard module detects when a fan is commanded to run but reports 0 RPM -- a stall condition caused by mechanical blockage, bearing failure, or insufficient starting voltage. When a stall is detected, the module progressively raises the fan's PWM output to attempt recovery and flags a persistent warning in Home Assistant so you know something went wrong.

## When to Use

Use Stall Guard when fan reliability matters -- server cooling, network closets, or any unattended installation where a stuck fan could cause overheating. The module is passive until a problem occurs: it monitors RPM in the background and only intervenes when a fan stops spinning unexpectedly.

:::caution
Do **not** use Stall Guard together with [RPM PI Control](/reference/modules/rpm-pi-control/). RPM PI Control writes directly to PWM outputs, bypassing the fan entity that Stall Guard uses. If you need closed-loop RPM control, RPM PI Control already handles stall-like scenarios through its feedback loop.
:::

See the [modules overview](/reference/modules/) for a comparison of all available modules.

## Safety Floor

Stall Guard cooperates with all temperature control modules ([Temperature PID](/reference/modules/temperature-pid/), [Temperature Linear](/reference/modules/temperature-linear/), [Temperature Curve](/reference/modules/temperature-curve/)) through a **safety floor** mechanism.

When Stall Guard detects a stall and starts recovery, it sets a per-fan safety floor -- a minimum speed that temperature modules will not go below. This prevents the temperature module from fighting the stall recovery by lowering the fan speed back down.

**How the safety floor works:**

1. Fan stalls → Stall Guard raises the fan speed and sets the safety floor to the new value
2. Temperature module runs its normal calculation (e.g., 30%)
3. Temperature module sees the safety floor (e.g., 45%) and uses the higher value
4. Result: fan runs at 45%, the stall recovery value

**When the fan is turned OFF** (either manually or because temperature dropped below the off threshold), the safety floor is ignored -- off always means off. On the next check, Stall Guard automatically clears the stall state and resets the floor for that fan. No manual clear needed.

You can also press **Clear Stall Warnings** at any time to manually reset all stall states and floors.

:::tip
The safety floor is defined in the hardware package, not in any module. This means it works automatically when you include both Stall Guard and a temperature module -- no extra configuration needed.
:::

## Configuration

The module accepts these substitution variables in the `packages:` block:

| Variable | Default | Description |
|----------|---------|-------------|
| `friendly_name` | `"Fancontroller"` | Device name prefix for all HA entities |
| `stall_guard_interval` | `"5s"` | How often to check each fan's RPM |
| `stall_guard_grace_ticks` | `"2"` | Initial value for Grace Ticks (adjustable at runtime via HA) |
| `stall_guard_step_pct` | `"1"` | Initial value for Step % (adjustable at runtime via HA) |
| `stall_guard_min_rpm` | `"1"` | Initial value for Min RPM (adjustable at runtime via HA) |

The `stall_guard_grace_ticks`, `stall_guard_step_pct`, and `stall_guard_min_rpm` substitutions set the **initial values** for the corresponding Home Assistant number entities. Once the device boots, users can adjust these values at runtime through the Home Assistant UI, and changes persist across reboots.

## Runtime Configuration

These parameters can be adjusted at runtime through Home Assistant without reflashing:

### Number Entities (3)

| Entity | Default | Range | Description |
|--------|---------|-------|-------------|
| Stall Guard Min RPM | 1 | 0–1000 | RPM threshold below which a fan is considered stalled. Default of 1 detects complete standstill. Set higher (e.g., 200) to catch fans spinning too slowly to move air |
| Stall Guard Step % | 1 | 1–20 | Percentage to raise fan speed each tick during recovery |
| Stall Guard Grace Ticks | 2 | 1–20 | Consecutive low-RPM checks before declaring a stall (effective grace period = interval × ticks) |

### Switch Entities (4)

| Entity | Default | Description |
|--------|---------|-------------|
| Fan 1 Stall Guard | ON | Enable/disable stall detection for fan 1 |
| Fan 2 Stall Guard | ON | Enable/disable stall detection for fan 2 |
| Fan 3 Stall Guard | ON | Enable/disable stall detection for fan 3 |
| Fan 4 Stall Guard | ON | Enable/disable stall detection for fan 4 |

All runtime settings use `restore_value` / `restore_mode`, so changes made in the Home Assistant UI persist across reboots.

:::tip
Disable stall guard for fan ports with nothing connected to avoid false stall warnings. With runtime switches, you can do this directly from the Home Assistant UI instead of reflashing.
:::

## Home Assistant Entities

### Binary Sensors (4)

One per fan. Shows `ON` (problem detected) when a stall is active, `OFF` when clear.

| Entity | Device Class | Description |
|--------|-------------|-------------|
| Fan 1 Stall | `problem` | Stall detected on fan 1 |
| Fan 2 Stall | `problem` | Stall detected on fan 2 |
| Fan 3 Stall | `problem` | Stall detected on fan 3 |
| Fan 4 Stall | `problem` | Stall detected on fan 4 |

These are ideal triggers for Home Assistant automations -- send a notification when any stall sensor turns on.

### Text Sensors (4)

One per fan. Shows `"OK"` when clear, or a message like `"Fancontroller Fan 1 stall - raised to 45%"` during active stall recovery.

| Entity | Description |
|--------|-------------|
| Fan 1 Stall Message | Human-readable stall status for fan 1 |
| Fan 2 Stall Message | Human-readable stall status for fan 2 |
| Fan 3 Stall Message | Human-readable stall status for fan 3 |
| Fan 4 Stall Message | Human-readable stall status for fan 4 |

### Button (1)

| Entity | Description |
|--------|-------------|
| Clear Stall Warnings | Resets all stall flags, messages, and safety floors to OK. Does **not** change fan speed -- the fan continues at whatever speed recovery raised it to, but temperature modules can now lower it freely. |

### Number Entities (3)

| Entity | Range | Description |
|--------|-------|-------------|
| Stall Guard Min RPM | 0–1000 RPM | RPM threshold for stall detection |
| Stall Guard Step % | 1–20% | Speed increase per recovery tick |
| Stall Guard Grace Ticks | 1–20 | Low-RPM checks before declaring stall |

### Switch Entities (4)

| Entity | Description |
|--------|-------------|
| Fan 1–4 Stall Guard | Enable/disable stall detection per fan |

## How It Works

1. Every `stall_guard_interval`, the module checks each enabled fan
2. If a fan is commanded ON but reports RPM below `stall_guard_min_rpm`, a grace counter starts
3. After `stall_guard_grace_ticks` consecutive low-RPM readings, the module declares a stall and immediately begins recovery
4. On that tick and every tick thereafter, it raises the fan speed by `stall_guard_step_pct` percent (capped at 100%) and sets the safety floor to that value
5. The stall warning **persists even if the fan recovers** -- this is intentional so you investigate the cause
6. If the fan is turned **OFF**, the stall state and safety floor **auto-clear** for that fan
7. Press **Clear Stall Warnings** in Home Assistant to manually reset all fans

## YAML Examples

### Basic Usage

Monitor all 4 fans with default settings (10-second grace period, 1% step-up per tick):

```yaml
packages:
  stall_guard:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/stall_guard.yaml
        vars:
          friendly_name: "My Fan Controller"
```

### Two-Fan Setup with Faster Recovery

Only fans 1 and 2 connected, more aggressive recovery:

```yaml
packages:
  stall_guard:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/stall_guard.yaml
        vars:
          friendly_name: "Server Rack"
```

After flashing, disable Fan 3 and Fan 4 stall guard switches and set Step % to 2 in the Home Assistant UI.

### Combined with Temperature Linear

Stall Guard works cooperatively with any temperature module (except RPM PI Control). The temperature module controls fan speed based on temperature, while Stall Guard monitors for stalls and sets a safety floor during recovery. No extra configuration needed -- include both and they coordinate automatically:

```yaml
packages:
  hardware:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files: [hardware-rev-3.1.yaml]
  temperature:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/temperature_linear.yaml
        vars:
          friendly_name: "NAS Cooling"
  stall_guard:
    url: https://github.com/zeroflow/wifi-fancontroller
    ref: main
    files:
      - path: modules/stall_guard.yaml
        vars:
          friendly_name: "NAS Cooling"
```

After flashing, set Step % to 2 in the Home Assistant UI for more aggressive recovery.

During normal operation, Temperature Linear has full control. If a fan stalls, Stall Guard raises the safety floor so Temperature Linear won't reduce speed below the recovery value. When the temperature drops enough to turn fans off, the safety floor auto-clears.

## Tips

1. **Disable unused fans** -- disable the Fan X Stall Guard switch in Home Assistant for fan ports with nothing connected, otherwise you'll get false stall warnings
2. **Tune the grace period** -- the effective grace period is `interval × ticks`. The default of 5s × 2 = 10 seconds prevents false triggers during normal speed changes. Increase for fans that spin down slowly
3. **Watch the text sensors** -- the stall message shows the current recovery speed percentage, which tells you how far the module had to raise the fan to attempt recovery
4. **Create HA automations** -- use the binary sensors as triggers for notifications (e.g., send a push notification when `Fan 1 Stall` turns on)
5. **Clear warnings after investigating** -- the warnings are intentionally persistent. After you've checked the fan, press Clear Stall Warnings to reset
6. **Adjust step size for your fans** -- adjust the Stall Guard Step % number entity in Home Assistant to 2 or higher for fans that need a bigger kick to start spinning
7. **Set a minimum RPM for airflow** -- some fans spin at very low RPM (100-150) without actually moving air. Set the Stall Guard Min RPM entity to 200 in Home Assistant to treat these as stalled and trigger recovery to a useful speed
