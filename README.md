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

## Install HACS first

HACS is the Home Assistant Community Store. It lets Home Assistant install and
update custom integrations like this one from GitHub.

The steps below are a condensed HACS install guide for Home Assistant OS and Home
Assistant Supervised. If you use Home Assistant Container or Core, follow the
official HACS download instructions instead:
<https://www.hacs.xyz/docs/use/download/download/>

### 1. Add the HACS app repository

1. In Home Assistant, go to **Settings -> Apps -> Install app**.
2. Open the three-dot menu in the top-right corner and select **Repositories**.
3. Add this repository URL:

   ```text
   https://github.com/hacs/addons
   ```

Official Home Assistant screenshots:

![Home Assistant app store](https://www.home-assistant.io/images/getting-started/app-store.png)

![Adding an app repository URL](https://www.home-assistant.io/images/getting-started/adding_repositories-url.png)

### 2. Install and run Get HACS

1. Stay in **Settings -> Apps -> Install app**.
2. Search for **Get HACS**.
3. Select **Get HACS** and install it.
4. Start the app.
5. Open its logs and follow the instructions shown there.
6. When it says HACS has been downloaded, restart Home Assistant.

### 3. Add the HACS integration

1. After Home Assistant restarts, hard refresh your browser or clear your browser
   cache.
2. Go to **Settings -> Devices & services**.
3. Click **Add integration**.
4. Search for **HACS** and select it.
5. Acknowledge the HACS warning statements and click **Submit**.

Official HACS screenshots:

![Add integration](https://www.hacs.xyz/assets/images/screenshots/core/integrations/light.png)

![Select HACS](https://www.hacs.xyz/assets/images/screenshots/core/select_brand/light.png)

![HACS acknowledgement screen](https://www.hacs.xyz/assets/images/screenshots/core/config_flow/init/light.png)

### 4. Authorize HACS with GitHub

HACS uses GitHub device authorization.

1. Copy the code shown by Home Assistant.
2. Open the GitHub device login page when Home Assistant prompts you:
   <https://github.com/login/device>
3. Sign in to GitHub.
4. Paste the code.
5. Click **Authorize HACS**.
6. Return to Home Assistant and click **Finish**.

Official HACS screenshots:

![HACS device code](https://www.hacs.xyz/assets/images/screenshots/core/config_flow/waiting/light.png)

![GitHub device code entry](https://www.hacs.xyz/assets/images/screenshots/github/enter_code/light.png)

![Authorize HACS on GitHub](https://www.hacs.xyz/assets/images/screenshots/github/authorize/light.png)

![HACS setup success](https://www.hacs.xyz/assets/images/screenshots/core/config_flow/success/light.png)

You now have HACS installed and can install PianoDisc Prodigy II.

## Install with HACS

1. Open the **HACS** store from the Home Assistant left sidebar.
   If you are on the HACS device page under **Settings -> Devices & services**,
   click **Visit** to open the HACS store first. The device page itself is not
   where custom repositories are added.
2. Open the three-dot menu in the top-right corner.
3. Select **Custom repositories**.
4. Add this repository URL:

   ```text
   https://github.com/PianoDisc/pianodisc_prodigy.git
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
