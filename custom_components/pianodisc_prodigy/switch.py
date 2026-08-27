"""Switch platform — independent control for a linked external power outlet."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Expose a power proxy only when the user linked an external outlet."""
    if entry.runtime_data.power_linked:
        async_add_entities([PianoDiscPowerSwitch(entry.runtime_data)])


class PianoDiscPowerSwitch(PianoDiscEntity, SwitchEntity):
    """Power proxy whose availability never depends on the piano transport."""

    _attr_translation_key = "power"
    _attr_icon = "mdi:power-socket"

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_power"

    @property
    def available(self) -> bool:
        # This entity represents the linked outlet, not the piano. It stays usable
        # throughout boot, WARMING_UP, library syncing and a lost MQTT/HTTP link.
        return self.coordinator.power_on is not None

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.power_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_outlet_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_outlet_power(False)
