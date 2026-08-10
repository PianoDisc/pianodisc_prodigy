"""Firmware update entities — the certification "update available" signal.

CR#3 (minimum): surface installed vs. recommended firmware so Home Assistant
shows whether an update is available. Installed comes from the device (…/version
over MQTT, or /debugJson over HTTP); the recommended ("latest") version is a
maintained constant for now.

Read-only on purpose: a real HA-triggered install needs the firmware binary URL
from the PianoDisc backend (a separate firmware task), so no INSTALL feature is
advertised yet — this entity is the "update available" indicator only.
"""

from __future__ import annotations

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DEVICE_ID, FW_AUDIO_RECOMMENDED, FW_MIDI_RECOMMENDED
from .coordinator import PianoDiscConfigEntry, PianoDiscCoordinator
from .entity import PianoDiscEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PianoDiscConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the audio + MIDI firmware update entities."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            PianoDiscFirmwareUpdate(coordinator, "audio", FW_AUDIO_RECOMMENDED),
            PianoDiscFirmwareUpdate(coordinator, "midi", FW_MIDI_RECOMMENDED),
        ]
    )


class PianoDiscFirmwareUpdate(PianoDiscEntity, UpdateEntity):
    """Read-only firmware update signal: installed vs. recommended version."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE

    def __init__(
        self, coordinator: PianoDiscCoordinator, kind: str, recommended: str
    ) -> None:
        super().__init__(coordinator)
        self._kind = kind  # "audio" | "midi"
        self._recommended = recommended
        self._attr_translation_key = f"{kind}_firmware"
        device_id = (
            coordinator.config_entry.unique_id
            or coordinator.config_entry.data[CONF_DEVICE_ID]
        )
        self._attr_unique_id = f"{device_id}_update_{kind}"

    @property
    def available(self) -> bool:
        # Version is cached/diagnostic — keep showing it even when the piano is
        # offline (mirrors the Library sensor rather than the live entities).
        return True

    @property
    def installed_version(self) -> str | None:
        data = self.coordinator.data
        return data.firmware_audio if self._kind == "audio" else data.firmware_midi

    @property
    def latest_version(self) -> str | None:
        # Prefer the device's own backend check (CR#3 ②, MQTT .../update); fall back
        # to the maintained constant until the device has reported (e.g. HTTP-only).
        data = self.coordinator.data
        dynamic = data.latest_audio if self._kind == "audio" else data.latest_midi
        return dynamic or self._recommended
