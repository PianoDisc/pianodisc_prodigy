"""Transport abstraction for the PianoDisc Prodigy II.

A ``Transport`` is the only thing that talks to the piano. The coordinator owns one
transport and feeds entities from it. Two production transports are planned:

* ``MqttTransport`` — push status + command publishes (preferred / ``local_push``)
* ``HttpTransport`` — request/library + transport control + polling fallback

``FakeTransport`` (see ``fake.py``) implements the full contract in memory and is used
by the scaffold and the test suite.

Command methods are fire-and-forget on the wire; the coordinator reconciles observed
state from snapshots/push. Library reads (``async_fetch_song_list`` /
``async_fetch_playlists``) are *prime-then-poll, eventually-consistent*.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..models import ProdigyData

#: A transport invokes this with a fresh full snapshot when it observes a change
#: (used by push transports). The coordinator wires it via ``set_push_listener``.
PushListener = Callable[[ProdigyData], None]

#: A transport invokes this during a library scan with ``(count_so_far, scanning)`` so
#: the UI can show live progress. The coordinator wires it via
#: ``set_library_progress_listener``. Scan progress is coordinator-level state, not part
#: of the device snapshot, so it is a separate channel from ``PushListener`` (a normal
#: status push must never clobber the running scan count).
LibraryProgressListener = Callable[[int, bool], None]

#: A transport invokes this for each MSC cue. This is event-shaped, so it must not
#: travel through ``ProdigyData`` where consecutive cues could be coalesced.
MscListener = Callable[[str, str], None]


class Transport(ABC):
    """Contract every transport implements."""

    def __init__(self) -> None:
        self._push_listener: PushListener | None = None
        self._library_progress: LibraryProgressListener | None = None
        self._msc_listener: MscListener | None = None

    @property
    def uses_push_updates(self) -> bool:
        """True when the transport receives live status without coordinator polling."""
        return False

    @property
    def supports_msc(self) -> bool:
        """True when this transport can receive live MIDI Show Control cues."""
        return False

    @property
    def supports_realtime_events(self) -> bool:
        """True when live piano-originated events are currently observable."""
        return False

    # -- lifecycle ----------------------------------------------------------
    @abstractmethod
    async def async_setup(self) -> None:
        """Open connections / subscriptions. Raise on unrecoverable failure."""

    @abstractmethod
    async def async_close(self) -> None:
        """Tear down connections / subscriptions."""

    @abstractmethod
    async def async_fetch_snapshot(self) -> ProdigyData:
        """Return the current best-effort full state (the coordinator poll path)."""

    async def async_fetch_debug_json(self) -> dict[str, Any] | None:
        """Collect an on-demand raw piano diagnostic snapshot, when supported.

        This is deliberately not part of regular polling. Home Assistant calls it
        only while the user explicitly downloads diagnostics.
        """
        return None

    # -- push (push transports override; pollers leave the default no-op) ----
    def set_push_listener(self, listener: PushListener) -> None:
        """Register the coordinator callback for out-of-band state changes."""
        self._push_listener = listener

    def _emit(self, data: ProdigyData) -> None:
        if self._push_listener is not None:
            self._push_listener(data)

    # -- library scan progress (optional; scanners emit, composed transports forward) --
    def set_library_progress_listener(self, listener: LibraryProgressListener) -> None:
        """Register the coordinator callback for live library-scan progress.

        A composing transport (e.g. MQTT wrapping HTTP) overrides this to forward the
        listener to the transport that actually runs the scan.
        """
        self._library_progress = listener

    def _emit_library_progress(self, count: int, scanning: bool) -> None:
        if self._library_progress is not None:
            self._library_progress(count, scanning)

    def set_msc_listener(self, listener: MscListener) -> None:
        """Register the coordinator callback for individual MSC cue messages."""
        self._msc_listener = listener

    def _emit_msc(self, command: str, cue: str) -> None:
        if self._msc_listener is not None:
            self._msc_listener(command, cue)

    def invalidate(self) -> None:  # noqa: B027 - optional hook, default is a no-op
        """Drop cached liveness so the next snapshot re-seeds (after a power cycle).

        Pollers re-fetch regardless; push transports override to forget stale state.
        """

    # -- transport commands -------------------------------------------------
    @abstractmethod
    async def async_play(self, index: int | None = None) -> None:
        """Play song ``index`` (None / -1 = play/resume)."""

    @abstractmethod
    async def async_play_path(self, path: str) -> None:
        """Play the exact SD-card path, resolved by the device's live library."""

    @abstractmethod
    async def async_pause(self) -> None:
        """Pause playback."""

    @abstractmethod
    async def async_stop(self) -> None:
        """Stop playback."""

    @abstractmethod
    async def async_next(self) -> None:
        """Skip to the next song."""

    @abstractmethod
    async def async_previous(self) -> None:
        """Skip to the previous song."""

    @abstractmethod
    async def async_set_volume(self, level_1_100: int) -> None:
        """Set volume on the device scale (1..100)."""

    @abstractmethod
    async def async_mute_volume(self, mute: bool) -> None:
        """Mute/unmute output while preserving the user's prior non-zero volume."""

    @abstractmethod
    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Set the sort/shuffle mode (sequential vs shuffle)."""

    @abstractmethod
    async def async_set_repeat(self, mode: int) -> None:
        """Set All Songs repeat: 0=off, 1=all songs, 2=current song."""

    @abstractmethod
    async def async_select_playlist(self, name: str) -> None:
        """Select / play the named playlist as the active source."""

    @abstractmethod
    async def async_reboot(self) -> None:
        """Reboot the device (only device-side power action; see power-architecture)."""

    # -- library reads (prime-then-poll on real hardware) -------------------
    @abstractmethod
    async def async_fetch_song_list(self, force: bool = False) -> list[str]:
        """Return the SD-card song list (ordered; index == position).

        ``force`` bypasses any cache and re-scans (e.g. the Refresh-library button).
        """

    @abstractmethod
    async def async_fetch_song_paths(self, force: bool = False) -> list[str]:
        """Return the raw SD-card song paths (ordered; index == position)."""

    @abstractmethod
    async def async_fetch_playlists(self) -> list[str]:
        """Return the playlist names."""

    @abstractmethod
    async def async_fetch_playlist_definitions(self) -> list[dict[str, Any]]:
        """Return the raw playlist objects, preserving device/App fields."""

    @abstractmethod
    async def async_save_playlist_definitions(
        self, playlists: list[dict[str, Any]]
    ) -> None:
        """Replace the device playlist set with ``playlists``."""

    @abstractmethod
    async def async_fetch_autoplay_config(self) -> dict[str, Any]:
        """Return the persisted AutoPlay configuration."""

    @abstractmethod
    async def async_save_autoplay_config(self, config: dict[str, Any]) -> None:
        """Persist the AutoPlay configuration."""
