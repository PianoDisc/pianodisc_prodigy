"""Constants for the PianoDisc Prodigy II integration.

See the project planning memory ([[plan-review-v2]], [[mvp-v1-architecture]]) for the
rationale behind these values. Anything marked TODO is a build-time item to confirm
against real hardware (deviceID DEFAEE5C894F) before locking.
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Final

DOMAIN: Final = "pianodisc_prodigy"
LOGGER: Final = logging.getLogger(__package__)

# Device identity -----------------------------------------------------------
MANUFACTURER: Final = "PianoDisc"
MODEL: Final = "Prodigy II"

# Config-entry / options keys (CONF_HOST and CONF_NAME come from homeassistant.const)
CONF_DEVICE_ID: Final = "device_id"
# optional dedicated-outlet link (off by default)
CONF_POWER_SWITCH: Final = "power_switch"

# Transport selection -------------------------------------------------------
TRANSPORT_MQTT: Final = "mqtt"
TRANSPORT_HTTP: Final = "http"
TRANSPORT_FAKE: Final = "fake"  # in-memory transport for dev/tests/scaffold

# MQTT contract (PianoDisc-Prodigy/<device_id>/...) -------------------------
# Verified live 2026-05-29 against DEFAEE5C894F; see [[mqtt-contract]].
MQTT_TOPIC_ROOT: Final = "PianoDisc-Prodigy"
MQTT_TOPIC_COMMAND: Final = "player"  # HA -> piano JSON command envelope
MQTT_TOPIC_DEVICE: Final = "device"  # HA -> piano (DebugJSON etc.)
MQTT_TOPIC_READY: Final = "ready"  # retained availability: "OK" online / "OFFLINE" via Last-Will
# P1 firmware makes these slow-moving status topics retained and truthful.
MQTT_TOPIC_BUSY: Final = "busy"  # "TRUE"/"FALSE" (solenoids striking)
MQTT_TOPIC_VOLUME: Final = "volume"  # percent string "0".."100" (not MIDI 0..127)
MQTT_TOPIC_PLAYER_STATUS: Final = "player/status"  # retained /playerStatus JSON
MQTT_TOPIC_DEVICE_NAME: Final = "deviceName"
MQTT_TOPIC_MSC: Final = "msc"  # JSON {"command":"GO|STOP|FIRE","cue":"NNN"}
# CR#3: retained {"audio":"x.y.z","midi":"x.y.z"} so MQTT-only installs (no HTTP
# IP) still learn the firmware versions that HTTP /debugJson otherwise provides.
MQTT_TOPIC_VERSION: Final = "version"
# CR#3 ②: retained {"audio_latest","midi_latest","audio_url","midi_url"} — the
# latest available firmware, from the device's own backend check (the HA
# integration is public, so it can't hold the backend credential itself).
MQTT_TOPIC_UPDATE: Final = "update"
# CR#14: MQTT library/playlist request-response bridge. These remove the HTTP
# dependency for Browse Media / playlist source discovery once matching firmware ships.
MQTT_TOPIC_LIBRARY_REQUEST: Final = "library/request"
MQTT_TOPIC_LIBRARY_PAGE: Final = "library/page"
MQTT_TOPIC_PLAYLIST_REQUEST: Final = "playlist/request"
MQTT_TOPIC_PLAYLIST_STATE: Final = "playlist/state"

# Availability payloads on .../ready. CR#2: firmware registers an MQTT Last-Will of
# "OFFLINE" (retained) so the broker announces an ungraceful disconnect instantly;
# the connect-time "OK" is retained too, so an HA restart reads availability at once.
MQTT_PAYLOAD_ONLINE: Final = "OK"
MQTT_PAYLOAD_OFFLINE: Final = "OFFLINE"

# MQTT discovery subscription (manifest "mqtt" key fires async_step_mqtt on this)
MQTT_DISCOVERY_TOPIC: Final = f"{MQTT_TOPIC_ROOT}/+/{MQTT_TOPIC_READY}"

# HTTP surface (unauthenticated on LAN, version-pinned) ---------------------
HTTP_PORT: Final = 80
HTTP_REQUEST_TIMEOUT: Final = 10  # seconds, per request
HTTP_SOCKET_LIMIT: Final = 2  # device caps at 3 open sockets; leave headroom

# Prime-then-poll async-cache tuning (the library/status GETs are eventually
# consistent with no completion signal — see [[golden-capture]]).
PRIME_POLL_WAIT: Final = 0.5  # seconds between a prime (e.g. /scanSD) and the read
MAX_SCAN_PAGES: Final = 50  # hard cap for paged /songlist scan (Repair if hit)
SONGLIST_PAGE_SIZE: Final = 10  # entries in a full /scanSD page; a short page = the end
# /songlist is a single shared buffer with NO completion signal (firmware ask), so the
# paged scan must POLL until the buffer advances to the *next* page — a fixed wait reads
# the stale buffer and silently truncates the library (verified live 2026-06-03).
# Cadence + termination mirror the reference Calibrate app (getProdigySongs, verified
# 2026-07): poll gently every SCAN_POLL_INTERVAL up to SCAN_POLL_MAX times per attempt,
# re-priming /scanSD?page=N for SCAN_PAGE_ATTEMPTS tries if the buffer hasn't advanced.
# CRUCIAL: a buffer that never advances is NOT end-of-library (that reading truncated the
# scan under load, and lost everything when the buffer already held the page) — only a
# SHORT page (< SONGLIST_PAGE_SIZE) authoritatively ends the scan.
# The app polls every 2s but loads pages lazily (user only waits for page 0); HA scans
# every page eagerly for a flat BROWSE_MEDIA list, so a 1s poll keeps the full scan ~30s
# while staying far gentler than the old 0.4s (which hammered the device). Advance is
# detected by content diff, not timing, so a faster poll only detects the flip sooner.
SCAN_POLL_INTERVAL: Final = 1.0  # seconds between /songlist polls (was 0.4 — it hammered the device)
SCAN_POLL_MAX: Final = 10  # /songlist polls per scan attempt (~10s at SCAN_POLL_INTERVAL)
SCAN_PAGE_ATTEMPTS: Final = 2  # times to (re-)prime /scanSD?page=N before giving up on a page
SONGLIST_TTL: Final = 21600  # 6h backstop; Refresh-library button forces a re-scan

# /playerStatus "state" code -> HA MediaPlayerState (0 idle, 1 playing, 2 paused).
# /debugJson?type=request keys (single source of deviceID + both firmware versions).
DEBUG_KEY_DEVICE_ID: Final = "Device ID"
DEBUG_KEY_AUDIO_VERSION: Final = "Audio Version"
DEBUG_KEY_MIDI_VERSION: Final = "MIDI Version"

# Volume scaling: device speaks 1..100 (SD playback / solenoid force), HA speaks 0..1.
# NB: 0.0 must map to >= VOLUME_MIN so we never send an out-of-range no-op.
VOLUME_MIN: Final = 1
VOLUME_MAX: Final = 100

# Polling cadence. In MQTT mode the HTTP poll is authoritative for state/volume, but the
# device's HTTP server competes with the audio/solenoid task — so poll LIGHTLY while
# playing (MQTT busy carries the real-time "playing" between polls). Aggressive polling
# makes playback choppy and the device's MQTT laggy.
SCAN_INTERVAL_PLAYING: Final = timedelta(seconds=30)
SCAN_INTERVAL_IDLE: Final = timedelta(seconds=30)
DEFAULT_SCAN_INTERVAL: Final = SCAN_INTERVAL_IDLE
# Unreachable: poll fast to catch recovery (a non-answer costs the device nothing).
SCAN_INTERVAL_DISCONNECTED: Final = timedelta(seconds=5)
# Reachable but state/volume not resolved yet (boot / ~1-min audio-engine sync).
SCAN_INTERVAL_SYNCING: Final = timedelta(seconds=10)

# Availability watchdog (MQTT mode): treat absence of .../ready as offline.
READY_WATCHDOG: Final = timedelta(seconds=75)

# Power-link (optional dedicated outlet). When a switch is linked, TURN_ON energizes it
# and waits up to POWER_ON_TIMEOUT for the piano to come online; TURN_OFF gracefully
# stops, waits POWER_OFF_SETTLE, then de-energizes. See [[power-architecture]].
POWER_ON_TIMEOUT: Final = 90  # seconds to wait for the piano after energizing
POWER_ON_POLL: Final = 3.0  # seconds between availability checks during that wait
POWER_OFF_SETTLE: Final = 1.0  # seconds between the graceful Stop and cutting power

# Autoplay publishes per-note .../busy bursts. Hold PLAYING this long after the last
# burst so the per-note flapping doesn't bounce the state (verified live 2026-06-08).
BUSY_DEBOUNCE: Final = 10.0  # seconds

# After a Stop, hold PLAYING at most this long and let …/busy verify the result: if keys
# keep striking the command was missed (stay PLAYING so the user can retry), else IDLE.
STOP_CONFIRM: Final = 5.0  # seconds

# After a (re)play the device keeps reporting the previous /playerStatus.song for a
# moment, so suppress the stale title until a new one appears — bounded so replaying the
# same song isn't hidden forever.
SONG_UNKNOWN_GRACE: Final = 30.0  # seconds

# /playerStatus.sort lags after we POST a shuffle change; hold the just-set value until
# the device's reading catches up (or this lapses) so the shuffle switch sticks.
SHUFFLE_HOLD_GRACE: Final = 60.0  # seconds

# Firmware version policy (decision #3). Floors/recommended.
# TODO: confirm the exact compat range with the audio-engine team.
FW_AUDIO_FLOOR: Final = "0.4.5"
FW_AUDIO_RECOMMENDED: Final = "0.4.7"
FW_MIDI_FLOOR: Final = "1.0.5"
FW_MIDI_RECOMMENDED: Final = "1.3.5"
