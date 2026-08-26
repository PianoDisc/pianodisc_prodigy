# Entity reference

The integration creates one **PianoDisc Prodigy II** device. Everything below belongs to
it.

Entity IDs vary — Home Assistant builds them from the name you gave the piano and the area
it's in. The examples here use `media_player.piano`; substitute your own.

## Piano (media player)

The main control surface. Shows what's playing, how far through it is, and the volume.

**Supports:** play, pause, stop, next track, previous track, volume set, volume up/down,
mute, shuffle, and browsing the SD-card library.

Power on/off appears only when you've [linked a power outlet](../README.md#link-a-power-outlet).

### States

| State | Meaning |
|---|---|
| Playing | A song is playing |
| Paused | Playback is paused, or was stopped part-way |
| Idle | Connected, nothing playing |
| Off | Powered down through a linked outlet |
| Unavailable | Powered off, unreachable, or still starting up |

While the piano is starting up, the now-playing line reads **Getting ready…**. Between
songs, or just after you start one, it can briefly read **Loading…** until the piano
reports the new title.

### Browsing the library

The media browser shows **All songs** and **Playlists**, both read from the piano's SD
card. Selecting a song plays it immediately.

> Songs chosen this way are referenced by their position in the library. If you later add
> or remove songs on the SD card, a saved reference may play a different song. For
> anything you're keeping — a dashboard button, an automation — use the `play_song` action
> and name the song instead. See [automation examples](automations.md).

### Attributes

While playing, the media player also reports `track_index` and `track_total` — the song's
position within the current list and how many songs it holds.

## Playlist (select)

Lists the playlists on the SD card. Choosing one starts it playing right away.

Unavailable when the piano hasn't reported any playlists — either because it's offline, or
because there are none yet. Create playlists from the **Piano Playlists** sidebar panel;
see [SD card, MIDI files and playlists](sd-card.md).

## Keys active (binary sensor)

On while the player system is playing — that is, while the piano is driving its own keys.

The piano reports this straight from its SD player, so it changes the moment playback
starts or stops. That makes it the most immediate signal the integration receives, and
it's what lets Home Assistant show the piano as playing without waiting for the next
status update.

**Requires MQTT.** Without a broker it reports unknown, because the piano publishes this
over MQTT only. See [Adding MQTT](mqtt.md).

The integration holds it on for about 10 seconds after playback stops, so short gaps
between songs don't make it flicker.

> **This is not a key sensor.** It reports that the player system is actuating the keys.
> It does not detect a person playing the piano by hand.

It turns on for anything that drives the keys, including music played from the iQ App —
though in that case Home Assistant knows only that the keys are moving, not what's
playing. See [the piano is playing but Home Assistant shows no song](troubleshooting.md#the-piano-is-playing-but-home-assistant-shows-no-song).

## Library (sensor)

How many songs Home Assistant has found on the SD card, with a `scanning` attribute that
is `true` while a scan is running.

This reflects Home Assistant's cached list, not the piano's current state, so it stays
available even when the piano is powered off — it's telling you what was last read.

A scan runs automatically when the piano finishes starting up, and whenever you press
**Refresh library**. A full scan of a large card takes around 30 seconds; the count climbs
as it goes.

*Diagnostic entity — hidden from dashboards by default.*

## Readiness (sensor)

Whether the piano has finished its startup work and is safe to play.

A player piano isn't ready the instant it appears on the network — it prepares its MIDI
and playback systems first. Waiting for this to read `READY` before triggering playback is
the reliable way to automate a piano that gets powered on and off.

Common values are `READY` (safe to play), `WARMING_UP` (still starting), `OFFLINE`, and
`NO_SD` (no SD card detected).

*Diagnostic entity — hidden from dashboards by default.*

## Refresh library (button)

Re-scans the SD card. Press it after adding or removing songs.

The scan runs in the background and posts a notification that tracks its progress, so you
can carry on using Home Assistant while it works.

*Configuration entity.*

## Reboot (button)

Restarts the piano. Playback stops.

*Diagnostic entity — hidden from dashboards by default.*

## Audio firmware / MIDI firmware (update)

The Prodigy II runs two separate firmwares that are versioned independently. Each entity
shows the installed version and whether a newer one is available.

These are **read-only indicators**. Installing firmware is done with the PianoDisc
Calibrate App, not from Home Assistant. Calibrate is a technician and installer tool —
if an update is available, your installer or dealer is the right person to ask.

The Prodigy II runs its two engines as a matched pair, so both are normally updated
together. After an update you can confirm the versions on the piano's LCD screen under
**Info → Version**.

Both stay available when the piano is offline, since they report the last known versions
rather than live state.

## Piano Playlists (sidebar panel)

Not an entity — a page in the Home Assistant sidebar for creating and editing the piano's
playlists. See [SD card, MIDI files and playlists](sd-card.md).

## Actions

### `pianodisc_prodigy.play_song`

Plays a song by name.

| Field | Required | Description |
|---|---|---|
| `song` | Yes | Name of the song. Matched against the library — an exact match wins, otherwise the first song containing this text |
| `volume` | No | Volume 0–100 to set before playing |
| `restore_volume_after` | No | Return to the previous volume once the song starts. Default `false` |

Raises an error if no song matches, so a failing automation is visible in the logs rather
than silently doing nothing.

### Standard media player actions

These work as usual: `media_play`, `media_pause`, `media_stop`, `media_next_track`,
`media_previous_track`, `volume_set`, `volume_up`, `volume_down`, `volume_mute`,
`shuffle_set`, `play_media` and `browse_media`.

`turn_on` and `turn_off` work only when you've
[linked a power outlet](../README.md#link-a-power-outlet).

These are **not** supported, because the piano has no equivalent: `repeat_set`,
`select_source`, `media_seek`, `clear_playlist`, and the `join` / `unjoin` grouping
actions.

## When entities are unavailable

A piano is not a device that stays on. **Unavailable usually means "powered off", not
"broken"** — that's expected and not an error.

The exceptions are the entities that deliberately stay available because they report
cached information rather than live state: **Library**, **Readiness**, **Audio firmware**
and **MIDI firmware**.
