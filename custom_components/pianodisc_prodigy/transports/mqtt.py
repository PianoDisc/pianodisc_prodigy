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
import json
import uuid

from homeassistant.components import mqtt
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.components.mqtt import ReceiveMessage
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from ..const import (
    BUSY_DEBOUNCE,
    MAX_SCAN_PAGES,
    MQTT_PAYLOAD_OFFLINE,
    MQTT_TOPIC_BUSY,
    MQTT_TOPIC_COMMAND,
    MQTT_TOPIC_DEVICE_NAME,
    MQTT_TOPIC_LIBRARY_PAGE,
    MQTT_TOPIC_LIBRARY_REQUEST,
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


class MqttTransport(Transport):
    """MQTT command/status transport, optionally backed by HTTP for legacy gaps."""

    @property
    def uses_push_updates(self) -> bool:
        return True

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str,
        http: HttpTransport | None = None,
    ) -> None:
        super().__init__()
        self._hass = hass
        self._http = http
        self._root = f"{MQTT_TOPIC_ROOT}/{device_id}"
        self._command_topic = f"{self._root}/{MQTT_TOPIC_COMMAND}"
        self._library_request_topic = f"{self._root}/{MQTT_TOPIC_LIBRARY_REQUEST}"
        self._playlist_request_topic = f"{self._root}/{MQTT_TOPIC_PLAYLIST_REQUEST}"
        self._data = ProdigyData()
        # State inputs. The displayed state is derived from these (see _derive_state).
        self._http_state: MediaPlayerState | None = None  # last /playerStatus state
        self._busy_until = 0.0  # busy counts as "playing" until this loop time
        self._stopped = False  # a Stop we issued holds IDLE until play / confirmed idle
        self._paused = False
        self._playing = False
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
            MQTT_TOPIC_VERSION: self._on_version,
            MQTT_TOPIC_UPDATE: self._on_update,
            MQTT_TOPIC_LIBRARY_PAGE: self._on_library_page,
            MQTT_TOPIC_PLAYLIST_STATE: self._on_playlist_state,
        }
        for sub, handler in handlers.items():
            unsub = await mqtt.async_subscribe(
                self._hass, f"{self._root}/{sub}", handler
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
        for waiters in (self._library_waiters, self._playlist_waiters):
            for fut in waiters.values():
                if not fut.done():
                    fut.cancel()
            waiters.clear()

    # -- status overlay (MQTT push) ----------------------------------------
    @callback
    def _avail(self, msg: ReceiveMessage) -> bool:
        # CR#6: these status topics are now published retained, so the broker replays
        # them on every (re)subscribe — including while the device is offline. A
        # retained replay is last-known state, NOT proof the device is online now, so
        # it must preserve availability and leave …/ready (+ its Last-Will) and the
        # watchdog as the authority. A live (non-retained) publish still proves online.
        return True if not msg.retain else self._data.available

    @callback
    def _on_busy(self, msg: ReceiveMessage) -> None:
        busy = _truthy(msg.payload)
        if msg.retain:
            # Retained replay on subscribe: reflect the value but don't treat it as
            # live solenoid activity (no debounce hold) or as a liveness signal.
            self._push(busy=busy, available=self._data.available)
            return
        if busy:  # keys striking → playing; extend the hold and cancel any expiry
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
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict):
            return

        raw_song = payload.get("song")
        song = (
            title_from_path(raw_song)
            if isinstance(raw_song, str) and raw_song.strip()
            else None
        )
        song_index = _track_index(payload.get("track_index"))
        track_total = _positive_int(payload.get("track_total"))
        sort = payload.get("sort")
        duration = _positive_number(payload.get("duration"))

        raw_state = _int_value(payload.get("state"))
        state = _STATE_MAP.get(raw_state) if raw_state is not None else None
        was_playing = (
            self._data.state is MediaPlayerState.PLAYING or self._busy_active()
        )
        new_song_hint = (
            song is not None
            and (song != self._data.song or song_index != self._data.song_index)
        )
        intersong_stop = (
            state is MediaPlayerState.IDLE
            and was_playing
            and not self._stopped
            and new_song_hint
        )
        if state is not None:
            self._http_state = state
            self._paused = state is MediaPlayerState.PAUSED
            self._playing = state is MediaPlayerState.PLAYING
            if intersong_stop:
                self._hold_playing_for_song_gap()
            elif state is not MediaPlayerState.PLAYING:
                self._busy_until = 0.0
                if self._cancel_busy is not None:
                    self._cancel_busy()
                    self._cancel_busy = None
            if state is MediaPlayerState.IDLE:
                self._stopped = False

        if intersong_stop:
            self._mqtt_status_seen = True
            self._push(
                available=self._avail(msg),
                song=None,
                media_position_updated_at=None,
                shuffle=self._resolve_shuffle(
                    (sort == 1) if sort is not None else None
                ),
            )
            return

        display_song = self._status_song_for_display(song)
        position = _non_negative_number(payload.get("position"))
        position_updated_at = dt_util.utcnow() if position is not None else None
        if position is None and display_song is not None:
            position, position_updated_at = self._local_position_for_status(
                state, song, duration
            )
        changes: dict[str, object] = {
            "available": self._avail(msg),
            "song": display_song,
            "song_index": song_index,
            "song_count": track_total,
            "media_position": position,
            "media_duration": duration,
            "shuffle": self._resolve_shuffle((sort == 1) if sort is not None else None),
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
            payload = json.loads(msg.payload)
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
            payload = json.loads(msg.payload)
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
            payload = json.loads(msg.payload)
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
            payload = json.loads(msg.payload)
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
    def _on_ready(self, msg: ReceiveMessage) -> None:
        # CR#2: …/ready now carries availability. The broker's retained Last-Will
        # publishes OFFLINE the instant the device drops ungracefully, so honor it
        # immediately instead of waiting out the heartbeat watchdog.
        if str(msg.payload).strip().upper() == MQTT_PAYLOAD_OFFLINE:
            self._push(available=False)
            return
        # "OK" heartbeat → available; keep the watchdog as a backstop for the case
        # where the broker itself becomes unreachable (no Last-Will delivered).
        self._push(available=True)
        self._arm_watchdog()

    # -- state machine ------------------------------------------------------
    def _busy_active(self) -> bool:
        return self._hass.loop.time() < self._busy_until

    def _hold_playing_for_song_gap(self) -> None:
        """Keep the media card in PLAYING while autoplay advances between songs."""
        self._busy_until = self._hass.loop.time() + SONG_UNKNOWN_GRACE
        if self._cancel_busy is not None:
            self._cancel_busy()
        self._cancel_busy = async_call_later(
            self._hass, SONG_UNKNOWN_GRACE, self._busy_expired
        )

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
        self._push(song=None, media_position=None, media_position_updated_at=None)

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
        # Solenoid activity is the real-time truth, checked BEFORE the stop-hold: a
        # missed Stop (keys still striking) stays PLAYING so the user can retry, not a
        # false Idle. Busy also covers boot before /playerStatus is responsive.
        if self._playing or self._busy_active():
            return MediaPlayerState.PLAYING
        if self._http_state is MediaPlayerState.PAUSED:
            return MediaPlayerState.PAUSED
        # A Stop we issued, now keys are quiet → really stopped (IDLE), overriding the
        # device's /playerStatus (lags 1-2 min). Released on play / a confirmed-0 poll.
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
        if index is None and self._data.state is MediaPlayerState.PAUSED:
            self._optimistic_resume()
        else:
            self._optimistic_new_song()
        command: dict = {"exec": "Play"}
        if index is not None and index >= 0:
            command["params"] = int(index)
        await self._publish(command)
        self._push()

    async def async_pause(self) -> None:
        await self._publish({"exec": "Pause"})

    async def async_stop(self) -> None:
        await self._publish({"exec": "Stop"})
        # Verify before claiming IDLE: keep the busy hold (capped at STOP_CONFIRM) so
        # the state stays PLAYING until …/busy goes quiet. If keys keep striking the
        # Stop was MISSED → stays PLAYING (Stop button remains); only quiet keys → IDLE
        # (_derive checks busy BEFORE the _stopped flag). /playerStatus lags 1-2 min.
        self._stopped = True
        self._playing = self._paused = False
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
        await self._publish({"exec": "Next"})
        self._push()

    async def async_previous(self) -> None:
        self._optimistic_new_song()
        await self._publish({"exec": "Prev"})
        self._push()

    async def async_set_volume(self, level_1_100: int) -> None:
        # Optimistic percent so the slider tracks instantly; the poll reads it back.
        if level_1_100 > 0:
            self._pre_mute_volume = int(level_1_100)
        self._mqtt_volume_seen = True
        self._push(volume=int(level_1_100))
        await self._publish({"exec": "SetVolume", "params": int(level_1_100)})

    async def async_mute_volume(self, mute: bool) -> None:
        if mute and self._data.volume is not None and self._data.volume > 0:
            self._pre_mute_volume = self._data.volume
        target = 0 if mute else self._pre_mute_volume
        self._mqtt_volume_seen = True
        self._push(volume=target)
        await self._publish({"exec": "SetMute", "params": bool(mute)})

    async def async_set_shuffle(self, shuffle: bool) -> None:
        self._shuffle_target = shuffle
        self._shuffle_hold_until = self._hass.loop.time() + SHUFFLE_HOLD_GRACE
        await self._publish({"exec": "Sort", "params": 1 if shuffle else 0})
        self._push(shuffle=shuffle)

    async def async_select_playlist(self, name: str) -> None:
        if name not in self._playlist_names:
            await self.async_fetch_playlists()
        try:
            index = self._playlist_names.index(name)
        except ValueError:
            await self._publish(
                {"type": "MIDIPlayer", "exec": "Playback", "params": {"playlist": name}}
            )
        else:
            await self._request_response(
                self._playlist_request_topic,
                self._playlist_waiters,
                {"op": "play", "index": index},
            )
        self._push(source=name)

    async def async_reboot(self) -> None:
        # Prefer MQTT when the device is live (or when MQTT is the only transport).
        # Hybrid mode falls back to HTTP only after MQTT has gone stale/offline.
        if self._data.available or self._http is None:
            await self._publish({"exec": "Reboot"})
            self.invalidate()
            self._emit(self._data)
            return
        await self._http.async_reboot()

    # -- snapshot (HTTP fallback/backfill) + library -----------------------
    async def async_fetch_snapshot(self) -> ProdigyData:
        mqtt_is_live = self._data.available and self._mqtt_status_seen
        if self._http is not None and not mqtt_is_live:
            playback = await self._http.async_fetch_playback(
                fetch_volume=not self._mqtt_volume_seen
            )
            if playback.available:
                volume = (
                    self._data.volume
                    if self._mqtt_volume_seen or playback.volume is None
                    else playback.volume
                )
                if mqtt_is_live:
                    merged = self._data.merge(
                        available=True,
                        volume=volume,
                        source_list=playback.source_list or self._data.source_list,
                    )
                else:
                    self._http_state = playback.state
                    if playback.state == MediaPlayerState.IDLE:
                        self._stopped = (
                            False  # device confirms idle → release the stop hold
                        )
                    merged = self._data.merge(
                        available=True,
                        volume=volume,
                        song=self._resolve_song(playback.song),
                        song_index=playback.song_index,
                        song_count=playback.song_count,
                        media_position=playback.media_position,
                        media_duration=playback.media_duration,
                        media_position_updated_at=playback.media_position_updated_at,
                        shuffle=self._resolve_shuffle(playback.shuffle),
                        source_list=playback.source_list or self._data.source_list,
                    )
                if merged.firmware_audio is None:  # firmware is static → fetch once
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
            try:
                for page in range(MAX_SCAN_PAGES):
                    payload = await self._request_response(
                        self._library_request_topic,
                        self._library_waiters,
                        {"op": "scan", "page": page},
                    )
                    if not isinstance(payload, dict):
                        break
                    items = payload.get("items")
                    if not isinstance(items, list):
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
                    if len(page_paths) < SONGLIST_PAGE_SIZE:
                        break
            finally:
                self._emit_library_progress(len(titles), False)

            if not titles:
                return await self._fetch_song_list_http_fallback(force=force)

            self._song_titles = titles
            self._song_paths = paths
            self._song_cache_at = self._hass.loop.time()
            return list(titles)

    async def async_fetch_song_paths(self, force: bool = False) -> list[str]:
        if self._http is not None:
            return await self._http.async_fetch_song_paths(force=force)
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
        if isinstance(playlists, list):
            for item in playlists:
                if isinstance(item, dict):
                    playlists_out.append(dict(item))
        if not playlists_out and self._http is not None:
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
