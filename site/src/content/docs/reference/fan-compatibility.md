---
title: Fan Compatibility
description: Community-reported fan behavior at low PWM duty cycles, including which fans spin down to 0 RPM
---

## Connector Compatibility

The controller uses standard 4-pin PWM fan headers. Fan type determines what is possible before any speed control is considered:

| Fan type | Speed control | RPM sensing |
|----------|--------------|-------------|
| 4-pin PWM | Full range | Yes (tachometer wire) |
| 3-pin DC (with tach) | None (runs at full speed) | Yes |
| 3-pin DC (no tach) | None (runs at full speed) | No |
| 2-pin | None (runs at full speed) | No |

3-pin fans are physically compatible with 4-pin headers (the PWM pin simply has no contact), but the controller cannot slow them down. All speed control, temperature curves, and RPM-PI modules require a 4-pin PWM fan.

## PWM Spin-Down Behavior

The Intel 4-Wire PWM Fan Specification (Chapter 3.3) defines fan behavior at 100% duty cycle, but leaves behavior below approximately 20% duty cycle undefined. Individual fan manufacturers implement this range differently: some fans have a hard minimum PWM threshold below which they stop responding and continue spinning at their minimum speed, while others can spin all the way down to 0 RPM at sufficiently low PWM values. Some fans in the latter group also exhibit hysteresis - they spin down to 0 RPM but will not restart until PWM rises above a higher threshold than the one that stopped them.

This matters for any control module that sweeps the full 0-100% output range. If a fan cannot spin down to 0 RPM, it will continue running at its minimum speed even when the controller output is 0%.

## Community-Reported Fans

This table reflects user-reported observations. PWM behavior can vary between firmware revisions of the same fan model.

| Fan | RPM Range (per spec) | Spins down to 0 RPM |
|-----|----------------------|---------------------|
| [Arctic P12 Max](https://www.arctic.de/en/P12-Max/ACFAN00280A) | 400-3300 RPM | Yes (user reported) |
| [Noctua NF-A14 Industrial PPC PWM 3000RPM](https://www.noctua.at/en/products/nf-a14-industrialppc-3000-pwm) | 0-3000 RPM | Yes (user reported) |
| [Noctua NF-A12x25 120mm PWM](https://www.noctua.at/en/products/nf-a12x25-pwm) | 0-2000 RPM | Yes (user reported) |
| [Noctua NF-A20 PWM](https://www.noctua.at/en/products/nf-a20-pwm) | 350-800 RPM | No (user reported) |
| [Thermaltake CT200](https://www.thermaltake.com/ct200-pc-cooling-fan-single-fan-pack.html) | 500-900 RPM | No (user reported) |

## What "Spins down to 0 RPM" Means in Practice

**Fans that do NOT spin down to 0 RPM:** When the controller output drops below the fan's minimum PWM threshold, the fan continues spinning at its minimum speed. The RPM sensor will still report a non-zero value and the fan will remain audible. For use cases where fans must fully stop (e.g., silence during idle), these fans are not suitable without additional hardware.

**Fans that DO spin down to 0 RPM:** The fan will stop when PWM drops low enough. If the fan also exhibits hysteresis, it may require a higher PWM value to restart than the value that stopped it. This can cause brief delays when the controller ramps up from 0%.

:::note[Hardware limitation]
If your use case requires fans to fully stop, choose a fan confirmed to spin down to 0 RPM. Switchable power outputs (cutting 12V to the fan header) are not currently supported by the controller hardware.
:::

## Adding Your Fan

This list is community-reported. If you have tested a fan not listed here, please [open a GitHub issue](https://github.com/zeroflow/wifi-fancontroller/issues) with the fan model, observed RPM range, and whether it spins down to 0 RPM.
