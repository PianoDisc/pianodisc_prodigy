"""WebSocket API for the PianoDisc playlist editor panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import PianoDiscCoordinator
from .transports.http import title_from_path

_WS_DATA = f"{DOMAIN}/playlist_data"
_WS_SAVE = f"{DOMAIN}/save_playlists"
_WS_AUTOPLAY_DATA = f"{DOMAIN}/autoplay_data"
_WS_SAVE_AUTOPLAY = f"{DOMAIN}/save_autoplay"
_WS_LIBRARY_DATA = f"{DOMAIN}/library_data"


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    """Register playlist editor websocket commands."""
    websocket_api.async_register_command(hass, websocket_playlist_data)
    websocket_api.async_register_command(hass, websocket_save_playlists)
    websocket_api.async_register_command(hass, websocket_autoplay_data)
    websocket_api.async_register_command(hass, websocket_save_autoplay)
    websocket_api.async_register_command(hass, websocket_library_data)


@websocket_api.websocket_command(
    {
        vol.Required("type"): _WS_DATA,
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("refresh", default=False): cv.boolean,
    }
)
@websocket_api.async_response
async def websocket_playlist_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return pianos, playlists and SD-card songs for the editor."""
    try:
        selected = _coordinator_from_msg(hass, msg)
    except ValueError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return

    coordinator, entity_id = selected
    try:
        if msg["refresh"]:
            # Refresh both caches, then return exactly those shared cache values.
            await coordinator.async_refresh_library()
        playlists = await coordinator.async_fetch_playlist_definitions()
        paths = await coordinator.transport.async_fetch_song_paths()
    except Exception as err:
        connection.send_error(msg["id"], "playlist_load_failed", str(err))
        return
    songs = [{"title": title_from_path(path), "path": path} for path in paths]
    connection.send_result(
        msg["id"],
        {
            "entity_id": entity_id,
            "entities": _media_player_entities(hass),
            "playlists": playlists,
            "songs": songs,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): _WS_SAVE,
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("playlists"): [dict],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_save_playlists(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist the edited playlist set."""
    try:
        coordinator, _entity_id = _coordinator_from_msg(hass, msg)
    except ValueError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return

    playlists = [_normalize_playlist(item) for item in msg["playlists"]]
    try:
        await coordinator.async_save_playlist_definitions(playlists)
    except Exception as err:
        connection.send_error(msg["id"], "playlist_save_failed", str(err))
        return
    await coordinator.async_request_refresh()
    connection.send_result(msg["id"], {"playlists": playlists})


@websocket_api.websocket_command({vol.Required("type"): _WS_AUTOPLAY_DATA, vol.Optional("entity_id"): cv.entity_id, vol.Optional("refresh", default=False): cv.boolean})
@websocket_api.async_response
async def websocket_autoplay_data(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return AutoPlay configuration with the shared playlist cache."""
    try:
        coordinator, entity_id = _coordinator_from_msg(hass, msg)
        playlists = await coordinator.async_fetch_playlists(force=msg["refresh"])
        config = await coordinator.transport.async_fetch_autoplay_config()
    except Exception as err:
        connection.send_error(msg["id"], "autoplay_load_failed", str(err))
        return
    connection.send_result(msg["id"], {"entity_id": entity_id, "entities": _media_player_entities(hass), "playlists": playlists, "config": config})


@websocket_api.websocket_command({vol.Required("type"): _WS_LIBRARY_DATA, vol.Optional("entity_id"): cv.entity_id})
@websocket_api.async_response
async def websocket_library_data(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Return the cached library for the searchable library panel."""
    try:
        coordinator, entity_id = _coordinator_from_msg(hass, msg)
        paths = await coordinator.transport.async_fetch_song_paths()
    except Exception as err:
        connection.send_error(msg["id"], "library_load_failed", str(err))
        return
    connection.send_result(msg["id"], {"entity_id": entity_id, "entities": _media_player_entities(hass), "songs": [{"title": title_from_path(path), "path": path} for path in paths]})


@websocket_api.websocket_command({vol.Required("type"): _WS_SAVE_AUTOPLAY, vol.Required("entity_id"): cv.entity_id, vol.Required("config"): dict})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_save_autoplay(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Validate and persist the one AutoPlay configuration object."""
    try:
        coordinator, _entity_id = _coordinator_from_msg(hass, msg)
        config = _normalize_autoplay(msg["config"])
        await coordinator.transport.async_save_autoplay_config(config)
    except Exception as err:
        connection.send_error(msg["id"], "autoplay_save_failed", str(err))
        return
    connection.send_result(msg["id"], {"config": config})


def _coordinator_from_msg(
    hass: HomeAssistant, msg: dict[str, Any]
) -> tuple[PianoDiscCoordinator, str]:
    """Resolve a media_player entity id to its config entry coordinator."""
    entities = _media_player_entities(hass)
    if not entities:
        raise ValueError("No PianoDisc media player is loaded")
    entity_id = msg.get("entity_id") or entities[0]["entity_id"]
    registry_entry = er.async_get(hass).async_get(entity_id)
    if (
        registry_entry is None
        or registry_entry.domain != MEDIA_PLAYER_DOMAIN
        or registry_entry.platform != DOMAIN
        or registry_entry.config_entry_id is None
    ):
        raise ValueError(f"{entity_id} is not a PianoDisc media player")
    config_entry = hass.config_entries.async_get_entry(registry_entry.config_entry_id)
    if config_entry is None or config_entry.runtime_data is None:
        raise ValueError(f"{entity_id} is not loaded")
    return config_entry.runtime_data, entity_id


def _media_player_entities(hass: HomeAssistant) -> list[dict[str, str]]:
    """Return all loaded PianoDisc media_player entities."""
    registry = er.async_get(hass)
    entities: list[dict[str, str]] = []
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        for entry in registry.entities.get_entries_for_config_entry_id(
            config_entry.entry_id
        ):
            if entry.domain != MEDIA_PLAYER_DOMAIN or entry.platform != DOMAIN:
                continue
            state = hass.states.get(entry.entity_id)
            entities.append(
                {
                    "entity_id": entry.entity_id,
                    "name": state.name if state is not None else entry.entity_id,
                }
            )
    return entities


def _normalize_playlist(playlist: dict[str, Any]) -> dict[str, Any]:
    """Keep App-compatible playlist shape while preserving unknown fields."""
    item = dict(playlist)
    content = item.get("content")
    if not isinstance(content, dict):
        content = {}
    include = content.get("include")
    exclude = content.get("exclude")
    content["include"] = [str(path) for path in include] if isinstance(include, list) else []
    content["exclude"] = [str(path) for path in exclude] if isinstance(exclude, list) else []
    item["content"] = content
    if not isinstance(item.get("name"), str) or not item["name"].strip():
        item["name"] = "Untitled Playlist"
    item.setdefault("sort", "Shuffle")
    item.setdefault("repeat", 1)
    return item


def _normalize_autoplay(config: dict[str, Any]) -> dict[str, object]:
    playlist, sort = config.get("playlist"), config.get("sort", 0)
    if not isinstance(playlist, int) or playlist < 0:
        raise ValueError("Choose an AutoPlay playlist")
    if not isinstance(sort, int) or sort not in {0, 1, 2}:
        raise ValueError("Invalid AutoPlay playback order")
    return {"enable": bool(config.get("enable", False)), "playlist": playlist, "loop": bool(config.get("loop", False)), "sort": sort}
