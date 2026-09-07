"""Binary sensor: solenoids actively striking keys (MQTT mode only)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DEVICE_ID
from .coordinator import PianoDiscConfigEntry, PianoDiscCoordinator
from .entity import PianoDiscEntity, PianoDiscShowControlEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PianoDiscConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up piano activity and configured MSC channel sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [PianoDiscBusySensor(coordinator)]
        + [
            PianoDiscMscChannel(coordinator, channel)
            for channel in range(1, coordinator.msc_channel_count + 1)
        ]
    )


class PianoDiscBusySensor(PianoDiscEntity, BinarySensorEntity):
    """True while the piano's solenoids are striking keys."""

    _attr_translation_key = "busy"

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_busy"

    @property
    def is_on(self) -> bool | None:
        # No HTTP equivalent exists. A HA MQTT client alone is also insufficient:
        # wait until this piano itself has supplied live MQTT status.
        if not self.coordinator.transport.supports_realtime_events:
            return None
        return self.coordinator.data.busy

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        if self.coordinator.transport.supports_realtime_events:
            return {}
        return {
            "requires": "MQTT",
            "setup": "Configure this piano to use Home Assistant's MQTT broker.",
        }


class PianoDiscMscChannel(PianoDiscShowControlEntity, BinarySensorEntity):
    """Sticky GO/STOP state for one MIDI Show Control cue channel."""

    _attr_translation_key = "msc_channel"

    def __init__(self, coordinator: PianoDiscCoordinator, channel: int) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.unique_id or coordinator.config_entry.data[
            CONF_DEVICE_ID
        ]
        self._channel = channel
        self._attr_unique_id = f"{device_id}_msc_ch{channel}"
        self._attr_translation_placeholders = {"channel": str(channel)}

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.transport.supports_realtime_events:
            return None
        return self.coordinator.msc_channel_states.get(self._channel, False)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        if self.coordinator.transport.supports_realtime_events:
            return {}
        return {
            "requires": "MQTT",
            "setup": "Configure this piano to use Home Assistant's MQTT broker.",
        }
