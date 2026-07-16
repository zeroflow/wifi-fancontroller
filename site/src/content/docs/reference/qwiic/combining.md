---
title: Combining Expansion Modules
description: How to run multiple Qwiic / STEMMA QT boards on one shared I2C bus, including addresses, speed, pull-ups, and power
---

Every device on the Qwiic connector, the 100mil I2C extension header, and the onboard HDC1080 temperature/humidity sensor sits on the same I2C bus: `bus_a`, SDA on GPIO33, SCL on GPIO34, at 3.3V logic. For the physical pinout and connector location, see the [Rev 3.x hardware page](/reference/hardware/rev-3-x/).

One shared bus means one clock speed, one address space, one set of pull-up resistors, and one power budget, all shared across whatever you plug in. Those are the four things that can collide when you combine more than one module, and they are the four sections below, after the compatibility matrix.

## Compatibility matrix

| Device | Address | Max I2C speed | Typical current | Framework | Notes |
|---|---|---|---|---|---|
| HDC1080 (onboard) | `0x40` | 400 kHz | not measured | Any | Built into every board, always present, not a module you add |
| [BME680](/reference/qwiic/examples/bme680/) | `0x77` default, `0x76` via jumper | not verified | not measured | Any | |
| [BME680 with BSEC2](/reference/qwiic/examples/bme680-bsec2/) | `0x77` default, `0x76` via jumper | not verified | not measured | Arduino only | Same chip and address as the plain BME680, so the two are mutually exclusive |
| [SSD1306 OLED](/reference/qwiic/examples/ssd1306/) | `0x3C` | 400 kHz | not measured | Any | |
| [DS2484](/reference/qwiic/examples/ds2484/) | `0x18` | not verified | not measured | Any | I2C-to-1-Wire bridge for Dallas sensors |
| [SCD41](/reference/qwiic/examples/scd41/) | `0x62` (fixed) | 100 kHz (hard datasheet limit) | ~17 mA average at a 5s rate | Any | Heaviest current draw of the current module set, because of the NDIR cell |

No two devices in this table share an address: `0x40`, `0x77` / `0x76`, `0x3C`, `0x18`, and `0x62` are all distinct.

