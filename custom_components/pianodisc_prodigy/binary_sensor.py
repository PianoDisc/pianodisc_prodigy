"""Binary sensor: solenoids actively striking keys (MQTT mode only)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up the busy binary sensor."""
    async_add_entities([PianoDiscBusySensor(entry.runtime_data)])


class PianoDiscBusySensor(PianoDiscEntity, BinarySensorEntity):
    """True while the piano's solenoids are striking keys."""

    _attr_translation_key = "busy"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_busy"

    @property
    def is_on(self) -> bool | None:
        # None (unknown) in HTTP-only mode — there is no HTTP equivalent for busy.
        return self.coordinator.data.busy
