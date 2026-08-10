"""Switch platform — the piano's device-level shuffle (playback order)."""

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
    """Set up the device-level shuffle switch."""
    async_add_entities([PianoDiscShuffleSwitch(entry.runtime_data)])


class PianoDiscShuffleSwitch(PianoDiscEntity, SwitchEntity):
    """Device-level shuffle (the firmware's ``sort``), exposed as a switch.

    Deliberately NOT the media_player SHUFFLE_SET button: shuffle here is a *persistent
    device setting* (on by default), so it must stay toggleable even when idle. The
    media card only renders its shuffle control during active playback, which made it
    one-way (toggle off → the button vanishes → no way back). A switch is always
    available and clearly on/off. See device captures.
    """

    _attr_translation_key = "shuffle"
    _attr_icon = "mdi:shuffle"

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_shuffle"

    @property
    def available(self) -> bool:
        # Reachable AND the piano has actually reported a sort value.
        return super().available and self.coordinator.data.shuffle is not None

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.shuffle

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set_shuffle(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set_shuffle(False)

    async def _set_shuffle(self, shuffle: bool) -> None:
        await self.coordinator.transport.async_set_shuffle(shuffle)
        await self.coordinator.async_request_refresh()
