"""Buttons: reboot the piano, and refresh the SD-card song library."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
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
    """Set up the reboot and refresh-library buttons."""
    async_add_entities(
        [
            PianoDiscRebootButton(entry.runtime_data),
            PianoDiscRefreshLibraryButton(entry.runtime_data),
        ]
    )


class PianoDiscRebootButton(PianoDiscEntity, ButtonEntity):
    """Reboots the piano. Diagnostic category keeps it off default dashboards."""

    _attr_translation_key = "reboot"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_reboot"

    async def async_press(self) -> None:
        await self.coordinator.transport.async_reboot()


class PianoDiscRefreshLibraryButton(PianoDiscEntity, ButtonEntity):
    """Re-scans the SD-card song library (press after changing the card's contents)."""

    _attr_translation_key = "refresh_library"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_refresh_library"

    @property
    def available(self) -> bool:
        """Avoid overlapping scans while preserving media-player availability."""
        return (
            super().available
            and not self.coordinator.library_scanning
            and not self.coordinator.playlist_loading
        )

    async def async_press(self) -> None:
        # The paged scan is slow, so re-scan off the press and let the cache update for
        # the next browse rather than blocking the button for seconds. Routed through the
        # coordinator so it also drives the live progress notification + Library sensor.
        entry = self.coordinator.config_entry
        entry.async_create_background_task(
            self.hass,
            self.coordinator.async_refresh_library(),
            "pianodisc_prodigy_library_refresh",
        )
