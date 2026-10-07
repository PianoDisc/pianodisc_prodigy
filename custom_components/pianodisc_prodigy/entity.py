"""Shared base entity: device registry wiring and availability."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
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


def _piano_device_id(coordinator: PianoDiscCoordinator, device_id: str) -> str | None:
    """Registry id of the piano device, the parent of the sub-devices below.

    The piano device is created before the platforms load, so it is normally found.
    """
    device = dr.async_get(coordinator.hass).async_get_device(
        identifiers={(DOMAIN, device_id)}
    )
    return device.id if device is not None else None


class PianoDiscShowControlEntity(PianoDiscEntity):
    """Entity on the piano's Show Control sub-device."""

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        device_id = entry.unique_id or entry.data[CONF_DEVICE_ID]
        piano_name = coordinator.data.device_name or entry.title
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{device_id}_show_control")},
            manufacturer=MANUFACTURER,
            name=f"{piano_name} Show Control",
        )
        if (parent := _piano_device_id(coordinator, device_id)) is not None:
            self._attr_device_info["via_device_id"] = parent


class PianoDiscAutoPlayEntity(PianoDiscEntity):
    """Entity on the piano's AutoPlay sub-device.

    AutoPlay is four related settings. Grouping them on their own device keeps
    the entity names short ("Playlist", "Loop") instead of prefixing each one.
    """

    def __init__(self, coordinator: PianoDiscCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        device_id = entry.unique_id or entry.data[CONF_DEVICE_ID]
        piano_name = coordinator.data.device_name or entry.title
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{device_id}_autoplay")},
            manufacturer=MANUFACTURER,
            name=f"{piano_name} AutoPlay",
        )
        if (parent := _piano_device_id(coordinator, device_id)) is not None:
            self._attr_device_info["via_device_id"] = parent
