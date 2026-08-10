"""MQTT transport — a real-time overlay on an authoritative HTTP poll.

Wire reality (live-captured 2026-06-08): during hospitality autoplay the piano keeps
``…/playing`` FALSE and only toggles ``…/busy`` (per-note solenoid bursts); ``…/song``
and ``…/volume`` publish on change only; and ``…/volume`` is a **MIDI 0-127** value, not
the percent a slider needs. The piano's HTTP API is authoritative — ``/playerStatus``
reports the real ``state`` (0/1/2) during autoplay and ``/getVolume`` is the percent
volume. So in MQTT mode we **poll HTTP for state/song/volume** and use MQTT as the
real-time overlay:

* ``…/busy`` → instant "playing" (HTTP then confirms + sustains it through busy's gaps),
* ``…/song`` → instant now-playing title,
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

from ..const import (
    BUSY_DEBOUNCE,
    MAX_SCAN_PAGES,
    MQTT_PAYLOAD_OFFLINE,
    MQTT_TOPIC_BUSY,
    MQTT_TOPIC_COMMAND,
    MQTT_TOPIC_DEVICE_NAME,
    MQTT_TOPIC_LIBRARY_PAGE,
    MQTT_TOPIC_LIBRARY_REQUEST,
    MQTT_TOPIC_PAUSED,
    MQTT_TOPIC_PLAYING,
    MQTT_TOPIC_PLAYLIST_REQUEST,
    MQTT_TOPIC_PLAYLIST_STATE,
    MQTT_TOPIC_READY,
    MQTT_TOPIC_ROOT,
    MQTT_TOPIC_SONG,
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


def _truthy(payload: object) -> bool:
    """`TRUE`/`FALSE` (any case) -> bool. The device uses uppercase strings."""
    return str(payload).strip().upper() == "TRUE"


def _percent_volume(payload: object) -> int | None:
    """Parse a 0..100 percent volume payload; reject boot/legacy sentinels."""
    try:
        volume = int(str(payload).strip())
    except ValueError:
        return None
    return volume if 0 <= volume <= 100 else None


class MqttTransport(Transport):
    """MQTT real-time overlay; state/song/volume polled from the composed HTTP."""

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
        self._paused = False  # MQTT …/paused
        self._playing = False  # MQTT …/playing (rarely TRUE; busy is the real signal)
        self._mqtt_song: str | None = None
        self._mqtt_volume_seen = False
        self._shuffle_target: bool | None = None
        self._shuffle_hold_until = 0.0
        # After a (re)play, suppress this stale title until a new one appears.
        self._prev_song: str | None = None
        self._song_grace_until = 0.0
        self._cancel_busy: Callable[[], None] | None = None
        self._unsubs: list[Callable[[], None]] = []
        self._cancel_watchdog: Callable[[], None] | None = None
        self._closed = False
        self._library_waiters: dict[str, asyncio.Future[dict]] = {}
        self._playlist_waiters: dict[str, asyncio.Future[dict]] = {}
        self._song_titles: list[str] = []
        self._song_cache_at: float | None = None
        self._song_lock = asyncio.Lock()
        self._playlist_names: list[str] = []

    # -- lifecycle ----------------------------------------------------------
    async def async_setup(self) -> None:
        handlers = {
            MQTT_TOPIC_PLAYING: self._on_playing,
            MQTT_TOPIC_PAUSED: self._on_paused,
            MQTT_TOPIC_BUSY: self._on_busy,
            MQTT_TOPIC_SONG: self._on_song,
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
    def _on_playing(self, msg: ReceiveMessage) -> None:
        playing = _truthy(msg.payload)
        ended = (
            self._playing and not playing
        )  # a song just finished (autoplay gap / stop)
        self._playing = playing
        if ended:
            # Suppress the just-ended title so the card shows "Loading…" between
            # autoplay songs (not the old one) until the next …/song arrives.
            self._suppress_current_title()
        else:
            self._push(available=self._avail(msg))

    @callback
    def _on_paused(self, msg: ReceiveMessage) -> None:
        self._paused = _truthy(msg.payload)
        if self._paused:
            self._prev_song = None
            self._song_grace_until = 0.0
        self._push(available=self._avail(msg))

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
    def _on_song(self, msg: ReceiveMessage) -> None:
        self._mqtt_song = str(msg.payload).strip() or None
        self._push(song=self._resolve_song(self._mqtt_song), available=self._avail(msg))

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

    def _resolve_song(self, observed: str | None) -> str | None:
        """Suppress the pre-(re)play title until a genuinely new one appears."""
        if observed is None:
            return None
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
        self._song_grace_until = self._hass.loop.time() + SONG_UNKNOWN_GRACE
        self._mqtt_song = None
        self._push(song=None)

    def _optimistic_new_song(self) -> None:
        """On play/next/prev: optimistically PLAYING + clear the now-stale title."""
        self._stopped = False
        self._busy_until = self._hass.loop.time() + BUSY_DEBOUNCE
        self._suppress_current_title()

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
        # false Idle. Autoplay never sets …/playing, so busy is the signal; it also
        # covers boot before /playerStatus is responsive.
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
        self._mqtt_song = None
        self._mqtt_volume_seen = False
        self._shuffle_target = None
        self._shuffle_hold_until = 0.0
        self._prev_song = None
        self._song_grace_until = 0.0
        self._data = self._data.merge(
            available=False,
            state=None,
            song=None,
            song_index=None,
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
        available = False
        if self._http is not None:
            available = await self._http.async_get_device_info() is not None
        if self._closed:  # async_close can land during the HTTP await
            return
        self._push(available=available)
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
        self._mqtt_volume_seen = True
        self._push(volume=int(level_1_100))
        await self._publish({"exec": "SetVolume", "params": int(level_1_100)})

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
        # Reboot is an HTTP action (/reboot.json); no MQTT equivalent in the contract.
        if self._http is not None:
            await self._http.async_reboot()

    # -- snapshot (authoritative HTTP poll) + library ----------------------
    async def async_fetch_snapshot(self) -> ProdigyData:
        if self._http is not None:
            playback = await self._http.async_fetch_playback(
                fetch_volume=not self._mqtt_volume_seen
            )
            if playback.available:  # piano answered → its state/song/volume are truth
                self._http_state = playback.state
                if playback.state == MediaPlayerState.IDLE:
                    self._stopped = (
                        False  # device confirms idle → release the stop hold
                    )
                volume = (
                    self._data.volume
                    if self._mqtt_volume_seen or playback.volume is None
                    else playback.volume
                )
                merged = self._data.merge(
                    available=True,
                    volume=volume,
                    song=self._resolve_song(self._mqtt_song or playback.song),
                    song_index=playback.song_index,
                    song_count=playback.song_count,
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
        if not force and self._songlist_fresh():
            return list(self._song_titles)

        async with self._song_lock:
            if not force and self._songlist_fresh():
                return list(self._song_titles)

            titles: list[str] = []
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
                    new = 0
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
                            titles.append(title_from_path(path))
                            new += 1
                    self._emit_library_progress(len(titles), True)
                    if new == 0 or len(page_paths) < SONGLIST_PAGE_SIZE:
                        break
            finally:
                self._emit_library_progress(len(titles), False)

            if not titles:
                return await self._fetch_song_list_http_fallback(force=force)

            self._song_titles = titles
            self._song_cache_at = self._hass.loop.time()
            return list(titles)

    async def async_fetch_playlists(self) -> list[str]:
        payload = await self._request_response(
            self._playlist_request_topic,
            self._playlist_waiters,
            {"op": "get"},
        )
        names: list[str] = []
        playlists = payload.get("playlists") if isinstance(payload, dict) else None
        if isinstance(playlists, list):
            for item in playlists:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    names.append(item["name"])
        if not names:
            names = await self._fetch_playlists_http_fallback()
        self._playlist_names = names
        self._push(source_list=names)
        return names
