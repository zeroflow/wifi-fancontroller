---
title: Safety and Compliance
description: Power supply requirements, RF exposure separation distance, and user button scope for the WiFi Fan Controller
---

This page carries the normative wording for the WiFi Fan Controller. Where any other page,
product listing, or printed insert says something different, the text on this page applies.

## Power supply

The Fancontroller requires an external 12 V DC SELV power supply, not included.

- **Connector:** 5.5 × 2.1 mm barrel jack, centre positive
- **Voltage:** 12 V DC ±5 %
- **Current:** minimum 2.5 A recommended, depending on fan load

The power supply is not part of the product. Users must supply a power source that is
certified for their region.

The 2.5 A figure is the maximum total input current of the board, set by the DC barrel jack.
It applies to the sum of all connected fans plus the board electronics, not per fan header.
Size the supply to the combined draw of the fans you connect, with headroom.

The USB-C port (Rev 2.0 and later) powers the microcontroller only. It cannot power fans.

The supply must be a regulated switch-mode (SMPS) 12 V DC unit. The input voltage must never exceed 15 V under any condition, including no load or light load.
The board itself draws under 50 mA, so an unregulated transformer-based supply, which has no
feedback regulation, can rise well above its rated voltage when lightly loaded.

**Warning:** do not use old transformer-based heavy brick adapters. These are often unregulated
and can output 15 to 18 V at light load, which permanently damages the board.

Damage caused by overvoltage from an unsuitable power supply is not a manufacturing defect and
is not covered under warranty.

How to identify an unsuitable supply:

- Heavy for its size
- Audible hum
- Ventilation slots on the casing
- Input marking that lists only "50 Hz" with no switching frequency listed
- Very old

If unsure, measure the output with no load connected. Do not use it if it reads above about 13 V.

Suitable supplies include modern regulated switching wall adapters, and MeanWell DIN-rail
supplies (for example the HDR or MDR series) for cabinet installations.

Tip: connect the barrel plug to the board first, then plug the adapter into mains.

## RF exposure

This product contains a radio transmitter. Install the product so that a separation distance
of at least 20 cm is maintained between the antenna and any person during normal operation.
This product is not intended to be worn on the body or operated in close proximity to the user.

## User buttons

The board provides three user-assignable push buttons connected to GPIO. They have no function
in the default configuration. Any behaviour is defined by the user's ESPHome configuration.
Typical use is setup, commissioning, or occasional manual override; regular operation is via
the network interface.

In the factory firmware the buttons are exposed to Home Assistant as binary sensors reporting
their pressed state. They trigger no action on the board itself unless you configure one.

See [USR Buttons](/reference/modules/usr-buttons/) for one ready-made way to assign them.

## Intended use

The WiFi Fan Controller is intended for the following operating conditions:

- Supply from an external 12 V DC SELV power supply, not included
- Operation in dry indoor locations only
- Connection of 4-pin PWM fans only
- Maximum total input current of 2.5 A

The 2.5 A figure is the maximum total input current of the board, set by the DC barrel jack.
It applies to the sum of all connected fans plus the board electronics. Size the supply to the
combined draw of the fans you connect, with headroom.

## Explicit exclusions

The WiFi Fan Controller is NOT suitable for, and must not be used in, the following
applications:

- Safety critical applications (for example personal protection, fire protection, emergency shutdown)
- Explosive atmospheres
- Medical applications
- Operation without an enclosure (open assembly with no protective cover)
- Unattended continuous operation without regular checks
- Use in motor vehicles or other vehicles

No suitability is warranted for any of these applications.

## External power supply requirements

The external power supply you provide must meet the following requirements:

- **Voltage:** 12 V DC
- **Regulation:** regulated switch-mode supply (SMPS), not an unregulated transformer-based supply
- **Maximum voltage:** must never exceed 15 V under any circumstances, including no load
- **Marking:** CE marked
- **Current limiting:** the supply must limit its output current
- **Polarity:** correct polarity, centre positive (5.5 × 2.1 mm barrel jack)

## Firmware notice

The Fancontroller ships with factory tested firmware. The declaration of conformity covers the
product in that state. Custom ESPHome YAML, custom modules or third party firmware may affect
CE conformity. Whether they do depends on what the change alters.

Configurations that stay within the documented envelope change neither the radio behaviour nor
the electrical behaviour the assessment rests on. These include a changed device name, changed
update intervals, an added temperature curve or a control module from this repository, and the
firmware update provided by the manufacturer.

CE conformity of the product as delivered is void, however, for changes that leave the
documented envelope. These include in particular:

- Altering radio parameters, for example transmit power via `wifi: output_power:`
- Changing the PWM output frequency away from 25 kHz
- Operating the outputs outside their specified limits
- Operation outside the intended use described in this document

Not every possible configuration can be assessed in advance. No general approval is therefore
given for modified firmware, and responsibility for a modified configuration rests with whoever
operates it.

Warranty claims are void for damage attributable to such a change.
