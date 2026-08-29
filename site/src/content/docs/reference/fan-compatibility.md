---
title: Fan Compatibility
description: Which fans spin down to 0 RPM, how to check a fan that is not listed, and community-reported behavior at low PWM duty cycles
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

The Intel 4-Wire PWM Fan Specification defines fan behavior at 100% duty cycle, but leaves the low end of the range to the fan manufacturer. Each fan has its own minimum duty cycle, stated in that fan's datasheet, and behavior below that minimum is undefined. A minimum somewhere around 20% is common in practice, but it is not a value the specification fixes.

Manufacturers implement that range differently: some fans have a hard minimum PWM threshold below which they stop responding and continue spinning at their minimum speed, while others can spin all the way down to 0 RPM at sufficiently low PWM values. Some fans in the latter group also exhibit hysteresis - they spin down to 0 RPM but will not restart until PWM rises above a higher threshold than the one that stopped them.

This matters for any control module that sweeps the full 0-100% output range. If a fan cannot spin down to 0 RPM, it will continue running at its minimum speed even when the controller output is 0%.

## Checking a Fan That Is Not Listed

The table below only covers fans someone has actually tested. For anything else, there are two ways to find out.

**Before you buy,** check the manufacturer datasheet for a stated speed at 0% PWM. Noctua publishes this under Performance Specifications as "Rotational speed @ 0% PWM". Most other manufacturers do not publish it at all, in which case the behavior is undetermined and you are buying on trust. Note that this is model-specific and not a property of the brand: the [NF-A20](https://www.noctua.at/en/products/nf-a20-pwm) in the table below does not stop, and the [NF-A6x25](https://www.noctua.at/en/products/nf-a6x25-pwm) specifies a 550 RPM minimum.

**If you already have the fan,** measure it instead of researching it. Plug it in, set that fan to 0% in Home Assistant, and watch its RPM sensor. A reading that settles at zero means the fan stops. A reading that settles at some non-zero value is the fan's minimum speed, and that is what the fan will do whenever the controller commands 0%. This takes under a minute and answers the question for the fan you actually own, which matters because most datasheets are silent on it.

## Community-Reported Fans

This table reflects user-reported observations. PWM behavior can vary between firmware revisions of the same fan model.

| Fan | Size | RPM Range (per spec) | Spins down to 0 RPM |
|-----|------|----------------------|---------------------|
| [Arctic P12 Max](https://www.arctic.de/en/P12-Max/ACFAN00280A) | 120 x 25 mm | 400-3300 RPM | Yes (user reported) |
| [Arctic S12038-4K](https://www.arctic.de/S12038-4K/ACFAN00296A) | 120 x 38 mm | 600-4000 RPM (400-4000 RPM tested) | No, holds 400 RPM when "off" (user reported, [#48](https://github.com/zeroflow/wifi-fancontroller/issues/48)); tested with 4 fans on rev 3.3, firmware 3.3 / ESPHome 2026.5.2 |
| [Arctic S4028-15k](https://www.arctic.de/S4028-15K/ACFAN00264A) | 40 x 28 mm | 1400-15000 RPM | No, holds 940-1900 RPM when "off" (user reported, [#54](https://github.com/zeroflow/wifi-fancontroller/issues/54)) |
| [be quiet! Pure Wings 3 120mm PWM high-speed](https://www.bequiet.com/de/casefans/4607) | 120 x 25 mm | 2100 RPM | No, holds 240-270 RPM when "off" (user reported, [#56](https://github.com/zeroflow/wifi-fancontroller/issues/56)) |
| Evercool EC7015H12EP | 70 x 15 mm | Not published | No, holds ~1500 RPM when "off", ~2600 RPM at full speed (user reported, [#70](https://github.com/zeroflow/wifi-fancontroller/issues/70)) |
| [Noctua NF-A14 Industrial PPC PWM 3000RPM](https://www.noctua.at/en/products/nf-a14-industrialppc-3000-pwm) | 140 x 25 mm | 0-3000 RPM | Yes (user reported) |
| [Noctua NF-A12x25 120mm PWM](https://www.noctua.at/en/products/nf-a12x25-pwm) | 120 x 25 mm | 0-2000 RPM | Yes (user reported) |
| [Noctua NF-A20 PWM](https://www.noctua.at/en/products/nf-a20-pwm) | 200 x 30 mm | 350-800 RPM | No (user reported) |
| [Thermaltake CT200](https://www.thermaltake.com/ct200-pc-cooling-fan-single-fan-pack.html) | 200 x 30 mm | 500-900 RPM | No (user reported) |

Almost every entry above is a 120 mm or larger PC case fan, because that is what most people have on hand to test. The two smaller formats reported so far, the 40 mm S4028 and the 70 mm Evercool, both hold a minimum speed rather than stopping. Two data points are not a rule, but small OEM-format fans rarely publish a 0% PWM figure either, so if you need a fan below 120 mm to stop completely, treat it as unverified until you have measured it yourself.

## What "Spins down to 0 RPM" Means in Practice

**Fans that do NOT spin down to 0 RPM:** When the controller output drops below the fan's minimum PWM threshold, the fan continues spinning at its minimum speed. The RPM sensor will still report a non-zero value and the fan will remain audible. For use cases where fans must fully stop (e.g., silence during idle), these fans are not suitable without additional hardware.

**Fans that DO spin down to 0 RPM:** The fan will stop when PWM drops low enough. If the fan also exhibits hysteresis, it may require a higher PWM value to restart than the value that stopped it. This can cause brief delays when the controller ramps up from 0%.

:::note[Hardware limitation]
If your use case requires fans to fully stop, choose a fan confirmed to spin down to 0 RPM. Switchable power outputs (cutting 12V to the fan header) are not currently supported by the controller hardware.
:::

## Adding Your Fan

This list is community-reported. If you have tested a fan not listed here, please [open a GitHub issue](https://github.com/zeroflow/wifi-fancontroller/issues) with the fan model, size, observed RPM range, and whether it spins down to 0 RPM.
