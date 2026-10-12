/**
 * Main ESPHome OTA Manager sidebar panel.
 */

import { t } from "./i18n.js";
import { definePanelElement } from "./elements.js";
import "./job-dialog.js";
import "./device-dialog.js";
import "./migration-dialog.js";
import "./build-dialog.js";

const css = `
:host {
  display: flex;
  flex-direction: column;
  height: var(--esphome-ota-panel-height, 100%);
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
  height: var(--header-height, 56px);
  min-height: 56px;
  position: sticky;
  top: 0;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  background: var(--card-background-color, #ffffff);
  border-bottom: 1px solid var(--divider-color, #e2e8f0);
  z-index: 10;
}
.header-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}
h1 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  white-space: nowrap;
}
.version-tag {
  display: inline-flex;
  align-items: center;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--secondary-text-color, #64748b);
  background: var(--secondary-background-color, #f1f5f9);
  padding: 2px 7px;
  border-radius: 9999px;
  line-height: 1.3;
  border: 1px solid var(--divider-color, #e2e8f0);
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

.bottom-notifications {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  width: calc(100% - 40px);
  max-width: 680px;
  z-index: 990;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}
.selection-banner,
.migration-banner {
  pointer-events: auto;
  padding: 12px 16px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 0.9rem;
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.12), 0 4px 6px -4px rgba(0, 0, 0, 0.08);
  animation: bannerSlideUp 0.2s ease-out;
}
@keyframes bannerSlideUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.selection-banner {
  background: #fff7ed;
  border: 1px solid #fdba74;
  color: #9a3412;
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
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  color: #1e40af;
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
.selection-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 20px;
  color: var(--secondary-text-color, #64748b);
  font-size: 0.85rem;
}
.selection-summary[hidden] { display: none; }
.selection-summary-text { min-width: 0; }
.selection-summary button {
  flex: none;
  padding: 5px 10px;
  font-size: 0.8rem;
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
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
button.primary {
  background: var(--primary-color, #0284c7);
  color: #ffffff;
  border-color: var(--primary-color, #0284c7);
}
button.primary:hover {
  opacity: 0.92;
}
button.danger {
  background: #ffffff;
  color: #b91c1c;
  border-color: #fca5a5;
}
button.danger:hover {
  background: #fef2f2;
}

.controls {
  flex: 0 0 auto;
  padding: 16px 20px 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}
.controls input[type="search"],
.controls select {
  height: 40px;
  box-sizing: border-box;
  font: inherit;
  font-size: 0.875rem;
  border-radius: 8px;
  border: 1px solid var(--divider-color, #cbd5e1);
  background: var(--card-background-color, #ffffff);
  color: inherit;
  line-height: normal;
  transition: border-color 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
}
.controls input[type="search"]:focus,
.controls select:focus {
  outline: none;
  border-color: var(--primary-color, #0284c7);
  box-shadow: 0 0 0 2px rgba(2, 132, 199, 0.15);
}
.controls input[type="search"] {
  flex: 1;
  min-width: 220px;
  padding: 0 14px;
  -webkit-appearance: none;
  appearance: none;
}
.controls input[type="search"]::-webkit-search-decoration,
.controls input[type="search"]::-webkit-search-cancel-button {
  -webkit-appearance: none;
}
.controls select {
  flex: none;
  min-width: 12rem;
  max-width: 100%;
  padding: 0 32px 0 12px;
  cursor: pointer;
  appearance: none;
  -webkit-appearance: none;
  background-image: linear-gradient(45deg, transparent 50%, currentColor 50%),
                    linear-gradient(135deg, currentColor 50%, transparent 50%);
  background-position: calc(100% - 17px) 50%, calc(100% - 12px) 50%;
  background-size: 5px 5px, 5px 5px;
  background-repeat: no-repeat;
}
.controls select::-ms-expand {
  display: none;
}

.content {
  flex: 1 1 auto;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-gutter: stable;
  -webkit-overflow-scrolling: touch;
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
.badge-unmanaged { background: var(--secondary-background-color, #f1f5f9); color: var(--secondary-text-color, #475569); }
.badge-initial { background: var(--warning-background-color, #fef3c7); color: var(--warning-color, #92400e); }
.badge-update { background: var(--success-background-color, #dcfce7); color: var(--success-color, #166534); }
.badge-installed { background: var(--info-background-color, #e0f2fe); color: var(--info-color, #0369a1); }
.badge-building { background: var(--info-background-color, #e0f2fe); color: var(--info-color, #075985); }
.badge-failed { background: var(--error-background-color, #fee2e2); color: var(--error-color, #991b1b); }

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
.initial-install-guidance {
  padding: 9px 11px;
  border: 1px solid var(--warning-color, #fcd34d);
  border-radius: 8px;
  background: var(--secondary-background-color, #fffbeb);
  color: var(--primary-text-color, #78350f);
  font-size: 0.78rem;
  line-height: 1.45;
}
.binary-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.72rem;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 999px;
  line-height: 1.2;
}
.binary-active {
  background: var(--success-background-color, #dcfce7);
  color: var(--success-color, #166534);
}
.binary-hidden {
  background: var(--secondary-background-color, #f1f5f9);
  color: var(--secondary-text-color, #64748b);
}
.status-dot-sm {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}
.status-dot-sm.ok { background: var(--success-color, #16a34a); }
.status-dot-sm.neutral { background: #94a3b8; }

.card-actions {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  margin-top: auto;
}
.card-actions button {
  width: 100%;
  min-width: 0;
  height: 36px;
  padding: 0 6px;
  font-size: 0.8rem;
  justify-content: center;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  box-sizing: border-box;
}
.card-secondary-actions button:only-child {
  grid-column: 1 / -1;
}
.card-main-actions,
.card-secondary-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.card-main-actions .primary:only-child { grid-column: 1 / -1; }
.card-secondary-actions button {
  color: var(--secondary-text-color, #64748b);
  border-color: var(--divider-color, #cbd5e1);
  background: transparent;
}
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--secondary-text-color, #64748b);
}
@media (max-width: 650px) {
  header {
    height: auto;
    min-height: 0;
    padding: 10px 12px;
    gap: 8px;
    flex-wrap: wrap;
  }
  .header-title-wrap { flex: 1 1 calc(100% - 52px); }
  .header-title-wrap h1 {
    font-size: 1.1rem;
  }
  .builder-badge {
    order: 2;
    margin-left: 4px;
  }
  .header-actions {
    order: 3;
    width: 100%;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px;
  }
  .header-actions button {
    min-width: 0;
    min-height: 38px;
    padding: 5px 6px;
    justify-content: center;
    text-align: center;
    white-space: normal;
    line-height: 1.2;
  }
  .builder-badge {
    padding: 4px 8px;
    font-size: 0.75rem;
  }
  .controls {
    padding: 12px 12px 6px;
    gap: 8px;
  }
  .controls input[type="search"] {
    min-width: 100%;
  }
  .controls select {
    width: 100%;
    min-width: 0;
  }
  .content {
    padding: 8px 12px 20px;
  }
  .selection-summary { padding: 8px 12px; }
  .grid {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }
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
    this.devicesLoaded = false;
    this.initialLoadError = false;
    this.jobs = [];
    this.candidates = [];
    this.status = "discovering";
    this.builder = null;
    this.query = "";
    this.filter = "all";
    this._filterManual = false;
    this._filterDefaulted = false;
    this.selectedDevices = new Set();
    this.batchBuilding = false;
    this._unsubEvents = null;
    this._subscriptionAttempted = false;
    this._subscriptionPending = false;
    this._domInitialized = false;
    this._migrationPreview = null;
    this._dismissedMigration = false;
    this._panel = null;
    this._backendVersion = null;
    this.resizePanel = null;
    this.panelObserver = null;
  }

  set panel(value) {
    this._panel = value;
    this._updateVersionTag();
  }

  get panel() {
    return this._panel;
  }

  get version() {
    return this._panel?.config?.version || this._backendVersion || "";
  }

  _updateVersionTag() {
    const el = this.shadowRoot?.getElementById("panel-version");
    if (!el) return;
    const v = this.version;
    if (v) {
      el.textContent = `v${v}`;
      const titleStr = t(this.hass, "integration_version") || "ESPHome OTA version";
      el.title = `${titleStr} v${v}`;
      el.style.display = "inline-flex";
    } else {
      el.style.display = "none";
    }
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
    // HA's custom-panel wrapper may have an automatic height. Bound our own
    // panel to the available viewport so that only the content can overflow.
    this.resizePanel = () => {
      const height = Math.max(
        0,
        window.innerHeight - this.getBoundingClientRect().top,
      );
      this.style.setProperty("--esphome-ota-panel-height", `${height}px`);
    };
    this.panelObserver = new ResizeObserver(this.resizePanel);
    this.panelObserver.observe(this);
    window.addEventListener("resize", this.resizePanel);
    this.resizePanel();

    this._initDom();
    this.render();
    if (this._hass) {
      if (!this._unsubEvents) {
        this.subscribe();
      }
    }
  }

  disconnectedCallback() {
    this.panelObserver?.disconnect();
    this.panelObserver = null;
    window.removeEventListener("resize", this.resizePanel);
    if (this._unsubEvents) {
      this._unsubEvents();
      this._unsubEvents = null;
    }
    this._subscriptionAttempted = false;
  }

  async loadMigrationPreview() {
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
    if (this._subscriptionAttempted || this._subscriptionPending) return;
    this._subscriptionAttempted = true;
    this._subscriptionPending = true;
    try {
      this._unsubEvents = await this.hass.connection.subscribeMessage(
        (msg) => this.handleEvent(msg),
        { type: "esphome_ota/subscribe" }
      );
      await this.loadMigrationPreview();
    } catch (err) {
      console.error("Subscription error:", err);
      await this.loadInitialFallback();
    } finally {
      this._subscriptionPending = false;
    }
  }

  async loadInitialFallback() {
    const [statusResult, devicesResult] = await Promise.allSettled([
      this.hass.callWS({ type: "esphome_ota/status" }),
      this.hass.callWS({ type: "esphome_ota/devices" }),
    ]);

    if (statusResult.status === "fulfilled") {
      const status = statusResult.value;
      this.status = status.status || this.status;
      this.builder = status.builder || null;
      this.candidates = status.candidates || [];
      if (status.version) this._backendVersion = status.version;
    }
    if (devicesResult.status === "fulfilled") {
      this.devices = devicesResult.value.devices || [];
      this.initialLoadError = false;
    } else {
      console.error("Initial devices fallback error:", devicesResult.reason);
      this.devices = [];
      this.initialLoadError = true;
    }

    this.devicesLoaded = true;
    this._updateVersionTag();
    this.render();
    await this.loadMigrationPreview();
  }

  handleEvent(msg) {
    if (!msg) return;
    const { event, data } = msg;
    if (event === "snapshot" && data) {
      if (data.version) this._backendVersion = data.version;
      this.initialLoadError = false;
      this.status = data.status || this.status;
      if (data.candidates) this.candidates = data.candidates;
      this.devices = data.devices || [];
      this.devicesLoaded = true;
      this.jobs = data.jobs || [];
      this.render();
    } else if (event === "status_changed" && data) {
      this.status = data.status;
      if (data.candidates) this.candidates = data.candidates;
      this._updateStatusBadge();
      this._renderSelectionBanner();
    } else if (event === "devices_updated" && data) {
      this.devices = data.devices || [];
      this.devicesLoaded = true;
      this._renderDeviceList();
    } else if (event === "installation_verified" && data) {
      if (data.devices) {
        this.devices = data.devices;
        this.devicesLoaded = true;
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
      this.devicesLoaded = true;
      this.jobs = msg.jobs || [];
      this.render();
    }
  }

  async refresh() {
    try {
      await this.hass.callWS({ type: "esphome_ota/reconnect" });
      if (!this._unsubEvents && !this._subscriptionPending) {
        this._subscriptionAttempted = false;
        await this.subscribe();
      }
    } catch (err) {
      console.error("Refresh error:", err);
    }
  }

  async buildDevice(device, returnFocus = undefined) {
    const activeJob = this._getActiveJob(device.device_id);
    if (activeJob) {
      this.openJobDialog(activeJob, returnFocus);
      return;
    }
    this.shadowRoot
      .querySelector("esphome-ota-build-dialog")
      ?.open(device, this.hass, returnFocus);
  }

  openBuildStarted(detail) {
    const job = {
      job_id: detail.job_id,
      device_id: detail.device?.device_id,
      configuration: detail.device?.configuration,
      stage: "preparing",
      reserved_version: detail.target_version,
      log_tail: [],
    };
    this.openJobDialog(job, detail.returnFocus);
  }

  async batchBuild() {
    if (this.batchBuilding) return;
    if (this.selectedDevices.size === 0) {
      this.showToast(t(this.hass, "batch_select_required"));
      return;
    }
    const requestedIds = Array.from(this.selectedDevices);
    this.batchBuilding = true;
    this._renderSelectionSummary();
    try {
      const result = await this.hass.callWS({
        type: "esphome_ota/batch_build",
        device_ids: requestedIds,
      });
      const jobs = result?.jobs && typeof result.jobs === "object" ? result.jobs : {};
      const queuedIds = requestedIds.filter((id) => Object.hasOwn(jobs, id));
      const failedIds = requestedIds.filter((id) => !Object.hasOwn(jobs, id));
      queuedIds.forEach((id) => this.selectedDevices.delete(id));
      this._renderDeviceList();
      this._renderSelectionSummary();
      const message = failedIds.length
        ? this._formatText("batch_partial", { queued: queuedIds.length, failed: failedIds.length })
        : this._formatText("batch_queued", { count: queuedIds.length });
      this.showToast(message);
    } catch (err) {
      this.showToast(`Batch build error: ${err.message || err}`);
    } finally {
      this.batchBuilding = false;
      this._renderSelectionSummary();
    }
  }

  _formatText(key, values) {
    return Object.entries(values).reduce(
      (text, [name, value]) => text.replaceAll(`{${name}}`, String(value)),
      t(this.hass, key),
    );
  }

  _renderSelectionSummary() {
    const summary = this.shadowRoot.getElementById("selection-summary");
    const text = this.shadowRoot.getElementById("selection-summary-text");
    const batchButton = this.shadowRoot.getElementById("btn-batch");
    if (!summary || !text || !batchButton) return;
    const count = this.selectedDevices.size;
    const visibleIds = new Set(
      [...this.shadowRoot.querySelectorAll(".card-select")].map((checkbox) => checkbox.dataset.id),
    );
    const hiddenCount = [...this.selectedDevices].filter((id) => !visibleIds.has(id)).length;
    summary.hidden = count === 0;
    text.textContent = hiddenCount
      ? this._formatText("selection_summary_hidden", { count, hidden: hiddenCount })
      : this._formatText("selection_summary", { count });
    batchButton.disabled = count === 0 || this.batchBuilding;
    batchButton.textContent = this.batchBuilding
      ? t(this.hass, "batch_building")
      : `${t(this.hass, "batch_build")} (${count})`;
    const clearButton = this.shadowRoot.getElementById("btn-clear-selection");
    if (clearButton) {
      clearButton.textContent = t(this.hass, "clear_selection");
      clearButton.disabled = this.batchBuilding;
    }
    this.shadowRoot.querySelectorAll(".card-select").forEach((checkbox) => {
      checkbox.disabled = this.batchBuilding;
    });
  }

  openJobDialog(job, returnFocus = undefined) {
    const dialog = this.shadowRoot.querySelector("esphome-ota-job-dialog");
    dialog?.open(job, this.hass, returnFocus);
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
        <div class="header-title-wrap">
          <h1>${escapeHtml(t(this.hass, "title") || "ESPHome OTA")}</h1>
          <span class="version-tag" id="panel-version" title="${escapeHtml(t(this.hass, "integration_version") || "ESPHome OTA version")}" style="display: none;"></span>
        </div>
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

      <div class="controls">
        <input type="search" id="search" aria-label="${escapeHtml(t(this.hass, "search_label"))}" placeholder="${escapeHtml(t(this.hass, "search_placeholder") || "Search devices...")}" value="${escapeHtml(this.query)}">
        <select id="filter" aria-label="${escapeHtml(t(this.hass, "filter_label"))}">
          <option value="all">${escapeHtml(t(this.hass, "filter_all") || "All Devices")}</option>
          <option value="managed">${escapeHtml(t(this.hass, "filter_managed") || "OTA Configured")}</option>
          <option value="unmanaged">${escapeHtml(t(this.hass, "filter_unmanaged") || "Unmanaged")}</option>
          <option value="initial">${escapeHtml(t(this.hass, "filter_initial") || "Initial Install Needed")}</option>
          <option value="update">${escapeHtml(t(this.hass, "filter_update") || "Update Available")}</option>
          <option value="installed">${escapeHtml(t(this.hass, "filter_installed") || "Installed")}</option>
          <option value="building">${escapeHtml(t(this.hass, "filter_building") || "Building")}</option>
        </select>
      </div>

      <div id="selection-summary" class="selection-summary" hidden>
        <span id="selection-summary-text" class="selection-summary-text"></span>
        <button id="btn-clear-selection" type="button"></button>
      </div>

      <div class="content" id="content-container"></div>

      <div class="bottom-notifications">
        <div id="selection-banner" class="selection-banner" style="display: none;"></div>
        <div id="migration-banner" class="migration-banner" style="display: none;"></div>
      </div>

      <esphome-ota-job-dialog></esphome-ota-job-dialog>
      <esphome-ota-device-dialog></esphome-ota-device-dialog>
      <esphome-ota-migration-dialog></esphome-ota-migration-dialog>
      <esphome-ota-build-dialog></esphome-ota-build-dialog>
    `;

    this.shadowRoot.getElementById("btn-migration")?.addEventListener("click", () => {
      this.shadowRoot.querySelector("esphome-ota-migration-dialog")?.open(this.hass);
    });
    this.shadowRoot.getElementById("btn-reconnect")?.addEventListener("click", () => this.refresh());
    this.shadowRoot.getElementById("btn-batch")?.addEventListener("click", () => this.batchBuild());
    this.shadowRoot.getElementById("btn-clear-selection")?.addEventListener("click", () => {
      this.selectedDevices.clear();
      this._renderDeviceList();
      this._renderSelectionSummary();
    });

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
      if (e.detail?.device) {
        this.buildDevice(e.detail.device, e.detail.returnFocus);
      }
    });
    devDialog?.addEventListener("device-updated", () => {
      this.refresh();
    });

    const migDialog = this.shadowRoot.querySelector("esphome-ota-migration-dialog");
    migDialog?.addEventListener("migration-completed", (e) => {
      if (e.detail?.success) {
        if (this._migrationPreview) this._migrationPreview.already_migrated = true;
        this._renderMigrationBanner();
      }
    });

    const buildDialog = this.shadowRoot.querySelector("esphome-ota-build-dialog");
    buildDialog?.addEventListener("build-started", (e) => {
      if (e.detail) this.openBuildStarted(e.detail);
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
            this.showToast(`Failed to select builder: ${err.message || err}`);
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
          <span class="migration-banner-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="21 8 21 21 3 21 3 8"></polyline><rect x="1" y="3" width="22" height="5"></rect><line x1="10" y1="12" x2="14" y2="12"></line></svg>
          </span>
          <div>
            <div class="migration-banner-title">${escapeHtml(title)} (${p.device_count})</div>
            <div class="migration-banner-desc">${escapeHtml(desc)}</div>
          </div>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <button class="primary" id="btn-start-migration">${escapeHtml(btnTxt)}</button>
          <button id="btn-dismiss-migration" style="padding: 4px 6px; border: none; background: transparent; cursor: pointer; color: #64748b; display: inline-flex; align-items: center; justify-content: center;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
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
    this._updateVersionTag();
    this._updateStatusBadge();
    this._renderSelectionBanner();
    this._renderMigrationBanner();
    this._renderDeviceList();
    this._renderSelectionSummary();
  }

  _isTerminalJobStage(stage) {
    return ["published", "failed", "cancelled"].includes(stage);
  }

  _getDeviceJobs(deviceId) {
    return this.jobs.filter((j) => j.device_id === deviceId);
  }

  _getLatestJob(deviceId) {
    const jobs = this._getDeviceJobs(deviceId);
    if (!jobs.length) return null;
    return jobs.reduce((latest, job) => {
      const latestTs = Date.parse(latest.updated_at || latest.created_at || 0);
      const jobTs = Date.parse(job.updated_at || job.created_at || 0);
      return jobTs >= latestTs ? job : latest;
    });
  }

  _getActiveJob(deviceId) {
    const latest = this._getLatestJob(deviceId);
    if (!latest || this._isTerminalJobStage(latest.stage)) return null;
    return latest;
  }

  _getDeviceBadge(dev) {
    const activeJob = this._getActiveJob(dev.device_id);
    if (activeJob) {
      if (activeJob.stage === "recovery_required") {
        return { badgeKey: "stage_recovery_required", badgeClass: "badge-initial" };
      }
      return { badgeKey: "badge_building", badgeClass: "badge-building" };
    }

    const latest = this._getLatestJob(dev.device_id);
    if (latest?.stage === "failed") {
      return { badgeKey: "stage_failed", badgeClass: "badge-failed" };
    }
    if (latest?.stage === "cancelled") {
      return { badgeKey: "stage_cancelled", badgeClass: "badge-unmanaged" };
    }

    if (dev.status === "unmanaged") {
      return { badgeKey: "badge_unmanaged", badgeClass: "badge-unmanaged" };
    }
    if (dev.status === "needs_initial_install") {
      return { badgeKey: "badge_initial", badgeClass: "badge-initial" };
    }
    if (dev.status === "update_available") {
      return { badgeKey: "badge_update", badgeClass: "badge-update" };
    }
    if (dev.status === "installed" || dev.status === "ready") {
      return { badgeKey: "badge_installed", badgeClass: "badge-installed" };
    }
    return { badgeKey: "badge_installed", badgeClass: "badge-installed" };
  }

  _isOtaConfigured(dev) {
    return !!dev?.is_managed;
  }

  _hasOtaConfiguredDevices() {
    return this.devices.some((d) => this._isOtaConfigured(d));
  }

  _syncDefaultFilter() {
    if (this._filterManual || this._filterDefaulted || this.devices.length === 0) return;
    this._filterDefaulted = true;
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

    // Live job events can arrive several times a second. Keep the list position
    // and the active card control stable while replacing the card markup.
    const scrollTop = container.scrollTop;
    const active = this.shadowRoot.activeElement;
    const focusTarget = active && container.contains(active)
      ? {
          className: [...active.classList].find((name) => name !== "") || "",
          deviceId: active.dataset?.id,
          jobId: active.dataset?.jobId,
        }
      : null;

    this._syncDefaultFilter();

    const filtered = this.devices.filter((dev) => {
      if (this.query) {
        const q = this.query.toLowerCase();
        const matchesName = (dev.friendly_name || "").toLowerCase().includes(q);
        const matchesCfg = (dev.configuration || "").toLowerCase().includes(q);
        if (!matchesName && !matchesCfg) return false;
      }
      if (this.filter === "all") return true;
      if (this.filter === "managed") return this._isOtaConfigured(dev);
      if (this.filter === "unmanaged") return dev.status === "unmanaged";
      if (this.filter === "initial") return dev.status === "needs_initial_install";
      if (this.filter === "update") return dev.status === "update_available";
      if (this.filter === "installed") {
        return (
          dev.status === "installed" ||
          (dev.status === "ready" && !!dev.last_installed_version) ||
          (!!dev.last_installed_version &&
            dev.status !== "needs_initial_install" &&
            dev.status !== "update_available")
        );
      }
      if (this.filter === "building") return !!this._getActiveJob(dev.device_id);
      return true;
    });

    if (filtered.length === 0) {
      let emptyMessage;
      if (!this.devicesLoaded) {
        emptyMessage = t(this.hass, "empty_loading");
      } else if (this.initialLoadError) {
        emptyMessage = t(this.hass, "empty_load_error");
      } else if (this.devices.length === 0) {
        emptyMessage = t(this.hass, "empty_no_devices");
      } else {
        emptyMessage = t(this.hass, "empty_no_matches");
      }
      container.innerHTML = `
        <div class="empty-state">
          <p>${escapeHtml(emptyMessage)}</p>
          ${this.initialLoadError
            ? `<button class="primary" id="btn-empty-retry">${escapeHtml(t(this.hass, "retry"))}</button>`
            : this.devices.length > 0
              ? `<button id="btn-empty-reset">${escapeHtml(t(this.hass, "reset_search_filter"))}</button>`
              : ""}
        </div>
      `;
      this.shadowRoot.getElementById("btn-empty-retry")?.addEventListener("click", async () => {
        await this.refresh();
        if (this.initialLoadError) await this.loadInitialFallback();
      });
      this.shadowRoot.getElementById("btn-empty-reset")?.addEventListener("click", () => {
        this.query = "";
        this.filter = "all";
        this._filterManual = true;
        this.shadowRoot.getElementById("search").value = "";
        this.shadowRoot.getElementById("filter").value = "all";
        this._renderDeviceList();
      });
      container.scrollTop = scrollTop;
      this._renderSelectionSummary();
      return;
    }

    container.innerHTML = `
      <div class="grid">
        ${filtered.map((dev) => this.renderCard(dev)).join("")}
      </div>
    `;

    this._attachCardListeners();
    container.scrollTop = scrollTop;
    if (focusTarget?.className) {
      const candidate = [...container.querySelectorAll(`.${focusTarget.className}`)].find((el) =>
        (focusTarget.deviceId === undefined || el.dataset.id === focusTarget.deviceId) &&
        (focusTarget.jobId === undefined || el.dataset.jobId === focusTarget.jobId),
      );
      candidate?.focus({ preventScroll: true });
    }
    this._renderSelectionSummary();
  }

  _attachCardListeners() {
    this.shadowRoot.querySelectorAll(".card-select").forEach((cb) => {
      cb.addEventListener("change", (e) => {
        const id = e.target.getAttribute("data-id");
        if (e.target.checked) this.selectedDevices.add(id);
        else this.selectedDevices.delete(id);
        this._renderSelectionSummary();
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

    this.shadowRoot.querySelectorAll(".btn-view-logs").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const jobId = e.target.getAttribute("data-job-id");
        const job = this.jobs.find((j) => j.job_id === jobId);
        if (job) this.openJobDialog(job);
      });
    });

    this.shadowRoot.querySelectorAll(".btn-hide").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.target.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.hideBinary(dev);
      });
    });

    this.shadowRoot.querySelectorAll(".btn-republish").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.target.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.republishBinary(dev);
      });
    });

    this.shadowRoot.querySelectorAll(".btn-details").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.target.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.openDeviceDialog(dev, "info");
      });
    });

    this.shadowRoot.querySelectorAll(".btn-remove-ota").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.target.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.removeOta(dev);
      });
    });
  }

  async hideBinary(device) {
    try {
      await this.hass.callWS({
        type: "esphome_ota/deactivate",
        device_id: device.device_id,
      });
      device.has_public_binary = false;
      this._renderDeviceList();
      this.showToast(t(this.hass, "hide_success"));
    } catch (err) {
      this.showToast(`Hide error: ${err.message || err}`);
    }
  }

  async republishBinary(device) {
    try {
      await this.hass.callWS({
        type: "esphome_ota/republish",
        device_id: device.device_id,
      });
      device.has_public_binary = true;
      this._renderDeviceList();
      this.showToast(t(this.hass, "republish_success"));
    } catch (err) {
      this.showToast(`Republish error: ${err.message || err}`);
    }
  }

  showToast(message) {
    this.dispatchEvent(
      new CustomEvent("hass-notification", {
        detail: { message },
        bubbles: true,
        composed: true,
      })
    );
  }

  async removeOta(device) {
    const confirmMsg = t(this.hass, "remove_ota_confirm");
    if (!window.confirm(confirmMsg)) return;
    try {
      await this.hass.callWS({
        type: "esphome_ota/remove_ota",
        device_id: device.device_id,
      });
      this.selectedDevices.delete(device.device_id);
      try {
        const res = await this.hass.callWS({ type: "esphome_ota/devices" });
        if (Array.isArray(res)) this.devices = res;
        else if (res?.devices) this.devices = res.devices;
        this.devicesLoaded = true;
      } catch (_err) {
        // devices_updated subscription will refresh the list
      }
      this._renderDeviceList();
    } catch (err) {
      this.showToast(`Remove OTA error: ${err.message || err}`);
    }
  }

  renderCard(dev) {
    const activeJob = this._getActiveJob(dev.device_id);
    const latestJob = this._getLatestJob(dev.device_id);
    const { badgeKey, badgeClass } = this._getDeviceBadge(dev);

    const badgeText = t(this.hass, badgeKey);
    const isSelected = this.selectedDevices.has(dev.device_id);
    const needsInitialInstall = dev.status === "needs_initial_install"
      || (!dev.has_http_ota && !dev.last_installed_version);
    const canChangeBinaryVisibility = !!dev.last_published_version && !activeJob;
    const expiryLabel = dev.has_public_binary
      ? (dev.expires_at ? `${new Date(dev.expires_at).toLocaleString()} · ${this._remainingTime(dev.expires_at)}` : t(this.hass, "expiry_disabled"))
      : "";

    let actionButton = "";
    if (activeJob) {
      actionButton = `<button class="primary btn-build" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_view_logs"))}</button>`;
    } else if (latestJob && (latestJob.stage === "failed" || latestJob.stage === "cancelled")) {
      actionButton = `
        <button class="primary btn-build" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_build"))}</button>
        <button class="btn-view-logs" data-job-id="${escapeHtml(latestJob.job_id)}">${escapeHtml(t(this.hass, "btn_view_logs"))}</button>
      `;
    } else if (dev.status === "unmanaged") {
      actionButton = `<button class="primary btn-prepare" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_prepare"))}</button>`;
    } else {
      actionButton = `<button class="primary btn-build" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_build"))}</button>`;
    }

    return `
      <div class="card" data-id="${escapeHtml(dev.device_id)}">
        <div class="card-header">
          <div style="display: flex; gap: 8px; align-items: flex-start;">
            <input type="checkbox" class="card-select" data-id="${escapeHtml(dev.device_id)}" aria-label="${escapeHtml(t(this.hass, "select_device"))}: ${escapeHtml(dev.friendly_name || dev.name)}" ${isSelected ? "checked" : ""}>
            <div>
              <h3 class="card-title">${escapeHtml(dev.friendly_name || dev.name)}</h3>
              <div class="card-sub">${escapeHtml(dev.configuration)} • ${escapeHtml(dev.chip_family)}</div>
            </div>
          </div>
          <span class="badge ${badgeClass}">${escapeHtml(badgeText)}</span>
        </div>

        ${expiryLabel ? `<div class="card-sub" style="padding: 0 16px 10px;">${escapeHtml(t(this.hass, "publication_expiry"))}: ${escapeHtml(expiryLabel)}</div>` : ""}

        <div class="card-stats">
          <div class="stat-item">
            <span class="stat-label">${escapeHtml(t(this.hass, "installed_version"))}</span>
            <span class="stat-val">${escapeHtml(dev.last_installed_version || "—")}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">${escapeHtml(t(this.hass, "published_version"))}</span>
            <div style="display: flex; align-items: center; gap: 6px;">
              <span class="stat-val">${escapeHtml(dev.last_published_version || "—")}</span>
              ${dev.last_published_version ? (
                dev.has_public_binary
                  ? `<span class="binary-status binary-active" title="${escapeHtml(t(this.hass, "status_active"))}"><span class="status-dot-sm ok"></span> ${escapeHtml(t(this.hass, "status_active"))}</span>`
                  : `<span class="binary-status binary-hidden" title="${escapeHtml(t(this.hass, "status_hidden"))}"><span class="status-dot-sm neutral"></span> ${escapeHtml(t(this.hass, "status_hidden"))}</span>`
              ) : ""}
            </div>
          </div>
        </div>

        ${needsInitialInstall ? `<div class="initial-install-guidance" role="status">${escapeHtml(t(this.hass, "initial_install_card_help"))}</div>` : ""}

        <div class="card-actions">
          <div class="card-main-actions">${actionButton}</div>
          <div class="card-secondary-actions">
            <button class="btn-details" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_details"))}</button>
            ${canChangeBinaryVisibility
              ? dev.has_public_binary
                ? `<button class="btn-hide" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_hide"))}</button>`
                : `<button class="btn-republish" data-id="${escapeHtml(dev.device_id)}">${escapeHtml(t(this.hass, "btn_republish"))}</button>`
              : ""}
          </div>
        </div>
      </div>
    `;
  }

  _remainingTime(expiresAt) {
    const seconds = Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000));
    if (!seconds) return t(this.hass, "expiry_pending");
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return hours ? `${hours}h ${minutes}m ${t(this.hass, "time_remaining")}` : `${minutes}m ${t(this.hass, "time_remaining")}`;
  }
}

definePanelElement("esphome-ota-manager", EsphomeOtaManager);
