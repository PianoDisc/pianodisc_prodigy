# Changelog

## v0.1.3 - 2026-08-27

- Adds startup readiness and initial library-sync states, so controls wait until the
  piano and its SD-card library are safe to use.
- Adds cached library and playlist loading, a searchable **Piano Library** sidebar,
  and shared manual refresh for songs and playlists.
- Adds the **Piano AutoPlay** workspace and models the piano's all-songs, playlist,
  shuffle, and repeat behaviors in Home Assistant.
- Adds safer, faster path-based song selection and improved media metadata.
- Adds optional independent smart-outlet power control, device IP display, native
  diagnostics download, and device-card firmware-version updates.
- Makes MQTT the preferred live transport while retaining HTTP fallback.
