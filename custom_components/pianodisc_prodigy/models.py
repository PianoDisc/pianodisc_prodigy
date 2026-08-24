"""Typed state model shared between transports, the coordinator, and entities.

The coordinator is the single source of truth. Transports only ever produce a
``ProdigyData`` (via snapshot or push); entities only ever read ``coordinator.data``.
Adding or swapping a transport never touches entity code.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from homeassistant.components.media_player import MediaPlayerState


@dataclass(slots=True)
class ProdigyData:
    """A point-in-time snapshot of the piano's observable state."""

    # Availability is tracked separately from playback state so the watchdog /
    # transport can mark the device unreachable (e.g. external power loss) without
    # inventing a playback state.
    available: bool = False
    readiness: str = "unknown"

    # Playback
    state: MediaPlayerState | None = None
    song: str | None = None  # raw device title; entities blank it when idle
    song_index: int | None = None  # position in the cached song list (best-effort)
    song_count: int | None = None  # total songs (best-effort)
    media_position: float | None = None  # elapsed seconds in current song
    media_duration: float | None = None  # total seconds in current song
    media_position_updated_at: datetime | None = None
    volume: int | None = None  # device scale 1..100 (None = unknown)
    shuffle: bool | None = None
    queue_mode: str | None = None
    repeat_mode: int | None = None
    playlist_repeat: int | None = None
    autoplay_loop: bool | None = None
    busy: bool | None = None  # solenoids actively striking (MQTT only)

    # Source / library
    source: str | None = None  # current playlist (tracked locally)
    source_list: list[str] = field(default_factory=list)

    # Device metadata
    device_name: str | None = None
    firmware_audio: str | None = None
    firmware_midi: str | None = None
    # Latest available firmware from the device's backend check (CR#3 ②, MQTT
    # .../update). None until the device has reported; the update entity then
    # falls back to a maintained constant.
    latest_audio: str | None = None
    latest_midi: str | None = None

    def merge(self, **changes: object) -> ProdigyData:
        """Return a copy with the given fields overridden (push deltas)."""
        return replace(self, **changes)  # type: ignore[arg-type]