:::note[Open point]
Max I2C speed for the BME680 and the DS2484 has not been measured on this board and is not printed anywhere in this repo: those cells read "not verified" rather than a number copied from a datasheet this project has not confirmed against the actual hardware. That gap is the one worth watching, since an unverified speed limit could force the shared bus slower than expected. Per-module current draw for the rest of the table is unmeasured too, but now that the [power budget](#the-qwiic-cable-sets-the-power-budget) works out to roughly 13 modules of headroom, filling those cells in is a completeness note rather than a real risk.
:::

## Bus speed: the slowest device wins

One rule governs a shared I2C bus: the slowest device on it sets the ceiling for everyone. No module raises the bus speed on its own, so left alone the bus stays at ESPHome's default of 50 kHz.

The one known collision on this board is the SCD41 against the OLED. The SCD41 has a hard 100 kHz limit, while the OLED page recommends 400 kHz for a smooth screen refresh. Run both together and the bus has to stay at 100 kHz or below, so the display simply refreshes slower. See [Bus speed: the 100 kHz rule](/reference/qwiic/examples/scd41/#bus-speed-the-100-khz-rule) for the full explanation.

:::caution
Above 100 kHz the SCD41 does not fail cleanly. It returns CRC errors and dropped readings that look exactly like a loose cable. If your SCD41 readings are flaky right after adding another module, check the bus frequency first.
:::

The hardware package defines `bus_a` as a list, which is what makes changing its speed from your own firmware config possible. Extend it with `!extend`, as the OLED module's header comment shows:

```yaml
i2c:
  - id: !extend bus_a
    frequency: 400kHz
```

## Addresses must be unique

No two devices on the bus may share an address. The onboard HDC1080 permanently occupies `0x40`, so every module you add needs a different one. The current module set has no clashes, as shown in the matrix above.

To confirm your setup at boot, the bus runs with `scan: true`, so ESPHome logs every address it finds on every start. See the worked log example on the [Qwiic overview page](/reference/qwiic/).

The BME680 case is worth calling out explicitly. The plain BME680 module and the BME680 with BSEC2 module drive the same physical chip at the same address, so they are mutually exclusive: importing both is a configuration error, not an address clash you can jumper your way out of. A second, separate BME680 chip alongside the first is possible, using the `0x76` solder jumper and the module's `bme680_address` var.

## Pull-ups add in parallel

The board fits its own pull-up resistors, [4.7k on both SDA and SCL](/reference/hardware/rev-3-x/#qwiic-connector), on both the Qwiic connector and the 100mil extension port. That pair is already enough for the bus, and every Qwiic or STEMMA QT board you chain on adds its own pull-ups in parallel with it. [SparkFun](https://docs.sparkfun.com/SparkFun_Qwiic_Buzzer/hardware_overview/), who designed the connector, gives the rule that answers what to do about it: "As a general rule of thumb, disable all but one pair of pull-up resistors if multiple devices are connected to the bus." On this controller, that one pair is the board's own 4.7k, so the pull-ups to disable are the ones on the modules you attach, not the board's.

Most breakouts make that easy to act on, though exactly how varies by board. SparkFun's own Qwiic boards fit 2.2k pull-ups as standard, wired through a three-way jumper labeled I2C: cut it and the pull-ups disconnect. The [Adafruit STEMMA QT spec](https://learn.adafruit.com/introducing-adafruit-stemma-qt/technical-specs) does not commit to a resistor value at all; it only states the expectation that "the I2C device is expected to have pullups from SDA & SCL to V+". Individual Adafruit boards still fit real resistors of their own choosing: the [Adafruit Qwiic / STEMMA QT Breakout Board (#5961)](https://www.adafruit.com/product/5961), for example, fits two 10k pull-ups that can be "deactivated by cutting some small traces on the back of the PCB, if they are not needed." Check your own breakout's documentation for its value and how to disable it.

Chaining pull-ups pulls in two opposite directions at once. More pull-ups in parallel lower the total resistance, which improves rise time but raises the current the bus has to sink. More devices and more cable raise the bus's capacitance, which worsens rise time. Which one bites first depends entirely on what values the breakouts in your chain fit, which is why the rule of thumb above is the safe default rather than a module count.

As an illustration of that dependency, not a guarantee: against the board's own 4.7k, breakouts fitting SparkFun's 2.2k put you near 890 ohm with just two modules chained, already under the ~1k floor described below. Breakouts fitting the Adafruit board's 10k instead leave you around 1.4k even with five modules chained, still comfortably above that floor, so capacitance would bite first there instead. The gap between those two real, sourced values is exactly why board-to-board pull-up values vary this much, and why disabling all but one pair beats trying to count modules.

### Method 1: ohmmeter

Power the board down before measuring.

1. Measure resistance from SDA to `+3V3`.
2. Unplugged, you should read the board's own 4.7k.
3. With the full chain attached, you read the parallel total of every pull-up on the bus.

The floor is roughly 1k. An I2C device only guarantees it can sink 3mA, and (3.3V - 0.4V) / 3mA works out to about 970 ohm. Below that, the bus can no longer pull the line down to a clean low level.

:::caution
Measure with the board powered off. Internal protection diodes on some devices can skew the reading, which shows up as a different value if you reverse the probes.
:::

### Method 2: oscilloscope

Probe SDA at the far end of the chain, the worst case for both capacitance and pull-up strength. Trigger on a rising edge during real bus traffic, then measure the 30% to 70% rise time, which at 3.3V logic is 0.99V to 2.31V.

| Bus speed | Rise time budget |
|---|---|
| 100 kHz | under 1000ns |
| 400 kHz | under 300ns |

From the measured rise time you can back-calculate the bus capacitance: Cb is approximately tr / (0.85 x Rp). The I2C specification's limit is 400pF.

### No scope? Pass/fail only

Without a scope, run the bus with your full chain attached and watch the ESPHome log for CRC errors and dropped readings. This is not a measurement, it is pass/fail. If the log stays clean, the chain works. If it does not, this failure mode looks identical to the [SCD41 overclock symptom](#bus-speed-the-slowest-device-wins) described above, so rule out the pull-ups before assuming a bad cable.

If a chain fails any of these three checks, disabling the extra pull-ups as described above, down to the controller's one pair, is the fix all three point you toward.

## The Qwiic cable sets the power budget

Everything on the bus, and every module powered from the Qwiic connector's `+3V3` pin, draws from the board's 3.3V rail. But the rail is not what limits you here: the binding constraint is the Qwiic cable itself.

[SparkFun](https://www.sparkfun.com/qwiic), who designed the connector, states it plainly: "The very conservative max current on a Qwiic cable is 226mA. If you want to push it, 28AWG is good for up to 1.4A for chassis wiring." This page adopts SparkFun's conservative 226mA figure as the budget, rather than deriving its own.

The board's 3.3V rail can spare more than 226mA under both conservative and best-case assumptions, so the board itself is not the bottleneck.

The status LEDs and the NeoPixel port run off the 5V rail, not the 3.3V regulator, so they do not eat into this budget either.

226mA against the SCD41's ~17mA average, the heaviest module in the [compatibility matrix](#compatibility-matrix) above, is roughly 13 modules. Power is not the limit anyone will actually hit combining Qwiic modules on this board: [addresses](#addresses-must-be-unique) and [bus speed](#bus-speed-the-slowest-device-wins) bite first.

In practice this is irrelevant if the controller runs on USB or barrel-jack power, and only worth budgeting for if you are running something current-constrained, like a battery.
