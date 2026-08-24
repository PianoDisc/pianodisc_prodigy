"""The coordinator — single source of truth, fed by exactly one transport."""

from __future__ import annotations

import asyncio

from homeassistant.components import persistent_notification
from homeassistant.components.media_player import MediaPlayerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_POWER_SWITCH,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    POWER_OFF_SETTLE,
    POWER_ON_POLL,
    POWER_ON_TIMEOUT,
    SCAN_INTERVAL_DISCONNECTED,
    SCAN_INTERVAL_IDLE,
    SCAN_INTERVAL_PLAYING,
    SCAN_INTERVAL_SYNCING,
)
from .models import ProdigyData
from .transports import Transport

type PianoDiscConfigEntry = ConfigEntry[PianoDiscCoordinator]

# The generic turn_on/off service dispatches to the linked entity's own domain
# (switch / input_boolean / light), so one call covers every supported power entity.
_HA_DOMAIN = "homeassistant"


class PianoDiscCoordinator(DataUpdateCoordinator[ProdigyData]):
    """Owns the transport and publishes ``ProdigyData`` to entities.

    Push transports call ``async_set_updated_data`` via the push listener; the polling
    path (``_async_update_data``) is the fallback and the snapshot-on-startup seed.

    Optionally tracks a user-linked power outlet (``CONF_POWER_SWITCH``): its on/off
    state becomes the piano's power authority, and TURN_ON/TURN_OFF drive it. See
    power-control design (revised 2026-06-08: linking grants full on/off control).
    """

    config_entry: PianoDiscConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: PianoDiscConfigEntry,
        transport: Transport,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}:{entry.title}",
            config_entry=entry,
            update_interval=(
                None if transport.uses_push_updates else DEFAULT_SCAN_INTERVAL
            ),
        )
        self.transport = transport
        self.transport.set_push_listener(self._handle_push)
        self.transport.set_library_progress_listener(self._handle_library_progress)
        # Live library-scan progress (a diagnostic sensor reads these; the scan pushes
        # them). Kept off ProdigyData so a normal status push can't reset the count.
        self.library_count: int | None = None
        self.library_scanning: bool = False
        self._notify_library_refresh = False
        self._library_lock = asyncio.Lock()
        # Optional linked power outlet (entity_id) and its last-known on/off state.
        self.power_switch: str | None = entry.options.get(CONF_POWER_SWITCH) or None
        self.power_on: bool | None = None
        # Loop-time deadline: while "now" is before it AND the piano isn't reachable
        # yet, the media_player shows a transient "starting" state. Time-bounded so it
        # can never wedge, and overridden the moment the piano reports. See
        # power-control design.
        self._powering_on_until = 0.0

    @property
    def power_linked(self) -> bool:
        """True when the user has dedicated a power outlet to the piano."""
        return self.power_switch is not None

    @property
    def getting_ready(self) -> bool:
        """True while a linked, powered-on piano hasn't reported a state yet (booting).

        Accurate because the linked switch tells us it *is* on, so this is "getting
        ready", not unknown/idle. Cleared the moment a real state arrives; time-bounded
        so a non-responding piano can't wedge it. See power-control design.
        """
        if not (self.power_linked and self.power_on):
            return False
        if self.hass.loop.time() >= self._powering_on_until:
            return False
        return self.data is None or self.data.state is None

    async def _async_setup(self) -> None:
        """Bring the transport up and start tracking the power outlet (if linked)."""
        await self.transport.async_setup()
        if self.power_switch is not None:
            self.power_on = self._read_power_state(
                self.hass.states.get(self.power_switch)
            )
            # Already on at startup → "getting ready" until it reports a state.
            if self.power_on:
                self._powering_on_until = self.hass.loop.time() + POWER_ON_TIMEOUT
            self.config_entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, [self.power_switch], self._handle_power_event
                )
            )

    async def _async_update_data(self) -> ProdigyData:
        # Powered down through the linked outlet → don't poll a host that can't answer.
        if self.power_switch is not None and self.power_on is False:
            return (self.data or ProdigyData()).merge(available=False)
        try:
            data = await self.transport.async_fetch_snapshot()
        except Exception as err:  # transports raise heterogeneous errors
            raise UpdateFailed(f"Error polling piano: {err}") from err
        self._retune_interval(data)
        return data

    @callback
    def _handle_push(self, data: ProdigyData) -> None:
        """Apply an out-of-band update from a push transport."""
        became_ready = data.available and (
            self.data is None or not self.data.available
        )
        self._retune_interval(data)
        self.async_set_updated_data(data)
        if became_ready:
            self._schedule_library_prefetch()

    # -- library scan progress ---------------------------------------------
    @property
    def _library_notification_id(self) -> str:
        return f"{DOMAIN}_library_scan_{self.config_entry.entry_id}"

    @callback
    def _handle_library_progress(self, count: int, scanning: bool) -> None:
        """Live library-scan progress → the Library sensor, and (only for a manual
        Refresh) a persistent notification that tracks the count and clears when done."""
        self.library_count = count
        self.library_scanning = scanning
        self.async_update_listeners()
        if not self._notify_library_refresh:
            return
        if scanning:
            persistent_notification.async_create(
                self.hass,
                f"Scanning the SD-card library… {count} songs so far.",
                title=self.config_entry.title,
                notification_id=self._library_notification_id,
            )
        else:
            persistent_notification.async_dismiss(
                self.hass, self._library_notification_id
            )
            self._notify_library_refresh = False

    async def async_refresh_library(self) -> None:
        """Force a library re-scan (the Refresh-library button), with a progress
        notification. The scan's terminal progress event clears the notification."""
        self._notify_library_refresh = True
        try:
            await self._async_scan_library(force=True)
        finally:
            # Belt-and-suspenders: if the scan raised before its terminal event, still
            # clear the notification and the flag.
            if self._notify_library_refresh:
                self._notify_library_refresh = False
                persistent_notification.async_dismiss(
                    self.hass, self._library_notification_id
                )

    @callback
    def _schedule_library_prefetch(self) -> None:
        """Refresh the cache after the piano transitions into playable READY."""
        self.config_entry.async_create_background_task(
            self.hass,
            self.async_prefetch_library(),
            "pianodisc_prodigy_library_prefetch",
        )

    async def async_prefetch_library(self) -> None:
        """Populate the library automatically once playback is safe."""
        try:
            await self._async_scan_library(force=True)
        except Exception:
            LOGGER.debug("Library prefetch failed", exc_info=True)

    async def _async_scan_library(self, *, force: bool) -> list[str]:
        """Serialize automatic and manual scans against the device's shared buffer."""
        async with self._library_lock:
            songs = await self.transport.async_fetch_song_list(force=force)
            self.library_count = len(songs)
            self.async_update_listeners()
            return songs

    @callback
    def _retune_interval(self, data: ProdigyData) -> None:
        """Poll lightly when settled; faster while unreachable or still resolving."""
        if self.transport.uses_push_updates:
            if self.update_interval is not None:
                self.update_interval = None
            return
        if not data.available:
            interval = SCAN_INTERVAL_DISCONNECTED
        elif data.state is None:
            interval = SCAN_INTERVAL_SYNCING
        elif data.state == MediaPlayerState.PLAYING and data.song is None:
            interval = (
                SCAN_INTERVAL_SYNCING  # just (re)started — get the new title fast
            )
        elif data.state == MediaPlayerState.PLAYING:
            interval = SCAN_INTERVAL_PLAYING
        else:
            interval = SCAN_INTERVAL_IDLE
        if interval != self.update_interval:
            self.update_interval = interval

    # -- linked power outlet -----------------------------------------------
    @staticmethod
    def _read_power_state(state: State | None) -> bool | None:
        """Map the tracked outlet's state to on/off, or None when it can't be read."""
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        return state.state == STATE_ON

    @callback
    def _handle_power_event(self, event: Event[EventStateChangedData]) -> None:
        """React to the linked outlet changing (from HA, the app, or a wall switch)."""
        new = self._read_power_state(event.data["new_state"])
        if new == self.power_on:
            return
        self.power_on = new
        if new:  # came on out-of-band → show "starting" + pick it up before idle poll
            self.transport.invalidate()
            self._powering_on_until = self.hass.loop.time() + POWER_ON_TIMEOUT
            self.async_set_updated_data(self._blank_snapshot())
            self.hass.async_create_task(self.async_refresh())
        else:
            self._powering_on_until = 0.0
            self.async_update_listeners()

    def _blank_snapshot(self) -> ProdigyData:
        """Current data with live playback cleared — shown while (re)powering on."""
        base = self.data or ProdigyData()
        return base.merge(
            available=False,
            state=None,
            song=None,
            song_index=None,
            volume=None,
            busy=None,
        )

    async def async_power_on(self) -> None:
        """Energize the linked outlet and wait for the piano to come online."""
        if self.power_switch is None:
            return
        await self.hass.services.async_call(
            _HA_DOMAIN,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: self.power_switch},
            blocking=True,
        )
        # Forget stale state from before the power cycle and show "starting" at once.
        self.transport.invalidate()
        self.power_on = True
        self._powering_on_until = self.hass.loop.time() + POWER_ON_TIMEOUT
        self.async_set_updated_data(self._blank_snapshot())
        if await self._async_wait_until_available(POWER_ON_TIMEOUT):
            self._powering_on_until = 0.0
            ir.async_delete_issue(self.hass, DOMAIN, self._power_issue_id)
            return
        self._powering_on_until = 0.0
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._power_issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="power_on_timeout",
            translation_placeholders={
                "name": self.config_entry.title,
                "switch": self.power_switch,
            },
        )
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="power_on_timeout",
            translation_placeholders={"seconds": str(POWER_ON_TIMEOUT)},
        )

    async def async_power_off(self) -> None:
        """Gracefully stop playback, let it settle, then cut power to the outlet."""
        if self.power_switch is None:
            return
        try:
            await self.transport.async_stop()
        except Exception as err:  # cut power even if the graceful stop didn't land
            LOGGER.debug("Stop before power-off failed (%s); cutting power anyway", err)
        await asyncio.sleep(POWER_OFF_SETTLE)
        await self.hass.services.async_call(
            _HA_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: self.power_switch},
            blocking=True,
        )
        self.power_on = False
        self._powering_on_until = 0.0
        self.async_update_listeners()

    async def _async_wait_until_available(self, seconds: float) -> bool:
        """Poll until the piano reports a real playback state, or ``seconds`` elapse."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + seconds
        while True:
            await self.async_refresh()
            if self.data is not None and self.data.state is not None:
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(POWER_ON_POLL)

    @property
    def _power_issue_id(self) -> str:
        return f"power_on_timeout_{self.config_entry.entry_id}"

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.transport.async_close()
