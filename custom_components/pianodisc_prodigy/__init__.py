"""The PianoDisc Prodigy II integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.components import mqtt
from homeassistant.components.frontend import (
    DATA_EXTRA_MODULE_URL,
    add_extra_js_url,
    async_remove_panel,
)
from homeassistant.components.lovelace.const import (
    CONF_RESOURCE_TYPE_WS,
    LOVELACE_DATA,
    MODE_STORAGE,
)
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.setup import async_setup_component

from .const import (
    CONF_DEVICE_ID,
    CONF_NETWORK_MAC,
    DOMAIN,
    LOGGER,
    MANUFACTURER,
    MAX_MSC_CHANNELS,
    MODEL,
)
from .coordinator import PianoDiscConfigEntry, PianoDiscCoordinator
from .transports import Transport
from .transports.http import HttpTransport
from .transports.mqtt import MqttTransport
from .websocket import async_register_websocket_api

PLATFORMS: list[Platform] = [
    Platform.MEDIA_PLAYER,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.UPDATE,
    Platform.EVENT,
]

# The macOS companion app keeps ES modules by URL. Bump this whenever either
# Lovelace card changes so it cannot revive an old custom-element definition.
_CARD_RESOURCE_REVISION = "2"


async def async_setup_entry(hass: HomeAssistant, entry: PianoDiscConfigEntry) -> bool:
    """Set up PianoDisc Prodigy II from a config entry."""
    await _async_register_frontend(hass)
    transport = await _async_build_transport(hass, entry)
    LOGGER.debug("Using transport %s for %s", type(transport).__name__, entry.title)

    coordinator = PianoDiscCoordinator(hass, entry, transport)
    await coordinator.async_config_entry_first_refresh()

    _remove_legacy_shuffle_entity(hass, entry)
    _remove_legacy_power_proxy_entity(hass, entry)
    _async_sync_msc_registry(hass, entry, coordinator)

    entry.runtime_data = coordinator
    # An options change (linking/unlinking the power outlet) reloads the entry so the
    # coordinator re-reads it and the media_player recomputes its supported features.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Do not probe the SD card until the NRF reports that MIDI and its own initial
    # scan are complete. A retained READY received during setup is already reflected
    # in coordinator.data; later transitions are handled by the coordinator push path.
    if coordinator.data.available:
        coordinator._schedule_library_prefetch()
    return True


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Register the playlist editor as a Lovelace custom-card resource."""
    data = hass.data.setdefault(DOMAIN, {})
    frontend_dir = Path(__file__).with_name("frontend")
    module_urls = (
        f"/{DOMAIN}/playlist-panel.js?v={_CARD_RESOURCE_REVISION}",
        f"/{DOMAIN}/library-card.js?v={_CARD_RESOURCE_REVISION}",
    )
    # v0.1.3 exposed global panels. Remove them on upgrade/reload so the old sidebar
    # entries do not linger after the editor becomes a dashboard card.
    for legacy_panel in (
        "pianodisc-playlists",
        "pianodisc-autoplay",
        "pianodisc-library",
    ):
        async_remove_panel(hass, legacy_panel, warn_if_unknown=False)
    if data.get("frontend_registered"):
        # An integration reload can happen in the same HA process that previously ran
        # the old sidebar implementation. The static route is already present, but the
        # new Lovelace resource still needs to be created.
        for module_url in module_urls:
            _replace_extra_module_url(hass, module_url)
            await _async_register_lovelace_resource(hass, module_url)
        return
    await async_setup_component(hass, "http", {})
    await async_setup_component(hass, "frontend", {})
    async_register_websocket_api(hass)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"/{DOMAIN}/playlist-panel.js",
                str(frontend_dir / "playlist-panel.js"),
                cache_headers=False,
            ),
            StaticPathConfig(
                f"/{DOMAIN}/library-card.js",
                str(frontend_dir / "library-card.js"),
                cache_headers=False,
            ),
            StaticPathConfig(
                f"/{DOMAIN}/default-album-art.png",
                str(Path(__file__).with_name("brand") / "default-album-art.png"),
                cache_headers=True,
            )
        ]
    )
    # ``frontend`` normally creates this set during setup. Keep registration safe for
    # minimal/headless HA installations too, where the visual frontend is unavailable.
    for module_url in module_urls:
        _replace_extra_module_url(hass, module_url)
        await _async_register_lovelace_resource(hass, module_url)
    data["frontend_registered"] = True


