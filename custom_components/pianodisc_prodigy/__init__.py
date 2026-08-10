"""The PianoDisc Prodigy II integration."""

from __future__ import annotations

from homeassistant.components import mqtt
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_DEVICE_ID, LOGGER
from .coordinator import PianoDiscConfigEntry, PianoDiscCoordinator
from .transports import Transport
from .transports.http import HttpTransport
from .transports.mqtt import MqttTransport

# Remaining aux platforms (event, autoplay select) land next.
PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: PianoDiscConfigEntry) -> bool:
    """Set up PianoDisc Prodigy II from a config entry."""
    transport = await _async_build_transport(hass, entry)
    LOGGER.debug("Using transport %s for %s", type(transport).__name__, entry.title)

    coordinator = PianoDiscCoordinator(hass, entry, transport)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    # An options change (linking/unlinking the power outlet) reloads the entry so the
    # coordinator re-reads it and the media_player recomputes its supported features.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Warm the song-library cache in the background so the first BROWSE_MEDIA is instant
    # (the paged SD scan is slow); never block setup on it.
    entry.async_create_background_task(
        hass,
        _async_prefetch_library(coordinator),
        "pianodisc_prodigy_library_prefetch",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PianoDiscConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: PianoDiscConfigEntry) -> None:
    """Reload the entry when its options change (e.g. the linked power outlet)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_prefetch_library(coordinator: PianoDiscCoordinator) -> None:
    """Warm the library cache (best-effort); scan-on-browse remains the fallback."""
    try:
        await coordinator.transport.async_fetch_song_list()
    except Exception:
        LOGGER.debug("Library prefetch failed; will scan on browse", exc_info=True)


async def _async_build_transport(
    hass: HomeAssistant, entry: PianoDiscConfigEntry
) -> Transport:
    """Select the transport for this entry (decision #2: hybrid mode).

    MQTT is preferred (push / ``local_push``). The HTTP transport composes into the
    MQTT one for the request/library half MQTT lacks — song list, playlists, firmware
    versions and the cold-start snapshot seed — and is omitted only when the entry has
    no host yet (an MQTT-discovered unit before its IP is set via the reconfigure flow;
    control and status still work). With no broker available, HTTP-only is the fallback.

    The in-memory ``FakeTransport`` is reached by tests patching this factory; it is
    deliberately never selected for a real entry.
    """
    host = entry.data.get(CONF_HOST) or None
    device_id = entry.data[CONF_DEVICE_ID]
    http = HttpTransport(async_get_clientsession(hass), host) if host else None

    if await mqtt.async_wait_for_mqtt_client(hass):
        return MqttTransport(hass, device_id, http=http)
    if http is not None:
        return http
    raise ConfigEntryNotReady(
        "No MQTT broker is available and no device IP is configured. "
        "Set the piano's IP address via Reconfigure, or start the MQTT broker."
    )
