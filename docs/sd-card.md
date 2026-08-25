# SD card, MIDI files and playlists

Everything the piano can play lives on the SD card inside it. This page covers what to put
there and how playlists work.

For the full detail, see the *PianoDisc Prodigy II User's Guide* — Appendix D covers
sourcing MIDI files and Appendix E covers playlists and indexing. You can find it on the
[Prodigy II Guide](https://pianodisc.com/support/prodigy2-guide/) page.

## Choosing MIDI files

The Prodigy II drives real hammers on a real piano, so it plays piano MIDI files well and
general-purpose ones badly. Files that work best are:

- **written for piano** — not multi-instrument arrangements
- **single track, single channel, single tempo**
- **notes and pedal only** — the piano responds to note, pedal and MIDI Show Control
  messages and ignores the rest, but a lot of unnecessary data (continuous controllers,
  for instance) can degrade playback
- **stored at the root of the card** — folders do work, but keep them shallow and avoid
  folders inside folders

Files with multiple instruments will still play, but everything gets mapped onto the piano
at once, which rarely sounds like it should.

## Naming files

Keep names simple. Use the song title and nothing else:

| Good | Avoid |
|---|---|
| `Clair de Lune.mid` | `03 - Clair de Lune (Debussy) [Remastered].mid` |
| `Autumn Leaves.mid` | `Autumn_Leaves_ver2_FINAL.mid` |

Track numbers, performer credits and punctuation all end up in the name you see in Home
Assistant, and long or unusual names can be rewritten by the card's FAT32 file system —
`Heidi's Song.mid` can become `HEIDI~1.MID`. Home Assistant shows the name the piano
reports, so a rewritten name is what you'll see in the media browser and what `play_song`
has to match.

Sticking to plain letters, numbers and spaces avoids this entirely.

## After changing the card

The piano rebuilds its own index when the card is inserted. Home Assistant caches the song
list, so after adding or removing songs:

1. Press the **Refresh library** button.
2. Watch the **Library** sensor — its count climbs as the scan runs.

A full scan of a large card takes around 30 seconds.

You may also see a file called `index.txt` on the card. The piano generates and maintains
it automatically. Don't edit or delete it.

## Playlists

A playlist is a named selection of songs with its own play order.

> **These are not the same as iQ App playlists.** SD card playlists live on the card and
> exist so the piano can be driven by automation — Home Assistant, Alexa, or the piano's
> own auto-play. The iQ App's playlists are separate, and made for listening on the spot.
> Home Assistant reads and writes the SD card ones.

The piano creates two to start with: **All Songs**, containing everything on the card in
order, and **Example List**, a demo you can edit or delete.

### Editing them from Home Assistant

Open **Piano Playlists** in the Home Assistant sidebar. This is the easiest way to work
with playlists — the piano has no built-in playlist editor, and editing the file on the
card by hand is easy to get wrong.

<!-- SCREENSHOT: the Piano Playlists panel with a playlist open -->

Each playlist has:

- **Name** — how you'll refer to it in Home Assistant, in the **Playlist** control, and by
  voice
- **Order** — *Sequence* plays in order, *Shuffle* plays at random
- **Repeat** — how many times to repeat; `0` repeats forever
- **Songs** — which songs are included

> Save writes the complete set of playlists back to the piano, replacing what was there.
> Make your changes and save once, rather than saving part-way through.

### Playing a playlist

Three ways:

- Pick it from the **Playlist** control on the piano's device page
- Choose it under **Playlists** in the media browser
- Select it from an automation:

  ```yaml
  action: select.select_option
  target:
    entity_id: select.piano_playlist
  data:
    option: Dinner Music
  ```

### The file behind it

Playlists are stored on the card as `playlists.json`. You don't need to touch this — the
sidebar panel is there so you don't have to — but if you're curious or need to inspect it:

```json
[{
  "name": "My Favorites",
  "sort": "Shuffle",
  "repeat": 0,
  "content": {
    "include": [],
    "exclude": ["/sd/Happy Birthday.mid"]
  }
}]
```

An empty `include` means "every song on the card", which is why `exclude` is useful: it
lets you build "everything except these" without listing your whole library.

## A note on play order

There's no single "correct" order for the library. The piano has its own setting —
*Default* (the order the card holds), *Sequence* (alphabetical), or *Shuffle* — and each
playlist carries its own order as well.

This is why a song's position isn't a dependable way to refer to it, and why the
`play_song` action takes a name. See [automation examples](automations.md).
