---
title: Troubleshooting
description: Solutions to common issues with the WiFi Fan Controller
sidebar:
  order: 4
---

Find solutions to common issues below. Each section is organized by symptom so you can jump directly to your problem.

## WiFi won't connect

- **Check your credentials** -- make sure you entered the correct WiFi network name and password during provisioning
- **2.4 GHz only** -- the ESP32 and ESP32-S2 do not support 5 GHz WiFi networks. This applies to all board revisions.
- **Check signal strength** -- move the board closer to your access point or check for interference
- **Fallback hotspot** -- if the board can't connect, it creates a hotspot called **"Fan Controller Fallback"**. Connect to this hotspot from your phone or laptop to re-enter WiFi credentials.
- **Factory reset** -- if nothing works, [reflash the factory firmware via USB](/getting-started/firmware-updates/) to start fresh

## Fans not spinning

- **Check 12V power** -- the fans are powered by the 12V DC barrel jack input, not USB-C. The USB-C port only provides 5V to the microcontroller and cannot power fans. Make sure your 12V power supply is connected and providing power.
- **Use PWM fans** -- the board controls fan speed via the PWM signal. Standard 3-pin DC fans won't respond to speed control (though they may run at full speed).
- **Check fan speed in HA** -- verify the fan speed is set above 0% in Home Assistant. A newly adopted device defaults to fans off.
- **Minimum startup speed** -- some fans require a higher PWM percentage to start spinning (typically 20-30%). Try setting the fan to 100% first, then lower gradually to find the minimum speed your fans support.
- **Check wiring** -- make sure the fan connector is fully seated and oriented correctly. See your [hardware revision page](/reference/hardware/) for pin diagrams.

## Fans keep spinning when set to off

- **This is usually the fan, not the board** - the Intel 4-wire PWM specification leaves behavior at very low duty cycles to the fan manufacturer. Many fans hold a minimum speed instead of stopping when the controller output reaches 0%.
- **Read the RPM sensor** - if a fan reports a steady non-zero RPM while its fan entity is switched off, that value is the fan's own minimum speed. [Fan Compatibility](/reference/fan-compatibility/) lists the fans that have been tested and explains how to check a fan that is not listed.
- **The board cannot switch 12V** - the fan headers are always powered while the barrel jack is connected. A fan that does not stop on its own cannot be stopped by the controller. If a hard stop is a firm requirement, pick a fan confirmed to spin down to 0 RPM.
- **3-pin fans always run at full speed** - a 3-pin DC fan has no PWM input and ignores the speed setting entirely. Check that your fan is a true 4-pin PWM model.

## Not showing in Home Assistant

- **ESPHome integration required** -- the fan controller uses the ESPHome native API. Make sure the [ESPHome integration](https://www.home-assistant.io/integrations/esphome/) is installed.
- **Same network/VLAN** -- the device must be on the same network as Home Assistant for mDNS discovery to work. If you use VLANs, ensure mDNS traffic can cross between them.
- **Manual add** -- go to **Settings > Devices & Services > Add Integration > ESPHome** and enter the device's IP address manually.
- **Check HA logs** -- look in **Settings > System > Logs** for API connection errors related to the fan controller.

## Web interface not reachable (port 80 refused)

- **The web server is off by default** -- the firmware ships without the built-in web interface for security and memory reasons, so `http://<board-ip>` returns `ERR_CONNECTION_REFUSED`. This is expected, not a fault.
- **Home Assistant does not need it** -- the board is controlled over the encrypted ESPHome API. Fan control, sensors, and automations all work without the web interface.
- **Enable it yourself** -- add the `web_server` component (with authentication) to your own ESPHome config and re-flash. See [Web Interface](/reference/web-server/) for the exact configuration, or [Standalone Usage](/reference/standalone/) if you're running without Home Assistant entirely.
- **`dashboard_import` won't do it** -- importing the package does not start a web server. You have to add the `web_server` block yourself.

## Temperature or humidity reads wrong

- **Sensor accuracy** -- the HDC1080 sensor has a typical accuracy of +/- 0.2 C for temperature and +/- 2% for relative humidity. Small deviations from a reference thermometer are expected.
- **Board self-heating** -- at high fan loads, components on the board generate heat that can affect the temperature reading. This is most noticeable in enclosed spaces with poor airflow around the board itself.
- **Stabilization time** -- allow 5 minutes after power-on for the sensor readings to stabilize.

## RPM shows 0 for a spinning fan

- **Tachometer wire required** -- the RPM sensor reads the fan's tachometer signal. Your fan must have a tach wire (3-pin fans with tach, or 4-pin PWM fans). 2-pin fans have no tachometer output.
- **Minimum speed threshold** -- some fans don't generate a reliable tach signal below a certain speed. Try increasing fan speed to 50% or higher to test.
- **Pulse counter configuration** -- if you're using a custom ESPHome config, verify the pulse counter sensor is configured for the correct GPIO pin matching your hardware revision.

## ESP32-S2 USB not detected

- **Try a different cable** -- many USB-C cables are charge-only and don't carry data. Use a cable that you know works for data transfer.
- **Hold BOOT button** -- hold the BOOT button on the board while plugging in the USB cable to force the board into bootloader mode.
- **Try a different USB port** -- some USB ports (especially through hubs) don't provide enough power or have compatibility issues. Use a port directly on your computer.
- **Use ESPWEBTOOL** -- try [ESPWEBTOOL](https://esptool.spacehuhn.com/) as an alternative flashing tool that may handle the USB connection differently.

## OTA update fails

- **Check network connectivity** -- make sure the device is reachable on your network. Try pinging its IP address.
- **Check flash space** -- very large custom configs may exceed available flash space. Check the ESPHome compile output for size warnings.
- **Retry once** -- transient network issues can interrupt OTA. Try the update again.
- **Fallback to USB** -- if OTA consistently fails, [reflash via USB](/getting-started/firmware-updates/) to restore a known-good firmware and try OTA again afterward.

---

## Still stuck?

Can't find a solution? [Open an issue on GitHub](https://github.com/zeroflow/wifi-fancontroller/issues) with details about your hardware revision, firmware version, and the problem you're experiencing.
