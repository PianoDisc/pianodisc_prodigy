# Troubleshooting

## Start here: download diagnostics

If you're reporting a problem, this is the single most useful thing to attach.

**Settings → Devices & services → PianoDisc Prodigy II → ⋮ → Download diagnostics**

It captures how the integration is connected, what the piano last reported, and the state
of the library. Personal details such as your piano's identifier and network address are
removed automatically.

## The integration doesn't appear after installing

Restart Home Assistant. HACS downloads the files, but Home Assistant only loads new
integrations at startup.

If it's still missing, clear your browser cache, then confirm the files landed in
`/config/custom_components/pianodisc_prodigy`.

## Home Assistant can't reach the piano

The setup screen says it couldn't connect, or the entities show as unavailable.

- **Is the piano powered on?** Unavailable almost always means the piano is switched off.
  This is normal and not an error.
- **Is it on the same network as Home Assistant?** A guest or IoT network that's isolated
  from your main network will block it.
- **Is the IP address still correct?** Routers reassign addresses. If your piano's address
  changed, open the integration, choose **Reconfigure**, and enter the new one. Giving the
  piano a fixed address in your router avoids this for good.
- **Can you open it in a browser?** Visit `http://<piano-ip-address>` from the same
  network. If that doesn't load, the problem is between your network and the piano, not in
  Home Assistant.
- **Does the piano's address read `192.168.4.1`?** That means its Wi-Fi isn't configured
  and it's serving its own setup network. Connect it to your Wi-Fi first — see the
  [Prodigy II Guide](https://pianodisc.com/support/prodigy2-guide/).

## Setup says a piano is "already in progress"

Home Assistant already found this piano and has a setup waiting. Go back to
**Settings → Devices & services** and use the **PianoDisc Prodigy II discovered** card
instead of adding it again by hand.

## Setup says it's a different piano

You'll see this when reconfiguring, if the address you entered answers but belongs to
another instrument. Home Assistant checks this deliberately so a typo can't silently
repoint your entry at a different piano. Check the address and try again.

## The piano was discovered but has no IP address

A piano found over MQTT arrives without one. Everything works on current firmware, but if
the song library, playlists or firmware versions are missing, add its address: open the
integration, choose **Reconfigure**, and enter the piano's IP.

## MQTT discovery doesn't happen

- Confirm the MQTT integration is set up in Home Assistant and the broker is running.
- Check the broker's log for authentication failures — a wrong password for the piano
  shows up there.
- Confirm the broker address entered on the piano is the **Home Assistant server's**
  address, not the piano's own.
- Restart the piano so it announces itself again.

See [Adding MQTT](mqtt.md).

## Keys active never changes

This sensor needs MQTT. Without a broker the piano has no way to report it and the sensor
stays unknown. See [Adding MQTT](mqtt.md).

If it's connected but never turns on while you play the piano **by hand**, that's expected
— it reports the player system driving the keys, not a person playing them. It should turn
on when you start a song.

## Voice commands don't stop the piano

This is usually the room, not the integration. A piano playing at volume drowns out speech
from the point of view of a microphone sitting in the same space, so the assistant either
misses the wake word or mishears the command. Starting a song works because the room is
quiet when you ask; stopping one is much harder.

Lowering the volume first often helps, but the reliable fix is to keep a non-voice control
available — a dashboard button, a wall tablet, or the piano's own controls. Reach for the
iQ App only if you mean to take the piano over: it won't stop something Home Assistant
started, though connecting MIDI from it does send an off event that halts auto-play. See
[voice control](automations.md#voice-control).

## The piano is playing but Home Assistant shows no song

Usually this means the music was started from the **iQ App**. Home Assistant sees the keys
moving — **Keys active** turns on and the piano shows as playing — but it gets no title,
duration or position, so the now-playing line stays empty.

Nothing is broken. Home Assistant tracks what the piano plays from its own SD card; music
the iQ App is playing doesn't come with that information.

To get full now-playing details, start the music from Home Assistant, the piano's own
controls, or auto-play instead.

## Songs are missing from the library

- Press **Refresh library** and watch the **Library** sensor count climb. A large card
  takes around 30 seconds.
- Confirm they're `.mid` files.
- Folders work, but deeply nested ones are unreliable — the root of the card is safest.
- Check `index.txt` on the card. The piano regenerates it on every scan, and it lists every
  song it recognised, so anything missing from that file was never detected.
- If the count is stuck at zero, check the **Readiness** sensor. `NO_SD` means the piano
  isn't seeing the card at all.

See [SD card, MIDI files and playlists](sd-card.md).

## A song plays, but the wrong one

Songs picked from the media browser are saved by their **position** in the library, so
adding or removing songs on the card shifts what a saved reference points at.

Change the automation to use the `play_song` action with the song's name — see
[automation examples](automations.md).

## Song names look wrong

Names with apostrophes, punctuation or unusual characters can be rewritten by the card's
file system — `Heidi's Song.mid` may appear as `HEIDI~1`. Home Assistant shows the name
the piano reports. Renaming the file on the card using plain letters, numbers and spaces
fixes it; press **Refresh library** afterwards.

## The playlist control is unavailable

It has no playlists to offer. Either the piano is offline, or no playlists exist yet.
Create one in the **Piano Playlists** sidebar panel.

## Playback state looks stale

Without MQTT, Home Assistant checks the piano every 30 seconds, so a song started on the
piano itself can take that long to show up. [Adding MQTT](mqtt.md) makes state changes
immediate.

## The piano won't turn on from Home Assistant

Power control requires a [linked outlet](../README.md#link-a-power-outlet). If Home
Assistant switches the outlet on but the piano never comes online, a repair notice
appears. Check that the linked switch really powers this piano, and that the piano
reconnects to your network after a power cycle.

## Reading the logs

**Settings → System → Logs**, then filter for `pianodisc`.

For more detail, add this to `configuration.yaml` and restart:

```yaml
logger:
  default: warning
  logs:
    custom_components.pianodisc_prodigy: debug
```

Remember to remove it afterwards — debug logging is noisy.

## Still stuck?

- **Problems with this integration:**
  [open an issue](https://github.com/PianoDisc/pianodisc_prodigy/issues) and attach your
  diagnostics file.
- **Questions about the piano itself — firmware, the SD card, the apps:**
  start with your installer or dealer, who knows your setup. Otherwise see the
  [Prodigy II Guide](https://pianodisc.com/support/prodigy2-guide/), or contact PianoDisc
  technical support at [tech@pianodisc.com](mailto:tech@pianodisc.com) or (866) 566-3472.
