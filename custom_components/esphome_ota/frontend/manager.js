/**
 * Main ESPHome OTA Manager sidebar panel.
 */

import { t } from "./i18n.js";
import "./job-dialog.js";
import "./device-dialog.js";
import "./migration-dialog.js";

const css = `
:host {
  display: flex;
  flex-direction: column;
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: var(--primary-text-color, #1f2937);
  background: var(--primary-background-color, #f8fafc);
}
* {
  box-sizing: border-box;
}
header {
  flex: 0 0 auto;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  background: var(--card-background-color, #ffffff);
  border-bottom: 1px solid var(--divider-color, #e2e8f0);
  z-index: 10;
}
h1 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  flex: 1;
}
.builder-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 9999px;
  font-size: 0.8rem;
  font-weight: 500;
  background: var(--secondary-background-color, #e2e8f0);
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
}
.status-ready .status-dot { background: #22c55e; }
.status-ready { color: #166534; background: #dcfce7; }
.status-connecting .status-dot, .status-reconnecting .status-dot, .status-waiting .status-dot { background: #eab308; }
.status-connecting, .status-reconnecting, .status-waiting { color: #854d0e; background: #fef9c3; }
.status-selection_required .status-dot { background: #f97316; }
.status-selection_required { color: #c2410c; background: #ffedd5; }
.status-error .status-dot, .status-unsupported .status-dot { background: #ef4444; }
.status-error, .status-unsupported { color: #991b1b; background: #fee2e2; }

.selection-banner {
  flex: 0 0 auto;
  margin: 16px 20px 0;
  padding: 12px 16px;
  background: #fff7ed;
  border: 1px solid #fdba74;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #9a3412;
  font-size: 0.9rem;
}
.selection-banner select {
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid #fdba74;
  background: #ffffff;
  color: #1e293b;
  font-size: 0.85rem;
}

.migration-banner {
  flex: 0 0 auto;
  margin: 16px 20px 0;
  padding: 12px 16px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #1e40af;
  font-size: 0.9rem;
}
.migration-banner-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.migration-banner-icon {
  font-size: 1.25rem;
}
.migration-banner-title {
  font-weight: 600;
  color: #1e3a8a;
}
.migration-banner-desc {
  font-size: 0.8rem;
  color: #3b82f6;
  margin-top: 2px;
}

.header-actions {
  display: flex;
  gap: 8px;
}
button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 0.85rem;
  font-weight: 500;
  border-radius: 8px;
  border: 1px solid var(--divider-color, #cbd5e1);
  background: var(--card-background-color, #ffffff);
  color: var(--primary-text-color, #1e293b);
  cursor: pointer;
  transition: all 0.15s ease-in-out;
}
button:hover {
  background: var(--secondary-background-color, #f1f5f9);
}
button.primary {
  background: var(--primary-color, #0284c7);
  color: #ffffff;
  border-color: var(--primary-color, #0284c7);
}
button.primary:hover {
  opacity: 0.92;
}

.controls {
  flex: 0 0 auto;
  padding: 16px 20px 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.controls input[type="search"] {
  flex: 1;
  min-width: 220px;
  padding: 8px 14px;
  font-size: 0.875rem;
  border-radius: 8px;
  border: 1px solid var(--divider-color, #cbd5e1);
  background: var(--card-background-color, #ffffff);
  color: inherit;
}
.controls select {
  padding: 8px 12px;
  font-size: 0.875rem;
  border-radius: 8px;
  border: 1px solid var(--divider-color, #cbd5e1);
  background: var(--card-background-color, #ffffff);
  color: inherit;
}

.content {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 12px 20px 24px;
  -webkit-overflow-scrolling: touch;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}
.card {
  background: var(--card-background-color, #ffffff);
  border: 1px solid var(--divider-color, #e2e8f0);
  border-radius: 12px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.card:hover {
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.08);
}
.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.card-title {
  font-size: 1.05rem;
  font-weight: 600;
  margin: 0;
}
.card-sub {
  font-size: 0.78rem;
  color: var(--secondary-text-color, #64748b);
  margin-top: 2px;
}
.badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}
.badge-unmanaged { background: #f1f5f9; color: #475569; }
.badge-initial { background: #fef3c7; color: #92400e; }
.badge-update { background: #dcfce7; color: #166534; }
.badge-installed { background: #e0f2fe; color: #0369a1; }
.badge-building { background: #ede9fe; color: #6d28d9; }

.card-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  background: var(--secondary-background-color, #f8fafc);
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 0.8rem;
}
.stat-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-label {
  color: var(--secondary-text-color, #64748b);
  font-size: 0.72rem;
}
.stat-val {
  font-weight: 600;
}

.card-actions {
  display: flex;
  gap: 8px;
  margin-top: auto;
}
.card-actions button {
  flex: 1;
  justify-content: center;
}
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--secondary-text-color, #64748b);
}
`;

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

