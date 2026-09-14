# Changelog

## Unreleased (0.1.6)

- Adds the **PianoDisc MSC cue** blueprint with an import button: one automation per
  show-control channel, with On, Off, and flash-length inputs.
- Show control: one cue event per channel carrying GO, STOP, and FIRE, plus a channel
  binary sensor.
- Groups the AutoPlay settings on a sub-device; adds a **Refresh device info** button.
- Fixes an unload crash that left every entity unavailable after a reload.
- Previous track restarts the current song when more than 3 s in.
- `play_song` with `restore_volume_after` now puts the volume back when the song ends
  instead of immediately after the play command.
- A play command sent while the piano is off waits for the piano to become ready
  before playing.
- MQTT discovery accepts any readiness word, so a piano on the broker is offered as a
  discovered device.
- Status sensor: adds **Fault** (SD-card scan failed); options are lowercase and
  words no firmware sends are gone.
- Blueprint: **Fade in** and **Fade out** inputs (seconds, default 0) so GO and STOP
  ramp lights and scenes that support transitions; FIRE stays a hard flash.
- The **Stop** button works while the piano is starting up: a press before the piano
  reports ready is held and sent the moment it is.
- Single Play switch is always available, so automations can set it while the piano
  is off.
- Declares `http` and `frontend` as dependencies; default album art is the PianoDisc
  wordmark.

## v0.1.5 - 2026-09-07

- Adds **Single Play** (default on): a directly chosen song plays and then stops;
  `play_song` accepts `continue_after` to keep going through the library.
- Adds a dedicated **Stop** button and stop logic for dashboards that hide the
  media-player Stop control.
- Adds the `get_debug_info` action, which returns the piano's live debug payload for
  automations, and more device information on the device page.
- Cards no longer register themselves through Lovelace resource storage and are
  removed cleanly on uninstall; fixes the card editor going blank and the compact
  playlist card title.
- Both custom cards now show in HTTP-only mode.
- Reads the device ID from the piano over HTTP instead of the network MAC.

## v0.1.4 - 2026-09-02

- Adds MIDI Show Control (MSC) channels and FIRE events for MIDI files authored with
  the PianoDisc MSC Cue Editor.
- Replaces the three sidebar panels: the library is browsed through the media
  player, AutoPlay is a set of device entities, and playlists are a custom
  **Piano Playlist** dashboard card. A **Piano Library** card is added as well, with
  search and a visual editor.
- Raises the minimum Home Assistant version.

## v0.1.3 - 2026-08-27

- Adds startup readiness and initial library-sync states, so controls wait until the
  piano and its SD-card library are safe to use.
- Adds cached library and playlist loading, a searchable **Piano Library** sidebar,
  and shared manual refresh for songs and playlists.
- Adds the **Piano AutoPlay** workspace and models the piano's all-songs, playlist,
  shuffle, and repeat behaviors in Home Assistant.
- Adds safer, faster path-based song selection and improved media metadata.
- Adds optional independent smart-outlet power control, device IP display, native
  diagnostics download, and device-card firmware-version updates.
- Makes MQTT the preferred live transport while retaining HTTP fallback.
