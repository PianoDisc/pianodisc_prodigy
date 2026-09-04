"""Shared base entity: device registry wiring and availability."""

from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, CONF_NETWORK_MAC, DOMAIN, MANUFACTURER, MODEL
from .coordinator import PianoDiscCoordinator


class PianoDiscEntity(CoordinatorEntity[PianoDiscCoordinator]):
    """Common device_info + availability for every Prodigy entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        device_id: str = entry.unique_id or entry.data[CONF_DEVICE_ID]

        connections: set[tuple[str, str]] = set()
        network_mac = entry.data.get(CONF_NETWORK_MAC)
        if network_mac:
            connections = {(CONNECTION_NETWORK_MAC, network_mac)}

        # Device name = firmware device_name (display only; never an identity key).
        # TODO(naming): once the squeezelite/LMS device-merge is confirmed, decide
        # whether to disambiguate the piano media_player from the streaming player
        # (plan_review_v2 "<name> Piano" — likely _attr_name="Piano" on the media
        # player). Deferred with the merge since it's unverified and cosmetic.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            connections=connections,
            manufacturer=MANUFACTURER,
            model=MODEL,
            model_id=device_id,
            name=coordinator.data.device_name or entry.title,
            serial_number=coordinator.data.serial_number,
            hw_version=coordinator.data.hardware_version,
            sw_version=self._format_sw_version(),
            configuration_url=self._configuration_url(),
        )

    def _configuration_url(self) -> str | None:
        """Offer Home Assistant's device-card link when MQTT supplied the IP."""
        ip_address = self.coordinator.data.ip_address
        return f"http://{ip_address}" if ip_address else None

    def _format_sw_version(self) -> str | None:
        data = self.coordinator.data
        parts = []
        if data.firmware_audio:
            parts.append(f"audio {data.firmware_audio}")
        if data.firmware_midi:
            parts.append(f"MIDI {data.firmware_midi}")
        return ", ".join(parts) or None

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.available


class PianoDiscShowControlEntity(PianoDiscEntity):
    """Entity on the piano's Show Control sub-device."""

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        device_id = entry.unique_id or entry.data[CONF_DEVICE_ID]
        piano_name = coordinator.data.device_name or entry.title
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{device_id}_show_control")},
            via_device=(DOMAIN, device_id),
            manufacturer=MANUFACTURER,
            name=f"{piano_name} Show Control",
        )
