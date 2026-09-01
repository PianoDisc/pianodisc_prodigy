# Automation examples

Working examples to copy and adapt. Entity IDs vary by installation — replace
`media_player.piano`, `binary_sensor.piano_keys_active` and the rest with your own.

> Every one of these makes an acoustic piano play out loud. Try new automations at a time
> and volume that suit the room.

## Play a song by name

The dependable way to play a specific song. Because it matches on the name, it keeps
working when the SD card contents change.

```yaml
action: pianodisc_prodigy.play_song
target:
  entity_id: media_player.piano
data:
  song: Clair de Lune
```

Set a volume just for this song and put it back afterwards:

```yaml
action: pianodisc_prodigy.play_song
target:
  entity_id: media_player.piano
data:
  song: Clair de Lune
  volume: 45
  restore_volume_after: true
```

### Why not use the media browser?

Picking a song from the media browser saves its **position** in the library, not its name.
Add or remove a song on the card and that position may point somewhere else. For anything
you're saving — a dashboard button, an automation, a script — name the song.

## Morning music

```yaml
alias: Morning piano
triggers:
  - trigger: time
    at: "08:00:00"
conditions:
  - condition: state
    entity_id: binary_sensor.workday_sensor
    state: "on"
actions:
  - action: select.select_option
    target:
      entity_id: select.piano_playlist
    data:
      option: Morning
mode: single
```

The workday condition comes from Home Assistant's
[Workday integration](https://www.home-assistant.io/integrations/workday/). Leave it out
if you haven't set that up.

## Set the scene while the piano is playing

**Keys active** follows the player system directly, so it turns on the moment a song
starts and off when it ends — a quicker trigger than waiting for the media player's state
to catch up.

```yaml
alias: Piano lighting
triggers:
  - trigger: state
    entity_id: binary_sensor.piano_keys_active
    to: "on"
actions:
  - action: light.turn_on
    target:
      entity_id: light.living_room
    data:
      brightness_pct: 40
      transition: 3
mode: single
```

To bring the lights back up when the piano finishes, add a second automation triggered on
the same entity going `to: "off"`. It waits about 10 seconds after playback stops before
it does, so short gaps between songs won't flicker your lights.

Requires [MQTT](mqtt.md).

## MIDI Show Control cues

MSC-enabled MIDI files can trigger automations without YAML on the piano itself. Cue N is
channel N. A `GO` cue turns a channel on, a `STOP` cue turns it off, and a `FIRE` cue
triggers the matching event entity.

```yaml
alias: Cue 1 lights
triggers:
  - trigger: state
    entity_id: binary_sensor.piano_show_control_msc_channel_1
    to: "on"
actions:
  - action: light.turn_on
    target:
      entity_id: light.stage
```

```yaml
alias: Cue 2 fog
triggers:
  - trigger: state
    entity_id: event.piano_show_control_msc_channel_2_fire
actions:
  - action: scene.turn_on
    target:
      entity_id: scene.fog
```

For every valid cue, including channels outside your configured range, Home Assistant
also fires the `pianodisc_prodigy_msc` bus event:

```yaml
triggers:
  - trigger: event
    event_type: pianodisc_prodigy_msc
    event_data:
      command: FIRE
      cue: "042"
```

Its `device_id` is the PianoDisc MAC-derived ID, not Home Assistant's device registry ID.

## Wait until the piano is ready before playing

A piano that's been powered off isn't ready the moment it appears on the network. If your
automation switches it on first, wait for it:

```yaml
alias: Evening piano
triggers:
  - trigger: time
    at: "18:30:00"
actions:
  - action: media_player.turn_on
    target:
      entity_id: media_player.piano
  - wait_for_trigger:
      - trigger: state
        entity_id: sensor.piano_readiness
        to: "READY"
    timeout: "00:02:00"
    continue_on_timeout: false
  - action: pianodisc_prodigy.play_song
    target:
      entity_id: media_player.piano
    data:
      song: Autumn Leaves
      volume: 40
mode: single
```

`media_player.turn_on` needs a [linked power outlet](../README.md#link-a-power-outlet).
Without one, drop that step and keep the wait.

## Stop at bedtime

```yaml
alias: Piano quiet hours
triggers:
  - trigger: time
    at: "22:00:00"
actions:
  - action: media_player.media_stop
    target:
      entity_id: media_player.piano
mode: single
```

## Don't start during quiet hours

Add this condition to any automation that plays:

```yaml
conditions:
  - condition: time
    after: "09:00:00"
    before: "21:00:00"
```

## Turn on shuffle

Shuffle is a playback setting on the piano:

```yaml
action: media_player.shuffle_set
target:
  entity_id: media_player.piano
data:
  shuffle: true
```

## Play a song for an occasion

The classic use for `volume` and `restore_volume_after` together: something that should be
louder than usual for a moment, without leaving the piano set that way afterwards.

A script fits this better than an automation, since you'll want to trigger it yourself
when the cake arrives:

```yaml
script:
  happy_birthday:
    alias: Happy Birthday on the piano
    sequence:
      - action: pianodisc_prodigy.play_song
        target:
          entity_id: media_player.piano
        data:
          song: Happy Birthday
          volume: 75
          restore_volume_after: true
```

It plays loudly enough to carry over a room full of people, then the volume goes back to
normal so the next thing that plays isn't at party level.

The same pattern works in reverse for a quieter moment:

```yaml
alias: Evening wind-down
triggers:
  - trigger: time
    at: "21:00:00"
conditions:
  - condition: state
    entity_id: media_player.piano
    state: idle
actions:
  - action: pianodisc_prodigy.play_song
    target:
      entity_id: media_player.piano
    data:
      song: Clair de Lune
      volume: 30
      restore_volume_after: true
mode: single
```

Both start a song from the beginning. A player piano can't play over itself, so if
something is already playing it will be replaced rather than resumed afterwards — which
is why the scheduled example checks that the piano is `idle` first, and why the birthday
script doesn't (there, interrupting is the point).

## Voice control

The media player works with Assist and other voice assistants once exposed under
**Settings → Voice assistants → Expose**. Naming the piano something a person would
actually say — "the piano" rather than "Prodigy II living room" — makes commands like
*"play the piano"* work naturally.

To make a specific song available by voice, build a script around `play_song` and expose
the script.

### Starting by voice works better than stopping

Worth knowing before you rely on it: **an acoustic piano is loud, and it is in the same
room as your microphone.**

Starting a song by voice is easy, because the room is quiet when you ask. Stopping or
pausing one is a different matter — the piano is playing while you speak, and a voice
assistant has to pick your wake word and command out of a live instrument a few feet away.
Expect it to mishear you, or miss you entirely. The louder the volume, the worse it gets.

So treat voice as a convenient way to *start* the piano, and make sure there is always
another way to stop it:

- a dashboard button or a wall tablet within reach
- the controls on the piano itself

This matters most in a showroom, lobby or other unattended installation, where the person
who wants the music to stop may not be the person who started it. Don't build a setup
whose only stop control is a voice command that has to compete with the piano.

> **The iQ App is not your stop button.** It controls its own playback and doesn't reach
> the automation path, so it won't stop a song Home Assistant or auto-play started. The
> one exception: opening the iQ App and connecting MIDI sends an off event, which stops
> auto-play and hands control to the app. That's a way to take over the piano, not a
> general-purpose stop.
>
> Music playing from the iQ App does turn **Keys active** on, so automations that react to
> the piano playing will still fire — but Home Assistant won't know the song title.
