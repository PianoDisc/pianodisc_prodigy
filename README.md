# PianoDisc Prodigy II for Home Assistant

Control and monitor a PianoDisc Prodigy II system from Home Assistant.

This is a custom Home Assistant integration distributed through HACS as a custom
repository.

## Features

- Local HTTP control and status polling
- MQTT discovery and low-latency status overlay
- SD-card MIDI playback controls
- Now-playing song, volume, shuffle, playlist, library, firmware, and update entities
- Media browser support for the piano's SD-card song library
- Playlist editor panel in the Home Assistant sidebar
- Optional linked power switch support

## Requirements

- Home Assistant 2024.12 or newer
- HACS installed in Home Assistant
- A PianoDisc Prodigy II system on the same local network
- Optional but recommended: Home Assistant's MQTT integration with a local broker

## Install with HACS

1. Open **HACS** in Home Assistant.
2. Open the three-dot menu in the top-right corner.
3. Select **Custom repositories**.
4. Add this repository URL:

   ```text
   https://github.com/PianoDisc/pianodisc-prodigy-ha-public
   ```

5. Select **Integration** as the category.
6. Click **Add**.
7. Search HACS for **PianoDisc Prodigy II**.
8. Install the integration.
9. Restart Home Assistant when HACS asks you to restart.

After the restart, go to **Settings -> Devices & services -> Add integration** and
search for **PianoDisc Prodigy II**.

## Set up your piano

### Recommended: MQTT discovery

MQTT gives the best user experience: automatic discovery, fast state updates, and
fewer polling delays.

1. In Home Assistant, go to **Settings -> Devices & services -> Add integration**.
2. Add **MQTT** and let Home Assistant set up or connect to your broker.
3. In the PianoDisc Calibrate app, set the piano's MQTT broker to your Home
   Assistant server IP address.
4. Return to **Settings -> Devices & services**.
5. When **PianoDisc Prodigy II discovered** appears, click **Configure**.

If the discovered piano does not have an IP address attached, open the integration's
**Reconfigure** option and enter the piano's IP address. This enables HTTP-based
features such as firmware information, library browsing, and playlist management.

### Manual IP setup

If MQTT discovery is not available:

1. Go to **Settings -> Devices & services -> Add integration**.
2. Search for **PianoDisc Prodigy II**.
3. Enter the piano's IP address.
4. Finish the setup flow.

Manual IP setup works without MQTT, but state updates may be slower.

## Using the integration

After setup, Home Assistant creates a PianoDisc Prodigy II device with entities for:

- Media playback
- Keys active status
- Library status
- Playlist selection
- Shuffle
- Library refresh
- Reboot
- Audio and MIDI firmware updates

The integration also adds a **Piano Playlists** item to the Home Assistant sidebar
for editing playlists, and a `pianodisc_prodigy.play_song` action for automations.

## Optional power control

You can link a dedicated smart plug, relay, switch, light, or helper that controls
power to the piano:

1. Open the PianoDisc Prodigy II integration entry.
2. Select **Configure**.
3. Choose the entity that powers the piano.

Only link an outlet dedicated to the piano. Turning off the PianoDisc media player
will turn off the linked power entity.

## Troubleshooting

### The integration does not appear after installing

Restart Home Assistant. If it still does not appear, clear your browser cache and
confirm HACS installed the files under:

```bash
/config/custom_components/pianodisc_prodigy
```

### Home Assistant cannot connect to the piano

- Confirm the piano is powered on.
- Confirm the piano and Home Assistant are on the same local network.
- Confirm the IP address is correct.
- If using MQTT, confirm the piano is pointed at the Home Assistant MQTT broker.

### MQTT discovery does not appear

- Confirm the Home Assistant MQTT integration is configured.
- Confirm the broker address and credentials in the PianoDisc Calibrate app.
- Restart the piano or reconnect it to the network so it publishes its discovery
  topic again.

### Logs

Open **Settings -> System -> Logs** and filter for `pianodisc`.

## Manual installation

HACS is recommended. Manual installation is mainly useful for development and support.

Copy `custom_components/pianodisc_prodigy` into your Home Assistant config directory:

```bash
mkdir -p /config/custom_components
cp -r custom_components/pianodisc_prodigy /config/custom_components/
ha core restart
```

## Notes

- MQTT topics use the `PianoDisc-Prodigy/<device_id>/...` namespace.
- The integration uses Home Assistant's configured MQTT broker; it does not store
  broker credentials itself.
- Firmware behavior varies by Prodigy II firmware version. Recent firmware provides
  retained and truthful playback state topics for best results.
