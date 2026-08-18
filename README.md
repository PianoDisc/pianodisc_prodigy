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

#### 1. Install Mosquitto broker in Home Assistant

The easiest MQTT broker for Home Assistant OS and Home Assistant Supervised is the
official **Mosquitto broker** app.

1. In Home Assistant, go to **Settings -> Apps -> Install app**.
2. Search for **Mosquitto broker**.
3. Select **Mosquitto broker** and click **Install**.
4. Start the Mosquitto broker app.
5. Open the app logs and confirm it started without errors.
6. Go to **Settings -> Devices & services -> Add integration**.
7. Search for **MQTT**.
8. Select **MQTT** and follow the prompts to connect it to the Mosquitto broker.
9. Keep MQTT discovery enabled.

Home Assistant can automatically manage its own Mosquitto credentials. For the
PianoDisc device, create a separate Mosquitto login so the device has credentials
you can enter in its web UI.

#### 2. Create a Mosquitto login for the piano

1. In Home Assistant, go to **Settings -> Apps**.
2. Open **Mosquitto broker**.
3. Open the **Configuration** tab.
4. Find **Logins** and add a new list item.
5. Set:

   ```text
   username: pianodisc_mqtt
   password: choose-a-strong-password
   ```

6. Save the Mosquitto broker configuration.
7. Restart the Mosquitto broker app.
8. Open the Mosquitto broker logs and confirm it started without authentication
   errors.
9. Keep the username and password available for the next step.

If your Mosquitto broker configuration screen is in YAML mode instead of form mode,
add the same login like this:

   ```yaml
   logins:
     - username: pianodisc_mqtt
       password: choose-a-strong-password
   ```

Use a dedicated username such as `pianodisc_mqtt`. Do not use `homeassistant` or
`addons`; those names are reserved by Home Assistant's Mosquitto setup.

#### 3. Point the PianoDisc device to Home Assistant

1. Find the IP address of your PianoDisc Prodigy2 device.
2. Open the Prodigy2 device web UI in a browser:

   ```text
   http://<piano-ip-address>
   ```

3. Open the **System** page.
4. Find the IP address of your Home Assistant server.
5. In the **MQTT Broker** section, enter:

   ```text
   MQTT broker server host name or LAN IP address: <Home Assistant IP address>
   MQTT broker port: 1883
   MQTT broker username: <the Mosquitto login username you created>
   MQTT broker password: <the Mosquitto login password you created>
   ```

6. Click **Save**.
7. Click **Apply**.
8. Restart the PianoDisc device.

After the PianoDisc device restarts and connects to Mosquitto, Home Assistant should discover it automatically. Go to **Settings -> Devices & services** and look for a new **PianoDisc Prodigy II discovered** card, then click **Configure**.

If the discovered piano does not have an IP address attached, open the integration's **Reconfigure** option and enter the piano's IP address. This enables HTTP-based features such as firmware information, library browsing, and playlist management.

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

### HACS says the repository already exists

If **Custom repositories** shows:

```text
Repository 'pianodisc/pianodisc_prodigy' exists in the store.
```

the repository is already known to HACS. Close the **Custom repositories** dialog,
return to the HACS store, search for **PianoDisc Prodigy II**, and install it from
there. Do not delete the repository from the dialog unless you are trying to remove
it completely.

### HACS says the version cannot be used

If the download dialog says something like:

```text
The version fa6e441 for this integration can not be used with HACS.
```

the repository likely needs a GitHub release. Ask the maintainer to publish a
release whose tag matches the integration version in
`custom_components/pianodisc_prodigy/manifest.json`, for example `v0.1.0` for
version `0.1.0`. After the release is published, open HACS, use **Update
information** on the repository, and try **Download** again.

### Home Assistant cannot connect to the piano

- Confirm the piano is powered on.
- Confirm the piano and Home Assistant are on the same local network.
- Confirm the IP address is correct.
- If using MQTT, confirm the piano is pointed at the Home Assistant MQTT broker.

### Home Assistant says setup is already in progress

If manual IP setup shows:

```text
already_in_progress
```

Home Assistant already has a PianoDisc setup flow open, usually because MQTT or DHCP
discovery found the piano first. Go back to **Settings -> Devices & services** and
use the **PianoDisc Prodigy II discovered** card instead of starting another manual
setup. If another setup dialog is open, close it and try again.

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
