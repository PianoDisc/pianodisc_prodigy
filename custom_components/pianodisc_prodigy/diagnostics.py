"""Diagnostics support for PianoDisc Prodigy II."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID
from .coordinator import PianoDiscConfigEntry

TO_REDACT = {CONF_DEVICE_ID, "host", "unique_id"}
PIANO_DEBUG_TO_REDACT = {
    "Wi-Fi SSID",
    "IP Address",
    "Device ID",
    "Serial Number",
    "Bluetooth Name",
    "License",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PianoDiscConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    piano_debug = await coordinator.transport.async_fetch_debug_json()
    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
            "transport": type(coordinator.transport).__name__,
        },
        "power": {
            "linked": coordinator.power_linked,
            "switch": coordinator.power_switch,
            "on": coordinator.power_on,
        },
        "msc": {
            "channels": coordinator.msc_channel_states,
            "last": coordinator.last_msc,
            "channel_count": coordinator.msc_channel_count,
        },
        "data": async_redact_data(asdict(coordinator.data), TO_REDACT),
        "piano_debug": (
            async_redact_data(piano_debug, PIANO_DEBUG_TO_REDACT)
            if piano_debug is not None
            else None
        ),
    }
