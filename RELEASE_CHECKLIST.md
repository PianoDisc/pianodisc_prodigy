# Release Checklist

- [ ] Create the public GitHub repository.
- [ ] Confirm the public repository URL is `https://github.com/PianoDisc/pianodisc_prodigy.git`.
- [ ] Confirm `README.md` uses HACS custom repository installation as the primary user path.
- [ ] Confirm `documentation` and `issue_tracker` in `custom_components/pianodisc_prodigy/manifest.json` point to the public repository.
- [ ] Create a GitHub release tag that matches `manifest.json` version, for example `v0.1.0` for version `0.1.0`.
- [ ] Choose and add a license file if this project should be open-source.
- [ ] Review `custom_components/pianodisc_prodigy` for secrets or private environment details.
- [ ] Test HACS custom repository install from a clean Home Assistant instance.
- [ ] Test uninstall and reinstall through HACS.
- [ ] Test MQTT discovery.
- [ ] Test manual IP setup.
- [ ] Test media playback, library browsing, playlist editing, diagnostics, and logs.
- [ ] Optional later: submit the repository to HACS default repositories.