def _replace_extra_module_url(hass: HomeAssistant, module_url: str) -> None:
    """Replace older revisions of a card module in the frontend module set."""
    urls = hass.data.setdefault(DATA_EXTRA_MODULE_URL, set())
    base_url = module_url.partition("?")[0]
    for existing in tuple(urls):
        if existing.partition("?")[0] == base_url:
            urls.discard(existing)
    add_extra_js_url(hass, module_url)


async def _async_register_lovelace_resource(hass: HomeAssistant, module_url: str) -> None:
    """Make the card module a first-class Lovelace resource when storage mode is used.

    ``add_extra_js_url`` helps on a full browser reload, but a storage-mode Lovelace
    resource additionally notifies already-open dashboards to load the module.
    """
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or lovelace_data.resource_mode != MODE_STORAGE:
        return
    resources = lovelace_data.resources
    if not isinstance(resources, ResourceStorageCollection):
        return
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    base_url = module_url.partition("?")[0]
    matching = [
        item
        for item in resources.async_items()
        if item.get("url", "").partition("?")[0] == base_url
    ]
    if any(item.get("url") == module_url for item in matching):
        return
    if matching:
        await resources.async_update_item(
            matching[0]["id"],
            {"url": module_url, CONF_RESOURCE_TYPE_WS: "module"},
        )
        for duplicate in matching[1:]:
            await resources.async_delete_item(duplicate["id"])
        return
    await resources.async_create_item(
        {"url": module_url, CONF_RESOURCE_TYPE_WS: "module"}
    )


async def async_unload_entry(hass: HomeAssistant, entry: PianoDiscConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _remove_legacy_shuffle_entity(hass: HomeAssistant, entry: PianoDiscConfigEntry) -> None:
    """Remove the retired standalone shuffle switch from upgraded installations."""
    device_id = entry.unique_id or entry.data[CONF_DEVICE_ID]
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, f"{device_id}_shuffle")
    if entity_id is not None:
        registry.async_remove(entity_id)


def _remove_legacy_power_proxy_entity(
    hass: HomeAssistant, entry: PianoDiscConfigEntry
) -> None:
    """Remove the retired duplicate switch for a linked power outlet."""
    device_id = entry.unique_id or entry.data[CONF_DEVICE_ID]
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", DOMAIN, f"{device_id}_power")
    if entity_id is not None:
        registry.async_remove(entity_id)


def _async_sync_msc_registry(
    hass: HomeAssistant, entry: PianoDiscConfigEntry, coordinator: PianoDiscCoordinator
) -> None:
    """Prune resized MSC entities and create the Show Control device hierarchy."""
    device_id = entry.unique_id or entry.data[CONF_DEVICE_ID]
    entity_registry = er.async_get(hass)
    for channel in range(coordinator.msc_channel_count + 1, MAX_MSC_CHANNELS + 1):
        for domain, unique_id in (
            ("binary_sensor", f"{device_id}_msc_ch{channel}"),
            ("event", f"{device_id}_msc_fire_ch{channel}"),
        ):
            entity_id = entity_registry.async_get_entity_id(domain, DOMAIN, unique_id)
            if entity_id is not None:
                entity_registry.async_remove(entity_id)

    device_registry = dr.async_get(hass)
    show_control_id = f"{device_id}_show_control"
    if coordinator.msc_channel_count == 0:
        device = device_registry.async_get_device(identifiers={(DOMAIN, show_control_id)})
        if device is not None:
            device_registry.async_remove_device(device.id)
        return

    connections = set()
    network_mac = entry.data.get(CONF_NETWORK_MAC)
    if network_mac:
        connections.add((CONNECTION_NETWORK_MAC, network_mac))
    piano = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        connections=connections,
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=coordinator.data.device_name or entry.title,
    )
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, show_control_id)},
        via_device=(DOMAIN, device_id),
        manufacturer=MANUFACTURER,
        name=f"{piano.name or entry.title} Show Control",
    )


async def _async_reload_entry(hass: HomeAssistant, entry: PianoDiscConfigEntry) -> None:
    """Reload the entry when its options change (e.g. the linked power outlet)."""
    await hass.config_entries.async_reload(entry.entry_id)


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
