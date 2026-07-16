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
