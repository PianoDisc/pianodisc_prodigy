class PianoDiscAutoPlayPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._load();
    }
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._entities = [];
    this._entityId = null;
    this._playlists = [];
    this._config = { enable: false, playlist: 0, loop: false, sort: 0 };
    this._loading = false;
    this._saving = false;
    this._dirty = false;
    this._error = "";
  }

  async _load(refresh = false) {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._error = "";
    this._render();
    try {
      const data = await this._hass.callWS({
        type: "pianodisc_prodigy/autoplay_data",
        entity_id: this._entityId || undefined,
        refresh,
      });
      this._entities = data.entities || [];
      this._entityId = data.entity_id;
      this._playlists = data.playlists || [];
      this._config = this._normalize(data.config || {});
      this._dirty = false;
    } catch (err) {
      this._error = err?.message || "Unable to load AutoPlay settings";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _save() {
    if (!this._hass || !this._entityId || this._saving || this._loading) return;
    this._saving = true;
    this._error = "";
    this._render();
    try {
      const data = await this._hass.callWS({
        type: "pianodisc_prodigy/save_autoplay",
        entity_id: this._entityId,
        config: this._config,
      });
      this._config = this._normalize(data.config || this._config);
      this._dirty = false;
    } catch (err) {
      this._error = err?.message || "Unable to save AutoPlay settings";
    } finally {
      this._saving = false;
      this._render();
    }
  }

  _normalize(config) {
    const playlist = Number(config.playlist);
    const sort = Number(config.sort);
    return {
      enable: Boolean(config.enable),
      playlist: Number.isInteger(playlist) && playlist >= 0 ? playlist : 0,
      loop: Boolean(config.loop),
      sort: [0, 1, 2].includes(sort) ? sort : 0,
    };
  }

  _change(field, value) {
    if (this._loading || this._saving) return;
    this._config = { ...this._config, [field]: value };
    this._dirty = true;
    this._render();
  }

  _render() {
    const busy = this._loading || this._saving;
    const disabled = busy ? "disabled" : "";
    const status = this._loading ? "Loading..." : this._saving ? "Saving..." : this._dirty ? "Unsaved changes" : "Saved";
    const selectedMissing = this._config.playlist >= this._playlists.length;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; min-height:100vh; color:var(--primary-text-color); background:var(--primary-background-color); }
        * { box-sizing:border-box; }
        .page { max-width:760px; margin:0 auto; padding:24px; }
        header { display:flex; gap:16px; align-items:center; justify-content:space-between; flex-wrap:wrap; margin-bottom:24px; }
        h1 { margin:0; font-size:24px; font-weight:600; }
        .toolbar { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
        .status { color:var(--secondary-text-color); font-size:14px; min-width:108px; }
        button, select { font:inherit; color:var(--primary-text-color); background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:4px; min-height:36px; padding:0 12px; }
        button.primary { color:var(--text-primary-color); background:var(--primary-color); border-color:var(--primary-color); }
        button:disabled, select:disabled { opacity:.55; cursor:not-allowed; }
        .panel { border:1px solid var(--divider-color); border-radius:8px; overflow:hidden; }
        .row { display:grid; grid-template-columns:minmax(150px, 1fr) minmax(220px, 2fr); align-items:center; gap:20px; padding:18px 20px; border-bottom:1px solid var(--divider-color); }
        .row:last-child { border-bottom:0; }
        .label { font-weight:600; }
        .hint { margin-top:4px; color:var(--secondary-text-color); font-size:13px; line-height:1.4; }
        .toggle { display:flex; align-items:center; gap:10px; min-height:36px; }
        input[type=checkbox] { width:18px; height:18px; accent-color:var(--primary-color); }
        .error { margin:0 0 16px; color:var(--error-color); }
        .empty { color:var(--secondary-text-color); padding:20px; }
        @media (max-width:600px) { .page { padding:16px; } .row { grid-template-columns:1fr; gap:10px; } .toolbar { width:100%; } .toolbar select { flex:1; min-width:150px; } }
      </style>
      <div class="page">
        <header>
          <h1>Piano AutoPlay</h1>
          <div class="toolbar">
            <select data-action="entity" ${disabled}>${this._entities.map((item) => `<option value="${this._escapeAttr(item.entity_id)}" ${item.entity_id === this._entityId ? "selected" : ""}>${this._escape(item.name)}</option>`).join("")}</select>
            <span class="status">${status}</span>
            <button data-action="refresh" ${disabled}>Refresh</button>
            <button class="primary" data-action="save" ${!this._dirty || busy ? "disabled" : ""}>Save</button>
          </div>
        </header>
        ${this._error ? `<p class="error">${this._escape(this._error)}</p>` : ""}
        ${this._playlists.length ? `<div class="panel">
          <div class="row"><div><div class="label">Enable AutoPlay</div><div class="hint">Starts the selected playlist after the piano finishes starting.</div></div><label class="toggle"><input type="checkbox" data-action="enable" ${this._config.enable ? "checked" : ""} ${disabled}>Enabled</label></div>
          <div class="row"><div><div class="label">Playlist</div><div class="hint">The playlist to start automatically.</div></div><select data-action="playlist" ${disabled}>${selectedMissing ? `<option value="${this._config.playlist}">Unavailable playlist</option>` : ""}${this._playlists.map((name, index) => `<option value="${index}" ${index === this._config.playlist ? "selected" : ""}>${this._escape(name)}</option>`).join("")}</select></div>
          <div class="row"><div><div class="label">Playback order</div><div class="hint">Default uses the selected playlist's own order.</div></div><select data-action="sort" ${disabled}><option value="0" ${this._config.sort === 0 ? "selected" : ""}>Default</option><option value="1" ${this._config.sort === 1 ? "selected" : ""}>Sequence</option><option value="2" ${this._config.sort === 2 ? "selected" : ""}>Shuffle</option></select></div>
          <div class="row"><div><div class="label">Loop</div><div class="hint">When disabled, the playlist plays once. When enabled, it repeats continuously.</div></div><label class="toggle"><input type="checkbox" data-action="loop" ${this._config.loop ? "checked" : ""} ${disabled}>Loop playlist</label></div>
        </div>` : `<div class="panel empty">Create a playlist before configuring AutoPlay.</div>`}
      </div>`;
    this.shadowRoot.querySelector("[data-action=refresh]")?.addEventListener("click", () => this._load(true));
    this.shadowRoot.querySelector("[data-action=save]")?.addEventListener("click", () => this._save());
    this.shadowRoot.querySelector("[data-action=entity]")?.addEventListener("change", (event) => { this._entityId = event.target.value; this._load(); });
    this.shadowRoot.querySelector("[data-action=enable]")?.addEventListener("change", (event) => this._change("enable", event.target.checked));
    this.shadowRoot.querySelector("[data-action=playlist]")?.addEventListener("change", (event) => this._change("playlist", Number(event.target.value)));
    this.shadowRoot.querySelector("[data-action=sort]")?.addEventListener("change", (event) => this._change("sort", Number(event.target.value)));
    this.shadowRoot.querySelector("[data-action=loop]")?.addEventListener("change", (event) => this._change("loop", event.target.checked));
  }

  _escape(value) { const div = document.createElement("div"); div.textContent = String(value); return div.innerHTML; }
  _escapeAttr(value) { return this._escape(value).replaceAll('"', "&quot;"); }
}

customElements.define("pianodisc-autoplay-panel", PianoDiscAutoPlayPanel);
