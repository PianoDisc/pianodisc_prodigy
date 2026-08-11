"""Media player entity — the primary control surface for the piano."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
import voluptuous as vol

from .const import CONF_DEVICE_ID, DOMAIN, VOLUME_MAX, VOLUME_MIN
from .coordinator import PianoDiscConfigEntry, PianoDiscCoordinator
from .entity import PianoDiscEntity
from .transports.http import title_from_path

# Commands are serialized by the coordinator's transport; the device caps open
# sockets, so only one command-issuing update runs at a time per platform.
PARALLEL_UPDATES = 1

# Features actually backed by a device control. NB: no REPEAT_SET (no transport repeat
# exists), no VOLUME_MUTE (SetMute is a firmware no-op). TURN_ON/TURN_OFF are added
# per-entity only when the user links a power outlet (see [[power-architecture]]).
# SELECT_SOURCE is intentionally omitted: playlists are browsed, not coerced into a
# "source" (plan-review-v2).
# SHUFFLE_SET is intentionally omitted too: shuffle is a persistent device setting (the
# firmware sort, on by default), so it lives on a dedicated switch entity that stays
# toggleable when idle — the media card only renders its shuffle control during active
# playback, which made toggling it off one-way. See switch.py / [[golden-capture]].
# TURN_ON/OFF are added only when a power outlet is linked.
_SUPPORTED = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.PLAY_MEDIA
)

_PLAYING_STATES = (
    MediaPlayerState.PLAYING,
    MediaPlayerState.PAUSED,
)

SERVICE_PLAY_SONG = "play_song"
SERVICE_CREATE_PLAYLIST = "create_playlist"
SERVICE_UPDATE_PLAYLIST = "update_playlist"
SERVICE_DELETE_PLAYLIST = "delete_playlist"
SERVICE_ADD_PLAYLIST_SONG = "add_playlist_song"
SERVICE_REMOVE_PLAYLIST_SONG = "remove_playlist_song"

ATTR_PLAYLIST = "playlist"
ATTR_SONG = "song"
ATTR_SONGS = "songs"
ATTR_EXCLUDES = "excludes"
ATTR_NAME = "name"
ATTR_SORT = "sort"
ATTR_REPEAT = "repeat"
ATTR_EXCLUDE = "exclude"

# Shown as the now-playing text during the power-on/boot window.
_STARTING_TITLE = "Getting ready…"
# Shown while playing but the new song's name isn't known yet (instead of the old one).
_SONG_LOADING = "Loading…"

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
    platform.async_register_entity_service(
        SERVICE_CREATE_PLAYLIST,
        {
            vol.Required(ATTR_NAME): cv.string,
            vol.Optional(ATTR_SONGS, default=[]): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional(ATTR_EXCLUDES, default=[]): vol.All(
                cv.ensure_list, [cv.string]
            ),
            vol.Optional(ATTR_SORT, default="Shuffle"): cv.string,
            vol.Optional(ATTR_REPEAT, default=1): vol.Coerce(int),
        },
        "async_create_playlist",
    )
    platform.async_register_entity_service(
        SERVICE_UPDATE_PLAYLIST,
        {
            vol.Required(ATTR_PLAYLIST): cv.string,
            vol.Optional(ATTR_NAME): cv.string,
            vol.Optional(ATTR_SORT): cv.string,
            vol.Optional(ATTR_REPEAT): vol.Coerce(int),
        },
        "async_update_playlist",
    )
    platform.async_register_entity_service(
        SERVICE_DELETE_PLAYLIST,
        {vol.Required(ATTR_PLAYLIST): cv.string},
        "async_delete_playlist",
    )
    platform.async_register_entity_service(
        SERVICE_ADD_PLAYLIST_SONG,
        {
            vol.Required(ATTR_PLAYLIST): cv.string,
            vol.Required(ATTR_SONG): cv.string,
            vol.Optional(ATTR_EXCLUDE, default=False): cv.boolean,
        },
        "async_add_playlist_song",
    )
    platform.async_register_entity_service(
        SERVICE_REMOVE_PLAYLIST_SONG,
        {
            vol.Required(ATTR_PLAYLIST): cv.string,
            vol.Required(ATTR_SONG): cv.string,
            vol.Optional(ATTR_EXCLUDE, default=False): cv.boolean,
        },
        "async_remove_playlist_song",
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
        features = _SUPPORTED
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
        return coordinator.data.state

    @property
    def available(self) -> bool:
        coordinator = self.coordinator
        # With a linked outlet the switch is the power authority: stay available while
        # powered off so the card shows OFF with a working power button rather than
        # greying out (which would hide turn-on). See [[power-architecture]].
        if coordinator.power_linked and coordinator.power_on is False:
            return True
        # Stay available (showing "getting ready") through the power-on/boot window.
        if coordinator.getting_ready:
            return True
        return super().available

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.power_linked:
            return {"power_switch": self.coordinator.power_switch}
        return None

    @property
    def volume_level(self) -> float | None:
        vol_ = self.coordinator.data.volume
        return None if vol_ is None else vol_ / VOLUME_MAX

    @property
    def media_content_type(self) -> MediaType | None:
        return MediaType.MUSIC if self.media_title else None

    @property
    def media_title(self) -> str | None:
        # While getting ready, show a clear status line instead of a missing title.
        if self.coordinator.getting_ready:
            return _STARTING_TITLE
        # The device never clears .../song on stop; only surface it while playing. After
        # a (re)play the stale previous title is suppressed (transport sets song None)
        # until the new one is known → show a placeholder, not the old song.
        if self.coordinator.data.state is MediaPlayerState.PAUSED:
            return self.coordinator.data.song
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
        # HA 0..1 → device 1..100; 0.0 must never send an out-of-range no-op.
        device_volume = max(VOLUME_MIN, min(VOLUME_MAX, round(volume * VOLUME_MAX)))
        await self._command(self.coordinator.transport.async_set_volume(device_volume))

    # -- browse / play media -----------------------------------------------
    async def async_browse_media(
        self,
        media_content_type: str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Browse the SD-card library as songs plus playable playlists."""
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
        await self.coordinator.transport.async_play(index)
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
        await self.coordinator.transport.async_select_playlist(name)
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
        await self._ensure_powered()
        transport = self.coordinator.transport
        prior = self.coordinator.data.volume
        if volume is not None:
            await transport.async_set_volume(max(VOLUME_MIN, volume))

        songs = await transport.async_fetch_song_list()
        index = _match_song(song, songs)
        if index is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="song_not_found",
                translation_placeholders={"song": song},
            )
        await transport.async_play(index)

        if restore_volume_after and prior is not None:
            await transport.async_set_volume(prior)
        await self.coordinator.async_request_refresh()

    async def async_create_playlist(
        self,
        name: str,
        songs: list[str],
        excludes: list[str],
        sort: str,
        repeat: int,
    ) -> None:
        """Create a playlist, then write the full playlist set back to the piano."""
        playlists = await self._fetch_playlist_defs()
        if _find_playlist(playlists, name) is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="playlist_already_exists",
                translation_placeholders={"playlist": name},
            )
        playlists.append(
            {
                "name": name.strip(),
                "sort": sort,
                "repeat": repeat,
                "content": {
                    "include": [
                        await self._resolve_song_path(song) for song in songs if song
                    ],
                    "exclude": [
                        await self._resolve_song_path(song) for song in excludes if song
                    ],
                },
            }
        )
        await self._save_playlist_defs(playlists)

    async def async_update_playlist(
        self,
        playlist: str,
        name: str | None = None,
        sort: str | None = None,
        repeat: int | None = None,
    ) -> None:
        """Update playlist metadata while preserving its songs and unknown fields."""
        playlists = await self._fetch_playlist_defs()
        index = self._playlist_index_or_raise(playlists, playlist)
        item = _normalize_playlist(playlists[index])
        if name is not None:
            item["name"] = name.strip()
        if sort is not None:
            item["sort"] = sort
        if repeat is not None:
            item["repeat"] = repeat
        playlists[index] = item
        await self._save_playlist_defs(playlists)

    async def async_delete_playlist(self, playlist: str) -> None:
        """Delete a playlist by name or zero-based index."""
        playlists = await self._fetch_playlist_defs()
        index = self._playlist_index_or_raise(playlists, playlist)
        del playlists[index]
        await self._save_playlist_defs(playlists)

    async def async_add_playlist_song(
        self, playlist: str, song: str, exclude: bool = False
    ) -> None:
        """Add a song path/title to a playlist include or exclude list."""
        playlists = await self._fetch_playlist_defs()
        index = self._playlist_index_or_raise(playlists, playlist)
        item = _normalize_playlist(playlists[index])
        content = item["content"]
        paths = content["exclude" if exclude else "include"]
        path = await self._resolve_song_path(song)
        if path not in paths:
            paths.append(path)
        playlists[index] = item
        await self._save_playlist_defs(playlists)

    async def async_remove_playlist_song(
        self, playlist: str, song: str, exclude: bool = False
    ) -> None:
        """Remove a song path/title from a playlist include or exclude list."""
        playlists = await self._fetch_playlist_defs()
        index = self._playlist_index_or_raise(playlists, playlist)
        item = _normalize_playlist(playlists[index])
        content = item["content"]
        paths = content["exclude" if exclude else "include"]
        path = await self._resolve_song_path(song)
        paths[:] = [candidate for candidate in paths if candidate != path]
        playlists[index] = item
        await self._save_playlist_defs(playlists)

    # -- helpers -----------------------------------------------------------
    async def _ensure_powered(self) -> None:
        """Power on first when the piano is off but linked to an outlet."""
        if self.coordinator.power_linked and self.coordinator.power_on is False:
            await self.coordinator.async_power_on()

    async def _fetch_playlist_defs(self) -> list[dict[str, Any]]:
        playlists = await self.coordinator.transport.async_fetch_playlist_definitions()
        return [_normalize_playlist(item) for item in playlists]

    async def _save_playlist_defs(self, playlists: list[dict[str, Any]]) -> None:
        await self.coordinator.transport.async_save_playlist_definitions(playlists)
        await self.coordinator.async_request_refresh()

    async def _resolve_song_path(self, song: str) -> str:
        raw = song.strip()
        if raw.startswith("/"):
            return raw
        paths = await self.coordinator.transport.async_fetch_song_paths()
        index = _match_song(raw, [title_from_path(path) for path in paths])
        if index is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="song_not_found",
                translation_placeholders={"song": song},
            )
        return paths[index]

    def _playlist_index_or_raise(
        self, playlists: list[dict[str, Any]], playlist: str
    ) -> int:
        index = _find_playlist(playlists, playlist)
        if index is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="playlist_not_found",
                translation_placeholders={"playlist": playlist},
            )
        return index

    async def _command(self, coro) -> None:
        await coro
        await self.coordinator.async_request_refresh()


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


def _find_playlist(playlists: list[dict[str, Any]], query: str) -> int | None:
    """Find a playlist by zero-based index or case-insensitive name."""
    raw = query.strip()
    if raw.isdigit():
        index = int(raw)
        if 0 <= index < len(playlists):
            return index
    q = raw.casefold()
    for index, playlist in enumerate(playlists):
        name = playlist.get("name")
        if isinstance(name, str) and name.casefold() == q:
            return index
    return None


def _normalize_playlist(playlist: dict[str, Any]) -> dict[str, Any]:
    """Copy a playlist while ensuring the App-compatible content lists exist."""
    item = deepcopy(playlist)
    content = item.get("content")
    if not isinstance(content, dict):
        content = {}
    include = content.get("include")
    exclude = content.get("exclude")
    content["include"] = list(include) if isinstance(include, list) else []
    content["exclude"] = list(exclude) if isinstance(exclude, list) else []
    item["content"] = content
    if not isinstance(item.get("name"), str):
        item["name"] = "Untitled Playlist"
    return item
