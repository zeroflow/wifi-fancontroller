---
title: Combining Expansion Modules
description: How to run multiple Qwiic / STEMMA QT boards on one shared I2C bus, including addresses, speed, pull-ups, and power
---

Every device on the Qwiic connector, the 100mil I2C extension header, and the onboard HDC1080 temperature/humidity sensor sits on the same I2C bus: `bus_a`, SDA on GPIO33, SCL on GPIO34, at 3.3V logic. For the physical pinout and connector location, see the [Rev 3.x hardware page](/reference/hardware/rev-3-x/).

One shared bus means one clock speed, one address space, one set of pull-up resistors, and one power rail, all shared across whatever you plug in. Those are the four things that can collide when you combine more than one module, and they are the four sections below, after the compatibility matrix.

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
Max I2C speed for the BME680 and the DS2484, and per-module current draw for every device including the onboard HDC1080, have not been measured on this board and are not printed anywhere in this repo. Those cells read "not measured" or "not verified" rather than a number copied from a datasheet this project has not verified against the actual hardware.
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

The board fits its own pull-up resistors on SDA and SCL, and most Qwiic breakouts fit their own too. Every module you chain onto the bus adds its pull-ups in parallel with everyone else's, which lowers the effective total resistance and raises the current the bus has to source.

The board's fitted value is [4.7k on both SDA and SCL](/reference/hardware/rev-3-x/#qwiic-connector), on both the Qwiic connector and the 100mil extension port. Whether a given breakout fits its own pull-ups, and at what value, is specific to that board: check your breakout's own documentation.

:::note[Open point]
The practical limit on how many modules you can chain before the combined pull-ups get marginal has not been measured on this board.
:::

Many breakouts expose a cuttable jumper to remove their own pull-ups if a long chain of modules gets marginal.

## The 3.3V budget

Everything on the bus, and every module powered from the Qwiic connector's `+3V3` pin, draws from the board's 3.3V rail. That rail is regulated by an AMS1117-3.3 linear regulator, fed from a 5V buck stage.

The one measured and published current figure available today is the SCD41's ~17 mA average at a 5s measurement rate, already the heaviest of the current modules by a wide margin because of its NDIR cell.

:::note[Open point]
The total headroom of the 3.3V rail has not been published on the schematic and is not stated anywhere else in this repo. Do not treat any number for it as fact until it is measured on the board.
:::

In practice this is irrelevant if the controller runs on USB or barrel-jack power, and only worth budgeting for if you are running something current-constrained, like a battery.
