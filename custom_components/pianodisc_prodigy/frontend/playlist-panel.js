class PianoDiscPlaylistCard extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._load();
    }
  }

  setConfig(config) {
    this._config = config || {};
    const entityId = this._config.entity;
    if (entityId && entityId !== this._entityId) {
      this._entityId = entityId;
      if (this._loaded) this._load();
    }
  }

  getCardSize() {
    return 12;
  }

  static getStubConfig() {
    return { type: "custom:pianodisc-playlist-card" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._entities = [];
    this._entityId = null;
    this._playlists = [];
    this._songs = [];
    this._selected = 0;
    this._query = "";
    this._dirty = false;
    this._loading = false;
    this._saving = false;
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
        type: "pianodisc_prodigy/playlist_data",
        entity_id: this._entityId || undefined,
        refresh,
      });
      this._entities = data.entities || [];
      this._entityId = data.entity_id;
      this._playlists = (data.playlists || []).map((playlist) =>
        this._normalizePlaylist(playlist)
      );
      this._songs = data.songs || [];
      this._libraryStatus = data.library_status || "ready";
      this._selected = Math.min(
        this._selected,
        Math.max(this._playlists.length - 1, 0)
      );
      this._dirty = false;
    } catch (err) {
      this._error = err?.message || "Unable to load playlists";
    } finally {
      this._loading = false;
    }
    this._render();
    this._scheduleRetry();
  }

  async _save() {
    if (!this._hass || !this._entityId || this._saving || this._loading) return;
    this._saving = true;
    this._error = "";
    this._render();
    try {
      const data = await this._hass.callWS({
        type: "pianodisc_prodigy/save_playlists",
        entity_id: this._entityId,
        playlists: this._playlists,
      });
      this._playlists = (data.playlists || this._playlists).map((playlist) =>
        this._normalizePlaylist(playlist)
      );
      this._dirty = false;
    } catch (err) {
      this._error = err?.message || "Unable to save playlists";
    }
    this._saving = false;
    this._render();
  }

  _normalizePlaylist(playlist) {
    const item = { ...playlist };
    const content = { ...(item.content || {}) };
    content.include = Array.isArray(content.include) ? [...content.include] : [];
    content.exclude = Array.isArray(content.exclude) ? [...content.exclude] : [];
    item.content = content;
    item.name =
      typeof item.name === "string" && item.name.trim()
        ? item.name
        : "Untitled Playlist";
    item.sort = item.sort || "Shuffle";
    item.repeat = Number.isFinite(Number(item.repeat)) ? Number(item.repeat) : 1;
    return item;
  }

  _select(index) {
    if (this._loading || this._saving) return;
    this._selected = index;
    this._render();
  }

  _markDirty(render = true) {
    if (this._loading) return;
    this._dirty = true;
    if (render) {
      this._render();
      return;
    }
    const status = this.shadowRoot.querySelector(".status");
    const save = this.shadowRoot.querySelector(".toolbar button.primary");
    if (status) status.textContent = "Unsaved changes";
    if (save) save.disabled = false;
  }

  _addPlaylist() {
    if (this._loading || this._saving) return;
    this._playlists = [
      ...this._playlists,
      {
        name: "New Playlist",
        sort: "Shuffle",
        repeat: 1,
        content: { include: [], exclude: [] },
      },
    ];
    this._selected = this._playlists.length - 1;
    this._markDirty();
  }

  _deletePlaylist(index) {
    if (this._loading || this._saving) return;
    const playlist = this._playlists[index];
    if (!playlist) return;
    if (!confirm(`Delete playlist "${playlist.name}"?`)) return;
    this._playlists = this._playlists.filter(
      (_item, itemIndex) => itemIndex !== index
    );
    this._selected = Math.min(
      this._selected,
      Math.max(this._playlists.length - 1, 0)
    );
    this._markDirty();
  }

  _renamePlaylist(value) {
    if (this._loading || this._saving) return;
    const playlist = this._playlists[this._selected];
    if (!playlist) return;
    playlist.name = value;
    const name = this.shadowRoot.querySelector(".playlist-row.active .name");
    if (name) name.textContent = value || "Untitled Playlist";
    this._markDirty(false);
  }

  _setSort(value) {
    if (this._loading || this._saving) return;
    const playlist = this._playlists[this._selected];
    if (!playlist) return;
    playlist.sort = value;
    this._markDirty(false);
  }

  _setRepeat(value) {
    if (this._loading || this._saving) return;
    const playlist = this._playlists[this._selected];
    if (!playlist) return;
    playlist.repeat = Math.max(0, Number(value) || 0);
    this._markDirty(false);
  }

  _addSong(path, listName) {
    if (this._loading || this._saving) return;
    const playlist = this._playlists[this._selected];
    if (!playlist || !["include", "exclude"].includes(listName)) return;
    const list = playlist.content[listName];
    if (!list.includes(path)) {
      list.push(path);
      this._markDirty();
    }
  }

  _removeSong(path, listName) {
    if (this._loading || this._saving) return;
    const playlist = this._playlists[this._selected];
    if (!playlist || !["include", "exclude"].includes(listName)) return;
    playlist.content[listName] = playlist.content[listName].filter(
      (item) => item !== path
    );
    this._markDirty();
  }

  _playPlaylist(index) {
    if (!this._hass || !this._entityId || this._loading || this._saving || this._libraryStatus !== "ready") return;
    this._hass.callService("media_player", "play_media", {
      entity_id: this._entityId,
      media_content_type: "playlist",
      media_content_id: `playlist:${index}`,
    });
  }

  _titleForPath(path) {
    const match = this._songs.find((song) => song.path === path);
    if (match) return match.title;
    return String(path).split("/").pop()?.replace(/\.mid$/i, "") || path;
  }

  _filteredSongs() {
    const query = this._query.trim().toLowerCase();
    return this._songs
      .filter((song) => {
        if (!query) return true;
        return (
          song.title.toLowerCase().includes(query) ||
          song.path.toLowerCase().includes(query)
        );
      })
      .slice(0, 80);
  }

  _ruleText(playlist) {
    const include = playlist.content.include.length;
    const exclude = playlist.content.exclude.length;
    const base =
      include === 0
        ? "starts with all songs"
        : `starts with ${include} included song${include === 1 ? "" : "s"}`;
    const removed =
      exclude === 0
        ? "excludes nothing"
        : `excludes ${exclude} song${exclude === 1 ? "" : "s"}`;
    return `This playlist ${base}, then ${removed}.`;
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
    const playlist = this._playlists[this._selected];
    const libraryReady = this._libraryStatus === "ready";
    const busy = this._loading || this._saving || !libraryReady;
    const disabled = busy ? "disabled" : "";
    const startupMessage = this._libraryStatus === "preparing" ? "Preparing piano..." : "Syncing library...";
    const status = !libraryReady
      ? startupMessage
      : this._loading
      ? "Loading..."
      : this._saving
      ? "Saving..."
      : this._dirty
        ? "Unsaved changes"
        : "Saved";
    const saveDisabled = !this._dirty || busy ? "disabled" : "";
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          color: var(--primary-text-color);
          box-sizing: border-box;
        }
        * { box-sizing: border-box; }
        .page {
          padding: 16px;
        }
        header {
          display: flex;
          gap: 12px;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 16px;
        }
        h1 {
          margin: 0;
          font-size: 24px;
          font-weight: 600;
        }
        .toolbar {
          display: flex;
          gap: 8px;
          align-items: center;
          flex-wrap: wrap;
        }
        select, input {
          height: 40px;
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          padding: 0 10px;
          font: inherit;
        }
        button {
          height: 40px;
          border: 0;
          border-radius: 6px;
          padding: 0 14px;
          font: inherit;
          cursor: pointer;
          color: var(--primary-text-color);
          background: var(--secondary-background-color);
        }
        button.primary {
          background: var(--primary-color);
          color: var(--text-primary-color);
        }
        button.icon {
          width: 40px;
          padding: 0;
          display: inline-grid;
          place-items: center;
        }
        button.small {
          height: 34px;
          padding: 0 10px;
          white-space: nowrap;
        }
        button:disabled {
          opacity: 0.45;
          cursor: default;
        }
        .status {
          color: var(--secondary-text-color);
          min-width: 116px;
          text-align: right;
        }
        .error {
          margin-bottom: 12px;
          padding: 12px;
          border-radius: 6px;
          color: var(--error-color);
          background: color-mix(in srgb, var(--error-color) 12%, transparent);
        }
        .loading {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 12px;
          padding: 12px;
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          color: var(--secondary-text-color);
          background: var(--secondary-background-color);
        }
        .spinner {
          width: 18px;
          height: 18px;
          border: 2px solid var(--divider-color);
          border-top-color: var(--primary-color);
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        .layout {
          display: grid;
          grid-template-columns: 300px minmax(0, 1fr);
          gap: 16px;
        }
        .layout.loading-active {
          opacity: 0.72;
        }
        .panel {
          display: block;
          overflow: hidden;
          border: 1px solid var(--divider-color);
          border-radius: 6px;
        }
        .card-title {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px;
          border-bottom: 1px solid var(--divider-color);
          font-size: 16px;
          font-weight: 600;
        }
        .playlist-list {
          padding: 8px;
        }
        .playlist-row {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 40px;
          gap: 4px;
          align-items: center;
          width: 100%;
          border-radius: 6px;
          background: transparent;
          text-align: left;
        }
        .playlist-row.active {
          background: var(--secondary-background-color);
        }
        .playlist-row .name {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .editor {
          padding: 16px;
          display: grid;
          gap: 18px;
        }
        .fields {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 150px 120px;
          gap: 12px;
        }
        .field {
          display: grid;
          gap: 6px;
        }
        label {
          color: var(--secondary-text-color);
          font-size: 12px;
        }
        .rule {
          border: 1px solid var(--divider-color);
          border-radius: 6px;
          padding: 12px;
          background: var(--secondary-background-color);
        }
        .rule strong {
          display: block;
          margin-bottom: 4px;
        }
        .rule p {
          margin: 0;
          color: var(--secondary-text-color);
          line-height: 1.45;
        }
        .lists {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 14px;
        }
        .section {
          min-width: 0;
        }
        .section-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 4px;
          font-weight: 600;
        }
        .hint {
          color: var(--secondary-text-color);
          font-size: 12px;
          line-height: 1.35;
          margin-bottom: 8px;
        }
        .song-list {
          display: grid;
          gap: 6px;
        }
        .song-row {
          display: grid;
          grid-template-columns: minmax(0, 1fr) auto;
          gap: 8px;
          align-items: center;
          min-height: 42px;
          padding: 0 8px 0 12px;
          border: 1px solid var(--divider-color);
          border-radius: 6px;
        }
        .song-title {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .song-path {
          color: var(--secondary-text-color);
          font-size: 12px;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .actions {
          display: flex;
          gap: 6px;
          align-items: center;
        }
        .badge {
          color: var(--secondary-text-color);
          font-size: 12px;
          border: 1px solid var(--divider-color);
          border-radius: 999px;
          padding: 3px 8px;
        }
        .search {
          width: 100%;
          margin-bottom: 8px;
        }
        .empty {
          color: var(--secondary-text-color);
          padding: 16px;
          text-align: center;
          border: 1px dashed var(--divider-color);
          border-radius: 6px;
        }
        @media (max-width: 920px) {
          .page { padding: 12px; }
          header { align-items: stretch; flex-direction: column; }
          .layout { grid-template-columns: 1fr; }
          .fields, .lists { grid-template-columns: 1fr; }
          .toolbar { align-items: stretch; }
          .toolbar > * { width: 100%; }
          .status { text-align: left; }
          .song-row { grid-template-columns: 1fr; padding: 10px; }
          .actions { justify-content: flex-end; }
        }
      </style>
      <ha-card>
      <div class="page">
        <header>
          <h1>Piano Playlists</h1>
          <div class="toolbar">
            ${this._entitySelectTemplate()}
            <span class="status">${status}</span>
            <button data-action="refresh" ${disabled}>Refresh</button>
            <button class="primary" data-action="save" ${saveDisabled}>Save</button>
          </div>
        </header>
        ${this._error ? `<div class="error">${this._escape(this._error)}</div>` : ""}
        ${this._loading ? `<div class="loading"><span class="spinner"></span><span>Loading playlists and SD-card songs from the piano...</span></div>` : !libraryReady ? `<div class="loading"><span class="spinner"></span><span>${startupMessage}</span></div>` : ""}
        ${libraryReady ? `<div class="layout ${this._loading ? "loading-active" : ""}">
          <section class="panel">
            <div class="card-title">
              <span>Playlists</span>
              <button class="icon" title="Add playlist" data-action="add-playlist" ${disabled}>
                <ha-icon icon="mdi:plus"></ha-icon>
              </button>
            </div>
            <div class="playlist-list">
              ${this._playlistListTemplate()}
            </div>
          </section>
          <section class="panel">
            ${
              playlist
                ? this._editorTemplate(playlist)
                : this._loading
                  ? `<div class="empty">Loading playlist data...</div>`
                  : `<div class="empty">Create a playlist to begin.</div>`
            }
          </section>
        </div>` : ""}
      </div>
      </ha-card>
    `;
    this._bindEvents();
  }

  _entitySelectTemplate() {
    if (this._config.entity || this._entities.length <= 1) return "";
    return `
      <select data-action="entity" ${this._loading || this._saving ? "disabled" : ""}>
        ${this._entities
          .map(
            (entity) => `
          <option value="${this._escape(entity.entity_id)}" ${
            entity.entity_id === this._entityId ? "selected" : ""
          }>
            ${this._escape(entity.name)}
          </option>
        `
          )
          .join("")}
      </select>
    `;
  }

  _playlistListTemplate() {
    if (this._loading && !this._playlists.length) {
      return `<div class="empty">Loading playlists...</div>`;
    }
    if (!this._playlists.length) {
      return `<div class="empty">No playlists yet.</div>`;
    }
    const disabled = this._loading || this._saving ? "disabled" : "";
    return this._playlists
      .map(
        (playlist, index) => `
      <div class="playlist-row ${index === this._selected ? "active" : ""}">
        <button data-action="select" data-index="${index}" ${disabled}>
          <span class="name">${this._escape(playlist.name)}</span>
        </button>
        <button class="icon" title="Play" data-action="play" data-index="${index}" ${disabled}>
          <ha-icon icon="mdi:play"></ha-icon>
        </button>
      </div>
    `
      )
      .join("");
  }

  _editorTemplate(playlist) {
    const disabled = this._loading || this._saving ? "disabled" : "";
    return `
      <div class="card-title">
        <span>Edit Playlist</span>
        <button class="icon" title="Delete playlist" data-action="delete-playlist" ${disabled}>
          <ha-icon icon="mdi:delete-outline"></ha-icon>
        </button>
      </div>
      <div class="editor">
        <div class="fields">
          <div class="field">
            <label>Name</label>
            <input data-action="name" value="${this._escapeAttr(playlist.name)}" ${disabled}>
          </div>
          <div class="field">
            <label>Sort</label>
            <select data-action="sort" ${disabled}>
              <option value="Shuffle" ${
                playlist.sort === "Shuffle" ? "selected" : ""
              }>Shuffle</option>
              <option value="Cycle" ${
                playlist.sort === "Cycle" ? "selected" : ""
              }>Cycle</option>
            </select>
          </div>
          <div class="field">
            <label>Repeat</label>
            <input data-action="repeat" type="number" min="0" max="99" value="${
              playlist.repeat
            }" ${disabled}>
          </div>
        </div>
        <div class="rule">
          <strong>${this._escape(this._ruleText(playlist))}</strong>
          <p>Include is the optional starting set. Leave it empty to start from the full SD-card library. Exclude removes songs from that set. Leave it empty to remove nothing.</p>
        </div>
        <div class="lists">
          <section class="section">
            <div class="section-head">
              <span>Include</span>
              <span>${playlist.content.include.length}</span>
            </div>
            <div class="hint">Optional allowlist. Empty means all songs are included.</div>
            <div class="song-list">
              ${this._songListTemplate(playlist, "include")}
            </div>
          </section>
          <section class="section">
            <div class="section-head">
              <span>Exclude</span>
              <span>${playlist.content.exclude.length}</span>
            </div>
            <div class="hint">Optional blocklist. These songs will not play.</div>
            <div class="song-list">
              ${this._songListTemplate(playlist, "exclude")}
            </div>
          </section>
        </div>
        <section>
          <div class="section-head">
            <span>Add from library</span>
          </div>
          <input class="search" data-action="search" placeholder="Search library" value="${this._escapeAttr(
            this._query
          )}" ${disabled}>
          <div class="song-list">
            ${this._availableSongsTemplate(playlist)}
          </div>
        </section>
      </div>
    `;
  }

  _songListTemplate(playlist, listName) {
    const paths = playlist.content[listName] || [];
    const disabled = this._loading || this._saving ? "disabled" : "";
    if (!paths.length) {
      const text =
        listName === "include"
          ? "No include songs. This playlist starts from all songs."
          : "No excluded songs.";
      return `<div class="empty">${text}</div>`;
    }
    return paths
      .map(
        (path) => `
      <div class="song-row">
        <div>
          <div class="song-title">${this._escape(this._titleForPath(path))}</div>
          <div class="song-path">${this._escape(path)}</div>
        </div>
        <button class="icon" title="Remove song" data-action="remove-song" data-list="${listName}" data-path="${this._escapeAttr(
          path
        )}" ${disabled}>
          <ha-icon icon="mdi:minus"></ha-icon>
        </button>
      </div>
    `
      )
      .join("");
  }

  _availableSongsTemplate(playlist) {
    const songs = this._filteredSongs();
    const disabled = this._loading || this._saving;
    if (!songs.length) {
      return `<div class="empty">No matching songs.</div>`;
    }
    const include = new Set(playlist.content.include);
    const exclude = new Set(playlist.content.exclude);
    return songs
      .map((song) => {
        const isIncluded = include.has(song.path);
        const isExcluded = exclude.has(song.path);
        return `
          <div class="song-row">
            <div>
              <div class="song-title">${this._escape(song.title)}</div>
              <div class="song-path">${this._escape(song.path)}</div>
            </div>
            <div class="actions">
              ${isIncluded ? `<span class="badge">Included</span>` : ""}
              ${isExcluded ? `<span class="badge">Excluded</span>` : ""}
              <button class="small" data-action="add-song" data-list="include" data-path="${this._escapeAttr(
                song.path
              )}" ${isIncluded || disabled ? "disabled" : ""}>Include</button>
              <button class="small" data-action="add-song" data-list="exclude" data-path="${this._escapeAttr(
                song.path
              )}" ${isExcluded || disabled ? "disabled" : ""}>Exclude</button>
            </div>
          </div>
        `;
      })
      .join("");
  }

  _bindEvents() {
    this.shadowRoot
      .querySelector("[data-action='add-playlist']")
      ?.addEventListener("click", () => this._addPlaylist());
    this.shadowRoot
      .querySelector("[data-action='delete-playlist']")
      ?.addEventListener("click", () => this._deletePlaylist(this._selected));
    this.shadowRoot
      .querySelector("[data-action='refresh']")
      ?.addEventListener("click", () => this._load(true));
    this.shadowRoot
      .querySelector("[data-action='save']")
      ?.addEventListener("click", () => this._save());
    this.shadowRoot
      .querySelector("[data-action='entity']")
      ?.addEventListener("change", (ev) => {
        this._entityId = ev.target.value;
        this._selected = 0;
        this._load();
      });
    this.shadowRoot
      .querySelector("[data-action='name']")
      ?.addEventListener("input", (ev) => this._renamePlaylist(ev.target.value));
    this.shadowRoot
      .querySelector("[data-action='sort']")
      ?.addEventListener("change", (ev) => this._setSort(ev.target.value));
    this.shadowRoot
      .querySelector("[data-action='repeat']")
      ?.addEventListener("input", (ev) => this._setRepeat(ev.target.value));
    this.shadowRoot
      .querySelector("[data-action='search']")
      ?.addEventListener("input", (ev) => {
        this._query = ev.target.value;
        this._render();
      });
    this.shadowRoot.querySelectorAll("[data-action='select']").forEach((button) =>
      button.addEventListener("click", () =>
        this._select(Number(button.dataset.index))
      )
    );
    this.shadowRoot.querySelectorAll("[data-action='play']").forEach((button) =>
      button.addEventListener("click", () =>
        this._playPlaylist(Number(button.dataset.index))
      )
    );
    this.shadowRoot.querySelectorAll("[data-action='add-song']").forEach((button) =>
      button.addEventListener("click", () =>
        this._addSong(button.dataset.path, button.dataset.list)
      )
    );
    this.shadowRoot
      .querySelectorAll("[data-action='remove-song']")
      .forEach((button) =>
        button.addEventListener("click", () =>
          this._removeSong(button.dataset.path, button.dataset.list)
        )
      );
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  _escapeAttr(value) {
    return this._escape(value).replaceAll('"', "&quot;");
  }
}

customElements.define("pianodisc-playlist-card", PianoDiscPlaylistCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "pianodisc-playlist-card",
  name: "PianoDisc Playlists",
  description: "Edit playlists for a PianoDisc Prodigy II piano.",
});
