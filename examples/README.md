# WiFi Fan Controller - Example Configurations

This directory contains example configurations showing how to use the hardware packages.

## Basic Examples

Simple configurations that get you started quickly:

- **`basic-rev-1.0.yaml`** - Minimal config for Hardware Revision 1.0 (ESP32)
- **`basic-rev-2.0.yaml`** - Minimal config for Hardware Revision 2.0 (ESP32-S2)
- **`basic-rev-3.0.yaml`** - Minimal config for Hardware Revision 3.0 (ESP32-S2)
- **`basic-rev-3.1.yaml`** - Minimal config for Hardware Revision 3.1 (ESP32-S2 with RGB LEDs)

## Advanced Examples

Examples showing additional features and modules:

- **`with-rpm-pi-control-rev-3.1.yaml`** - Shows how to use the RPM PI control module for precise fan speed regulation with deadband and I-term reset
- **`with-rgb-status-leds-rev-3.1.yaml`** - Shows how to use the RGB status LED module for visual fan speed feedback
- **`with-temperature-curve-rev-3.1.yaml`** - Shows how to use the temperature curve module for flexible multi-point fan control (recommended!)
- **`with-temperature-control-rev-3.1.yaml`** - Shows how to use temperature control modules (linear/PID) for automatic fan speed adjustment
- **`with-temperature-curve-external-sensor-rev-3.1.yaml`** - Shows how to drive the temperature curve from an external Qwiic BME680 instead of the onboard sensor, via `temperature_sensor_id`

## Rev 4.0 Network Mode Examples (experimental, dev only)

These configs try the alternative network modes of the ESP32-C6 on Rev 4.0 developer boards. They reference the dev branch, are not validated by `test-examples.sh` or CI, and are not customer features.

- **`network-wifi-ble-rev-4.0.yaml`** - WiFi with Improv BLE and Improv Serial provisioning, Home Assistant API and OTA, no credentials compiled in
- **`network-thread-rev-4.0.yaml`** - Thread only (openthread FTD, no WiFi), Home Assistant API and OTA over Thread, status LED follows the Thread attach state; needs a `thread_tlv` secret with the active dataset of your border router

## Usage

1. Copy one of the example files to your ESPHome configuration directory
2. Rename it to match your device (e.g., `my-fancontroller.yaml`)
3. Create a `secrets.yaml` file with your WiFi credentials:
   ```yaml
   wifi_ssid: "Your WiFi SSID"
   wifi_password: "Your WiFi Password"
   ```
4. Customize the configuration to your needs
5. Flash to your device using ESPHome

## Hardware Packages

All examples use hardware packages located in the root directory:

- `hardware-rev-1.0.yaml` - ESP32 board configuration
- `hardware-rev-2.0.yaml` - ESP32-S2 board configuration
- `hardware-rev-3.0.yaml` - ESP32-S2 with monochromatic status LED
- `hardware-rev-3.1.yaml` - ESP32-S2 with RGB status LEDs

## Optional Modules

Additional functionality can be added via modules in the `modules/` directory:

- `modules/rpm_pi_control.yaml` - PI controller for precise RPM regulation with deadband and I-term reset features
- `modules/rpm_status_leds.yaml` - Visual feedback for fan operation (RGB LEDs change color based on RPM)
- `modules/temperature_curve.yaml` - Flexible 5-point temperature curve with linear interpolation (recommended!)
- `modules/temperature_linear.yaml` - Simple linear temperature-based fan control
- `modules/temperature_pid.yaml` - PID-based temperature control for precise regulation

## Factory Images

For initial device flashing, use the factory images instead:

- `fancontroller-rev1.0-esp32.factory.yaml`
- `fancontroller-rev2.0-esp32s2.factory.yaml`
- `fancontroller-rev3.0-esp32s2.factory.yaml`
- `fancontroller-rev3.1-esp32s2.factory.yaml`

Factory images include additional provisioning features like improv_serial and are meant for first-time setup.
