class PianoDiscLibraryCard extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._load();
    }
  }

  setConfig(config) {
    this._config = config || {};
    if (this._loaded) this._load();
  }

  getCardSize() { return 8; }

  getGridOptions() {
    return { columns: 6, min_columns: 3 };
  }

  static getConfigElement() {
    return document.createElement("pianodisc-library-card-editor");
  }

  static getStubConfig() {
    return { type: "custom:pianodisc-library-card" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._songs = [];
    this._query = "";
    this._loading = false;
    this._error = "";
    this._libraryStatus = "syncing";
  }

  get _entityId() {
    return this._config.entity;
  }

  async _load() {
    if (!this._hass) return;
    if (!this._entityId) {
      this._render();
      return;
    }
    this._loading = true;
    this._error = "";
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "pianodisc_prodigy/library_data",
        entity_id: this._entityId,
      });
      this._libraryStatus = result.library_status || "ready";
      this._songs = (result.songs || []).map((song) => ({
        title: song.title,
        path: song.path,
      }));
    } catch (error) {
      this._error = error?.message || "Unable to load the piano library.";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _play(song) {
    try {
      await this._hass.callService("media_player", "play_media", {
        entity_id: this._entityId,
        media_content_type: "music",
        media_content_id: song.path,
      });
    } catch (error) {
      this._error = error?.message || "Unable to start this song.";
      this._render();
    }
  }

  _render() {
    if (!this._entityId) {
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: block; }
          .empty { padding: 24px; color: var(--secondary-text-color); text-align: center; }
        </style>
        <ha-card><div class="empty">Select a Piano media player in the card configuration.</div></ha-card>
      `;
      return;
    }
    const query = this._query.toLocaleLowerCase().trim();
    const songs = this._songs.filter((song) =>
      !query || song.title.toLocaleLowerCase().includes(query)
    );
    const waiting = this._libraryStatus !== "ready";
    const waitingMessage = this._libraryStatus === "preparing"
      ? "Preparing piano..."
      : "Syncing library...";
    const body = this._loading
      ? '<div class="empty">Loading library...</div>'
      : this._error
        ? `<div class="error">${this._escape(this._error)}</div>`
        : waiting
          ? `<div class="empty">${waitingMessage}</div>`
        : songs.length
          ? songs.map((song) => `
              <button class="song" data-path="${this._escapeAttr(song.path)}">
                <ha-icon icon="mdi:play"></ha-icon>
                <span>${this._escape(song.title)}</span>
              </button>`).join("")
          : '<div class="empty">No matching songs.</div>';
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        .page { padding: 16px; }
        header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
        h2 { margin: 0; font-size: 20px; flex: 1; }
        input { box-sizing: border-box; width: 100%; height: 40px; margin-bottom: 12px; padding: 0 10px; border: 1px solid var(--divider-color); border-radius: 6px; background: var(--card-background-color); color: var(--primary-text-color); font: inherit; }
        button.icon { width: 40px; height: 40px; border: 0; border-radius: 6px; background: var(--secondary-background-color); color: var(--primary-text-color); cursor: pointer; }
        .songs { display: grid; gap: 4px; max-height: 540px; overflow: auto; }
        .song { display: grid; grid-template-columns: 28px minmax(0, 1fr); align-items: center; gap: 8px; min-height: 42px; width: 100%; border: 0; border-radius: 6px; padding: 0 10px; color: var(--primary-text-color); background: transparent; font: inherit; text-align: left; cursor: pointer; }
        .song:hover { background: var(--secondary-background-color); }
        .song span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .empty, .error { padding: 14px; border-radius: 6px; color: var(--secondary-text-color); background: var(--secondary-background-color); text-align: center; }
        .error { color: var(--error-color); background: color-mix(in srgb, var(--error-color) 12%, transparent); }
      </style>
      <ha-card><div class="page">
        <header><h2>Piano Library</h2><button class="icon" title="Reload song list" data-action="refresh"><ha-icon icon="mdi:refresh"></ha-icon></button></header>
        <input type="search" placeholder="Search songs" value="${this._escapeAttr(this._query)}" ${(this._loading || waiting) ? "disabled" : ""}>
        <div class="songs">${body}</div>
      </div></ha-card>`;
    this.shadowRoot.querySelector("input")?.addEventListener("input", (event) => {
      this._query = event.target.value;
      this._render();
    });
    this.shadowRoot.querySelector("[data-action='refresh']")?.addEventListener("click", () => this._load());
    this.shadowRoot.querySelectorAll(".song").forEach((button) =>
      button.addEventListener("click", () => {
        const song = this._songs.find((item) => item.path === button.dataset.path);
        if (song) this._play(song);
      })
    );
  }

  _escape(value) { return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;"); }
  _escapeAttr(value) { return this._escape(value).replaceAll('"', "&quot;"); }
}

class PianoDiscLibraryCardEditor extends HTMLElement {
  constructor() { super(); this.attachShadow({ mode: "open" }); this._config = {}; }
  set hass(hass) { this._hass = hass; this._render(); }
  setConfig(config) { this._config = { ...config }; this._render(); }
  _render() {
    if (!this._hass) return;
    this.shadowRoot.innerHTML = "<ha-form></ha-form>";
    const form = this.shadowRoot.querySelector("ha-form");
    form.hass = this._hass;
    form.data = { entity: this._config.entity || "" };
    form.schema = [{ name: "entity", selector: { entity: { domain: "media_player" } } }];
    form.computeLabel = () => "Piano media player";
    form.addEventListener("value-changed", (event) => {
      const config = { ...this._config, ...event.detail.value };
      this._config = config;
      this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
    });
  }
}

customElements.define("pianodisc-library-card", PianoDiscLibraryCard);
customElements.define("pianodisc-library-card-editor", PianoDiscLibraryCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({ type: "pianodisc-library-card", name: "PianoDisc Library", description: "Search and play the cached PianoDisc music library.", preview: false });