class EsphomeOtaManager extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.devices = [];
    this.jobs = [];
    this.candidates = [];
    this.status = "discovering";
    this.builder = null;
    this.query = "";
    this.filter = "all";
    this._filterManual = false;
    this.selectedDevices = new Set();
    this._unsubEvents = null;
    this._domInitialized = false;
    this._migrationPreview = null;
    this._dismissedMigration = false;
  }

  set hass(value) {
    this._hass = value;
    if (this.isConnected && !this._unsubEvents) {
      this.subscribe();
    }
  }

  get hass() {
    return this._hass;
  }

  connectedCallback() {
    this._initDom();
    this.render();
    if (this._hass) {
      this.loadInitialData();
      if (!this._unsubEvents) {
        this.subscribe();
      }
    }
  }

  disconnectedCallback() {
    if (this._unsubEvents) {
      this._unsubEvents();
      this._unsubEvents = null;
    }
  }

  async loadInitialData() {
    try {
      const res = await this.hass.callWS({ type: "esphome_ota/status" });
      if (res) {
        if (res.status !== undefined) this.status = res.status;
        if (res.candidates !== undefined) this.candidates = res.candidates;
        if (res.devices) this.devices = res.devices;
        if (res.jobs) this.jobs = res.jobs;
        this.render();
      }
    } catch (err) {
      console.debug("Initial status fetch error:", err);
    }

    try {
      const mig = await this.hass.callWS({ type: "esphome_ota/migrate_preview" });
      if (mig) {
        this._migrationPreview = mig;
        this._renderMigrationBanner();
      }
    } catch (err) {
      console.debug("Migration preview fetch error:", err);
    }
  }

  async subscribe() {
    try {
      this._unsubEvents = await this.hass.connection.subscribeMessage(
        (msg) => this.handleEvent(msg),
        { type: "esphome_ota/subscribe" }
      );
      await this.loadInitialData();
    } catch (err) {
      console.error("Subscription error:", err);
    }
  }

  handleEvent(msg) {
    if (!msg) return;
    const { event, data } = msg;
    if (event === "snapshot" && data) {
      this.status = data.status || this.status;
      if (data.candidates) this.candidates = data.candidates;
      this.devices = data.devices || [];
      this.jobs = data.jobs || [];
      this.render();
    } else if (event === "status_changed" && data) {
      this.status = data.status;
      if (data.candidates) this.candidates = data.candidates;
      this._updateStatusBadge();
      this._renderSelectionBanner();
    } else if (event === "devices_updated" && data) {
      this.devices = data.devices || [];
      this._renderDeviceList();
    } else if (event === "installation_verified" && data) {
      if (data.devices) {
        this.devices = data.devices;
      }
      this._renderDeviceList();
    } else if (event === "job_updated" && data) {
      const idx = this.jobs.findIndex((j) => j.job_id === data.job_id);
      if (idx >= 0) this.jobs[idx] = data;
      else this.jobs.push(data);
      this.shadowRoot.querySelector("esphome-ota-job-dialog")?.updateJob(data);
      if (data.stage === "published") {
        const d = this.devices.find((dev) => dev.device_id === data.device_id);
        if (d && data.reserved_version) {
          d.last_published_version = data.reserved_version;
        }
      }
      this._renderDeviceList();
    } else if (msg.status !== undefined) {
      this.status = msg.status;
      this.devices = msg.devices || [];
      this.jobs = msg.jobs || [];
      this.render();
    }
  }

  async refresh() {
    try {
      await this.hass.callWS({ type: "esphome_ota/reconnect" });
    } catch (err) {
      console.error("Refresh error:", err);
    }
  }

  async buildDevice(device) {
    const activeJob = this.jobs.find(
      (j) => j.device_id === device.device_id && !["published", "failed", "cancelled"].includes(j.stage)
    );
    if (activeJob) {
      this.openJobDialog(activeJob);
      return;
    }

    try {
      const res = await this.hass.callWS({
        type: "esphome_ota/build",
        device_id: device.device_id,
      });
      const job = {
        job_id: res.job_id,
        device_id: device.device_id,
        configuration: device.configuration,
        stage: "submitting",
        log_tail: [],
      };
      this.openJobDialog(job);
    } catch (err) {
      const fallbackJob = this.jobs.find(
        (j) => j.device_id === device.device_id && !["published", "failed", "cancelled"].includes(j.stage)
      );
      if (fallbackJob) {
        this.openJobDialog(fallbackJob);
        return;
      }
      alert(`Build error: ${err.message || err}`);
    }
  }

  async batchBuild() {
    if (this.selectedDevices.size === 0) {
      alert("Please select at least one device.");
      return;
    }
    try {
      await this.hass.callWS({
        type: "esphome_ota/batch_build",
        device_ids: Array.from(this.selectedDevices),
      });
      alert(`Batch build queued for ${this.selectedDevices.size} devices.`);
      this.selectedDevices.clear();
      this.render();
    } catch (err) {
      alert(`Batch build error: ${err.message || err}`);
    }
  }

  openJobDialog(job) {
    const dialog = this.shadowRoot.querySelector("esphome-ota-job-dialog");
    dialog?.open(job, this.hass);
  }

  openDeviceDialog(device, tab = "diff") {
    const dialog = this.shadowRoot.querySelector("esphome-ota-device-dialog");
    dialog?.open(device, this.hass, tab);
  }

  _initDom() {
    if (this._domInitialized) return;
    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <header>
        <ha-menu-button></ha-menu-button>
        <h1>${escapeHtml(t(this.hass, "title") || "ESPHome OTA")}</h1>
        <div class="builder-badge" id="builder-badge">
          <span class="status-dot"></span>
          <span id="status-text"></span>
        </div>
        <div class="header-actions">
          <button id="btn-migration">${escapeHtml(t(this.hass, "migration") || "Import")}</button>
          <button id="btn-reconnect">${escapeHtml(t(this.hass, "reconnect") || "Reconnect")}</button>
          <button class="primary" id="btn-batch">${escapeHtml(t(this.hass, "batch_build") || "Batch Build")}</button>
        </div>
      </header>

      <div id="selection-banner" class="selection-banner" style="display: none;"></div>
      <div id="migration-banner" class="migration-banner" style="display: none;"></div>

      <div class="controls">
        <input type="search" id="search" placeholder="${escapeHtml(t(this.hass, "search_placeholder") || "Search devices...")}" value="${escapeHtml(this.query)}">
        <select id="filter">
          <option value="all">${escapeHtml(t(this.hass, "filter_all") || "All Devices")}</option>
          <option value="managed">${escapeHtml(t(this.hass, "filter_managed") || "OTA Configured")}</option>
          <option value="unmanaged">${escapeHtml(t(this.hass, "filter_unmanaged") || "Unmanaged")}</option>
          <option value="initial">${escapeHtml(t(this.hass, "filter_initial") || "Initial Install Needed")}</option>
          <option value="update">${escapeHtml(t(this.hass, "filter_update") || "Update Available")}</option>
          <option value="installed">${escapeHtml(t(this.hass, "filter_installed") || "Installed")}</option>
          <option value="building">${escapeHtml(t(this.hass, "filter_building") || "Building")}</option>
        </select>
      </div>

      <div class="content" id="content-container"></div>

      <esphome-ota-job-dialog></esphome-ota-job-dialog>
      <esphome-ota-device-dialog></esphome-ota-device-dialog>
      <esphome-ota-migration-dialog></esphome-ota-migration-dialog>
    `;

    this.shadowRoot.getElementById("btn-migration")?.addEventListener("click", () => {
      this.shadowRoot.querySelector("esphome-ota-migration-dialog")?.open(this.hass);
    });
    this.shadowRoot.getElementById("btn-reconnect")?.addEventListener("click", () => this.refresh());
    this.shadowRoot.getElementById("btn-batch")?.addEventListener("click", () => this.batchBuild());

    const searchInput = this.shadowRoot.getElementById("search");
    searchInput?.addEventListener("input", (e) => {
      this.query = e.target.value;
      this._renderDeviceList();
    });

    const filterSelect = this.shadowRoot.getElementById("filter");
    filterSelect?.addEventListener("change", (e) => {
      this.filter = e.target.value;
      this._filterManual = true;
      this._renderDeviceList();
    });

    const devDialog = this.shadowRoot.querySelector("esphome-ota-device-dialog");
    devDialog?.addEventListener("start-build", (e) => {
      if (e.detail?.device) this.buildDevice(e.detail.device);
    });
    devDialog?.addEventListener("device-updated", () => {
      this.refresh();
    });

    const migDialog = this.shadowRoot.querySelector("esphome-ota-migration-dialog");
    migDialog?.addEventListener("migration-completed", () => {
      if (this._migrationPreview) this._migrationPreview.already_migrated = true;
      this._renderMigrationBanner();
    });

    this._domInitialized = true;
  }

  _updateStatusBadge() {
    const badge = this.shadowRoot.getElementById("builder-badge");
    const statusTextEl = this.shadowRoot.getElementById("status-text");
    if (!badge || !statusTextEl) return;

    badge.className = `builder-badge status-${this.status}`;
    const txt = t(this.hass, `status_${this.status}`) || this.status;
    statusTextEl.textContent = txt;
  }

  _renderSelectionBanner() {
    const banner = this.shadowRoot.getElementById("selection-banner");
    if (!banner) return;
    if (this.status === "selection_required" && this.candidates && this.candidates.length > 0) {
      banner.style.display = "flex";
      const options = this.candidates.map(
        (c) => `<option value="${escapeHtml(c.slug)}">${escapeHtml(c.name || c.slug)} (${escapeHtml(c.host)}:${escapeHtml(c.port)})</option>`
      ).join("");
      banner.innerHTML = `
        <span>${escapeHtml(t(this.hass, "select_builder_prompt") || "Multiple Builders found. Select one:")}</span>
        <div style="display: flex; gap: 8px; align-items: center;">
          <select id="builder-candidate-select">${options}</select>
          <button class="primary" id="btn-confirm-selection">${escapeHtml(t(this.hass, "btn_select_builder") || "Connect")}</button>
        </div>
      `;
      this.shadowRoot.getElementById("btn-confirm-selection")?.addEventListener("click", async () => {
        const sel = this.shadowRoot.getElementById("builder-candidate-select");
        if (sel && sel.value) {
          try {
            await this.hass.callWS({
              type: "esphome_ota/select_builder",
              slug: sel.value,
            });
            await this.refresh();
          } catch (err) {
            alert(`Failed to select builder: ${err.message || err}`);
          }
        }
      });
    } else {
      banner.style.display = "none";
      banner.innerHTML = "";
    }
  }

  _renderMigrationBanner() {
    const banner = this.shadowRoot.getElementById("migration-banner");
    if (!banner) return;
    const p = this._migrationPreview;
    if (p && p.has_legacy_registry && p.device_count > 0 && !p.already_migrated && !this._dismissedMigration) {
      banner.style.display = "flex";
      const title = t(this.hass, "migration_banner_title");
      const desc = t(this.hass, "migration_banner_desc");
      const btnTxt = t(this.hass, "migration_btn_import");
      banner.innerHTML = `
        <div class="migration-banner-left">
          <span class="migration-banner-icon">📦</span>
          <div>
            <div class="migration-banner-title">${escapeHtml(title)} (${p.device_count})</div>
            <div class="migration-banner-desc">${escapeHtml(desc)}</div>
          </div>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <button class="primary" id="btn-start-migration">${escapeHtml(btnTxt)}</button>
          <button id="btn-dismiss-migration" style="padding: 4px 8px; border: none; background: transparent; cursor: pointer; font-size: 1.1rem; color: #64748b;">✕</button>
        </div>
      `;
      this.shadowRoot.getElementById("btn-start-migration")?.addEventListener("click", () => {
        this.shadowRoot.querySelector("esphome-ota-migration-dialog")?.open(this.hass);
      });
      this.shadowRoot.getElementById("btn-dismiss-migration")?.addEventListener("click", () => {
        this._dismissedMigration = true;
        this._renderMigrationBanner();
      });
    } else {
      banner.style.display = "none";
      banner.innerHTML = "";
    }
  }

  render() {
    this._initDom();
    this._updateStatusBadge();
    this._renderSelectionBanner();
    this._renderMigrationBanner();
    this._renderDeviceList();
  }

  _hasOtaConfiguredDevices() {
    return this.devices.some(
      (d) => d.is_managed || (d.status && d.status !== "unmanaged")
    );
  }

  _syncDefaultFilter() {
    if (this._filterManual) return;
    const next = this._hasOtaConfiguredDevices() ? "managed" : "all";
    this.filter = next;
    const filterSelect = this.shadowRoot?.getElementById("filter");
    if (filterSelect && filterSelect.value !== next) {
      filterSelect.value = next;
    }
  }

  _renderDeviceList() {
    const container = this.shadowRoot.getElementById("content-container");
    if (!container) return;

    this._syncDefaultFilter();

    const filtered = this.devices.filter((dev) => {
      if (this.query) {
        const q = this.query.toLowerCase();
        const matchesName = (dev.friendly_name || "").toLowerCase().includes(q);
        const matchesCfg = (dev.configuration || "").toLowerCase().includes(q);
        if (!matchesName && !matchesCfg) return false;
      }
      if (this.filter === "all") return true;
      if (this.filter === "managed") {
        return !!dev.is_managed || (dev.status && dev.status !== "unmanaged");
      }
      if (this.filter === "unmanaged") return dev.status === "unmanaged";
      if (this.filter === "initial") return dev.status === "needs_initial_install";
      if (this.filter === "update") return dev.status === "update_available";
      if (this.filter === "installed") return dev.status === "installed";
      if (this.filter === "building") return dev.status === "building";
      return true;
    });

    if (filtered.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <p>No devices matching criteria.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = `
      <div class="grid">
        ${filtered.map((dev) => this.renderCard(dev)).join("")}
      </div>
    `;

    this._attachCardListeners();
  }

  _attachCardListeners() {
    this.shadowRoot.querySelectorAll(".card-select").forEach((cb) => {
      cb.addEventListener("change", (e) => {
        const id = e.target.getAttribute("data-id");
        if (e.target.checked) this.selectedDevices.add(id);
        else this.selectedDevices.delete(id);
      });
    });

    this.shadowRoot.querySelectorAll(".btn-prepare").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.target.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.openDeviceDialog(dev, "diff");
      });
    });

    this.shadowRoot.querySelectorAll(".btn-build").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.target.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.buildDevice(dev);
      });
    });

    this.shadowRoot.querySelectorAll(".btn-details").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.target.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.openDeviceDialog(dev, "info");
      });
    });
  }

  renderCard(dev) {
    const activeJob = this.jobs.find(
      (j) => j.device_id === dev.device_id && !["published", "failed", "cancelled"].includes(j.stage)
    );

    let badgeKey = dev.status === "unmanaged" ? "badge_unmanaged"
      : dev.status === "needs_initial_install" ? "badge_initial"
      : dev.status === "update_available" ? "badge_update"
      : dev.status === "installed" ? "badge_installed" : "badge_building";

    let badgeClass = `badge-${dev.status === "needs_initial_install" ? "initial" : dev.status === "update_available" ? "update" : dev.status === "installed" ? "installed" : "unmanaged"}`;

    if (activeJob) {
      if (activeJob.stage === "recovery_required") {
        badgeKey = "stage_recovery_required";
        badgeClass = "badge-initial";
      } else {
        badgeKey = "badge_building";
        badgeClass = "badge-update";
      }
    }

    const badgeText = t(this.hass, badgeKey);
    const isSelected = this.selectedDevices.has(dev.device_id);

    let actionButton = "";
    if (activeJob) {
      actionButton = `<button class="primary btn-build" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_view_logs"))}</button>`;
    } else if (dev.status === "unmanaged") {
      actionButton = `<button class="primary btn-prepare" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_prepare"))}</button>`;
    } else {
      actionButton = `<button class="primary btn-build" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_build"))}</button>`;
    }

    return `
      <div class="card" data-id="${escapeHtml(dev.device_id)}">
        <div class="card-header">
          <div style="display: flex; gap: 8px; align-items: flex-start;">
            <input type="checkbox" class="card-select" data-id="${escapeHtml(dev.device_id)}" ${isSelected ? "checked" : ""}>
            <div>
              <h3 class="card-title">${escapeHtml(dev.friendly_name || dev.name)}</h3>
              <div class="card-sub">${escapeHtml(dev.configuration)} • ${escapeHtml(dev.chip_family)}</div>
            </div>
          </div>
          <span class="badge ${badgeClass}">${escapeHtml(badgeText)}</span>
        </div>

        <div class="card-stats">
          <div class="stat-item">
            <span class="stat-label">${escapeHtml(t(this.hass, "installed_version"))}</span>
            <span class="stat-val">${escapeHtml(dev.last_installed_version || "—")}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">${escapeHtml(t(this.hass, "published_version"))}</span>
            <span class="stat-val">${escapeHtml(dev.last_published_version || "—")}</span>
          </div>
        </div>

        <div class="card-actions">
          ${actionButton}
          <button class="btn-details" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_details"))}</button>
        </div>
      </div>
    `;
  }
}

customElements.define("esphome-ota-manager", EsphomeOtaManager);
