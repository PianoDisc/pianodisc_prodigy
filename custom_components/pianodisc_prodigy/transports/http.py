"""HTTP transport — the full control surface over the device's LAN HTTP API.

This powers HTTP-only mode (poll + command + library) and is also composed by the
MQTT transport for the request/library half MQTT lacks. Per [[golden-capture]] the
endpoints are unauthenticated, return ``text/plain`` even for JSON (parse by path),
and the library/status GETs are *prime-then-poll* async caches with no completion
signal. Decoding mirrors the Calibrate app: ISO-8859-1 then strip control bytes.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.util import dt as dt_util

from ..const import (
    DEBUG_KEY_AUDIO_VERSION,
    DEBUG_KEY_BLUETOOTH_NAME,
    DEBUG_KEY_DEVICE_ID,
    DEBUG_KEY_MIDI_VERSION,
    DEBUG_KEY_SERIAL_NUMBER,
    DEBUG_KEY_WIFI_RSSI,
    DEBUG_KEY_WIFI_SSID,
    HTTP_REQUEST_TIMEOUT,
    HTTP_SOCKET_LIMIT,
    MAX_SCAN_PAGES,
    PRIME_POLL_WAIT,
    REPEAT_HOLD_GRACE,
    SCAN_PAGE_ATTEMPTS,
    SCAN_POLL_INTERVAL,
    SCAN_POLL_MAX,
    SHUFFLE_HOLD_GRACE,
    SONGLIST_PAGE_SIZE,
    SONGLIST_TTL,
)
from ..models import ProdigyData
from . import Transport

_STATE_MAP: dict[int, MediaPlayerState] = {
    0: MediaPlayerState.IDLE,
    1: MediaPlayerState.PLAYING,
    2: MediaPlayerState.PAUSED,
}


def title_from_path(path: str) -> str:
    """`/sd/A Foggy Day.mid\\n` -> `A Foggy Day` (basename, strip dir + .mid)."""
    name = path.strip().rsplit("/", 1)[-1]
    if name.lower().endswith(".mid"):
        name = name[:-4]
    return name


def _positive_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def _non_negative_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _track_index(value: object) -> int | None:
    if isinstance(value, int) and value > 0:
        return value - 1
    return None


class HttpTransport(Transport):
    """Talks to the piano over HTTP. Requires the device's LAN host/IP."""

    def __init__(self, session: ClientSession, host: str) -> None:
        super().__init__()
        self._session = session
        self._host = host
        self._base = f"http://{host}"
        self._sem = asyncio.Semaphore(HTTP_SOCKET_LIMIT)
        self._sleep = asyncio.sleep  # injectable for tests
        self._song_titles: list[str] = []
        self._song_paths: list[str] = []
        self._song_cache_at: float | None = None
        self._song_lock = asyncio.Lock()  # serialize scans of the shared SD buffer
        self._playlist_names: list[str] = []
        self._pre_mute_volume = 50
        # Shuffle (sort) lags in /playerStatus after we set it; hold the target until
        # the device's reading catches up (or grace lapses) so the switch sticks.
        self._shuffle_target: bool | None = None
        self._shuffle_hold_until = 0.0
        self._repeat_target: int | None = None
        self._repeat_hold_until = 0.0

    @property
    def ip_address(self) -> str | None:
        """Return the configured host only when it is a literal IPv4 address."""
        try:
            address = ipaddress.ip_address(self._host)
        except ValueError:
            return None
        return str(address) if address.version == 4 and not address.is_unspecified else None

    # -- lifecycle ----------------------------------------------------------
    async def async_setup(self) -> None:
        return None

    async def async_close(self) -> None:
        return None

    # -- low-level ----------------------------------------------------------
    async def _request(
        self, method: str, path: str, json_body: object | None = None
    ) -> str | None:
        """One request, socket-bounded; returns cleaned text body or None on error."""
        url = f"{self._base}/{path}"
        async with self._sem:
            try:
                async with self._session.request(
                    method,
                    url,
                    timeout=ClientTimeout(total=HTTP_REQUEST_TIMEOUT),
                    json=json_body,
                ) as resp:
                    raw = await resp.read()
            except (TimeoutError, ClientError, OSError):
                return None
        # ISO-8859-1 + strip control bytes before parsing (matches Calibrate).
        text = raw.decode("iso-8859-1", "replace")
        return "".join(ch for ch in text if ord(ch) >= 0x20)

    async def _get_json(self, path: str) -> Any | None:
        text = await self._request("GET", path)
        if not text:
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

    # -- identity / probe ---------------------------------------------------
    async def async_get_device_info(self) -> dict[str, Any] | None:
        """deviceID + firmware versions from /debugJson (the only HTTP source)."""
        debug = await self._get_json("debugJson?type=request")
        if not isinstance(debug, dict):
            return None
        device_id = debug.get(DEBUG_KEY_DEVICE_ID)
        if not device_id:
            return None
        return {
            "device_id": str(device_id),
            "audio_version": _as_str(debug.get(DEBUG_KEY_AUDIO_VERSION)),
            "midi_version": _as_str(debug.get(DEBUG_KEY_MIDI_VERSION)),
            "serial_number": _as_str(debug.get(DEBUG_KEY_SERIAL_NUMBER)),
            "hardware_version": _hardware_version(debug),
            "wifi_rssi": _as_int(debug.get(DEBUG_KEY_WIFI_RSSI)),
            "wifi_ssid": _as_str(debug.get(DEBUG_KEY_WIFI_SSID)),
            "bluetooth_name": _as_str(debug.get(DEBUG_KEY_BLUETOOTH_NAME)),
        }

    async def async_fetch_debug_json(self) -> dict[str, Any] | None:
        """Refresh then retrieve the full piano diagnostic JSON on user request."""
        # The firmware returns its existing cache from the prime request; a
        # subsequent GET is needed after the nRF has answered over UART.
        await self._get_json("debugJson?type=request")
        for _ in range(4):
            await self._sleep(PRIME_POLL_WAIT)
            debug = await self._get_json("debugJson")
            if isinstance(debug, dict):
                return debug
        return None

    # -- snapshot (poll path) ----------------------------------------------
    async def async_fetch_playback(self, *, fetch_volume: bool = True) -> ProdigyData:
        """Light poll of the changing bits: /playerStatus + /getVolume (2 GETs).

        This is the regular MQTT-mode poll — kept light so it doesn't preempt the
        device's audio task. status.json + debugJson (firmware) are static and fetched
        rarely via :meth:`async_fetch_snapshot`.
        """
        player = await self._get_json("playerStatus")
        volume = (
            await self._get_json("getVolume")
            if fetch_volume
            else None
        )  # percent (0-100); the slider source

        state = song = song_path = song_index = song_count = shuffle = None
        queue_mode = repeat_mode = playlist_repeat = autoplay_loop = source = None
        readiness = "READY"
        media_position = media_duration = None
        if isinstance(player, dict):
            reported_readiness = player.get("ready")
            if isinstance(reported_readiness, str) and reported_readiness:
                readiness = reported_readiness.upper()
            state = _STATE_MAP.get(player.get("state"))
            raw_song = player.get("song")
            song_path = raw_song.strip() if isinstance(raw_song, str) and raw_song else None
            song = (
                title_from_path(raw_song)
                if isinstance(raw_song, str) and raw_song
                else None
            )
            song_index = _track_index(player.get("track_index"))
            length = player.get("track_total")
            song_count = length if isinstance(length, int) and length > 0 else None
            media_position = _non_negative_number(player.get("position"))
            media_duration = _positive_number(player.get("duration"))
            sort = player.get("sort")
            shuffle = (sort == 1) if sort is not None else None
            reported_queue_mode = player.get("queue_mode")
            if reported_queue_mode in {"all_songs", "playlist", "autoplay"}:
                queue_mode = reported_queue_mode
            reported_repeat = player.get("repeat_mode")
            if isinstance(reported_repeat, int) and reported_repeat in {0, 1, 2}:
                repeat_mode = self._resolve_repeat(reported_repeat)
            reported_playlist_repeat = player.get("playlist_repeat")
            if isinstance(reported_playlist_repeat, int) and reported_playlist_repeat >= 0:
                playlist_repeat = reported_playlist_repeat
            if isinstance(player.get("autoplay_loop"), bool):
                autoplay_loop = player["autoplay_loop"]
            if queue_mode in {"playlist", "autoplay"} and isinstance(
                player.get("playlist"), str
            ):
                source = player["playlist"]
            # A bare PAUSED value can be the ESP's retained pre-reboot status.
            # Without a selected track or progress it represents idle, not playback.
            if (
                state is MediaPlayerState.PAUSED
                and song is None
                and song_index is None
                and media_position is None
            ):
                state = MediaPlayerState.IDLE

        vol = volume.get("volume") if isinstance(volume, dict) else None

        return ProdigyData(
            available=isinstance(player, dict) and readiness in {"READY", "OK"},
            readiness=readiness if isinstance(player, dict) else "unknown",
            state=state,
            song=song,
            song_path=song_path,
            song_index=song_index,
            song_count=song_count,
            media_position=media_position,
            media_duration=media_duration,
            media_position_updated_at=(
                dt_util.utcnow() if media_position is not None else None
            ),
            # 0-100 percent; the audio engine returns 255 ("unknown") for ~1 min after
            # boot until it syncs with the MIDI engine — treat out-of-range as unknown.
            volume=vol if isinstance(vol, int) and 0 <= vol <= 100 else None,
            shuffle=self._resolve_shuffle(shuffle),
            queue_mode=queue_mode,
            repeat_mode=repeat_mode,
            playlist_repeat=playlist_repeat,
            autoplay_loop=autoplay_loop,
            source=source,
            busy=None,  # no HTTP equivalent
            ip_address=self.ip_address,
            # device_name left None: the per-unit name comes from the entry / MQTT.
            source_list=list(self._playlist_names),
        )

    async def async_fetch_volume(self) -> int | None:
        """Fetch only /getVolume for MQTT-mode volume backfill."""
        volume = await self._get_json("getVolume")
        vol = volume.get("volume") if isinstance(volume, dict) else None
        return vol if isinstance(vol, int) and 0 <= vol <= 100 else None

    async def async_fetch_snapshot(self) -> ProdigyData:
        """Full snapshot = the light playback poll + firmware (HTTP-only path)."""
        data = await self.async_fetch_playback()
        debug = await self._get_json("debugJson?type=request")
        if isinstance(debug, dict):
            data = data.merge(
                firmware_audio=_as_str(debug.get(DEBUG_KEY_AUDIO_VERSION)),
                firmware_midi=_as_str(debug.get(DEBUG_KEY_MIDI_VERSION)),
                serial_number=_as_str(debug.get(DEBUG_KEY_SERIAL_NUMBER)),
                hardware_version=_hardware_version(debug),
                wifi_rssi=_as_int(debug.get(DEBUG_KEY_WIFI_RSSI)),
                wifi_ssid=_as_str(debug.get(DEBUG_KEY_WIFI_SSID)),
                bluetooth_name=_as_str(debug.get(DEBUG_KEY_BLUETOOTH_NAME)),
            )
        return data

    # -- transport commands -------------------------------------------------
    async def async_play(self, index: int | None = None) -> None:
        await self._request("POST", f"play?index={-1 if index is None else int(index)}")

    async def async_play_path(self, path: str, *, single: bool = False) -> None:
        payload: dict[str, object] = {"song": path}
        if single:
            payload["single"] = True
        await self._request("POST", "playback", json_body=payload)

    async def async_pause(self) -> None:
        await self._request("POST", "pause")

    async def async_stop(self) -> None:
        await self._request("POST", "stop")

    async def async_next(self) -> None:
        await self._request("POST", "next")

    async def async_previous(self) -> None:
        await self._request("POST", "prev")

    async def async_set_volume(self, level_1_100: int) -> None:
        if level_1_100 > 0:
            self._pre_mute_volume = int(level_1_100)
        await self._request("POST", f"volume?volume={int(level_1_100)}")

    async def async_mute_volume(self, mute: bool) -> None:
        if mute:
            await self.async_set_volume(0)
            return
        await self.async_set_volume(self._pre_mute_volume)

    async def async_set_shuffle(self, shuffle: bool) -> None:
        # /playerStatus.sort lags after this POST → hold the target in the snapshot
        # (_resolve_shuffle) so the switch doesn't snap back on the next poll.
        self._shuffle_target = shuffle
        self._shuffle_hold_until = (
            asyncio.get_running_loop().time() + SHUFFLE_HOLD_GRACE
        )
        await self._request("POST", f"player?sort={1 if shuffle else 0}")

    async def async_set_repeat(self, mode: int) -> None:
        if mode not in (0, 1, 2):
            raise ValueError(f"invalid repeat mode: {mode}")
        self._repeat_target = mode
        self._repeat_hold_until = asyncio.get_running_loop().time() + REPEAT_HOLD_GRACE
        await self._request("POST", f"player?repeat={mode}")

    def _resolve_shuffle(self, observed: bool | None) -> bool | None:
        """Hold a just-set shuffle target while /playerStatus.sort catches up."""
        target = self._shuffle_target
        if target is None:
            return observed
        if observed == target:
            self._shuffle_target = None  # device confirmed → release the hold
            return observed
        if asyncio.get_running_loop().time() < self._shuffle_hold_until:
            return target  # sort still lagging → keep what the user just set
        self._shuffle_target = None  # grace lapsed → trust the device
        return observed

    def _resolve_repeat(self, observed: int | None) -> int | None:
        """Hold a just-set repeat target while /playerStatus.repeat_mode catches up."""
        target = self._repeat_target
        if target is None:
            return observed
        if observed == target:
            self._repeat_target = None
            return observed
        if asyncio.get_running_loop().time() < self._repeat_hold_until:
            return target
        self._repeat_target = None
        return observed

    async def async_select_playlist(self, name: str) -> None:
        try:
            index = self._playlist_names.index(name)
        except ValueError:
            return
        await self._request("POST", f"playByPlaylist?index={index}")

    async def async_reboot(self) -> None:
        await self._request("POST", "reboot.json")

    # -- library reads (prime-then-poll) -----------------------------------
    async def _scan_one_page(
        self, page: int, prev_key: tuple[str, ...] | None
    ) -> list[str] | None:
        """Prime ``/scanSD?page=N`` and poll ``/songlist`` until the shared buffer
        advances past ``prev_key`` (the previously captured page).

        The device gives no completion signal, so "advanced" means the buffer's content
        differs from the previous page. A non-advance is *ambiguous* — a slow load, a
        dropped scan command, or a buffer that already holds this page — and is **never**
        proof of end-of-library, so we re-prime and retry ``SCAN_PAGE_ATTEMPTS`` times
        before giving up on the page. Cadence mirrors the reference Calibrate app
        (``getProdigySongs``): gentle ``SCAN_POLL_INTERVAL`` polls, not a tight loop.

        Returns the new page's paths, or ``None`` if the buffer never advances.
        """
        for _attempt in range(SCAN_PAGE_ATTEMPTS):
            await self._request("GET", f"scanSD?page={page}")
            for _ in range(SCAN_POLL_MAX):
                await self._sleep(SCAN_POLL_INTERVAL)
                key = _songlist_key(await self._get_json("songlist"))
                if key and key != prev_key:
                    return list(key)
        return None

    def _songlist_fresh(self) -> bool:
        """True if the cached song list is still within its TTL."""
        if not self._song_titles or self._song_cache_at is None:
            return False
        return asyncio.get_running_loop().time() - self._song_cache_at < SONGLIST_TTL

    async def async_fetch_song_list(self, force: bool = False) -> list[str]:
        """Paged scan of the SD library: /scanSD?page=N (prime) -> /songlist (poll).

        ``/songlist`` is a single shared buffer with no completion signal, so each page
        is read by polling until the buffer advances (see ``_scan_one_page``) rather than
        waiting a fixed time — a fixed wait reads the stale buffer and truncates the
        library (verified live). Termination and cadence mirror the reference Calibrate
        app: the SCAN ends **only** on a short/empty page (< SONGLIST_PAGE_SIZE) or the
        MAX_SCAN_PAGES cap — a buffer that stops advancing is *not* treated as the end
        (that truncated the library under load, and lost everything when the buffer
        already held page 0). On a page-0 non-advance we fall back to the current buffer
        so a preloaded page 0 is still captured. Cached (SONGLIST_TTL) and warmed by a
        startup prefetch; ``force`` (the Refresh-library button) re-scans a changed SD.
        A lock serializes scans so the prefetch and a concurrent browse cannot both
        prime the shared buffer at once.
        """
        if not force and self._songlist_fresh():
            return list(self._song_titles)
        async with self._song_lock:
            # Re-check: a scan we waited on (e.g. the prefetch) may have just filled it.
            if not force and self._songlist_fresh():
                return list(self._song_titles)

            titles: list[str] = []
            paths: list[str] = []
            seen: set[str] = set()
            # Report live progress so the UI (a "Library" sensor / a refresh notification)
            # can show the scan climbing rather than a silent multi-second wait. The
            # ``finally`` guarantees a terminal ``scanning=False`` even if a page raises.
            self._emit_library_progress(0, True)
            try:
                # Baseline = whatever is in the shared buffer now, so page 0's load is
                # detectable even if a prior scan left a stale page there.
                prev_key = _songlist_key(await self._get_json("songlist"))
                for page in range(MAX_SCAN_PAGES):
                    page_paths = await self._scan_one_page(page, prev_key)
                    if page_paths is None:
                        # The buffer never advanced. NOT a reliable end-of-list signal
                        # (only a short page is): on page 0 fall back to the current
                        # buffer so a preloaded page isn't lost; on a later page treat it
                        # as the end and keep everything gathered so far.
                        if page == 0 and prev_key:
                            page_paths = list(prev_key)
                        else:
                            break
                    new = 0
                    for path in page_paths:
                        path = path.strip()
                        if path and path not in seen:
                            seen.add(path)
                            paths.append(path)
                            titles.append(title_from_path(path))
                            new += 1
                    prev_key = tuple(page_paths)
                    self._emit_library_progress(len(titles), True)
                    if new == 0 or len(page_paths) < SONGLIST_PAGE_SIZE:
                        break  # all-duplicate or a short page -> last page (authoritative)
            finally:
                self._emit_library_progress(len(titles), False)

            if not titles:
                # Never block browse on a flaky scan — degrade to the current buffer.
                for path in _songlist_key(await self._get_json("songlist")) or ():
                    paths.append(path)
                    titles.append(title_from_path(path))
                # Settle the count to the degraded total (the finally emitted 0).
                self._emit_library_progress(len(titles), False)

            self._song_paths = paths
            self._song_titles = titles
            self._song_cache_at = asyncio.get_running_loop().time()
            return list(titles)

    async def async_fetch_song_paths(self, force: bool = False) -> list[str]:
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
        return list(names)

    async def async_fetch_playlist_definitions(self) -> list[dict[str, Any]]:
        await self._request("GET", "playlist")  # prime
        await self._sleep(PRIME_POLL_WAIT)
        data = await self._get_json("playlist")
        playlists: list[dict[str, Any]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    playlists.append(dict(item))
        self._playlist_names = [
            item["name"]
            for item in playlists
            if isinstance(item.get("name"), str)
        ]
        return playlists

    async def async_save_playlist_definitions(
        self, playlists: list[dict[str, Any]]
    ) -> None:
        await self._request("POST", "playlist", json_body=playlists)
        self._playlist_names = [
            item["name"]
            for item in playlists
            if isinstance(item.get("name"), str)
        ]

    async def async_fetch_autoplay_config(self) -> dict[str, Any]:
        await self._request("GET", "autoplay")
        await self._sleep(PRIME_POLL_WAIT)
        data = await self._get_json("autoplay")
        return dict(data) if isinstance(data, dict) else {}

    async def async_save_autoplay_config(self, config: dict[str, Any]) -> None:
        await self._request("POST", "autoplay", json_body=config)


def _as_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _hardware_version(debug: dict[str, Any]) -> str | None:
    for key in ("Hardware Version", "HW Version", "hw_version"):
        value = _as_str(debug.get(key))
        if value is not None:
            return value
    return None


def _songlist_key(data: object) -> tuple[str, ...] | None:
    """Stable comparison key for a /songlist buffer (stripped, non-empty paths)."""
    if not isinstance(data, list):
        return None
    return tuple(d.strip() for d in data if isinstance(d, str) and d.strip())
