# PianoDisc Prodigy II for Home Assistant

Custom Home Assistant integration for PianoDisc Prodigy II systems.

## Features

- Local HTTP control and status polling
- MQTT discovery and low-latency status overlay
- SD-card MIDI playback controls
- Now-playing song, volume, shuffle, firmware version, and update sensors
- Optional linked power switch support

## Manual Installation

Copy `custom_components/pianodisc_prodigy` into your Home Assistant config directory:

```bash
mkdir -p /config/custom_components
cp -r custom_components/pianodisc_prodigy /config/custom_components/
ha core restart
```

Or clone this repository from Home Assistant:

```bash
cd /config
git clone https://github.com/PianoDisc/pianodisc_prodigy.git pianodisc-prodigy-ha
mkdir -p custom_components
cp -r pianodisc-prodigy-ha/custom_components/pianodisc_prodigy custom_components/
ha core restart
```

## HACS

This repository is structured for HACS custom repository installation. Add it as a
custom repository with category `Integration`, then install `PianoDisc Prodigy II`.

## Setup

After restarting Home Assistant:

1. Go to Settings -> Devices & services.
2. Add integration: `PianoDisc Prodigy II`.
3. Use MQTT discovery when available, or enter the device host/IP manually.

## Notes

- MQTT topics use the `PianoDisc-Prodigy/<device_id>/...` namespace.
- The integration uses Home Assistant's configured MQTT broker; it does not store
  broker credentials itself.
- Firmware behavior varies by Prodigy II firmware version. Recent firmware provides
  retained and truthful playback state topics for best results.
