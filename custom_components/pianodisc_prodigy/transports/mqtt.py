"""MQTT transport — command/status transport with HTTP fallback when available.

Newer firmware publishes the raw ``/playerStatus`` JSON on ``…/player/status``. Once
that topic is seen, MQTT is the primary source for playback state/song/progress and HTTP
only backfills metadata/legacy gaps. Older firmware can still run with the historical
split status topics plus the composed HTTP poll.

* ``…/busy`` → instant "playing" (HTTP then confirms + sustains it through busy's gaps),
* ``…/player/status`` → full now-playing snapshot,
* ``…/ready`` / any message → availability (watchdog-driven offline).

See [[golden-capture]], [[power-architecture]].
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import ipaddress
import json
import uuid

from homeassistant.components import mqtt
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from ..const import (
    BUSY_DEBOUNCE,
    LOGGER,
    MAX_SCAN_PAGES,
    MQTT_PAYLOAD_OFFLINE,
    MQTT_TOPIC_BUSY,
    MQTT_TOPIC_AUTOPLAY_REQUEST,
    MQTT_TOPIC_AUTOPLAY_STATE,
    MQTT_TOPIC_COMMAND,
    MQTT_TOPIC_DEVICE_NAME,
    MQTT_TOPIC_LIBRARY_PAGE,
    MQTT_TOPIC_LIBRARY_REQUEST,
    MQTT_TOPIC_NETWORK,
    MQTT_TOPIC_MSC,
    MQTT_TOPIC_PLAYER_STATUS,
    MQTT_TOPIC_PLAYLIST_REQUEST,
    MQTT_TOPIC_PLAYLIST_STATE,
    MQTT_TOPIC_READY,
    MQTT_TOPIC_ROOT,
    MQTT_TOPIC_UPDATE,
    MQTT_TOPIC_VOLUME,
    MQTT_TOPIC_VERSION,
    READY_WATCHDOG,
    SONGLIST_PAGE_SIZE,
    SONGLIST_TTL,
    SHUFFLE_HOLD_GRACE,
    SONG_UNKNOWN_GRACE,
    STOP_CONFIRM,
)
from ..models import ProdigyData
from . import Transport
from .http import HttpTransport, title_from_path

_MQTT_LIBRARY_TIMEOUT = 12

_STATE_MAP: dict[int, MediaPlayerState] = {
    0: MediaPlayerState.IDLE,
    1: MediaPlayerState.PLAYING,
    2: MediaPlayerState.PAUSED,
}


def _truthy(payload: object) -> bool:
    """`true`/`false` (any case) -> bool."""
    return str(payload).strip().upper() == "TRUE"


def _percent_volume(payload: object) -> int | None:
    """Parse a 0..100 percent volume payload; reject boot/legacy sentinels."""
    try:
        volume = int(str(payload).strip())
    except ValueError:
        return None
    return volume if 0 <= volume <= 100 else None


def _int_value(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _positive_int(value: object) -> int | None:
    parsed = _int_value(value)
    return parsed if parsed is not None and parsed > 0 else None


def _non_negative_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


def _positive_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def _track_index(value: object) -> int | None:
    parsed = _positive_int(value)
    return parsed - 1 if parsed is not None else None


def _json_payload(payload: object) -> object:
    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
        for encoding in ("utf-8", "cp1252", "iso-8859-1"):
            try:
                return json.loads(raw.decode(encoding))
            except UnicodeDecodeError:
                continue
    return json.loads(payload)


class MqttTransport(Transport):
    """MQTT command/status transport, optionally backed by HTTP for legacy gaps."""

    @property
    def uses_push_updates(self) -> bool:
        """Whether the piano itself is currently delivering live MQTT status.

        Home Assistant can have an MQTT client even when this particular piano has
        not been configured with that broker.  In that case HTTP must remain the
        active poll/command path instead of leaving the integration at OFFLINE.
        """
        return self._mqtt_status_seen and self._data.available

    @property
    def supports_msc(self) -> bool:
        return True

    @property
    def supports_realtime_events(self) -> bool:
        """Events are usable only while this piano is live on MQTT."""
        return self._mqtt_live

    @property
    def _mqtt_live(self) -> bool:
        """Return whether MQTT is presently authoritative for this piano."""
        return self.uses_push_updates

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        http: HttpTransport | None = None,
    ) -> None:
        super().__init__()
        self._hass = hass
        self._http = http
        self._http_host = http.ip_address if isinstance(http, HttpTransport) else None
        self._root = f"{MQTT_TOPIC_ROOT}/{device_id}"
        self._command_topic = f"{self._root}/{MQTT_TOPIC_COMMAND}"
        self._library_request_topic = f"{self._root}/{MQTT_TOPIC_LIBRARY_REQUEST}"
        self._playlist_request_topic = f"{self._root}/{MQTT_TOPIC_PLAYLIST_REQUEST}"
        self._autoplay_request_topic = f"{self._root}/{MQTT_TOPIC_AUTOPLAY_REQUEST}"
        self._data = ProdigyData(ip_address=self._http_host)
        # State inputs. The displayed state is derived from these (see _derive_state).
        self._http_state: MediaPlayerState | None = None  # last /playerStatus state
        self._busy_until = 0.0  # busy counts as "playing" until this loop time
        self._stopped = False  # only used before playback is known
        self._paused = False
        self._playing = False
        self._playback_seen = False
        self._mqtt_status_seen = False
        self._mqtt_volume_seen = False
        self._shuffle_target: bool | None = None
        self._shuffle_hold_until = 0.0
        # After a (re)play, suppress this stale title until a new one appears.
        self._prev_song: str | None = None
        self._last_status_song: str | None = None
        self._pending_song_change = False
        self._song_grace_until = 0.0
        self._cancel_busy: Callable[[], None] | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._cancel_watchdog: Callable[[], None] | None = None
        self._closed = False
        self._library_waiters: dict[str, asyncio.Future[dict]] = {}
        self._playlist_waiters: dict[str, asyncio.Future[dict]] = {}
        self._autoplay_waiters: dict[str, asyncio.Future[dict]] = {}
        self._song_titles: list[str] = []
        self._song_paths: list[str] = []
        self._song_cache_at: float | None = None
        self._song_lock = asyncio.Lock()
        self._playlist_names: list[str] = []
        self._playlist_defs: list[dict[str, object]] = []
        self._pre_mute_volume = 50

    # -- lifecycle ----------------------------------------------------------
    async def async_setup(self) -> None:
        handlers = {
            MQTT_TOPIC_BUSY: self._on_busy,
            MQTT_TOPIC_PLAYER_STATUS: self._on_player_status,
            MQTT_TOPIC_VOLUME: self._on_volume,
            MQTT_TOPIC_READY: self._on_ready,
            MQTT_TOPIC_DEVICE_NAME: self._on_device_name,
            MQTT_TOPIC_NETWORK: self._on_network,
            MQTT_TOPIC_MSC: self._on_msc,
            MQTT_TOPIC_VERSION: self._on_version,
            MQTT_TOPIC_UPDATE: self._on_update,
            MQTT_TOPIC_LIBRARY_PAGE: self._on_library_page,
            MQTT_TOPIC_PLAYLIST_STATE: self._on_playlist_state,
            MQTT_TOPIC_AUTOPLAY_STATE: self._on_autoplay_state,
        }
        raw_json_topics = {
            MQTT_TOPIC_PLAYER_STATUS,
            MQTT_TOPIC_LIBRARY_PAGE,
            MQTT_TOPIC_PLAYLIST_STATE,
            MQTT_TOPIC_AUTOPLAY_STATE,
        }
        for sub, handler in handlers.items():
            unsub = await mqtt.async_subscribe(
                self._hass,
                f"{self._root}/{sub}",
                handler,
                encoding=None if sub in raw_json_topics else "utf-8",
            )
            self._unsubs.append(unsub)
        self._arm_watchdog()

    async def async_close(self) -> None:
        self._closed = True  # stop any in-flight cross-check from re-arming
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for cancel in (self._cancel_watchdog, self._cancel_busy):
            if cancel is not None:
                cancel()
        self._cancel_watchdog = self._cancel_busy = None
        for waiters in (
            self._library_waiters,
            self._playlist_waiters,
            self._autoplay_waiters,
        ):
            for fut in waiters.values():
                if not fut.done():
                    fut.cancel()
            waiters.clear()

    # -- status overlay (MQTT push) ----------------------------------------
    @callback
    def _on_msc(self, msg: ReceiveMessage) -> None:
        """Forward a live MIDI Show Control message without affecting snapshots."""
        if msg.retain:
            return
        try:
            payload = _json_payload(msg.payload)
            if not isinstance(payload, dict):
                raise ValueError("payload is not an object")
            command = str(payload["command"]).strip().upper()
            cue = str(payload["cue"]).strip()
            if not command or not cue:
                raise ValueError("empty command or cue")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as err:
            LOGGER.debug("Ignoring malformed MSC message: %s", err)
            return
        self._emit_msc(command, cue)

    @callback
    def _avail(self, msg: ReceiveMessage) -> bool:
        # CR#6: these status topics are now published retained, so the broker replays
        # them on every (re)subscribe — including while the device is offline. A
        # retained replay is last-known state, NOT proof the device is online now, so
        # it must preserve availability and leave …/ready (+ its Last-Will) and the
        # watchdog as the authority. A live (non-retained) publish still proves online.
        live = True if not msg.retain else self._data.available
        # Legacy firmware has no readiness payload; preserve its historic live-status
        # behavior until an explicit startup state is observed.
        return live and self._data.readiness not in {
            "WARMING_UP",
            "NO_SD",
            "FAULT",
            "OFFLINE",
        }

    @callback
    def _on_busy(self, msg: ReceiveMessage) -> None:
        busy = _truthy(msg.payload)
        if msg.retain:
            # Retained replay on subscribe: reflect the value but don't treat it as
            # live solenoid activity (no debounce hold) or as a liveness signal.
            self._push(busy=busy, available=self._data.available)
            return
        if busy:  # keys striking → playing; extend the hold and cancel any expiry
            self._playback_seen = True
            self._busy_until = self._hass.loop.time() + BUSY_DEBOUNCE
            if self._cancel_busy is not None:
                self._cancel_busy()
                self._cancel_busy = None
        elif self._cancel_busy is None:  # re-derive when the hold lapses
            self._cancel_busy = async_call_later(
                self._hass, BUSY_DEBOUNCE, self._busy_expired
            )
        self._push(busy=busy)

    @callback
    def _busy_expired(self, _now: object) -> None:
        self._cancel_busy = None
        self._push()

    @callback
    def _on_player_status(self, msg: ReceiveMessage) -> None:
        if not msg.retain and self._data.readiness == "OFFLINE":
            # A legacy device may prove it reconnected with status before it sends a
            # readiness payload. Treat that brief compatibility window as unknown;
            # new firmware follows with WARMING_UP or READY immediately.
            self._data = self._data.merge(readiness="unknown")
        try:
            payload = _json_payload(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return

        raw_song = payload.get("song")
        song_path = raw_song.strip() if isinstance(raw_song, str) and raw_song.strip() else None
        song = (
            title_from_path(raw_song)
            if isinstance(raw_song, str) and raw_song.strip()
            else None
        )
        song_index = _track_index(payload.get("track_index"))
        track_total = _positive_int(payload.get("track_total"))
        sort = payload.get("sort")
        duration = _positive_number(payload.get("duration"))
        queue_mode = payload.get("queue_mode")
        if queue_mode not in {"all_songs", "playlist", "autoplay"}:
            queue_mode = None
        repeat_mode = _int_value(payload.get("repeat_mode"))
        if repeat_mode not in {0, 1, 2}:
            repeat_mode = None
        playlist_repeat = _int_value(payload.get("playlist_repeat"))
        if playlist_repeat is not None and playlist_repeat < 0:
            playlist_repeat = None
        autoplay_loop = payload.get("autoplay_loop")
        if not isinstance(autoplay_loop, bool):
            autoplay_loop = None
        source = payload.get("playlist")
        if queue_mode not in {"playlist", "autoplay"} or not isinstance(source, str):
            source = None

        raw_state = _int_value(payload.get("state"))
        state = _STATE_MAP.get(raw_state) if raw_state is not None else None
        # The ESP retains player/status across an NRF reboot. A bare PAUSED state
        # with no observed playback is stale cache, not a paused song.
        if (
            state is MediaPlayerState.PAUSED
            and not self._playback_seen
            and song is None
            and song_index is None
            and _non_negative_number(payload.get("position")) is None
        ):
            state = MediaPlayerState.IDLE
        stop_after_playback = state is MediaPlayerState.IDLE and self._playback_seen
        if state is not None:
            self._http_state = state
            if state in (MediaPlayerState.PLAYING, MediaPlayerState.PAUSED):
                self._playback_seen = True
            if stop_after_playback:
                self._paused = True
                self._playing = False
                self._busy_until = 0.0
                if self._cancel_busy is not None:
                    self._cancel_busy()
                    self._cancel_busy = None
                self._stopped = False
            elif state is not MediaPlayerState.PLAYING:
                self._paused = state is MediaPlayerState.PAUSED
                self._playing = False
                self._busy_until = 0.0
                if self._cancel_busy is not None:
                    self._cancel_busy()
                    self._cancel_busy = None
            else:
                self._paused = False
                self._playing = True
            if state is MediaPlayerState.IDLE:
                self._stopped = False

        if stop_after_playback:
            self._mqtt_status_seen = True
            self._push(
                available=self._avail(msg),
                song=None,
                song_path=None,
                media_position_updated_at=None,
                shuffle=self._resolve_shuffle(
                    (sort == 1) if sort is not None else None
                ),
            )
            return

        display_song = self._status_song_for_display(song)
        display_song_path = song_path if display_song is not None else None
        position = _non_negative_number(payload.get("position"))
        position_updated_at = dt_util.utcnow() if position is not None else None
        if position is None and display_song is not None:
            position, position_updated_at = self._local_position_for_status(
                state, song, duration
            )
        changes: dict[str, object] = {
            "available": self._avail(msg),
            "song": display_song,
            "song_path": display_song_path,
            "song_index": song_index,
            "song_count": track_total,
            "media_position": position,
            "media_duration": duration,
            "shuffle": self._resolve_shuffle((sort == 1) if sort is not None else None),
            "queue_mode": queue_mode,
            "repeat_mode": repeat_mode,
            "playlist_repeat": playlist_repeat,
            "autoplay_loop": autoplay_loop,
            "source": source,
        }
        changes["media_position_updated_at"] = position_updated_at

        self._mqtt_status_seen = True
        self._push(**changes)

    def _status_song_for_display(self, song: str | None) -> str | None:
        if song is None:
            return None
        if (
            self._pending_song_change
            and song == self._last_status_song
            and self._hass.loop.time() < self._song_grace_until
        ):
            return None
        self._pending_song_change = False
        self._prev_song = None
        self._song_grace_until = 0.0
        self._last_status_song = song
        return song

    def _estimated_media_position(self, now) -> float | None:
        position = self._data.media_position
        updated_at = self._data.media_position_updated_at
        duration = self._data.media_duration
        if position is None:
            return None
        if self._data.state is MediaPlayerState.PLAYING and updated_at is not None:
            position += max(0.0, (now - updated_at).total_seconds())
        if duration is not None:
            position = min(position, duration)
        return position

    def _local_position_for_status(
        self,
        state: MediaPlayerState | None,
        song: str | None,
        duration: float | None,
    ) -> tuple[float | None, object | None]:
        if duration is None:
            return None, None
        now = dt_util.utcnow()
        if state is MediaPlayerState.PLAYING:
            if song is not None and song != self._data.song:
                return 0.0, now
            current = self._estimated_media_position(now)
            return (0.0 if current is None else current), now
        if state is MediaPlayerState.PAUSED:
            return self._estimated_media_position(now), None
        return None, None

    @callback
    def _on_device_name(self, msg: ReceiveMessage) -> None:
        self._push(
            device_name=str(msg.payload).strip() or None, available=self._avail(msg)
        )

    @callback
    def _on_network(self, msg: ReceiveMessage) -> None:
        """Adopt the retained LAN address without treating it as liveness."""
        try:
            payload = _json_payload(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict) or not isinstance(payload.get("ip"), str):
            return
        try:
            address = ipaddress.ip_address(payload["ip"])
        except ValueError:
            return
        if address.version != 4 or address.is_unspecified:
            return

        host = str(address)
        if self._http_host != host:
            self._http = HttpTransport(async_get_clientsession(self._hass), host)
            self._http_host = host
            if self._library_progress is not None:
                self._http.set_library_progress_listener(self._library_progress)
        # Retained metadata must not revive an offline device. Readiness remains
        # the liveness authority; this only gives HA the current LAN endpoint.
        self._push(ip_address=host, available=self._data.available)

    @callback
    def _on_volume(self, msg: ReceiveMessage) -> None:
        # CR#7: new firmware publishes percent here (matching /getVolume). Older
        # firmware sometimes emits raw MIDI-ish values; values outside HA's percent
        # range, including the boot-time 255 sentinel, remain unknown and the HTTP poll
        # keeps acting as the authoritative correction path.
        volume = _percent_volume(msg.payload)
        if volume is not None:
            self._mqtt_volume_seen = True
            self._push(volume=volume, available=self._avail(msg))

    @callback
    def _on_version(self, msg: ReceiveMessage) -> None:
        # CR#3: retained {"audio": "x.y.z", "midi": "x.y.z"} — the firmware version
        # over MQTT, so an MQTT-only install (no HTTP /debugJson) still populates
        # the device's sw_version. Empty strings mean "not known yet"; skip them.
        try:
            payload = _json_payload(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        changes: dict[str, object] = {}
        audio = payload.get("audio")
        midi = payload.get("midi")
        if isinstance(audio, str) and audio:
            changes["firmware_audio"] = audio
        if isinstance(midi, str) and midi:
            changes["firmware_midi"] = midi
        if changes:
            # Version is metadata, not liveness: a retained version message replays
            # on subscribe even while the device is offline, so don't let it flip
            # availability — …/ready (+ its Last-Will) is the availability authority.
            changes["available"] = self._data.available
            self._push(**changes)

    @callback
    def _on_update(self, msg: ReceiveMessage) -> None:
        # CR#3 ②: retained {"audio_latest","midi_latest","audio_url","midi_url"} — the
        # latest firmware the device's own backend check found. Feeds the update
        # entity's latest_version. Metadata (retained), so don't touch availability.
        try:
            payload = _json_payload(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        changes: dict[str, object] = {}
        audio = payload.get("audio_latest")
        midi = payload.get("midi_latest")
        if isinstance(audio, str) and audio:
            changes["latest_audio"] = audio
        if isinstance(midi, str) and midi:
            changes["latest_midi"] = midi
        if changes:
            changes["available"] = self._data.available
            self._push(**changes)

    @callback
    def _on_library_page(self, msg: ReceiveMessage) -> None:
        try:
            payload = _json_payload(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        request_id = payload.get("id")
        if not isinstance(request_id, str):
            return
        fut = self._library_waiters.pop(request_id, None)
        if fut is not None and not fut.done():
            fut.set_result(payload)

    @callback
    def _on_playlist_state(self, msg: ReceiveMessage) -> None:
        try:
            payload = _json_payload(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        request_id = payload.get("id")
        if not isinstance(request_id, str):
            return
        fut = self._playlist_waiters.pop(request_id, None)
        if fut is not None and not fut.done():
            fut.set_result(payload)

    @callback
    def _on_autoplay_state(self, msg: ReceiveMessage) -> None:
        try:
            payload = _json_payload(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return
        request_id = payload.get("id")
        if not isinstance(request_id, str):
            return
        fut = self._autoplay_waiters.pop(request_id, None)
        if fut is not None and not fut.done():
            fut.set_result(payload)

    @callback
    def _on_ready(self, msg: ReceiveMessage) -> None:
        """Apply the NRF-owned playback readiness reported by the ESP gateway."""
        readiness = str(msg.payload).strip().upper()
        if readiness == MQTT_PAYLOAD_OFFLINE:
            self._push(available=False, readiness="OFFLINE")
            return
        # Older firmware reports OK. New firmware distinguishes a reachable gateway
        # from a piano that has completed its MIDI and SD-card startup work.
        self._push(
            available=readiness in {"READY", "OK"},
            readiness=readiness,
        )
        self._arm_watchdog()

    # -- state machine ------------------------------------------------------
    def _busy_active(self) -> bool:
        return self._hass.loop.time() < self._busy_until

    def _resolve_song(
        self, observed: str | None, *, live_mqtt: bool = False
    ) -> str | None:
        """Suppress the pre-(re)play title until a genuinely new one appears."""
        if observed is None:
            return None
        if live_mqtt:
            self._prev_song = None
            self._song_grace_until = 0.0
            return observed
        within_grace = self._hass.loop.time() < self._song_grace_until
        if observed == self._prev_song and within_grace:
            return None  # still the song from before play → caller shows a placeholder
        self._prev_song = None  # a different song (or the grace lapsed) → trust it
        return observed

    def _suppress_current_title(self) -> None:
        """Blank the stale title until a new one arrives (card then shows 'Loading…').

        Used on play/next/prev AND when a song ends mid-autoplay, so the card shows a
        placeholder between songs, not the just-ended title. It emits the clear itself
        because the state often does not change (still PLAYING) — which is why the title
        used to clear only on a manual play from idle.
        """
        self._prev_song = self._data.song
        if self._prev_song is not None:
            self._last_status_song = self._prev_song
        self._pending_song_change = True
        self._song_grace_until = self._hass.loop.time() + SONG_UNKNOWN_GRACE
        self._push(
            song=None,
            song_path=None,
            media_position=None,
            media_position_updated_at=None,
        )

    def _optimistic_new_song(self) -> None:
        """On play/next/prev: optimistically PLAYING + clear the now-stale title."""
        self._stopped = False
        self._busy_until = self._hass.loop.time() + BUSY_DEBOUNCE
        self._suppress_current_title()

    def _optimistic_resume(self) -> None:
        """On pause -> play: resume the current title/progress, do not show Loading."""
        self._stopped = False
        self._paused = False
        self._playing = True
        self._pending_song_change = False
        self._prev_song = None
        self._song_grace_until = 0.0
        changes: dict[str, object] = {}
        if self._data.media_position is not None:
            changes["media_position_updated_at"] = dt_util.utcnow()
        self._push(**changes)

    def _resolve_shuffle(self, observed: bool | None) -> bool | None:
        """Hold a just-set shuffle target while /playerStatus.sort catches up."""
        target = self._shuffle_target
        if target is None:
            return observed
        if observed == target:
            self._shuffle_target = None
            return observed
        if self._hass.loop.time() < self._shuffle_hold_until:
            return target
        self._shuffle_target = None
        return observed

    def _derive_state(self) -> MediaPlayerState | None:
        if self._paused:
            return MediaPlayerState.PAUSED
        # Solenoid activity is the real-time truth unless a known Stop is being shown
        # as PAUSED/Loading. Busy also covers boot before /playerStatus is responsive.
        if self._playing or self._busy_active():
            return MediaPlayerState.PLAYING
        if self._http_state is MediaPlayerState.PAUSED:
            return MediaPlayerState.PAUSED
        # Before any playback is known, an issued Stop can still settle to true idle.
        # After playback, Stop is represented by _paused so the media card stays alive.
        if self._stopped:
            return MediaPlayerState.IDLE
        # Otherwise the authoritative HTTP poll, or None until the piano answers.
        return self._http_state

    def _push(self, **changes: object) -> None:
        # Any message from the device proves it is online; the watchdog handles offline.
        changes.setdefault("available", True)
        changes["state"] = self._derive_state()
        new = self._data.merge(**changes)
        if new == self._data:
            return  # idempotent: the device publishes every status twice
        self._data = new
        self._emit(new)

    def invalidate(self) -> None:
        # After a power cycle, forget everything so the next poll re-seeds and the
        # media_player shows "getting ready" rather than stale state.
        self._playing = self._paused = self._stopped = False
        self._playback_seen = False
        self._busy_until = 0.0
        self._http_state = None
        self._mqtt_status_seen = False
        self._mqtt_volume_seen = False
        self._shuffle_target = None
        self._shuffle_hold_until = 0.0
        self._prev_song = None
        self._last_status_song = None
        self._pending_song_change = False
        self._song_grace_until = 0.0
        self._data = self._data.merge(
            available=False,
            state=None,
            song=None,
            song_path=None,
            song_index=None,
            media_position=None,
            media_duration=None,
            media_position_updated_at=None,
            volume=None,
            busy=None,
        )

    # -- availability watchdog ---------------------------------------------
    def _arm_watchdog(self) -> None:
        if self._closed:
            return
        if self._cancel_watchdog is not None:
            self._cancel_watchdog()
        self._cancel_watchdog = async_call_later(
            self._hass, READY_WATCHDOG.total_seconds(), self._watchdog_fired
        )

    @callback
    def _watchdog_fired(self, _now: object) -> None:
        self._hass.async_create_task(self._async_cross_check())

    async def _async_cross_check(self) -> None:
        if self._closed:
            return
        if self._http is not None:
            self._data = self._data.merge(available=False)
            try:
                data = await self.async_fetch_snapshot()
            except Exception:
                self._push(available=False)
                self._arm_watchdog()
                return
            if self._closed:  # async_close can land during the HTTP await
                return
            self._data = data
            self._emit(data)
            self._arm_watchdog()
            return
        if self._closed:  # async_close can land during the HTTP await
            return
        self._push(available=False)
        self._arm_watchdog()

    # -- command publishes --------------------------------------------------
    async def _publish(self, command: dict) -> None:
        await mqtt.async_publish(
            self._hass, self._command_topic, json.dumps({"command": command})
        )

    async def _request_response(
        self, topic: str, waiters: dict[str, asyncio.Future[dict]], payload: dict
    ) -> dict | None:
        request_id = uuid.uuid4().hex
        payload = {"id": request_id, **payload}
        fut: asyncio.Future[dict] = self._hass.loop.create_future()
        waiters[request_id] = fut
        await mqtt.async_publish(self._hass, topic, json.dumps(payload))
        try:
            return await asyncio.wait_for(fut, timeout=_MQTT_LIBRARY_TIMEOUT)
        except asyncio.TimeoutError:
            waiters.pop(request_id, None)
            return None

    def _songlist_fresh(self) -> bool:
        if not self._song_titles or self._song_cache_at is None:
            return False
        return self._hass.loop.time() - self._song_cache_at < SONGLIST_TTL

    async def _fetch_song_list_http_fallback(self, force: bool) -> list[str]:
        if self._http is None:
            return []
        return await self._http.async_fetch_song_list(force=force)

    async def _fetch_playlists_http_fallback(self) -> list[str]:
        if self._http is None:
            return []
        return await self._http.async_fetch_playlists()

    async def async_play(self, index: int | None = None) -> None:
        # Verified live (2026-06-03): {"exec":"Play","params":N} is 0-based.
        self._playback_seen = True
        if index is None and self._data.state is MediaPlayerState.PAUSED:
            self._optimistic_resume()
        else:
            self._optimistic_new_song()
        command: dict = {"exec": "Play"}
        if index is not None and index >= 0:
            command["params"] = int(index)
        if not self._mqtt_live and self._http is not None:
            await self._http.async_play(index)
        else:
            await self._publish(command)
        self._push()

    async def async_play_path(self, path: str) -> None:
        """Ask the NRF to resolve a path against its current SD-card library."""
        self._playback_seen = True
        self._optimistic_new_song()
        if not self._mqtt_live and self._http is not None:
            await self._http.async_play_path(path)
        else:
            await self._publish(
                {"type": "MIDIPlayer", "exec": "Playback", "params": {"song": path}}
            )
        self._push()

    async def async_pause(self) -> None:
        if not self._mqtt_live and self._http is not None:
            await self._http.async_pause()
        else:
            await self._publish({"exec": "Pause"})

    async def async_stop(self) -> None:
        if not self._mqtt_live and self._http is not None:
            await self._http.async_stop()
        else:
            await self._publish({"exec": "Stop"})
        # Once playback has been seen, the device's Stop state is not HA "idle": keep
        # the card in PAUSED/Loading so the next Play can resume the visible surface.
        # On a cold/unknown stop, fall back to IDLE.
        self._stopped = True
        self._playing = False
        self._paused = self._playback_seen
        now = self._hass.loop.time()
        self._busy_until = min(self._busy_until, now + STOP_CONFIRM)
        if self._cancel_busy is not None:
            self._cancel_busy()
        self._cancel_busy = async_call_later(
            self._hass, max(0.0, self._busy_until - now), self._busy_expired
        )
        self._push()

    async def async_next(self) -> None:
        self._optimistic_new_song()
        if not self._mqtt_live and self._http is not None:
            await self._http.async_next()
        else:
            await self._publish({"exec": "Next"})
        self._push()

    async def async_previous(self) -> None:
        self._optimistic_new_song()
        if not self._mqtt_live and self._http is not None:
            await self._http.async_previous()
        else:
            await self._publish({"exec": "Prev"})
        self._push()

    async def async_set_volume(self, level_1_100: int) -> None:
        # Optimistic percent so the slider tracks instantly; the poll reads it back.
        if level_1_100 > 0:
            self._pre_mute_volume = int(level_1_100)
        self._mqtt_volume_seen = True
        self._push(volume=int(level_1_100))
        if not self._mqtt_live and self._http is not None:
            await self._http.async_set_volume(level_1_100)
        else:
            await self._publish({"exec": "SetVolume", "params": int(level_1_100)})

    async def async_mute_volume(self, mute: bool) -> None:
        if mute and self._data.volume is not None and self._data.volume > 0:
            self._pre_mute_volume = self._data.volume
        target = 0 if mute else self._pre_mute_volume
        self._mqtt_volume_seen = True
        self._push(volume=target)
        if not self._mqtt_live and self._http is not None:
            await self._http.async_mute_volume(mute)
        else:
            await self._publish({"exec": "SetMute", "params": bool(mute)})

    async def async_set_shuffle(self, shuffle: bool) -> None:
        self._shuffle_target = shuffle
        self._shuffle_hold_until = self._hass.loop.time() + SHUFFLE_HOLD_GRACE
        if not self._mqtt_live and self._http is not None:
            await self._http.async_set_shuffle(shuffle)
        else:
            await self._publish({"exec": "Sort", "params": 1 if shuffle else 0})
        self._push(shuffle=shuffle)

    async def async_set_repeat(self, mode: int) -> None:
        if mode not in (0, 1, 2):
            raise ValueError(f"invalid repeat mode: {mode}")
        if not self._mqtt_live and self._http is not None:
            await self._http.async_set_repeat(mode)
        else:
            await self._publish({"exec": "Repeat", "params": mode})
        self._push(queue_mode="all_songs", repeat_mode=mode)

    async def async_select_playlist(self, name: str) -> None:
        # Match the rest of hybrid control: an offline MQTT transport must not
        # prevent playlist playback when the piano's HTTP API is still reachable.
        if not self._mqtt_live and self._http is not None:
            await self._http.async_fetch_playlists()
            await self._http.async_select_playlist(name)
            self._push(source=name)
            return

        if name not in self._playlist_names:
            await self.async_fetch_playlists()
        try:
            index = self._playlist_names.index(name)
        except ValueError:
            await self._publish(
                {"type": "MIDIPlayer", "exec": "Playback", "params": {"playlist": name}}
            )
        else:
            response = await self._request_response(
                self._playlist_request_topic,
                self._playlist_waiters,
                {"op": "play", "index": index},
            )
            if response is None and self._http is not None:
                await self._http.async_fetch_playlists()
                await self._http.async_select_playlist(name)
        self._push(source=name)

    async def async_reboot(self) -> None:
        # Prefer MQTT when the device is live (or when MQTT is the only transport).
        # Hybrid mode falls back to HTTP only after MQTT has gone stale/offline.
        if self._mqtt_live or self._http is None:
            await self._publish({"exec": "Reboot"})
            self.invalidate()
            self._emit(self._data)
            return
        await self._http.async_reboot()

    async def async_fetch_debug_json(self) -> dict[str, object] | None:
        """Raw diagnostics are a local HTTP-only read, never a MQTT upload."""
        if self._http is None:
            return None
        return await self._http.async_fetch_debug_json()

    # -- snapshot (HTTP fallback/backfill) + library -----------------------
    async def async_fetch_snapshot(self) -> ProdigyData:
        mqtt_is_live = self._mqtt_live
        if self._http is not None and not mqtt_is_live:
            playback = await self._http.async_fetch_playback(
                fetch_volume=not self._mqtt_volume_seen
            )
            volume = (
                self._data.volume
                if self._mqtt_volume_seen or playback.volume is None
                else playback.volume
            )
            self._http_state = playback.state
            if playback.state == MediaPlayerState.IDLE:
                self._stopped = False  # device confirms idle → release the stop hold
            song = self._resolve_song(playback.song)
            # HTTP is authoritative whenever this piano is not live on MQTT. In
            # particular, it must replace an MQTT watchdog's stale OFFLINE with the
            # ESP's current WARMING_UP/READY state.
            merged = self._data.merge(
                available=playback.available,
                readiness=playback.readiness,
                volume=volume,
                song=song,
                song_path=playback.song_path if song is not None else None,
                song_index=playback.song_index,
                song_count=playback.song_count,
                media_position=playback.media_position,
                media_duration=playback.media_duration,
                media_position_updated_at=playback.media_position_updated_at,
                shuffle=self._resolve_shuffle(playback.shuffle),
                queue_mode=playback.queue_mode,
                repeat_mode=playback.repeat_mode,
                playlist_repeat=playback.playlist_repeat,
                autoplay_loop=playback.autoplay_loop,
                source=playback.source,
                source_list=playback.source_list or self._data.source_list,
                busy=None,
                ip_address=playback.ip_address or self._data.ip_address,
            )
            if playback.available and merged.firmware_audio is None:
                # Firmware is static. Fetch it once only after the HTTP endpoint is
                # actually reachable, rather than repeatedly probing a cold piano.
                info = await self._http.async_get_device_info()
                if info:
                    merged = merged.merge(
                        firmware_audio=info["audio_version"],
                        firmware_midi=info["midi_version"],
                    )
            self._data = merged
        self._data = self._data.merge(state=self._derive_state())
        return self._data

    def set_library_progress_listener(self, listener) -> None:
        # The scan runs on the composed HTTP transport, so forward progress there.
        super().set_library_progress_listener(listener)
        if self._http is not None:
            self._http.set_library_progress_listener(listener)

    async def async_fetch_song_list(self, force: bool = False) -> list[str]:
        if not force and not self._song_lock.locked() and self._songlist_fresh():
            return list(self._song_titles)

        async with self._song_lock:
            if not force and self._songlist_fresh():
                return list(self._song_titles)

            titles: list[str] = []
            paths: list[str] = []
            seen: set[str] = set()
            self._emit_library_progress(0, True)
            LOGGER.info("Starting MQTT library scan")
            try:
                for page in range(MAX_SCAN_PAGES):
                    LOGGER.debug("Requesting MQTT library page %s", page)
                    payload = await self._request_response(
                        self._library_request_topic,
                        self._library_waiters,
                        {"op": "scan", "page": page},
                    )
                    if not isinstance(payload, dict):
                        LOGGER.info(
                            "Stopping MQTT library scan at page %s: no response", page
                        )
                        break
                    items = payload.get("items")
                    if not isinstance(items, list):
                        LOGGER.info(
                            "Stopping MQTT library scan at page %s: invalid items",
                            page,
                        )
                        break
                    page_paths: list[str] = []
                    for item in items:
                        if not isinstance(item, str):
                            continue
                        path = item.strip()
                        if not path:
                            continue
                        page_paths.append(path)
                        if path not in seen:
                            seen.add(path)
                            paths.append(path)
                            titles.append(title_from_path(path))
                    self._emit_library_progress(len(titles), True)
                    LOGGER.info(
                        "MQTT library page %s: raw_items=%s valid_items=%s total=%s",
                        page,
                        len(items),
                        len(page_paths),
                        len(titles),
                    )
                    if len(page_paths) < SONGLIST_PAGE_SIZE:
                        LOGGER.info(
                            "Finished MQTT library scan at page %s: short page "
                            "(%s < %s)",
                            page,
                            len(page_paths),
                            SONGLIST_PAGE_SIZE,
                        )
                        break
            except Exception:
                LOGGER.exception(
                    "MQTT library scan failed after caching %s songs", len(titles)
                )
                raise
            finally:
                self._emit_library_progress(len(titles), False)

            if not titles:
                if self._http is None:
                    return []
                # A hybrid fallback must warm this transport's cache too. Otherwise
                # the READY prefetch reports a count from HTTP, but the next browse
                # sees an empty MQTT cache and starts the full scan again.
                titles = await self._http.async_fetch_song_list(force=force)
                paths = await self._http.async_fetch_song_paths()

            self._song_titles = titles
            self._song_paths = paths
            self._song_cache_at = self._hass.loop.time()
            LOGGER.info("MQTT library scan cached %s songs", len(titles))
            return list(titles)

    async def async_fetch_song_paths(self, force: bool = False) -> list[str]:
        # The READY prefetch fills this transport's MQTT cache. The playlist editor
        # must consume that cache too; otherwise merely opening it re-scans through
        # HTTP despite an already-complete MQTT library.
        await self.async_fetch_song_list(force=force)
        return list(self._song_paths)

    async def async_fetch_playlists(self) -> list[str]:
        playlists = await self.async_fetch_playlist_definitions()
        names = [
            item["name"]
            for item in playlists
            if isinstance(item.get("name"), str)
        ]
        self._playlist_names = names
        self._push(source_list=names)
        return names

    async def async_fetch_playlist_definitions(self) -> list[dict[str, object]]:
        payload = await self._request_response(
            self._playlist_request_topic,
            self._playlist_waiters,
            {"op": "get"},
        )
        playlists_out: list[dict[str, object]] = []
        playlists = payload.get("playlists") if isinstance(payload, dict) else None
        received_playlist_list = isinstance(playlists, list)
        if isinstance(playlists, list):
            for item in playlists:
                if isinstance(item, dict):
                    playlists_out.append(dict(item))
        # An empty list is a valid, meaningful MQTT result. Only use HTTP when
        # MQTT did not produce a playlist list at all.
        if not received_playlist_list and self._http is not None:
            playlists_out = await self._http.async_fetch_playlist_definitions()
        self._playlist_defs = playlists_out
        self._playlist_names = [
            item["name"]
            for item in playlists_out
            if isinstance(item.get("name"), str)
        ]
        return list(playlists_out)

    async def async_save_playlist_definitions(
        self, playlists: list[dict[str, object]]
    ) -> None:
        payload = await self._request_response(
            self._playlist_request_topic,
            self._playlist_waiters,
            {"op": "set", "playlists": playlists},
        )
        if payload is None and self._http is not None:
            await self._http.async_save_playlist_definitions(playlists)
        self._playlist_defs = [dict(item) for item in playlists]
        names = [
            item["name"]
            for item in playlists
            if isinstance(item.get("name"), str)
        ]
        self._playlist_names = names
        self._push(source_list=names)

    async def async_fetch_autoplay_config(self) -> dict[str, object]:
        payload = await self._request_response(
            self._autoplay_request_topic, self._autoplay_waiters, {"op": "get"}
        )
        config = payload.get("config") if isinstance(payload, dict) else None
        if isinstance(config, dict):
            return dict(config)
        if self._http is not None:
            return await self._http.async_fetch_autoplay_config()
        return {}

    async def async_save_autoplay_config(self, config: dict[str, object]) -> None:
        payload = await self._request_response(
            self._autoplay_request_topic,
            self._autoplay_waiters,
            {"op": "set", "config": config},
        )
        if payload is None and self._http is not None:
            await self._http.async_save_autoplay_config(config)
