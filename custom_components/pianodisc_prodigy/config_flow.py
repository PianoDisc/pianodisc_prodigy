"""Config flow for PianoDisc Prodigy II.

Three entry paths, all keyed on the MAC-derived deviceID so the same physical unit
never gets added twice:

* ``async_step_user``  — manual IP (always available).
* ``async_step_mqtt``  — zero-config when the unit is already publishing
  ``PianoDisc-Prodigy/<deviceID>/ready`` (manifest "mqtt" key).
* ``async_step_dhcp``  — passive, on DHCP lease for ``prodigy2-*`` / ``pianodisc-*``.

``async_step_reconfigure`` lets the user set or correct the host IP afterwards — the
MQTT-discovered path has no IP, so the HTTP half (firmware, library, cold-start seed)
cannot compose until one is supplied.

The options flow links an optional dedicated power outlet so HA can turn the piano on
and off and show its power state (see power-control design).
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
import voluptuous as vol

from .const import (
    CONF_DEVICE_ID,
    CONF_POWER_SWITCH,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    MQTT_TOPIC_ROOT,
)
from .transports.http import HttpTransport

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_NAME): str,
    }
)

# Entities that can act as the piano's power outlet (a smart plug, relay, or a virtual
# toggle). Driven via the generic homeassistant.turn_on/off, which dispatches by domain.
_POWER_SWITCH_DOMAINS = ["switch", "input_boolean", "light"]


def _default_name(device_id: str) -> str:
    """A human default name. The per-unit ``device_name`` is the generic "Prodigy2",
    so we suffix the deviceID tail (e.g. "PianoDisc Prodigy II ABCDEF")."""
    return f"{MANUFACTURER} {MODEL} {device_id[-6:]}"


class PianoDiscConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PianoDisc Prodigy II."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._device_id: str | None = None
        self._name: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PianoDiscOptionsFlow:
        """Return the options flow (link a power outlet)."""
        return PianoDiscOptionsFlow()

    # -- manual ------------------------------------------------------------
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                device_id, name = await self._async_probe(host)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME) or name,
                    data={
                        CONF_HOST: host,
                        CONF_DEVICE_ID: device_id,
                        CONF_NAME: user_input.get(CONF_NAME) or name,
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=_USER_SCHEMA, errors=errors
        )

    # -- MQTT discovery ----------------------------------------------------
    async def async_step_mqtt(
        self, discovery_info: MqttServiceInfo
    ) -> ConfigFlowResult:
        # topic = PianoDisc-Prodigy/<deviceID>/ready
        parts = discovery_info.topic.split("/")
        if len(parts) < 3 or parts[0] != MQTT_TOPIC_ROOT:
            return self.async_abort(reason="invalid_discovery_info")
        device_id = parts[1]
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured()
        self._device_id = device_id
        self._name = _default_name(device_id)
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_discovery_confirm()

    # -- DHCP discovery ----------------------------------------------------
    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        device_id = format_mac(discovery_info.macaddress).replace(":", "").upper()
        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: discovery_info.ip})
        self._host = discovery_info.ip
        self._device_id = device_id
        self._name = discovery_info.hostname or _default_name(device_id)
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._device_id is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._name or self._device_id,
                data={
                    CONF_HOST: self._host or "",
                    CONF_DEVICE_ID: self._device_id,
                    CONF_NAME: self._name or self._device_id,
                },
            )
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._name or self._device_id},
        )

    # -- reconfigure (set/correct the host IP) -----------------------------
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set or correct the device's IP.

        An MQTT-discovered entry has no host, so the HTTP half (firmware sensors,
        library browse, cold-start seed) cannot compose until one is supplied. The
        new IP is probed and must resolve to the *same* deviceID, so a typo can't
        point this entry at a different piano.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            try:
                device_id, _name = await self._async_probe(host)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                if device_id != entry.unique_id:
                    errors["base"] = "wrong_device"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_HOST: host}
                    )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, "")): str}
            ),
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    # -- helpers -----------------------------------------------------------
    async def _async_probe(self, host: str) -> tuple[str, str]:
        """Resolve ``(device_id, default_name)`` from a host over HTTP.

        ``GET /debugJson?type=request`` is the only HTTP source of the MAC-derived
        deviceID and both firmware versions (see device captures). Never key on the
        editable ``device_name`` — it is the generic "Prodigy2" on ``/status.json``.
        """
        transport = HttpTransport(async_get_clientsession(self.hass), host)
        info = await transport.async_get_device_info()
        if not info:
            raise CannotConnect
        device_id = info["device_id"]
        return device_id, _default_name(device_id)


class PianoDiscOptionsFlow(OptionsFlow):
    """Link (or unlink) a dedicated power outlet for the piano.

    The selected entity becomes the piano's power authority: TURN_ON energizes it and
    waits for the piano to come online, TURN_OFF gracefully stops then de-energizes it,
    and its on/off state shows on the media_player. Empty disables power control.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            # Drop empty values so clearing the field removes the link entirely.
            return self.async_create_entry(
                title="", data={k: v for k, v in user_input.items() if v}
            )

        current = self.config_entry.options.get(CONF_POWER_SWITCH)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_POWER_SWITCH,
                    description={"suggested_value": current},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=_POWER_SWITCH_DOMAINS)
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class CannotConnect(Exception):
    """Raised when a host cannot be reached during probing."""
