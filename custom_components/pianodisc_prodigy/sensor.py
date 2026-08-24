"""Diagnostic sensor: the SD-library song count / scan status.

Firmware versions no longer have standalone sensors — they are surfaced by the
device's ``sw_version`` and the CR#3 ``update`` entities (which show the installed
version plus whether a newer build is available), so a separate version sensor
would just duplicate the update entity's name and confuse users.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DEVICE_ID
from .coordinator import PianoDiscConfigEntry, PianoDiscCoordinator
from .entity import PianoDiscEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PianoDiscConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the diagnostic sensors."""
    async_add_entities(
        [
            PianoDiscLibrarySensor(entry.runtime_data),
            PianoDiscReadinessSensor(entry.runtime_data),
        ]
    )


class PianoDiscLibrarySensor(PianoDiscEntity, SensorEntity):
    """The SD-card song count, with a live ``scanning`` attribute.

    Reads coordinator-level scan state (not the device snapshot) so it climbs live while
    a scan runs and holds the last-known total between scans. Stays available even when
    the piano is offline — it reflects Home Assistant's cached library, not liveness.
    """

    _attr_translation_key = "library"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:playlist-music"
    _attr_native_unit_of_measurement = "songs"

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_library"

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> int | None:
        return self.coordinator.library_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"scanning": self.coordinator.library_scanning}


class PianoDiscReadinessSensor(PianoDiscEntity, SensorEntity):
    """Report whether the NRF has completed its safe-to-play startup work."""

    _attr_name = "Readiness"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:piano"

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_readiness"

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.data.readiness
