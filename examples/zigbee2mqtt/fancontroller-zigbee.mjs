// Zigbee2MQTT external converter for the Rev 4.0 Zigbee router example
// (examples/network-zigbee-rev-4.0.yaml). EXPERIMENTAL, like the firmware.
//
// Install: copy this file to the external_converters folder in the
// Zigbee2MQTT data directory and restart Zigbee2MQTT. A board that is already
// paired picks it up after the restart; if the old exposes stay, remove the
// device in Zigbee2MQTT and pair it again.
//
// Why: without a converter Zigbee2MQTT uses an automatically generated
// definition. Fan control and sensors work with it, but the generator adds one
// light extend per dimmable endpoint, each covering all four endpoints, so
// every fan expose shows up four times. It also names entities by endpoint
// number only and shows the RPM as generic analog inputs.
//
// Entities: state_fan1..4 and brightness_fan1..4 (brightness 0-254 = speed
// 0-100 %), rpm_fan1..4, temperature_sensor, humidity_sensor.

import * as m from "zigbee-herdsman-converters/lib/modernExtend";

const fans = ["fan1", "fan2", "fan3", "fan4"];

export default {
    // Must match name and manufacturer of the zigbee: block in the firmware
    fingerprint: [{modelID: "WiFi Fan Controller Rev 4.0", manufacturerName: "Arthofer Engineering"}],
    model: "WiFi Fan Controller Rev 4.0",
    vendor: "Arthofer Engineering",
    description: "4 channel PWM fan controller, Zigbee router (experimental)",
    extend: [
        m.deviceEndpoints({endpoints: {fan1: 1, fan2: 2, fan3: 3, fan4: 4, sensor: 5}}),
        // The firmware implements neither identify effects nor StartUpOnOff
        m.light({endpointNames: fans, effect: false, powerOnBehavior: false}),
        m.numeric({
            name: "rpm",
            cluster: "genAnalogInput",
            attribute: "presentValue",
            description: "Fan speed",
            unit: "rpm",
            precision: 0,
            access: "STATE_GET",
            endpointNames: fans,
            reporting: {min: "5_SECONDS", max: "1_HOUR", change: 10},
        }),
        m.temperature({endpointNames: ["sensor"]}),
        m.humidity({endpointNames: ["sensor"]}),
    ],
};
