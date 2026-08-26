"""Media player entity — the primary control surface for the piano."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
import voluptuous as vol

from .const import CONF_DEVICE_ID, DOMAIN, VOLUME_MAX
from .coordinator import PianoDiscConfigEntry, PianoDiscCoordinator
from .entity import PianoDiscEntity

# Commands are serialized by the coordinator's transport; the device caps open
# sockets, so only one command-issuing update runs at a time per platform.
PARALLEL_UPDATES = 1

# Features actually backed by a device control. REPEAT_SET is added dynamically for
# the All Songs session; playlist and AutoPlay keep their own repeat policies.
# per-entity only when the user links a power outlet (see [[power-architecture]]).
# SELECT_SOURCE is intentionally omitted: playlists are browsed, not coerced into a
# "source" (plan-review-v2).
# TURN_ON/OFF are added only when a power outlet is linked.
_SUPPORTED = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.SHUFFLE_SET
)

_PLAYING_STATES = (
    MediaPlayerState.PLAYING,
    MediaPlayerState.PAUSED,
)

SERVICE_PLAY_SONG = "play_song"

ATTR_SONG = "song"

# Shown as the now-playing text during the power-on/boot window.
_STARTING_TITLE = "Getting ready…"
# Shown after the NRF is ready while HA exclusively scans the shared SD library.
_LIBRARY_SYNCING_TITLE = "Syncing library…"
# Shown while playing but the new song's name isn't known yet (instead of the old one).
_SONG_LOADING = "Loading…"
_DEFAULT_ALBUM_ART = f"/{DOMAIN}/default-album-art.png"

# Root node ids/types for the SD-card browse tree.
_BROWSE_ROOT = "library"
_BROWSE_SONGS = "library:songs"
_BROWSE_PLAYLISTS = "library:playlists"
_PLAYLIST_ID_PREFIX = "playlist:"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PianoDiscConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the media player from a config entry."""
    async_add_entities([PianoDiscMediaPlayer(entry.runtime_data)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_PLAY_SONG,
        {
            vol.Required(ATTR_SONG): cv.string,
            vol.Optional("volume"): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=VOLUME_MAX)
            ),
            vol.Optional("restore_volume_after", default=False): cv.boolean,
        },
        "async_play_song",
    )


