/**
 * Main ESPHome OTA Manager sidebar panel.
 */

import { t } from "./i18n.js";
import "./job-dialog.js";
import "./device-dialog.js";

const css = `
:host {
  display: flex;
  flex-direction: column;
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
  flex: none;
  height: 56px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  background: var(--card-background-color, #ffffff);
  border-bottom: 1px solid var(--divider-color, #e2e8f0);
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
.status-error .status-dot, .status-unsupported .status-dot { background: #ef4444; }
.status-error, .status-unsupported { color: #991b1b; background: #fee2e2; }

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
  flex: 1;
  overflow-y: auto;
  padding: 12px 20px 24px;
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

class EsphomeOtaManager extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.devices = [];
    this.jobs = [];
    this.status = "discovering";
    this.builder = null;
    this.query = "";
    this.filter = "all";
    this.selectedDevices = new Set();
    this._unsubEvents = null;
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
        if (res.devices) this.devices = res.devices;
        if (res.jobs) this.jobs = res.jobs;
        this.render();
      }
    } catch (err) {
      console.debug("Initial status fetch error:", err);
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
      this.devices = data.devices || [];
      this.jobs = data.jobs || [];
    } else if (event === "status_changed" && data) {
      this.status = data.status;
    } else if (event === "devices_updated" && data) {
      this.devices = data.devices || [];
    } else if (event === "job_updated" && data) {
      const idx = this.jobs.findIndex((j) => j.job_id === data.job_id);
      if (idx >= 0) this.jobs[idx] = data;
      else this.jobs.push(data);
      this.shadowRoot.querySelector("esphome-ota-job-dialog")?.updateJob(data);
    } else if (msg.status !== undefined) {
      this.status = msg.status;
      this.devices = msg.devices || [];
      this.jobs = msg.jobs || [];
    }
    this.render();
  }

  async refresh() {
    try {
      await this.hass.callWS({ type: "esphome_ota/reconnect" });
    } catch (err) {
      console.error("Refresh error:", err);
    }
  }

  async buildDevice(device) {
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

  render() {
    const statusText = t(this.hass, `status_${this.status}`) || this.status;
    const statusClass = `status-${this.status}`;

    const filtered = this.devices.filter((dev) => {
      if (this.query) {
        const q = this.query.toLowerCase();
        const matchesName = (dev.friendly_name || "").toLowerCase().includes(q);
        const matchesCfg = (dev.configuration || "").toLowerCase().includes(q);
        if (!matchesName && !matchesCfg) return false;
      }
      if (this.filter === "all") return true;
      if (this.filter === "unmanaged") return dev.status === "unmanaged";
      if (this.filter === "initial") return dev.status === "needs_initial_install";
      if (this.filter === "update") return dev.status === "update_available";
      if (this.filter === "installed") return dev.status === "installed";
      if (this.filter === "building") return dev.status === "building";
      return true;
    });

    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <header>
        <ha-menu-button></ha-menu-button>
        <h1>${t(this.hass, "title")}</h1>
        <div class="builder-badge ${statusClass}">
          <span class="status-dot"></span>
          <span>${statusText}</span>
        </div>
        <div class="header-actions">
          <button id="btn-reconnect">${t(this.hass, "reconnect")}</button>
          <button class="primary" id="btn-batch">${t(this.hass, "batch_build")}</button>
        </div>
      </header>

      <div class="controls">
        <input type="search" id="search" placeholder="${t(this.hass, "search_placeholder")}" value="${this.query}">
        <select id="filter">
          <option value="all" ${this.filter === "all" ? "selected" : ""}>${t(this.hass, "filter_all")}</option>
          <option value="unmanaged" ${this.filter === "unmanaged" ? "selected" : ""}>${t(this.hass, "filter_unmanaged")}</option>
          <option value="initial" ${this.filter === "initial" ? "selected" : ""}>${t(this.hass, "filter_initial")}</option>
          <option value="update" ${this.filter === "update" ? "selected" : ""}>${t(this.hass, "filter_update")}</option>
          <option value="installed" ${this.filter === "installed" ? "selected" : ""}>${t(this.hass, "filter_installed")}</option>
          <option value="building" ${this.filter === "building" ? "selected" : ""}>${t(this.hass, "filter_building")}</option>
        </select>
      </div>

      <div class="content">
        ${filtered.length === 0 ? `
          <div class="empty-state">
            <p>No devices matching criteria.</p>
          </div>
        ` : `
          <div class="grid">
            ${filtered.map((dev) => this.renderCard(dev)).join("")}
          </div>
        `}
      </div>

      <esphome-ota-job-dialog></esphome-ota-job-dialog>
      <esphome-ota-device-dialog></esphome-ota-device-dialog>
    `;

    this.attachEventListeners();
  }

  renderCard(dev) {
    const badgeKey = dev.status === "unmanaged" ? "badge_unmanaged"
      : dev.status === "needs_initial_install" ? "badge_initial"
      : dev.status === "update_available" ? "badge_update"
      : dev.status === "installed" ? "badge_installed" : "badge_building";

    const badgeText = t(this.hass, badgeKey);
    const badgeClass = `badge-${dev.status === "needs_initial_install" ? "initial" : dev.status === "update_available" ? "update" : dev.status === "installed" ? "installed" : "unmanaged"}`;

    const isSelected = this.selectedDevices.has(dev.device_id);

    return `
      <div class="card" data-id="${dev.device_id}">
        <div class="card-header">
          <div style="display: flex; gap: 8px; align-items: flex-start;">
            <input type="checkbox" class="card-select" data-id="${dev.device_id}" ${isSelected ? "checked" : ""}>
            <div>
              <h3 class="card-title">${dev.friendly_name || dev.name}</h3>
              <div class="card-sub">${dev.configuration}.yaml • ${dev.chip_family}</div>
            </div>
          </div>
          <span class="badge ${badgeClass}">${badgeText}</span>
        </div>

        <div class="card-stats">
          <div class="stat-item">
            <span class="stat-label">${t(this.hass, "installed_version")}</span>
            <span class="stat-val">${dev.last_installed_version || "—"}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">${t(this.hass, "published_version")}</span>
            <span class="stat-val">${dev.last_published_version || "—"}</span>
          </div>
        </div>

        <div class="card-actions">
          ${dev.status === "unmanaged" ? `
            <button class="primary btn-prepare" data-id="${dev.device_id}">${t(this.hass, "btn_prepare")}</button>
          ` : `
            <button class="primary btn-build" data-id="${dev.device_id}">${t(this.hass, "btn_build")}</button>
          `}
          <button class="btn-details" data-id="${dev.device_id}">${t(this.hass, "btn_details")}</button>
        </div>
      </div>
    `;
  }

  attachEventListeners() {
    this.shadowRoot.getElementById("btn-reconnect")?.addEventListener("click", () => this.refresh());
    this.shadowRoot.getElementById("btn-batch")?.addEventListener("click", () => this.batchBuild());

    const searchInput = this.shadowRoot.getElementById("search");
    searchInput?.addEventListener("input", (e) => {
      this.query = e.target.value;
      this.render();
    });

    const filterSelect = this.shadowRoot.getElementById("filter");
    filterSelect?.addEventListener("change", (e) => {
      this.filter = e.target.value;
      this.render();
    });

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

    const devDialog = this.shadowRoot.querySelector("esphome-ota-device-dialog");
    devDialog?.addEventListener("start-build", (e) => {
      if (e.detail?.device) this.buildDevice(e.detail.device);
    });
    devDialog?.addEventListener("device-updated", () => {
      this.refresh();
    });
  }
}

customElements.define("esphome-ota-manager", EsphomeOtaManager);
