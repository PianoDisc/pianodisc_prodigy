class PianoDiscLibraryPanel extends HTMLElement {
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
    this._songs = [];
    this._query = "";
    this._loading = false;
    this._playingPath = null;
    this._error = "";
    this._libraryStatus = "syncing";
    this._retryTimer = null;
  }

  async _load(refresh = false) {
    if (!this._hass || this._loading) return;
    this._loading = true;
    this._error = "";
    this._render();
    try {
      const data = await this._hass.callWS({
        type: "pianodisc_prodigy/library_data",
        entity_id: this._entityId || undefined,
        refresh,
      });
      this._entities = data.entities || [];
      this._entityId = data.entity_id;
      this._songs = data.songs || [];
      this._libraryStatus = data.library_status || "ready";
    } catch (err) {
      this._error = err?.message || "Unable to load library";
    } finally {
      this._loading = false;
      this._render();
      this._scheduleRetry();
    }
  }

  _filteredSongs() {
    const query = this._query.trim().toLowerCase();
    return this._songs.filter((song) =>
      !query || song.title.toLowerCase().includes(query) || song.path.toLowerCase().includes(query)
    );
  }

  async _play(path) {
    if (!this._hass || !this._entityId || this._playingPath) return;
    this._playingPath = path;
    this._error = "";
    this._render();
    try {
      await this._hass.callService("media_player", "play_media", {
        entity_id: this._entityId,
        media_content_type: "music",
        media_content_id: path,
      });
    } catch (err) {
      this._error = err?.message || "Unable to play song";
    } finally {
      this._playingPath = null;
      this._render();
    }
  }

  _setQuery(value) {
    this._query = value;
    this._render();
    const input = this.shadowRoot.querySelector("[data-action=query]");
    input?.focus();
    input?.setSelectionRange(value.length, value.length);
  }

  _refresh() {
    this._load(true);
  }

  _scheduleRetry() {
    clearTimeout(this._retryTimer);
    if (this._libraryStatus !== "ready") {
      this._retryTimer = setTimeout(() => this._load(), 1500);
    }
  }

  disconnectedCallback() {
    clearTimeout(this._retryTimer);
  }

  _render() {
    const libraryReady = this._libraryStatus === "ready";
    const results = libraryReady ? this._filteredSongs() : [];
    const disabled = this._loading || this._playingPath || !libraryReady ? "disabled" : "";
    const startupMessage = this._libraryStatus === "preparing" ? "Preparing piano..." : "Syncing library...";
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; min-height:100vh; color:var(--primary-text-color); background:var(--primary-background-color); }
        * { box-sizing:border-box; }
        .page { max-width:900px; margin:0 auto; padding:24px; }
        header { display:flex; align-items:center; gap:16px; justify-content:space-between; flex-wrap:wrap; margin-bottom:20px; }
        h1 { margin:0; font-size:24px; font-weight:600; }
        .tools { display:flex; align-items:center; gap:10px; flex:1 1 440px; justify-content:flex-end; }
        select, input { min-height:40px; font:inherit; color:var(--primary-text-color); background:var(--secondary-background-color); border:1px solid var(--divider-color); border-radius:4px; padding:0 12px; }
        select { max-width:240px; }
        input { flex:1; min-width:200px; }
        .status, .empty { color:var(--secondary-text-color); font-size:14px; }
        .panel { border:1px solid var(--divider-color); border-radius:8px; overflow:hidden; }
        .song { display:grid; grid-template-columns:40px minmax(0, 1fr); align-items:center; min-height:56px; border-bottom:1px solid var(--divider-color); }
        .song:last-child { border-bottom:0; }
        .song-title { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        button { display:grid; place-items:center; width:40px; height:40px; margin:0; border:0; color:var(--primary-color); background:transparent; cursor:pointer; }
        button:hover { background:var(--secondary-background-color); }
        button:disabled { color:var(--disabled-text-color); cursor:not-allowed; }
        ha-icon { --mdc-icon-size:20px; }
        .error { margin:0 0 16px; color:var(--error-color); }
        .empty { padding:24px; }
        @media (max-width:600px) { .page { padding:16px; } .tools { justify-content:stretch; } select { max-width:none; flex:1 1 100%; } input { flex-basis:100%; } }
      </style>
      <div class="page">
        <header>
          <h1>Piano Library</h1>
          <div class="tools">
            ${this._entities.length > 1 ? `<select data-action="entity" ${disabled}>${this._entities.map((entity) => `<option value="${this._escapeAttr(entity.entity_id)}" ${entity.entity_id === this._entityId ? "selected" : ""}>${this._escape(entity.name)}</option>`).join("")}</select>` : ""}
            <input data-action="query" type="search" autocomplete="off" placeholder="Search songs" value="${this._escapeAttr(this._query)}" ${disabled}>
            <button data-action="refresh" title="Refresh library" aria-label="Refresh library" ${disabled}><ha-icon icon="mdi:refresh"></ha-icon></button>
          </div>
        </header>
        ${this._error ? `<p class="error">${this._escape(this._error)}</p>` : ""}
        ${this._loading ? `<div class="panel empty">Loading...</div>` : !libraryReady ? `<div class="panel empty">${startupMessage}</div>` : results.length ? `<div class="panel">${results.map((song) => `<div class="song"><button data-play="${this._escapeAttr(song.path)}" title="Play ${this._escapeAttr(song.title)}" aria-label="Play ${this._escapeAttr(song.title)}" ${disabled}><ha-icon icon="mdi:play"></ha-icon></button><div class="song-title" title="${this._escapeAttr(song.path)}">${this._escape(song.title)}</div></div>`).join("")}</div>` : `<div class="panel empty">${this._songs.length ? "No matching songs" : "No songs available"}</div>`}
        ${!this._loading && libraryReady ? `<p class="status">${results.length} of ${this._songs.length} songs</p>` : ""}
      </div>`;
    this.shadowRoot.querySelector("[data-action=query]")?.addEventListener("input", (event) => this._setQuery(event.target.value));
    this.shadowRoot.querySelector("[data-action=refresh]")?.addEventListener("click", () => this._refresh());
    this.shadowRoot.querySelector("[data-action=entity]")?.addEventListener("change", (event) => { this._entityId = event.target.value; this._load(); });
    this.shadowRoot.querySelectorAll("[data-play]").forEach((button) => button.addEventListener("click", () => this._play(button.dataset.play)));
  }

  _escape(value) { const div = document.createElement("div"); div.textContent = String(value); return div.innerHTML; }
  _escapeAttr(value) { return this._escape(value).replaceAll('"', "&quot;"); }
}

customElements.define("pianodisc-library-panel", PianoDiscLibraryPanel);
