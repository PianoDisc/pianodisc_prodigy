"""MIDI Show Control cue event entities: one per channel, carrying GO, STOP and FIRE."""

from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DEVICE_ID
from .coordinator import PianoDiscConfigEntry, PianoDiscCoordinator, msc_cue_signal
from .entity import PianoDiscShowControlEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PianoDiscConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one cue event entity per configured MSC channel."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            PianoDiscMscCue(coordinator, channel)
            for channel in range(1, coordinator.msc_channel_count + 1)
        ]
    )


class PianoDiscMscCue(PianoDiscShowControlEntity, EventEntity):
    """Every cue that reaches one channel, in order: GO, STOP or FIRE.

    The channel's on/off state lives on the matching binary sensor; this entity
    is the stateless record of each cue, which is what FIRE needs and what an
    automation wants to trigger on.
    """

    _attr_translation_key = "msc_cue"
    _attr_event_types = ["go", "stop", "fire"]

    def __init__(self, coordinator: PianoDiscCoordinator, channel: int) -> None:
        super().__init__(coordinator)
        device_id = coordinator.config_entry.unique_id or coordinator.config_entry.data[
            CONF_DEVICE_ID
        ]
        self._channel = channel
        self._attr_unique_id = f"{device_id}_msc_cue_ch{channel}"
        self._attr_translation_placeholders = {"channel": str(channel)}
        if not coordinator.transport.supports_msc:
            self._attr_name = f"Channel {channel} cue (MQTT required)"

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.transport.supports_msc
            and self.coordinator.transport.supports_realtime_events
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                msc_cue_signal(self.coordinator.config_entry.entry_id, self._channel),
                self._handle_cue,
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        # Live channel state, so a blueprint with only this entity picked can tell
        # whether a FIRE flash should restore to on or to off.
        return {
            "channel_on": bool(
                self.coordinator.msc_channel_states.get(self._channel, False)
            )
        }

    @callback
    def _handle_cue(self, command: str, cue: str) -> None:
        self._trigger_event(command.lower(), {"cue": cue})
        self.async_write_ha_state()
