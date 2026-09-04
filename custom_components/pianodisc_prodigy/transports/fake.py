"""In-memory transport — runs the integration with no hardware.

Used by the scaffold (so adding the config entry yields a working "piano" you can
play with in the HA UI) and by the test suite (a real coordinator + real entities
driven against a deterministic transport). It models the observable contract only:
transport state, volume echo, shuffle, song list, and a simulated ``busy`` pulse on
track load. It does NOT simulate UART/MQTT timing quirks — those belong in the real
transports' own tests.
"""

from __future__ import annotations

from homeassistant.components.media_player import MediaPlayerState

from ..models import ProdigyData
from . import Transport

_DEMO_SONGS: list[str] = [
    "Clair de Lune",
    "Rhapsody in Blue",
    "The Entertainer",
    "Moonlight Sonata",
    "Take Five",
]
_DEMO_PLAYLISTS: list[str] = ["Lobby Morning", "Dinner Service", "Late Night"]
_DEMO_SONG_PATHS: list[str] = [f"/sd/{song}.mid" for song in _DEMO_SONGS]


class FakeTransport(Transport):
    """A deterministic, in-memory piano."""

    @property
    def supports_msc(self) -> bool:
        return True

    @property
    def supports_realtime_events(self) -> bool:
        return True

    def __init__(self, device_name: str = "Demo Prodigy") -> None:
        super().__init__()
        self.reboot_count = 0
        self.song_fetch_count = 0
        self._pre_mute_volume = 40
        self._data = ProdigyData(
            available=True,
            readiness="READY",
            state=MediaPlayerState.IDLE,
            volume=40,
            shuffle=False,
            queue_mode="all_songs",
            repeat_mode=0,
            busy=False,
            song=None,
            song_index=None,
            song_count=len(_DEMO_SONGS),
            source=None,
            source_list=[],
            device_name=device_name,
            serial_number="DEMO-SERIAL",
            wifi_rssi=-54,
            wifi_ssid="Demo Wi-Fi",
            bluetooth_name="Demo Prodigy BT",
            firmware_audio="0.5.0",
            firmware_midi="1.4.0",
        )
        self.playlists: list[dict[str, object]] = [
            {
                "name": "Lobby Morning",
                "sort": "Shuffle",
                "repeat": 1,
                "content": {"include": [], "exclude": []},
            },
            {
                "name": "Dinner Service",
                "sort": "Shuffle",
                "repeat": 1,
                "content": {
                    "include": ["/sd/Clair de Lune.mid", "/sd/Take Five.mid"],
                    "exclude": [],
                },
            },
            {
                "name": "Late Night",
                "sort": "Shuffle",
                "repeat": 1,
                "content": {"include": [], "exclude": ["/sd/The Entertainer.mid"]},
            },
        ]
        self.autoplay_config: dict[str, object] = {
            "enable": False,
            "playlist": 0,
            "loop": False,
            "sort": 0,
        }

    # -- lifecycle ----------------------------------------------------------
    async def async_setup(self) -> None:
        self._data = self._data.merge(available=True)

    async def async_close(self) -> None:
        return None

    async def async_fetch_snapshot(self) -> ProdigyData:
        return self._data

    async def async_fetch_debug_json(self) -> dict[str, object]:
        return {
            "Device ID": "DEFAEE5C894F",
            "Name": self._data.device_name,
            "Audio Version": self._data.firmware_audio,
            "MIDI Version": self._data.firmware_midi,
            "Ready State": self._data.readiness,
            "Serial Number": self._data.serial_number,
            "Wi-Fi RSSI": self._data.wifi_rssi,
            "Wi-Fi SSID": self._data.wifi_ssid,
            "Bluetooth Name": self._data.bluetooth_name,
        }

    # -- helpers ------------------------------------------------------------
    def _update(self, **changes: object) -> None:
        self._data = self._data.merge(**changes)
        self._emit(self._data)

    def simulate_msc(self, command: object, cue: object) -> None:
        """Deliver one normalized MSC cue to the coordinator in tests."""
        self._emit_msc(str(command).strip().upper(), str(cue))

    # -- transport commands -------------------------------------------------
    async def async_play(self, index: int | None = None) -> None:
        if index is None or index < 0:
            index = self._data.song_index if self._data.song_index is not None else 0
        index = max(0, min(index, len(_DEMO_SONGS) - 1))
        self._update(
            state=MediaPlayerState.PLAYING,
            song=_DEMO_SONGS[index],
            song_path=_DEMO_SONG_PATHS[index],
            song_index=index,
            media_position=0,
            media_duration=180,
        )

    async def async_play_path(self, path: str) -> None:
        try:
            index = _DEMO_SONG_PATHS.index(path)
        except ValueError as err:
            raise ValueError(f"Song path is not on the SD card: {path}") from err
        await self.async_play(index)

    async def async_pause(self) -> None:
        if self._data.state == MediaPlayerState.PLAYING:
            self._update(state=MediaPlayerState.PAUSED)

    async def async_stop(self) -> None:
        # Real device does not clear .../song on stop; entities blank the title.
        self._update(state=MediaPlayerState.IDLE)

    async def async_next(self) -> None:
        nxt = ((self._data.song_index or 0) + 1) % len(_DEMO_SONGS)
        await self.async_play(nxt)

    async def async_previous(self) -> None:
        prv = ((self._data.song_index or 0) - 1) % len(_DEMO_SONGS)
        await self.async_play(prv)

    async def async_set_volume(self, level_1_100: int) -> None:
        volume = max(0, min(100, int(level_1_100)))
        if volume > 0:
            self._pre_mute_volume = volume
        self._update(volume=volume)

    async def async_mute_volume(self, mute: bool) -> None:
        if mute:
            if self._data.volume is not None and self._data.volume > 0:
                self._pre_mute_volume = self._data.volume
            self._update(volume=0)
            return
        self._update(volume=self._pre_mute_volume)

    async def async_set_shuffle(self, shuffle: bool) -> None:
        self._update(shuffle=bool(shuffle))

    async def async_set_repeat(self, mode: int) -> None:
        if mode not in (0, 1, 2):
            raise ValueError(f"invalid repeat mode: {mode}")
        self._update(queue_mode="all_songs", repeat_mode=mode)

    async def async_select_playlist(self, name: str) -> None:
        if name in self._data.source_list:
            self._update(source=name)

    async def async_reboot(self) -> None:
        self.reboot_count += 1

    # -- library reads ------------------------------------------------------
    async def async_fetch_song_list(self, force: bool = False) -> list[str]:
        self.song_fetch_count += 1
        return list(_DEMO_SONGS)

    async def async_fetch_song_paths(self, force: bool = False) -> list[str]:
        return list(_DEMO_SONG_PATHS)

    async def async_fetch_playlists(self) -> list[str]:
        names = [
            item["name"]
            for item in self.playlists
            if isinstance(item.get("name"), str)
        ]
        self._update(source_list=names)
        return names

    async def async_fetch_playlist_definitions(self) -> list[dict[str, object]]:
        playlists = [dict(item) for item in self.playlists]
        self._update(
            source_list=[
                item["name"]
                for item in playlists
                if isinstance(item.get("name"), str)
            ]
        )
        return playlists

    async def async_save_playlist_definitions(
        self, playlists: list[dict[str, object]]
    ) -> None:
        self.playlists = [dict(item) for item in playlists]
        self._update(source_list=await self.async_fetch_playlists())

    async def async_fetch_autoplay_config(self) -> dict[str, object]:
        return dict(self.autoplay_config)

    async def async_save_autoplay_config(self, config: dict[str, object]) -> None:
        self.autoplay_config = dict(config)
