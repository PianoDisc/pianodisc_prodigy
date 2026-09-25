# PianoDisc Prodigy II for Home Assistant

![Status: Beta](https://img.shields.io/badge/status-BETA-orange?style=for-the-badge)

## Beta

> **This integration is in beta.** It's ready to try, and it's still changing.
>
> - **It needs beta firmware.** The Prodigy II firmware this integration depends on is in
>   beta testing. To test it, email [tech@pianodisc.com](mailto:tech@pianodisc.com) and
>   ask to be added to the beta list, then follow
>   [Update the piano's firmware](#update-the-pianos-firmware).
> - **Expect some changes before 1.0.** Entity names and behaviour can still change
>   between releases, so an update may occasionally mean adjusting an automation. The
>   [changelog](CHANGELOG.md) lists what changed in each release.
> - **Report problems here.** For anything wrong with the integration, open a
>   [GitHub issue](https://github.com/PianoDisc/pianodisc_prodigy/issues) (see
>   [Getting help](#getting-help)).

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
  (or newer). These are beta releases — see
  [Update the piano's firmware](#update-the-pianos-firmware) for how to get and install
  them.

That's all. **MQTT is optional** — the integration works without it, and you can
[add it later](docs/mqtt.md) for instant updates and the keys-active sensor.

## Update the piano's firmware

The Prodigy II has two processors, the **audio engine** and the **MIDI engine**, and each
has its own firmware. Update both, **audio engine first**.

**Getting the firmware.** The firmware this integration needs is in beta testing and isn't
published here. If you'd like to test it, email
[tech@pianodisc.com](mailto:tech@pianodisc.com) and ask to be added to the beta list.
You'll receive two files:

| File | Engine | How it's installed |
|---|---|---|
| `sd5-audio-MMDDYY-VVV.bin` | Audio engine | Uploaded from a web browser |
| `sd5-midi-MMDDYY-VVV.zip` | MIDI engine | Unzipped onto a microSD card |

The two files are different; don't swap them.

**Before you start:**

- Note the piano's IP address (see
  [Finding your piano's IP address](#finding-your-pianos-ip-address)).
- Keep the piano powered for the whole update. If you've linked a power outlet or have
  automations that turn the piano off or reboot it, pause them until you're done.
- Between the two updates, the piano's screen may show **Version Mismatch** or stay on
  **Initializing**, and Home Assistant may show the piano as unavailable or warming up.
  That's expected — carry on with the second update.

### 1. Audio engine: upload it from a web browser

You need a computer on the same network as the piano.

1. Open a web browser (Chrome or Edge work best) and go to `http://` followed by the
   piano's IP address, for example `http://192.168.1.50`. A "Not secure" warning is normal
   for a device on your own network.
2. In the blue toolbar at the top of the page, select **Updates**.
3. Under **Local Firmware Upload**, click **Choose File** and pick the `sd5-audio-….bin`
   file.
4. Click **Upload!**. An **Upgrade Progress** window shows how it's going. Don't refresh
   the page or turn the piano off while it runs.
5. When it says **Success!**, click **Close**, then press the piano's **Reset** button or
   turn it off and on.
6. Reload the page. The button at the bottom should read **Reboot**. If it reads
   **Exit Recovery**, click it to start the piano normally.

If the progress stops changing for several minutes, wait three minutes, turn the piano
off and on, and try again. If the upload keeps failing, press **Recovery** on that page
first and wait until **Exit Recovery** shows at the bottom, then upload. The piano can
get a different IP address in recovery mode; check **Info → IP Address** on its screen.

### 2. MIDI engine: copy it to a microSD card

You need a computer that can write to a microSD card.

1. Unzip the `sd5-midi-….zip` file. It contains one file, `sd5-midi-update.bin`. Your
   computer may say it doesn't recognise the file type; that's fine.
2. Copy `sd5-midi-update.bin` to the top level of a FAT32-formatted microSD card — not
   into a folder — and don't rename it. The card that holds your songs works.
3. Eject the card safely and put it in the piano's SD card slot.
4. The piano's screen shows **Reading SD Card, Please Wait**, then **Update Available,
   Press Reset**. Press **Reset**, or turn the piano off and on.
5. The screen shows **Upgrading** with a percentage. Don't turn the piano off. When it's
   done, the piano restarts by itself.

### 3. Check the versions

- On the piano's screen, go to **Info → Version**. Both engines should show the new
  versions, with no **Version Mismatch** warning.
- In Home Assistant, the **Audio firmware** and **MIDI firmware** entities show the
  installed versions. If they still show the old ones, press **Refresh device info**.
- If you used the card that holds your songs, you can delete `sd5-midi-update.bin` from it
  now.

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
| **Stop** | A dedicated Stop button that also works while the piano is still starting up, when AutoPlay may already be playing |
| **Refresh library** | Re-scan the SD card after you add or remove songs |
| **Refresh device info** | Re-read the piano's serial number, hardware version, and Wi-Fi signal |
| **Reboot** | Restart the piano |
| **AutoPlay** (sub-device) | **Enabled**, **Playlist**, **Playback order**, and **Loop** for the playlist that starts automatically after power-up |
| **Audio firmware** / **MIDI firmware** | Shows whether newer firmware is available |

## Recommended dashboard

Use the media-player card's **Browse media** action to browse the per-piano SD-card library
and playlists. Home Assistant's native browser keeps this tied to the selected piano and
supports the integration's cached song search.

**Single play** is on by default: selecting a song from Browse Media, search, or the
`play_song` action plays that one song and stops. Turn the switch off to have a song
pick play on through the SD card instead. The switch is always available, so an
automation can set it before it starts a song. While a song is playing, flipping it
changes what happens when that song ends. Changing repeat to `all` or `one` during a
song also turns it off for that song.

Home Assistant's media controls never show a Stop button for the piano: a player that can
pause gets Pause in that spot, in the media player dialog and on every media card. The
player still stops from automations and scripts (`media_player.media_stop`). To stop from
a dashboard, add the **Stop** button entity next to the media player.

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

AutoPlay has its own device under the piano, with an **Enabled** switch and the
**Playlist**, **Playback order**, and **Loop** settings. Add them to an Entities card
alongside the player; they are ordinary entities, so they also work in automations and
voice control.

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
piano returns to its previous volume once the song has finished, which is useful when one
automation plays quietly and you don't want that to become the new normal. If you change
the volume yourself while the song plays, that change is kept.

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
pick the switch. The media player's power button then controls that outlet. If a ready piano
is actively playing, Home Assistant first asks it to stop, then cuts power. During startup or
a connection loss it cuts the outlet immediately instead of waiting for the piano to answer.
Turning the outlet on starts the piano; reconnection, readiness, library sync, and any
configured AutoPlay happen in the background.

A play command sent while the piano is off turns the outlet on and waits for the piano to
become ready before playing. The linked outlet's own switch keeps working as before.

`off` means the linked outlet reports that power is cut. `unavailable` means Home Assistant
cannot determine the linked outlet's state, or the piano itself is not ready for playback.

> **Only link an outlet that powers the piano alone.** Turning the piano off cuts power to
> whatever you select here.

### Show control: lights and effects that follow the music

MIDI files authored with the PianoDisc MSC Cue Editor carry MIDI Show Control cues. The
piano publishes them as they play, and the integration turns them into eight numbered
**channels** on the piano's Show Control device. Each channel has an on/off state
(`GO` turns it on, `STOP` turns it off) and a **cue** event that records every `GO`,
`STOP`, and `FIRE` as it arrives. Channel numbers mean the same thing in every song, so
you tie each channel to a device once and every cue file just works. Needs
[MQTT](docs/mqtt.md).

Use the blueprint to wire a channel without writing YAML:

[![Import the show control blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FPianoDisc%2Fpianodisc_prodigy%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fpianodisc_prodigy%2Fshow_control_channel.yaml)

Then, for each channel you use, **Settings → Automations → Create automation**, pick
**PianoDisc MSC cue**, and fill it in:

1. **Channel** — the channel's cue event, for example *Channel 1 cue*.
2. **On** — the lights, switches, scene, or script this channel turns on.
3. **Off** — optional; something to activate when the channel turns off, such as an
   "off" scene. Leave it empty and the On items are simply turned off; for a scene in
   On, that means the lights and switches the scene contains.
4. **Flash length** — how long a FIRE holds the channel on, default 100 ms.

GO turns On on, STOP turns it off, and FIRE flashes: on, wait, off. A flash while the
channel is already on leaves it on. A cue given a fade in the cue editor ramps lights and
scenes that support transitions over that many seconds (GO up, STOP down); a plain cue
switches at once, and FIRE never fades. Cues reach Home Assistant about a second after
the piano plays them, so use fades of a few seconds for mood changes rather than to hit a
beat.

| Device | On | Off |
|---|---|---|
| A floor lamp | the lamp | *(empty)* |
| A pump or fountain | the pump switch | *(empty)* |
| A DMX fixture, "purple wash" | scene **Purple wash** | *(empty)* or scene **Wash off** |

**Looks that share a fixture.** A "white wash" and a "pink wash" scene usually drive the
same dimmer. The newest look owns the fixture: a STOP only releases what no scene
activated since has claimed. So to change looks without a blink, author the new look's
GO and then the old look's STOP, on the same beat or later; the wash simply becomes pink.
Give the GO a fade and the change dissolves. The old look's STOP still turns off
anything only it used.

For a DMX fixture, make the scene first: set the fixture's dimmer, colour, and effect
entities exactly how you want them, then **Settings → Automations → Scenes → Add scene**
and capture them. A scene is Home Assistant's way of saying "this exact look across
several entities", and the scene editor gives you the colour picker. One scene per look,
one channel per look.

Home Assistant saves the automation under the blueprint's name and keeps it open in the
editor. Open the editor's **⋮** menu and choose **Rename** to add the channel number, for
example "PianoDisc MSC cue 1". For the next channel, either click the back arrow and
**Create automation** again, or choose **Duplicate** from the same menu and change the
channel and the scenes. Editing the fields and saving again changes the automation you
already saved; it does not create a new one. The blueprint runs cues in parallel so a burst of FIRE cues never
delays the GO or STOP behind it, and it ignores restarts so a reload never switches your
lights off.

**Reset between songs.** A fixture left on by a cue stays on until something turns it
off, and with a DMX rig that can spill into the rest of the house. The second blueprint
puts the show back to a known state when a song ends and, optionally, the moment the next
one begins:

[![Import the show reset blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FPianoDisc%2Fpianodisc_prodigy%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fpianodisc_prodigy%2Fshow_reset.yaml)

Create one automation from **PianoDisc show reset** per piano: pick the piano's media
player and an "everything off" scene (or the entities to turn off). The end-of-song reset
waits until the integration is sure the song is over, so a pause or the gap before the
next track never resets anything, while pressing Stop in Home Assistant resets at once.
Turn off **Reset when a song starts** if a song opens with a lighting cue on its very
first beat.

For hand-written automations and the raw bus event, see
[Automations → MIDI Show Control cues](docs/automations.md#midi-show-control-cues).

## Songs and playlists

All music lives on the SD card in the piano. How you name and organise those files affects
how well they play and how they appear in Home Assistant.

**→ [SD card, MIDI files and playlists](docs/sd-card.md)**

## Known limitations

- **"Busy" needs MQTT.** Without a broker the sensor stays unknown, because the
  piano reports it over MQTT only.
- **Firmware entities are read-only.** They tell you when a newer firmware is available;
  you install it on the piano itself — see
  [Update the piano's firmware](#update-the-pianos-firmware).
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
