"""Diagnostics support for PianoDisc Prodigy II."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID
from .coordinator import PianoDiscConfigEntry

TO_REDACT = {CONF_DEVICE_ID, "host", "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PianoDiscConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
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
        "data": async_redact_data(asdict(coordinator.data), TO_REDACT),
    }
