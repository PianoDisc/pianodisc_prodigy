"""Select platform — quick playlist playback."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DEVICE_ID
from .coordinator import PianoDiscConfigEntry, PianoDiscCoordinator
from .entity import PianoDiscEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PianoDiscConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the playlist selector."""
    async_add_entities([PianoDiscPlaylistSelect(entry.runtime_data)])


class PianoDiscPlaylistSelect(PianoDiscEntity, SelectEntity):
    """Select a playlist and play it immediately."""

    _attr_translation_key = "playlist"
    _attr_icon = "mdi:playlist-music"

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_playlist"

    @property
    def available(self) -> bool:
        return super().available and bool(self.options)

    @property
    def options(self) -> list[str]:
        return list(self.coordinator.data.source_list)

    @property
    def current_option(self) -> str | None:
        source = self.coordinator.data.source
        return source if source in self.options else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.transport.async_select_playlist(option)
        await self.coordinator.async_request_refresh()