class PianoDiscMediaPlayer(PianoDiscEntity, MediaPlayerEntity):
    """Represents the piano's SD-card MIDI playback (the player-piano transport)."""

    _attr_name = None  # primary entity → shows as the device/room name
    _attr_icon = "mdi:piano"  # the one icon we own (the browse button's icon is HA's)

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        # Only the first scan has no trustworthy cache for browse/play. Subsequent
        # refreshes retain the existing library and leave the player usable.
        features = (
            MediaPlayerEntityFeature(0)
            if self.coordinator.library_initializing
            else _SUPPORTED
        )
        if (
            not self.coordinator.library_initializing
            and self.coordinator.data.queue_mode == "all_songs"
        ):
            features |= MediaPlayerEntityFeature.REPEAT_SET
        # TURN_ON/TURN_OFF only when a power outlet is linked ([[power-architecture]]).
        if self.coordinator.power_linked:
            features |= (
                MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
            )
        return features

    # -- state -------------------------------------------------------------
    @property
    def state(self) -> MediaPlayerState | None:
        coordinator = self.coordinator
        # A linked outlet that is off means the piano is powered down → OFF.
        if coordinator.power_linked and coordinator.power_on is False:
            return MediaPlayerState.OFF
        # Linked + powered on but not reporting yet → "getting ready" (booting). We know
        # it's on (the switch), so present as ON with a "Getting ready…" title rather
        # than a false Idle/Playing. See [[power-architecture]].
        if coordinator.getting_ready:
            return MediaPlayerState.ON
        if coordinator.library_initializing:
            return MediaPlayerState.ON
        return coordinator.data.state

    @property
    def available(self) -> bool:
        coordinator = self.coordinator
        # With a linked outlet the switch is the power authority: stay available while
        # powered off so the card shows OFF with a working power button rather than
        # greying out (which would hide turn-on). See [[power-architecture]].
        if coordinator.power_linked and coordinator.power_on is False:
            return True
        # A device-reported non-ready state is authoritative. Keep the player
        # unavailable while the NRF is still preparing MIDI and playback logic.
        if coordinator.data.readiness not in {"unknown", "READY", "OK"}:
            return False
        # Stay available (showing "getting ready") through the power-on/boot window.
        # This only applies before the device has reported its own readiness state.
        if coordinator.getting_ready:
            return True
        return super().available

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs: dict[str, Any] = {}
        if self.coordinator.power_linked:
            attrs["power_switch"] = self.coordinator.power_switch
        data = self.coordinator.data
        if data.state in _PLAYING_STATES:
            if data.song_index is not None:
                attrs["track_index"] = data.song_index + 1
            if data.song_count is not None:
                attrs["track_total"] = data.song_count
        if data.queue_mode is not None:
            attrs["queue_mode"] = data.queue_mode
        if data.playlist_repeat is not None:
            attrs["playlist_repeat"] = data.playlist_repeat
        if data.autoplay_loop is not None:
            attrs["autoplay_loop"] = data.autoplay_loop
        return attrs or None

    @property
    def volume_level(self) -> float | None:
        vol_ = self.coordinator.data.volume
        return None if vol_ is None else vol_ / VOLUME_MAX

    @property
    def is_volume_muted(self) -> bool | None:
        vol_ = self.coordinator.data.volume
        return None if vol_ is None else vol_ == 0

    @property
    def shuffle(self) -> bool | None:
        return self.coordinator.data.shuffle

    @property
    def repeat(self) -> RepeatMode | None:
        """Expose standard repeat modes for an All Songs session only."""
        if self.coordinator.data.queue_mode != "all_songs":
            return None
        return {
            0: RepeatMode.OFF,
            1: RepeatMode.ALL,
            2: RepeatMode.ONE,
        }.get(self.coordinator.data.repeat_mode)

    @property
    def media_content_type(self) -> MediaType | None:
        return MediaType.MUSIC if self.media_title else None

    @property
    def media_image_url(self) -> str | None:
        if self.media_title:
            return _DEFAULT_ALBUM_ART
        return None

    @property
    def media_image_remotely_accessible(self) -> bool:
        return True

    @property
    def media_title(self) -> str | None:
        # While getting ready, show a clear status line instead of a missing title.
        if self.coordinator.getting_ready:
            return _STARTING_TITLE
        if self.coordinator.library_initializing:
            return _LIBRARY_SYNCING_TITLE
        # The device may retain the last title on stop; only surface it while playing.
        # After a (re)play the stale previous title is suppressed (transport sets song
        # None) until the new one is known → show a placeholder, not the old song.
        if self.coordinator.data.state is MediaPlayerState.PAUSED:
            return self.coordinator.data.song or _SONG_LOADING
        if self.coordinator.data.state is MediaPlayerState.PLAYING:
            return self.coordinator.data.song or _SONG_LOADING
        return None

    @property
    def media_content_id(self) -> str | None:
        # Integer song index is the play identifier (matches browse + PLAY_MEDIA).
        # Blank on idle identically to media_title (plan_review_v2).
        data = self.coordinator.data
        if data.state in _PLAYING_STATES and data.song_index is not None:
            return str(data.song_index)
        return None

    @property
    def media_track(self) -> int | None:
        data = self.coordinator.data
        if data.state in _PLAYING_STATES and data.song_index is not None:
            return data.song_index + 1
        return None

    @property
    def media_playlist(self) -> str | None:
        data = self.coordinator.data
        if data.state in _PLAYING_STATES:
            return data.source
        return None

    @property
    def media_duration(self) -> float | None:
        data = self.coordinator.data
        if data.state in _PLAYING_STATES:
            return data.media_duration
        return None

    @property
    def media_position(self) -> float | None:
        data = self.coordinator.data
        if data.state in _PLAYING_STATES:
            return data.media_position
        return None

    @property
    def media_position_updated_at(self) -> datetime | None:
        data = self.coordinator.data
        if data.state is MediaPlayerState.PLAYING and data.media_position is not None:
            return data.media_position_updated_at
        return None

    # -- commands ----------------------------------------------------------
    async def async_turn_on(self) -> None:
        await self.coordinator.async_power_on()

    async def async_turn_off(self) -> None:
        await self.coordinator.async_power_off()

    async def async_media_play(self) -> None:
        await self._ensure_powered()
        await self._command(self.coordinator.transport.async_play())

    async def async_media_pause(self) -> None:
        await self._command(self.coordinator.transport.async_pause())

    async def async_media_stop(self) -> None:
        await self._command(self.coordinator.transport.async_stop())

    async def async_media_next_track(self) -> None:
        await self._command(self.coordinator.transport.async_next())

    async def async_media_previous_track(self) -> None:
        await self._command(self.coordinator.transport.async_previous())

    async def async_set_volume_level(self, volume: float) -> None:
        # HA 0..1 → device 0..100; 0.0 is the mute volume.
        device_volume = max(0, min(VOLUME_MAX, round(volume * VOLUME_MAX)))
        await self._command(self.coordinator.transport.async_set_volume(device_volume))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._command(self.coordinator.transport.async_mute_volume(mute))

    async def async_set_shuffle(self, shuffle: bool) -> None:
        await self._command(self.coordinator.transport.async_set_shuffle(shuffle))

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set All Songs repeat: off, all songs, or the current song."""
        if self.coordinator.data.queue_mode != "all_songs":
            raise ServiceValidationError(
                "Repeat mode is controlled by the selected playlist or AutoPlay"
            )
        mode = {
            RepeatMode.OFF: 0,
            RepeatMode.ALL: 1,
            RepeatMode.ONE: 2,
        }.get(repeat)
        if mode is None:
            raise ServiceValidationError(f"Unsupported repeat mode: {repeat}")
        await self._command(self.coordinator.transport.async_set_repeat(mode))

    # -- browse / play media -----------------------------------------------
    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse the SD-card library as songs plus playable playlists."""
        self._ensure_library_ready()
        if media_content_id == _BROWSE_SONGS:
            return await self._browse_songs()
        if media_content_id == _BROWSE_PLAYLISTS:
            return await self._browse_playlists()
        return BrowseMedia(
            title="Piano library",
            media_class=MediaClass.DIRECTORY,
            media_content_type=_BROWSE_ROOT,
            media_content_id=_BROWSE_SONGS,
            can_play=False,
            can_expand=True,
            children=[
                BrowseMedia(
                    title="All songs",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=_BROWSE_SONGS,
                    media_content_id=_BROWSE_SONGS,
                    can_play=False,
                    can_expand=True,
                ),
                BrowseMedia(
                    title="Playlists",
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=_BROWSE_PLAYLISTS,
                    media_content_id=_BROWSE_PLAYLISTS,
                    can_play=False,
                    can_expand=True,
                ),
            ],
            children_media_class=MediaClass.DIRECTORY,
        )

    async def _browse_songs(self) -> BrowseMedia:
        titles = await self.coordinator.transport.async_fetch_song_list()
        children = [
            BrowseMedia(
                title=title,
                media_class=MediaClass.TRACK,
                media_content_type=MediaType.MUSIC,
                media_content_id=str(index),
                can_play=True,
                can_expand=False,
            )
            for index, title in enumerate(titles)
        ]
        return BrowseMedia(
            title="Piano library",
            media_class=MediaClass.DIRECTORY,
            media_content_type=_BROWSE_SONGS,
            media_content_id=_BROWSE_SONGS,
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.TRACK,
        )

    async def _browse_playlists(self) -> BrowseMedia:
        playlists = await self.coordinator.transport.async_fetch_playlists()
        children = [
            BrowseMedia(
                title=name,
                media_class=MediaClass.PLAYLIST,
                media_content_type=MediaType.PLAYLIST,
                media_content_id=f"{_PLAYLIST_ID_PREFIX}{index}",
                can_play=True,
                can_expand=False,
            )
            for index, name in enumerate(playlists)
        ]
        return BrowseMedia(
            title="Playlists",
            media_class=MediaClass.DIRECTORY,
            media_content_type=_BROWSE_PLAYLISTS,
            media_content_id=_BROWSE_PLAYLISTS,
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.PLAYLIST,
        )

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Play a library song by integer index (from browse) or by name.

        Only the device's own SD library is playable — a player piano has no
        external/URL playback path.
        """
        self._ensure_library_ready()
        await self._ensure_powered()
        if media_type == MediaType.PLAYLIST or media_id.startswith(_PLAYLIST_ID_PREFIX):
            await self._play_playlist_media(media_id)
            return
        titles = await self.coordinator.transport.async_fetch_song_list()
        if media_id.isdigit():
            index: int | None = int(media_id)
            if not 0 <= index < len(titles):
                index = None
        else:
            index = _match_song(media_id, titles)
        if index is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="song_not_found",
                translation_placeholders={"song": media_id},
            )
        await self.coordinator.async_execute_device_command(
            self.coordinator.transport.async_play(index)
        )
        await self.coordinator.async_request_refresh()

    async def _play_playlist_media(self, media_id: str) -> None:
        playlists = await self.coordinator.transport.async_fetch_playlists()
        raw = (
            media_id.removeprefix(_PLAYLIST_ID_PREFIX)
            if media_id.startswith(_PLAYLIST_ID_PREFIX)
            else media_id
        )
        name: str | None = None
        if raw.isdigit():
            index = int(raw)
            if 0 <= index < len(playlists):
                name = playlists[index]
        else:
            for playlist in playlists:
                if playlist.casefold() == raw.casefold().strip():
                    name = playlist
                    break
        if name is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="playlist_not_found",
                translation_placeholders={"playlist": media_id},
            )
        await self.coordinator.async_execute_device_command(
            self.coordinator.transport.async_select_playlist(name)
        )
        await self.coordinator.async_request_refresh()

    # -- custom service ----------------------------------------------------
    async def async_play_song(
        self, song: str, volume: int | None = None, restore_volume_after: bool = False
    ) -> None:
        """Play a song by (fuzzy) name, optionally setting/restoring volume.

        Delivers the one-call "power on → set volume → play by name → restore" ritual
        without HA scripting. When a power outlet is linked and the piano is off, it is
        powered on first. ``restore_volume_after`` snapshots the current volume and
        re-applies it (the device has no announce/overlay concept, so we do it here).
        """
        self._ensure_library_ready()
        await self._ensure_powered()
        transport = self.coordinator.transport
        prior = self.coordinator.data.volume
        if volume is not None:
            await self.coordinator.async_execute_device_command(
                transport.async_set_volume(max(0, min(VOLUME_MAX, volume)))
            )

        songs = await transport.async_fetch_song_list()
        index = _match_song(song, songs)
        if index is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="song_not_found",
                translation_placeholders={"song": song},
            )
        await self.coordinator.async_execute_device_command(transport.async_play(index))

        if restore_volume_after and prior is not None:
            await self.coordinator.async_execute_device_command(
                transport.async_set_volume(prior)
            )
        await self.coordinator.async_request_refresh()

    # -- helpers -----------------------------------------------------------
    async def _ensure_powered(self) -> None:
        """Power on first when the piano is off but linked to an outlet."""
        if self.coordinator.power_linked and self.coordinator.power_on is False:
            await self.coordinator.async_power_on()

    async def _command(self, coro) -> None:
        self._ensure_library_ready()
        await self.coordinator.async_execute_device_command(coro)
        await self.coordinator.async_request_refresh()

    def _ensure_library_ready(self) -> None:
        """Reject commands from services/voice while the scan owns the device."""
        if self.coordinator.library_initializing:
            raise ServiceValidationError("Piano library is still scanning")


def _match_song(query: str, songs: list[str]) -> int | None:
    """Exact (case-insensitive) then substring match against the song list."""
    q = query.casefold().strip()
    for i, name in enumerate(songs):
        if name.casefold() == q:
            return i
    for i, name in enumerate(songs):
        if q in name.casefold():
            return i
    return None
