"""Media player entity — the primary control surface for the piano."""

from __future__ import annotations

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

# Commands are serialized by the coordinator's transport; the device caps open
# sockets, so only one command-issuing update runs at a time per platform.
PARALLEL_UPDATES = 1

# Features actually backed by a device control. NB: no REPEAT_SET (no transport repeat
# exists), no VOLUME_MUTE (SetMute is a firmware no-op). TURN_ON/TURN_OFF are added
# per-entity only when the user links a power outlet (see power-control design).
# SELECT_SOURCE is intentionally omitted: playlists are browsed, not coerced into a
# "source" (plan-review-v2).
# SHUFFLE_SET is intentionally omitted too: shuffle is a persistent device setting (the
# firmware sort, on by default), so it lives on a dedicated switch entity that stays
# toggleable when idle — the media card only renders its shuffle control during active
# playback, which made toggling it off one-way. See switch.py / device captures.
# VOLUME_SET/STEP are added only once a real volume is known (the audio engine reports
# 255 = "unknown" for ~1 min after boot) and TURN_ON/OFF only when a power outlet is
# linked — both handled dynamically in supported_features().
_SUPPORTED = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.PLAY_MEDIA
)

_PLAYING_STATES = (
    MediaPlayerState.PLAYING,
    MediaPlayerState.PAUSED,
)

SERVICE_PLAY_SONG = "play_song"

# Shown as the now-playing text during the power-on/boot window.
_STARTING_TITLE = "Getting ready…"
# Shown while playing but the new song's name isn't known yet (instead of the old one).
_SONG_LOADING = "Loading…"

# Root node id/type for the flat song-library browse tree.
_BROWSE_ROOT = "library"


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
            vol.Required("song"): cv.string,
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
        features = _SUPPORTED
        # TURN_ON/TURN_OFF only when a power outlet is linked (power-control design).
        if self.coordinator.power_linked:
            features |= (
                MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
            )
        # Volume controls only once a real reading exists — hide the slider rather than
        # show the false 100% the audio engine's 255 ("unknown") produces during sync.
        if self.coordinator.data.volume is not None:
            features |= (
                MediaPlayerEntityFeature.VOLUME_SET
                | MediaPlayerEntityFeature.VOLUME_STEP
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
        # than a false Idle/Playing. See power-control design.
        if coordinator.getting_ready:
            return MediaPlayerState.ON
        return coordinator.data.state

    @property
    def available(self) -> bool:
        coordinator = self.coordinator
        # With a linked outlet the switch is the power authority: stay available while
        # powered off so the card shows OFF with a working power button rather than
        # greying out (which would hide turn-on). See power-control design.
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
        if self.coordinator.data.state in _PLAYING_STATES:
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
        """Browse the SD-card library as a flat list of playable songs.

        The library is flat (no folders), so every call returns the root listing.
        Each track's media_content_id is its integer index, which the transport
        resolves 0-based (verified live).
        """
        titles = await self.coordinator.transport.async_fetch_song_list()
        children = [
            BrowseMedia(
                title=title,
                media_class=MediaClass.MUSIC,
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
            media_content_type=_BROWSE_ROOT,
            media_content_id=_BROWSE_ROOT,
            can_play=False,
            can_expand=True,
            children=children,
            children_media_class=MediaClass.MUSIC,
        )

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        """Play a library song by integer index (from browse) or by name.

        Only the device's own SD library is playable — a player piano has no
        external/URL playback path.
        """
        await self._ensure_powered()
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

    # -- helpers -----------------------------------------------------------
    async def _ensure_powered(self) -> None:
        """Power on first when the piano is off but linked to an outlet."""
        if self.coordinator.power_linked and self.coordinator.power_on is False:
            await self.coordinator.async_power_on()

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
