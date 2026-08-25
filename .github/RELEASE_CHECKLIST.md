# Release checklist

Maintainer notes. Not user-facing documentation.

## Every release

- [ ] **Bump `version` in `custom_components/pianodisc_prodigy/manifest.json`.**
      The GitHub release tag must match it exactly — `v0.1.3` for version `0.1.3`.
      HACS, the Home Assistant integration page, and the update entity all read this
      field, and they disagree with each other the moment it drifts from the tag.
- [ ] Confirm `strings.json` and `translations/en.json` are still identical.
- [ ] Confirm any new entity has a `translation_key` and an entry in `strings.json`.
- [ ] Update the documentation for anything user-visible that changed.
- [ ] Create the GitHub release with the matching tag and readable release notes.
- [ ] Install the release into a clean Home Assistant instance through HACS and set it up
      following `README.md` alone, without prior knowledge.

## Before the next public milestone

- [ ] Submit the brand assets to
      [home-assistant/brands](https://github.com/home-assistant/brands) under
      `custom_integrations/pianodisc_prodigy/`. Until this merges, HACS and Home Assistant
      show a blank grey placeholder instead of the logo — they never read logos from this
      repository. Source files are in `custom_components/pianodisc_prodigy/brand/`.
- [ ] Add a repository description and topics on GitHub.
- [ ] Decide on a license and add the file.
- [ ] Add CI: the hassfest action and the HACS validation action, plus a release check that
      fails when the tag and the manifest version disagree.
- [ ] Capture the screenshots listed in `docs/images/SCREENSHOTS.md` and replace the
      placeholders in the documentation.
- [ ] Add `translations/zh-Hans.json`.
- [ ] Work through the open `docs-*` entries in
      `custom_components/pianodisc_prodigy/quality_scale.yaml`.

## Testing before a demo or a milestone release

- [ ] MQTT discovery, from a piano that has never been added.
- [ ] Manual setup by IP address, with no broker running at all.
- [ ] Reconfigure to change the IP address, including the wrong-piano rejection.
- [ ] Media playback, browsing, and playlist selection.
- [ ] The playlist panel: create, edit, save, and confirm on the piano.
- [ ] Library refresh after changing the SD card contents.
- [ ] Cold start: power the piano off and on, and confirm it recovers unattended.
- [ ] Power outlet linking, including the timeout repair notice.
- [ ] Download diagnostics, and confirm nothing identifying is present.
- [ ] Uninstall and reinstall through HACS.

## Later

- [ ] Submit to the HACS default repository list. This needs the brands entry, a
      repository description, topics, and a license to be in place first.
