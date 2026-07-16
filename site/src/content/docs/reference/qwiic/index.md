---
title: Qwiic / STEMMA QT Expansion
description: Add I2C expansion boards (sensors, displays) to the fan controller over the Qwiic / STEMMA QT connector
---

![WiFi Fan Controller with a Qwiic / STEMMA QT expansion board connected to the solderless JST-SH port](/images/qwiic/qwiic_hero.jpg)

The Qwiic (also sold as STEMMA QT) connector is a solderless way to add I2C boards to the fan controller. Think environmental sensors, small OLED displays, RTCs, or GPIO expanders. Any I2C device that ESPHome supports can be wired in and exposed to Home Assistant without soldering.

:::note[Rev 3.1+ only]
The Qwiic connector is present on Rev 3.x boards (3.1, 3.2, 3.3). Earlier revisions do not have it. For the physical pinout and connector location, see the [Rev 3.x hardware page](/reference/hardware/rev-3-x/).
:::

## The shared I2C bus

The Qwiic port, the 100mil I2C extension port, and the onboard HDC1080 temperature/humidity sensor all sit on the **same I2C bus** (`bus_a`, GPIO33 SDA / GPIO34 SCL), running at **3.3V logic**.

The most important consequence: **every device address on the bus must be unique.** The onboard HDC1080 occupies `0x40`, so any module you add must use a different address.

:::caution
Do not hot-plug Qwiic boards. Power the controller down before connecting or disconnecting a module, otherwise you risk glitching the shared bus (including the onboard sensor).
:::

## Finding a module's address

The bus is configured with `scan: true`, so on every boot ESPHome logs each address it finds. This is the quickest way to confirm your new module is wired correctly and does not clash with the HDC1080:

```text
[I][i2c:093]: Results from i2c bus scan:
[I][i2c:099]: Found i2c device at address 0x40   # onboard HDC1080
[I][i2c:099]: Found i2c device at address 0x77   # your new module (BME280)
```

If your module shows up at `0x40`, it conflicts with the onboard sensor. Most boards let you change the address with a solder jumper or a config option.

## Adding a module

You extend your **own firmware YAML** (the file that includes the hardware package), not the hardware package itself. Add the component under the matching platform (`sensor:`, `display:`, ...) and point it at the existing bus with `i2c_id: bus_a`.

Here is a complete BME280 environmental sensor as a copy-paste starting point:

```yaml
sensor:
  - platform: bme280_i2c
    i2c_id: bus_a
    address: 0x77        # default; 0x76 selectable on most boards
    temperature:
      name: "BME280 Temperature"
    humidity:
      name: "BME280 Humidity"
    pressure:
      name: "BME280 Pressure"
```

That is the whole pattern. **Any I2C device ESPHome supports drops in the same way:** pick the right platform from the [ESPHome component index](https://esphome.io/components/), give it a free address, and reference `i2c_id: bus_a`.

:::tip
Need an interrupt line (for motion sensors, touch controllers, etc.)? The board exposes an INT pin on GPIO35 next to the I2C signals on the internal 100mil header. See the [Rev 3.x hardware page](/reference/hardware/rev-3-x/).
:::

## Tested modules

These boards have been verified on the controller and have their own worked examples, including any framework or library caveats:

- [BME680](/reference/qwiic/examples/bme680/): temperature, humidity, pressure, gas
- [BME680 with BSEC2](/reference/qwiic/examples/bme680-bsec2/): BME680 with the Bosch BSEC2 air-quality library
- [SSD1306 OLED Display](/reference/qwiic/examples/ssd1306/): SSD1306 monochrome display
- [DS2484](/reference/qwiic/examples/ds2484/): I2C-to-1-Wire bridge for Dallas sensors
- [SCD41](/reference/qwiic/examples/scd41/): CO2, temperature, humidity

## Running more than one module

Multiple boards on the shared bus bring extra considerations: a single bus runs at a single clock speed (and not every device tolerates the same speed), pull-up resistors add up in parallel, and the 3.3V rail has a current budget. See [Combining Expansion Modules](/reference/qwiic/combining/) for the details and a compatibility matrix.
