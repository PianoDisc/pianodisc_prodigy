"""Switch platform — independent control for a linked external power outlet."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    """Set up the independent power proxy and AutoPlay configuration switches."""
    entities: list[SwitchEntity] = [
        PianoDiscAutoPlayEnableSwitch(entry.runtime_data),
        PianoDiscAutoPlayLoopSwitch(entry.runtime_data),
    ]
    if entry.runtime_data.power_linked:
        entities.insert(0, PianoDiscPowerSwitch(entry.runtime_data))
    async_add_entities(entities)


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


class _PianoDiscAutoPlaySwitch(PianoDiscEntity, SwitchEntity):
    """Shared behavior for the two persisted AutoPlay boolean settings."""

    _attr_entity_category = EntityCategory.CONFIG
    _config_key: str

    def __init__(self, coordinator: PianoDiscCoordinator, unique_suffix: str) -> None:
        super().__init__(coordinator)
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_{unique_suffix}"

    async def async_added_to_hass(self) -> None:
        """Fetch the shared configuration once the platform is listening."""
        await super().async_added_to_hass()
        self.hass.async_create_task(self.coordinator.async_fetch_autoplay_config())

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.autoplay_config is not None

    @property
    def is_on(self) -> bool | None:
        config = self.coordinator.autoplay_config
        return bool(config.get(self._config_key)) if config is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_save_autoplay_config({self._config_key: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_save_autoplay_config({self._config_key: False})


class PianoDiscAutoPlayEnableSwitch(_PianoDiscAutoPlaySwitch):
    """Enable or disable the configured automatic playlist."""

    _attr_translation_key = "autoplay"
    _attr_icon = "mdi:play-circle-outline"
    _config_key = "enable"

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator, "autoplay")


class PianoDiscAutoPlayLoopSwitch(_PianoDiscAutoPlaySwitch):
    """Set whether AutoPlay loops after the selected playlist ends."""

    _attr_translation_key = "autoplay_loop"
    _attr_icon = "mdi:repeat"
    _config_key = "loop"

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator, "autoplay_loop")
