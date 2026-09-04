# PianoDisc Prodigy II for Home Assistant

![Status: Alpha — not for public use](https://img.shields.io/badge/status-ALPHA%20%E2%80%94%20not%20for%20public%20use-critical?style=for-the-badge)

## ⚠️ Alpha — not ready for use

> **This integration is in alpha. Please don't install it yet.**
>
> - **It needs firmware we haven't released.** The Prodigy II firmware this integration
>   depends on is still in beta testing and isn't publicly available, so it will not work
>   on a current production piano.
> - **Breaking changes are frequent.** Entities, their names and their behaviour are all
>   still moving. An update can and will break automations you've built on it.
> - **It is not supported yet.** Please don't file issues or contact PianoDisc support
>   about it at this stage.
>
> **Wait for the beta.** Watch this repository to be notified when it's ready to try. The
> documentation below describes where the integration is heading and is published so it
> can be reviewed — not as an invitation to install.

---

Play and automate your PianoDisc Prodigy II player piano from Home Assistant. Browse the
songs on its SD card, start them from a dashboard, a schedule or a voice assistant, and
edit playlists from your own dashboard.

[![Release](https://img.shields.io/github/v/release/PianoDisc/pianodisc_prodigy?style=flat-square)](https://github.com/PianoDisc/pianodisc_prodigy/releases)
[![HACS custom repository](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square)](https://hacs.xyz/)
[![Home Assistant 2026.3+](https://img.shields.io/badge/Home%20Assistant-2026.3%2B-41BDF5?style=flat-square)](https://www.home-assistant.io/)

<!-- SCREENSHOT: hero — the media player card mid-playback -->

## Before you start

You need:

- **Home Assistant 2026.3** (or newer)
- **HACS** — if you don't have it yet, follow the
  [official HACS download guide](https://www.hacs.xyz/docs/use/download/download/)
- Your **Prodigy II powered on** and connected to the same network as Home Assistant
- PianoDisc **audio engine firmware 0.5.0** (or newer) and **MIDI engine firmware 1.4.0**
  (or newer). These are currently in beta testing and not yet officially released —
  contact [PianoDisc support](https://pianodisc.com/support/) about availability.

That's all. **MQTT is optional** — the integration works without it, and you can
[add it later](docs/mqtt.md) for instant updates and the keys-active sensor.

## Install

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=PianoDisc&repository=pianodisc_prodigy&category=integration)

Click the badge above, then **Download**. Restart Home Assistant when HACS asks you to.

<details>
<summary>Adding the repository by hand instead</summary>

1. Open **HACS** from the Home Assistant sidebar.
2. Open the three-dot menu in the top-right corner and select **Custom repositories**.
3. Paste `https://github.com/PianoDisc/pianodisc_prodigy` as the repository.
4. Choose **Integration** as the type, then click **Add**.
5. Search HACS for **PianoDisc Prodigy II**, open it, and click **Download**.
6. Restart Home Assistant.

</details>

## Connect your piano

### First, check whether it found itself

Go to **Settings → Devices & services**. If Home Assistant already spotted the piano on
your network, a **PianoDisc Prodigy II discovered** card is waiting there — click
**Configure** and you're done.

<!-- SCREENSHOT: the discovered card on the Devices & services page -->

### Otherwise, add it by IP address

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=pianodisc_prodigy)

1. Click the badge above (or go to **Settings → Devices & services → Add integration**
   and search for **PianoDisc Prodigy II**).
2. Enter the piano's IP address.
3. Optionally give it a name — this becomes the device name in Home Assistant.
4. Click **Submit**.

Home Assistant contacts the piano to confirm it's really a Prodigy II, then creates the
device and its entities.

#### Finding your piano's IP address

The piano's IP address is shown in two places:

- **On the Prodigy II's LCD screen** — navigate to **Info → IP Address**.
- **In the PianoDisc Calibrate App** — tap the Wi-Fi icon in the upper-right corner. It
  scans your network and lists every Prodigy II it finds, with their IP addresses.

If the address reads `192.168.4.1`, the piano's Wi-Fi isn't configured yet — set that up
first. See the [Prodigy II Guide](https://pianodisc.com/support/prodigy2-guide/).

## What you get

One **PianoDisc Prodigy II** device with these controls:

| Control | What it does |
|---|---|
| **Piano** (media player) | Play, pause, stop, skip, volume, and browse the SD-card library |
| **Playlist** | Pick a playlist and start it immediately |
| **Busy** | On while the player system is playing the piano — [needs MQTT](docs/mqtt.md) |
| **Show Control** | Optional MSC cue channels and FIRE events from MSC-enabled MIDI files — [needs MQTT](docs/mqtt.md) |
| **Library** | How many songs are on the SD card, and whether a scan is running |
| **Status** | Whether the piano has finished starting up and is safe to play |
| **Stop playback** | A dedicated Stop button for dashboards where Home Assistant hides the media-player Stop control |
| **Refresh library** | Re-scan the SD card after you add or remove songs |
| **Reboot** | Restart the piano |
| **Power** | Direct control of a linked, dedicated smart plug or outlet |
| **AutoPlay** | Enable the automatic playlist after startup |
| **AutoPlay playlist** | Select the playlist AutoPlay uses |
| **AutoPlay playback order** | Use the playlist default, sequence, or shuffle order |
| **AutoPlay loop** | Repeat the AutoPlay playlist continuously |
| **Audio firmware** / **MIDI firmware** | Shows whether newer firmware is available |

## Recommended dashboard

Use the media-player card's **Browse media** action to browse the per-piano SD-card library
and playlists. Home Assistant's native browser keeps this tied to the selected piano and
supports the integration's cached song search.

Selecting a song from Browse Media or search plays that one song and then stops by
default. Set repeat to `all` or `one` before selecting it when you want playback to
continue or loop.

Home Assistant's compact media controls may show Play/Pause without a visible Stop
button. Add the **Stop playback** button entity next to the media player if you want
Stop available directly on the dashboard.

For playlist editing, add the built-in **PianoDisc Playlists** custom card to any dashboard.
When you have more than one piano, set `entity` to the media player for the piano this card
should edit:

```yaml
type: custom:pianodisc-playlist-card
entity: media_player.living_room_piano
```

For a searchable song launcher, add the **PianoDisc Library** custom card:

```yaml
type: custom:pianodisc-library-card
entity: media_player.living_room_piano
```

After installing or upgrading the integration, reload the browser page before adding these
cards from the card picker.

Add the four **AutoPlay** entities to an Entities card alongside it. They are ordinary
configuration entities, so they can also be used directly in automations and voice control.

For what each entity reports and when it's unavailable, see the
[entity reference](docs/entities.md).

## Play a song from an automation

The `pianodisc_prodigy.play_song` action plays a song by name, so your automation keeps
working when the SD card contents change:

```yaml
action: pianodisc_prodigy.play_song
target:
  entity_id: media_player.piano
data:
  song: Clair de Lune
  volume: 55
  restore_volume_after: true
```

`volume` and `restore_volume_after` are optional. By default, the piano stops after the
requested song. Set `continue_after: true` to continue through the SD-card library after
that song. With `restore_volume_after: true` the
piano returns to its previous volume once the song has started, which is useful when one
automation plays quietly and you don't want that to become the new normal.

More examples — morning routine, evening wind-down, lighting, quiet hours — are in
[automation examples](docs/automations.md).

For advanced automations and support diagnostics,
`pianodisc_prodigy.get_debug_info` returns the piano's live `debugJson` payload through
`response_variable`. See [automation examples](docs/automations.md#get-debug-json).

## Optional extras

### Add MQTT for instant updates

With MQTT, playback state updates the moment it changes instead of on the next poll, the
piano is discovered automatically, and the **Busy** sensor works. If you already
run an MQTT broker this takes a few minutes.

**→ [Adding MQTT](docs/mqtt.md)**

### Link a power outlet

If your piano is plugged into a smart plug, open the integration, click **Configure**, and
pick the switch. The integration creates a separate **Power** switch on the piano device.
It directly controls the linked outlet and remains usable while the piano is off, starting,
warming up, synchronising its library, or disconnected from MQTT and HTTP.

The media player's power button uses that same outlet. If a ready piano is actively playing,
Home Assistant first asks it to stop, then cuts power. During startup or a connection loss it
cuts the outlet immediately instead of waiting for the piano to answer. Turning the outlet on
starts the piano; reconnection, readiness, library sync, and any configured AutoPlay happen in
the background.

`off` means the linked outlet reports that power is cut. `unavailable` means Home Assistant
cannot determine the linked outlet's state, or the piano itself is not ready for playback; it
does not prevent the separate **Power** switch from controlling a known outlet.

> **Only link an outlet that powers the piano alone.** Turning the piano off cuts power to
> whatever you select here.

## Songs and playlists

All music lives on the SD card in the piano. How you name and organise those files affects
how well they play and how they appear in Home Assistant.

**→ [SD card, MIDI files and playlists](docs/sd-card.md)**

## Known limitations

- **"Busy" needs MQTT.** Without a broker the sensor stays unknown, because the
  piano reports it over MQTT only.
- **Firmware entities are read-only.** They tell you when a newer firmware is available;
  installing it is done with the PianoDisc Calibrate App, which your installer or dealer
  normally handles.
- **Voice control is better at starting than stopping.** A playing piano is loud and sits
  in the same room as your microphone, so *"stop the piano"* is often misheard. Always
  keep another way to stop it within reach — see
  [voice control](docs/automations.md#voice-control).

## Troubleshooting

Start with the [troubleshooting guide](docs/troubleshooting.md), which covers the piano
not being found, entities showing as unavailable, missing songs, and how to collect
diagnostics.

## Getting help

- **Something wrong with this integration?**
  [Open an issue](https://github.com/PianoDisc/pianodisc_prodigy/issues) and attach the
  diagnostics file (**Settings → Devices & services → PianoDisc Prodigy II → Download
  diagnostics**).
- **Question about the piano itself — firmware, the SD card, the apps?**
  Start with your installer or dealer, who knows your particular setup. Otherwise see the
  [Prodigy II Guide](https://pianodisc.com/support/prodigy2-guide/) or contact PianoDisc
  technical support at [tech@pianodisc.com](mailto:tech@pianodisc.com) or
  (866) 566-3472.

## Manual installation

HACS is the supported way to install. To install by hand for development, copy
`custom_components/pianodisc_prodigy` into your Home Assistant configuration directory:

```bash
cp -r custom_components/pianodisc_prodigy /config/custom_components/
```

Then restart Home Assistant.

## Removing the integration

Go to **Settings → Devices & services → PianoDisc Prodigy II**, open the three-dot menu on
the integration entry, and select **Delete**. This removes the device and its entities.

To remove the files as well, open HACS, find **PianoDisc Prodigy II**, and choose
**Remove**.

Nothing is changed on the piano itself — its SD card, playlists and settings are left
exactly as they are.
