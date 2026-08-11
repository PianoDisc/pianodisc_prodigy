class PianoDiscPlaylistPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._load();
    }
  }

  set panel(config) {
    this._panelConfig = config || {};
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._entities = [];
    this._entityId = null;
    this._playlists = [];
    this._songs = [];
    this._selected = 0;
    this._query = "";
    this._dirty = false;
    this._saving = false;
    this._error = "";
  }

  async _load() {
    if (!this._hass) return;
    this._error = "";
    this._render();
    try {
      const data = await this._hass.callWS({
        type: "pianodisc_prodigy/playlist_data",
        entity_id: this._entityId || undefined,
      });
      this._entities = data.entities || [];
      this._entityId = data.entity_id;
      this._playlists = (data.playlists || []).map((playlist) =>
        this._normalizePlaylist(playlist)
      );
      this._songs = data.songs || [];
      this._selected = Math.min(this._selected, Math.max(this._playlists.length - 1, 0));
      this._dirty = false;
    } catch (err) {
      this._error = err?.message || "Unable to load playlists";
    }
    this._render();
  }

  async _save() {
    if (!this._hass || !this._entityId || this._saving) return;
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
    item.name = typeof item.name === "string" && item.name.trim()
      ? item.name
      : "Untitled Playlist";
    item.sort = item.sort || "Shuffle";
    item.repeat = Number.isFinite(Number(item.repeat)) ? Number(item.repeat) : 1;
    return item;
  }

  _select(index) {
    this._selected = index;
    this._render();
  }

  _markDirty(render = true) {
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
    const playlist = this._playlists[index];
    if (!playlist) return;
    if (!confirm(`Delete playlist "${playlist.name}"?`)) return;
    this._playlists = this._playlists.filter((_item, itemIndex) => itemIndex !== index);
    this._selected = Math.min(this._selected, Math.max(this._playlists.length - 1, 0));
    this._markDirty();
  }

  _renamePlaylist(value) {
    const playlist = this._playlists[this._selected];
    if (!playlist) return;
    playlist.name = value;
    const name = this.shadowRoot.querySelector(".playlist-row.active .name");
    if (name) name.textContent = value || "Untitled Playlist";
    this._markDirty(false);
  }

  _setSort(value) {
    const playlist = this._playlists[this._selected];
    if (!playlist) return;
    playlist.sort = value;
    this._markDirty(false);
  }

  _setRepeat(value) {
    const playlist = this._playlists[this._selected];
    if (!playlist) return;
    playlist.repeat = Math.max(0, Number(value) || 0);
    this._markDirty(false);
  }

  _addSong(path, listName = "include") {
    const playlist = this._playlists[this._selected];
    if (!playlist) return;
    const list = playlist.content[listName];
    if (!list.includes(path)) {
      list.push(path);
      this._markDirty();
    }
  }

  _removeSong(path, listName = "include") {
    const playlist = this._playlists[this._selected];
    if (!playlist) return;
    playlist.content[listName] = playlist.content[listName].filter((item) => item !== path);
    this._markDirty();
  }

  _playPlaylist(index) {
    if (!this._hass || !this._entityId) return;
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

  _filteredSongs(playlist) {
    const query = this._query.trim().toLowerCase();
    const include = new Set(playlist?.content?.include || []);
    return this._songs
      .filter((song) => !include.has(song.path))
      .filter((song) => {
        if (!query) return true;
        return (
          song.title.toLowerCase().includes(query) ||
          song.path.toLowerCase().includes(query)
        );
      })
      .slice(0, 80);
  }

  _render() {
    const playlist = this._playlists[this._selected];
    const status = this._saving ? "Saving..." : this._dirty ? "Unsaved changes" : "Saved";
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          min-height: 100vh;
          color: var(--primary-text-color);
          background: var(--primary-background-color);
          box-sizing: border-box;
        }
        * { box-sizing: border-box; }
        .page {
          max-width: 1180px;
          margin: 0 auto;
          padding: 24px;
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
        button:disabled {
          opacity: 0.5;
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
        .layout {
          display: grid;
          grid-template-columns: 300px minmax(0, 1fr);
          gap: 16px;
        }
        ha-card {
          display: block;
          overflow: hidden;
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
          gap: 16px;
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
        .section-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 8px;
          font-weight: 600;
        }
        .song-list {
          display: grid;
          gap: 6px;
        }
        .song-row {
          display: grid;
          grid-template-columns: minmax(0, 1fr) 40px;
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
        .search {
          width: 100%;
          margin-bottom: 8px;
        }
        .empty {
          color: var(--secondary-text-color);
          padding: 16px;
          text-align: center;
        }
        @media (max-width: 840px) {
          .page { padding: 12px; }
          header { align-items: stretch; flex-direction: column; }
          .layout { grid-template-columns: 1fr; }
          .fields { grid-template-columns: 1fr; }
          .toolbar { align-items: stretch; }
          .toolbar > * { width: 100%; }
          .status { text-align: left; }
        }
      </style>
      <div class="page">
        <header>
          <h1>Piano Playlists</h1>
          <div class="toolbar">
            ${this._entitySelectTemplate()}
            <span class="status">${status}</span>
            <button @click="refresh">Refresh</button>
            <button class="primary" ?disabled="${!this._dirty || this._saving}">Save</button>
          </div>
        </header>
        ${this._error ? `<div class="error">${this._escape(this._error)}</div>` : ""}
        <div class="layout">
          <ha-card>
            <div class="card-title">
              <span>Playlists</span>
              <button class="icon" title="Add playlist" data-action="add-playlist">
                <ha-icon icon="mdi:plus"></ha-icon>
              </button>
            </div>
            <div class="playlist-list">
              ${this._playlistListTemplate()}
            </div>
          </ha-card>
          <ha-card>
            ${playlist ? this._editorTemplate(playlist) : `<div class="empty">Create a playlist to begin.</div>`}
          </ha-card>
        </div>
      </div>
    `;
    this._bindEvents();
  }

  _entitySelectTemplate() {
    if (this._entities.length <= 1) return "";
    return `
      <select data-action="entity">
        ${this._entities.map((entity) => `
          <option value="${this._escape(entity.entity_id)}" ${entity.entity_id === this._entityId ? "selected" : ""}>
            ${this._escape(entity.name)}
          </option>
        `).join("")}
      </select>
    `;
  }

  _playlistListTemplate() {
    if (!this._playlists.length) {
      return `<div class="empty">No playlists yet.</div>`;
    }
    return this._playlists.map((playlist, index) => `
      <div class="playlist-row ${index === this._selected ? "active" : ""}">
        <button data-action="select" data-index="${index}">
          <span class="name">${this._escape(playlist.name)}</span>
        </button>
        <button class="icon" title="Play" data-action="play" data-index="${index}">
          <ha-icon icon="mdi:play"></ha-icon>
        </button>
      </div>
    `).join("");
  }

  _editorTemplate(playlist) {
    return `
      <div class="card-title">
        <span>Edit Playlist</span>
        <button class="icon" title="Delete playlist" data-action="delete-playlist">
          <ha-icon icon="mdi:delete-outline"></ha-icon>
        </button>
      </div>
      <div class="editor">
        <div class="fields">
          <div class="field">
            <label>Name</label>
            <input data-action="name" value="${this._escapeAttr(playlist.name)}">
          </div>
          <div class="field">
            <label>Sort</label>
            <select data-action="sort">
              <option value="Shuffle" ${playlist.sort === "Shuffle" ? "selected" : ""}>Shuffle</option>
              <option value="Cycle" ${playlist.sort === "Cycle" ? "selected" : ""}>Cycle</option>
            </select>
          </div>
          <div class="field">
            <label>Repeat</label>
            <input data-action="repeat" type="number" min="0" max="99" value="${playlist.repeat}">
          </div>
        </div>
        <section>
          <div class="section-head">
            <span>Songs in this playlist</span>
            <span>${playlist.content.include.length}</span>
          </div>
          <div class="song-list">
            ${this._playlistSongsTemplate(playlist)}
          </div>
        </section>
        <section>
          <div class="section-head">
            <span>Add songs</span>
          </div>
          <input class="search" data-action="search" placeholder="Search library" value="${this._escapeAttr(this._query)}">
          <div class="song-list">
            ${this._availableSongsTemplate(playlist)}
          </div>
        </section>
      </div>
    `;
  }

  _playlistSongsTemplate(playlist) {
    if (!playlist.content.include.length) {
      return `<div class="empty">No songs in this playlist.</div>`;
    }
    return playlist.content.include.map((path) => `
      <div class="song-row">
        <div>
          <div class="song-title">${this._escape(this._titleForPath(path))}</div>
          <div class="song-path">${this._escape(path)}</div>
        </div>
        <button class="icon" title="Remove song" data-action="remove-song" data-path="${this._escapeAttr(path)}">
          <ha-icon icon="mdi:minus"></ha-icon>
        </button>
      </div>
    `).join("");
  }

  _availableSongsTemplate(playlist) {
    const songs = this._filteredSongs(playlist);
    if (!songs.length) {
      return `<div class="empty">No matching songs.</div>`;
    }
    return songs.map((song) => `
      <div class="song-row">
        <div>
          <div class="song-title">${this._escape(song.title)}</div>
          <div class="song-path">${this._escape(song.path)}</div>
        </div>
        <button class="icon" title="Add song" data-action="add-song" data-path="${this._escapeAttr(song.path)}">
          <ha-icon icon="mdi:plus"></ha-icon>
        </button>
      </div>
    `).join("");
  }

  _bindEvents() {
    this.shadowRoot.querySelector("[data-action='add-playlist']")?.addEventListener("click", () => this._addPlaylist());
    this.shadowRoot.querySelector("[data-action='delete-playlist']")?.addEventListener("click", () => this._deletePlaylist(this._selected));
    this.shadowRoot.querySelector(".toolbar button:not(.primary)")?.addEventListener("click", () => this._load());
    this.shadowRoot.querySelector(".toolbar button.primary")?.addEventListener("click", () => this._save());
    this.shadowRoot.querySelector("[data-action='entity']")?.addEventListener("change", (ev) => {
      this._entityId = ev.target.value;
      this._selected = 0;
      this._load();
    });
    this.shadowRoot.querySelector("[data-action='name']")?.addEventListener("input", (ev) => this._renamePlaylist(ev.target.value));
    this.shadowRoot.querySelector("[data-action='sort']")?.addEventListener("change", (ev) => this._setSort(ev.target.value));
    this.shadowRoot.querySelector("[data-action='repeat']")?.addEventListener("input", (ev) => this._setRepeat(ev.target.value));
    this.shadowRoot.querySelector("[data-action='search']")?.addEventListener("input", (ev) => {
      this._query = ev.target.value;
      this._render();
    });
    this.shadowRoot.querySelectorAll("[data-action='select']").forEach((button) =>
      button.addEventListener("click", () => this._select(Number(button.dataset.index)))
    );
    this.shadowRoot.querySelectorAll("[data-action='play']").forEach((button) =>
      button.addEventListener("click", () => this._playPlaylist(Number(button.dataset.index)))
    );
    this.shadowRoot.querySelectorAll("[data-action='add-song']").forEach((button) =>
      button.addEventListener("click", () => this._addSong(button.dataset.path))
    );
    this.shadowRoot.querySelectorAll("[data-action='remove-song']").forEach((button) =>
      button.addEventListener("click", () => this._removeSong(button.dataset.path))
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

customElements.define("pianodisc-playlist-panel", PianoDiscPlaylistPanel);
