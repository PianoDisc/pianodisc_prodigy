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

    async def async_added_to_hass(self) -> None:
        """Options arrive from the coordinator's background cache prefetch."""
        await super().async_added_to_hass()

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.playlist_status == "Ready"
            and bool(self.options)
        )

    @property
    def options(self) -> list[str]:
        # Playlist definitions are the authoritative, shared cache. ``source_list``
        # is a playback-status convenience field and can be overwritten by a later
        # MQTT status push before the select is rendered.
        return [
            item["name"]
            for item in self.coordinator.playlist_definitions or []
            if isinstance(item.get("name"), str)
        ]

    @property
    def current_option(self) -> str | None:
        source = self.coordinator.data.source
        return source if source in self.options else None

    async def async_select_option(self, option: str) -> None:
        options = self.options
        await self.coordinator.async_execute_device_command(
            self.coordinator.transport.async_select_playlist(option)
        )
        await self.coordinator.async_request_refresh()
        self._publish(source=option, source_list=options)

    def _publish(
        self, *, source: str | None = None, source_list: list[str] | None = None
    ) -> None:
        data = self.coordinator.data
        if data is None:
            return
        changes: dict[str, object] = {}
        if source is not None:
            changes["source"] = source
        if source_list is not None:
            changes["source_list"] = list(source_list)
        if changes:
            self.coordinator.async_set_updated_data(data.merge(**changes))
