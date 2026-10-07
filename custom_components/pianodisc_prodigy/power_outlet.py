"""Take over the linked power outlet so voice assistants see one piano.

The Prodigy has no power switch of its own; power is a smart plug the user links in
the options. Users name that plug after the piano ("Piano"), so Assist and Alexa end
up with two entities called "Piano" and refuse "turn on the piano". This module hides
the plug's own entity and moves its voice-assistant exposure onto the media player,
which already turns the outlet on and off. It mirrors what Home Assistant's
``switch_as_x`` integration does for the entities it wraps, and undoes it the same way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.homeassistant import exposed_entities
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_DEVICE_ID, DOMAIN, LOGGER

if TYPE_CHECKING:
    from .coordinator import PianoDiscConfigEntry


def _media_player_entity_id(hass: HomeAssistant, entry: PianoDiscConfigEntry) -> str | None:
    """Registry entity_id of this entry's media player (None before first setup)."""
    unique_id = entry.unique_id or entry.data[CONF_DEVICE_ID]
    return er.async_get(hass).async_get_entity_id(
        Platform.MEDIA_PLAYER, DOMAIN, unique_id
    )


def async_take_over_outlet(
    hass: HomeAssistant, entry: PianoDiscConfigEntry, outlet_entity_id: str
) -> None:
    """Hide the outlet's entity and move its voice exposure to the media player.

    Idempotent: an outlet already hidden by this integration is left alone, so a
    reload never copies the outlet's now-false exposure back onto the media player.
    An outlet the user hid themselves is also left alone.
    """
    registry = er.async_get(hass)
    outlet = registry.async_get(outlet_entity_id)
    if outlet is None:
        LOGGER.debug("Power outlet %s has no registry entry; not hiding it", outlet_entity_id)
        return
    if outlet.hidden_by is not None:
        return
    media_player_id = _media_player_entity_id(hass, entry)
    if media_player_id is None:
        LOGGER.debug("Media player not registered yet; not taking over %s", outlet_entity_id)
        return

    for assistant, settings in exposed_entities.async_get_entity_settings(
        hass, outlet_entity_id
    ).items():
        if (should_expose := settings.get("should_expose")) is None:
            continue
        # The outlet's exposure becomes the media player's, so "turn on the piano"
        # reaches the piano in every assistant the plug was exposed to.
        if should_expose:
            exposed_entities.async_expose_entity(hass, assistant, media_player_id, True)
        exposed_entities.async_expose_entity(hass, assistant, outlet_entity_id, False)

    registry.async_update_entity(
        outlet_entity_id, hidden_by=er.RegistryEntryHider.INTEGRATION
    )
    LOGGER.info(
        "Hid power outlet %s; voice assistants now reach the piano through %s",
        outlet_entity_id,
        media_player_id,
    )


def async_release_outlet(
    hass: HomeAssistant, entry: PianoDiscConfigEntry, outlet_entity_id: str
) -> None:
    """Undo ``async_take_over_outlet``: unhide the outlet and restore its exposure."""
    registry = er.async_get(hass)
    outlet = registry.async_get(outlet_entity_id)
    if outlet is None or outlet.hidden_by is not er.RegistryEntryHider.INTEGRATION:
        return

    media_player_id = _media_player_entity_id(hass, entry)
    if media_player_id is not None:
        for assistant, settings in exposed_entities.async_get_entity_settings(
            hass, media_player_id
        ).items():
            if (should_expose := settings.get("should_expose")) is None:
                continue
            exposed_entities.async_expose_entity(
                hass, assistant, outlet_entity_id, should_expose
            )

    registry.async_update_entity(outlet_entity_id, hidden_by=None)
    LOGGER.info("Restored power outlet %s", outlet_entity_id)
