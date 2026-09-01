"""MIDI Show Control FIRE event entities."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DEVICE_ID
from .coordinator import PianoDiscConfigEntry, PianoDiscCoordinator, msc_fire_signal
from .entity import PianoDiscShowControlEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PianoDiscConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one FIRE event entity per configured MSC channel."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            PianoDiscMscFire(coordinator, channel)
            for channel in range(1, coordinator.msc_channel_count + 1)
        ]
    )


class PianoDiscMscFire(PianoDiscShowControlEntity, EventEntity):
    """One-shot FIRE notification for an MSC cue channel."""

    _attr_translation_key = "msc_fire"
    _attr_event_types = ["fire"]

    def __init__(self, coordinator: PianoDiscCoordinator, channel: int) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.unique_id or coordinator.config_entry.data[
            CONF_DEVICE_ID
        ]
        self._channel = channel
        self._attr_unique_id = f"{device_id}_msc_fire_ch{channel}"
        self._attr_translation_placeholders = {"channel": str(channel)}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                msc_fire_signal(self.coordinator.config_entry.entry_id, self._channel),
                self._handle_fire,
            )
        )

    @callback
    def _handle_fire(self, cue: str) -> None:
        self._trigger_event("fire", {"cue": cue})
        self.async_write_ha_state()
