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
  width: 100%;
  container-type: inline-size;
  container-name: manager;
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
  min-height: var(--header-height, 56px);
  position: sticky;
  top: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 6px 20px;
  box-sizing: border-box;
  background: var(--card-background-color, #ffffff);
  border-bottom: 1px solid var(--divider-color, #e2e8f0);
  z-index: 10;
}
.header-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1 1 auto;
  min-width: max-content;
}
h1 {
  margin: 0;
  flex: none;
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
.device-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.card {
  --row-accent: var(--divider-color, #cbd5e1);
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-areas: "select head" "select bottom";
  align-items: center;
  column-gap: 14px;
  row-gap: 8px;
  background: var(--card-background-color, #ffffff);
  border: 1px solid var(--divider-color, #e2e8f0);
  border-left: 3px solid var(--row-accent);
  border-radius: 10px;
  padding: 10px 14px 10px 12px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: box-shadow 0.15s ease;
}
.card:hover {
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}
.card.row-initial { --row-accent: var(--warning-color, #d97706); }
.card.row-update { --row-accent: var(--success-color, #16a34a); }
.card.row-building { --row-accent: var(--info-color, #0284c7); }
.card.row-failed { --row-accent: var(--error-color, #dc2626); }
label.card-select-wrap {
  grid-area: select;
  display: flex;
  cursor: pointer;
  align-items: center;
  justify-content: center;
}
.card-select {
  width: 18px;
  height: 18px;
  margin: 0;
  cursor: pointer;
}
.card-head {
  grid-area: head;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 4px 16px;
  min-width: 0;
}
.card-bottom {
  grid-area: bottom;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
  min-width: 0;
}
.card-meta {
  flex: 1 1 16rem;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.card-main {
  flex: 1 1 14rem;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.card-title-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px 8px;
  min-width: 0;
}
.card-title {
  font-size: 0.98rem;
  font-weight: 600;
  margin: 0;
  flex: 0 1 auto;
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}
.card-sub {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  font-size: 0.78rem;
  color: var(--secondary-text-color, #64748b);
  min-width: 0;
}
.card-sub-text {
  min-width: 0;
  overflow-wrap: anywhere;
}
.card-sub .btn-log-link {
  flex: none;
  appearance: none;
  background: none;
  border: 0;
  padding: 4px 2px;
  margin: -4px -2px;
  min-height: 24px;
  box-sizing: border-box;
  height: auto;
  font: inherit;
  color: var(--error-color, #b91c1c);
  text-decoration: underline;
  cursor: pointer;
}
.card-sub .btn-log-link:hover { background: none; }
.card-sub .btn-log-link:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
.badge {
  flex: 0 0 auto;
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.72rem;
  font-weight: 500;
  white-space: nowrap;
}
.badge-unmanaged { background: var(--secondary-background-color, #f1f5f9); color: var(--secondary-text-color, #475569); }
.badge-initial { background: var(--warning-background-color, color-mix(in srgb, var(--warning-color, #d97706) 10%, transparent)); color: var(--warning-color, #92400e); }
.badge-update { background: var(--success-background-color, color-mix(in srgb, var(--success-color, #16a34a) 10%, transparent)); color: var(--success-color, #166534); }
.badge-installed { background: var(--info-background-color, color-mix(in srgb, var(--info-color, #0284c7) 10%, transparent)); color: var(--info-color, #0369a1); }
.badge-building { background: var(--info-background-color, color-mix(in srgb, var(--info-color, #0284c7) 10%, transparent)); color: var(--info-color, #075985); }
.badge-failed { background: var(--error-background-color, color-mix(in srgb, var(--error-color, #dc2626) 10%, transparent)); color: var(--error-color, #991b1b); }

.card-versions {
  flex: 0 1 auto;
  margin-left: auto;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 4px 8px;
  min-width: 0;
  font-size: 0.82rem;
  color: var(--secondary-text-color, #64748b);
}
.ver-flow {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}
.ver-installed,
.ver-published {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.card-dates {
  color: var(--secondary-text-color, #64748b);
  font-size: 0.68rem;
  overflow-wrap: anywhere;
}
.ver-installed { color: var(--secondary-text-color, #64748b); }
.ver-published { color: var(--primary-text-color, #1e293b); }
.ver-arrow { opacity: 0.6; }
.card.row-update .ver-arrow { opacity: 1; color: var(--success-color, #16a34a); }
.card.row-update .ver-published { color: var(--success-color, #166534); }
.initial-install-guidance {
  overflow-wrap: anywhere;
  color: var(--secondary-text-color, #64748b);
  font-size: 0.76rem;
  line-height: 1.4;
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
  white-space: nowrap;
}
.binary-active {
  background: var(--success-background-color, color-mix(in srgb, var(--success-color, #16a34a) 10%, transparent));
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
  flex: 0 0 auto;
  margin-left: auto;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-items: center;
  gap: 6px;
}
/* Fixed slot order: [visibility] [details] [primary]; primary is always rightmost. */
.card-actions .slot-aux { order: 1; }
.card-actions .slot-details { order: 2; }
.card-actions .slot-primary { order: 3; }
/* Fixed widths so every row's slots land on the same x coordinates. */
.card-actions .slot-primary { min-width: 8.5rem; }
.card-actions .slot-details,
.card-actions .slot-aux { min-width: 5.5rem; }
.card-actions button {
  flex: none;
  min-width: 5rem;
  height: 34px;
  padding: 0 14px;
  font-size: 0.8rem;
  justify-content: center;
  white-space: nowrap;
  box-sizing: border-box;
  background: transparent;
  color: var(--primary-text-color, #1e293b);
  border-color: var(--divider-color, #cbd5e1);
}
.card-actions button:hover {
  background: var(--secondary-background-color, #f1f5f9);
}
.card-actions .btn-details,
.card-actions .btn-hide,
.card-actions .btn-republish,
.card-actions .btn-view-logs {
  color: var(--secondary-text-color, #64748b);
}
/* Only rows that really need action get a tinted outline; never a filled button. */
.card.row-update .card-actions .btn-build,
.card.row-initial .card-actions .btn-build {
  color: var(--primary-color, #0369a1);
  border-color: var(--primary-color, #0369a1);
}
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--secondary-text-color, #64748b);
}
@container manager (max-width: 650px) {
  header {
    height: auto;
    min-height: 0;
    padding: 10px 12px;
    gap: 8px;
    flex-wrap: wrap;
  }
  .header-title-wrap { flex: 1 1 calc(100% - 52px); min-width: 0; }
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
  .card {
    column-gap: 10px;
    padding: 10px 12px 12px 10px;
  }
  .card-select-wrap { min-width: 40px; min-height: 40px; align-self: start; }
  .card-versions { margin-left: 0; justify-content: flex-start; }
  .card-actions {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.3fr);
    width: 100%;
  }
  .card-actions button {
    flex: none;
    min-width: 0;
    min-height: 40px;
    height: auto;
    padding: 4px 6px;
    white-space: normal;
    line-height: 1.2;
    text-align: center;
  }
  .card-actions .slot-aux,
  .card-actions .slot-details,
  .card-actions .slot-primary { min-width: 0; }
  .card-actions .slot-aux { grid-column: 1; grid-row: 1; }
  .card-actions .slot-details { grid-column: 2; grid-row: 1; }
  .card-actions .slot-primary { grid-column: 3; grid-row: 1; }
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
    this.expiryInterval = setInterval(() => this._updateExpiryCountdowns(), 60_000);
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
    clearInterval(this.expiryInterval);
    this.expiryInterval = null;
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
      this._pruneSelection();
      this._renderDeviceList();
      this._renderSelectionSummary();
    } else if (event === "installation_verified" && data) {
      if (data.devices) {
        this.devices = data.devices;
        this.devicesLoaded = true;
        this._pruneSelection();
      }
      this._renderDeviceList();
      this._renderSelectionSummary();
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

  _pruneSelection() {
    const known = new Set((this.devices || []).map((dev) => dev.device_id));
    for (const id of [...this.selectedDevices]) {
      if (!known.has(id)) this.selectedDevices.delete(id);
    }
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
    devDialog?.addEventListener("device-updated", async (e) => {
      const removedId = e.detail?.device_id;
      if (removedId) {
        this.selectedDevices.delete(removedId);
        this._renderDeviceList();
        this._renderSelectionSummary();
      }
      await this.refresh();
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
    this._pruneSelection();
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
      <div class="device-list" role="list">
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
        const id = e.currentTarget.getAttribute("data-id");
        if (e.currentTarget.checked) this.selectedDevices.add(id);
        else this.selectedDevices.delete(id);
        this._renderSelectionSummary();
      });
    });

    this.shadowRoot.querySelectorAll(".btn-prepare").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.openDeviceDialog(dev, "diff");
      });
    });

    this.shadowRoot.querySelectorAll(".btn-build").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.buildDevice(dev);
      });
    });

    this.shadowRoot.querySelectorAll(".btn-progress").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const job = this._getActiveJob(e.currentTarget.getAttribute("data-id"));
        if (job) this.openJobDialog(job);
      });
    });

    this.shadowRoot.querySelectorAll(".btn-view-logs").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const jobId = e.currentTarget.getAttribute("data-job-id");
        const job = this.jobs.find((j) => j.job_id === jobId);
        if (job) this.openJobDialog(job);
      });
    });

    this.shadowRoot.querySelectorAll(".btn-hide").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.hideBinary(dev);
      });
    });

    this.shadowRoot.querySelectorAll(".btn-republish").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.republishBinary(dev);
      });
    });

    this.shadowRoot.querySelectorAll(".btn-details").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.getAttribute("data-id");
        const dev = this.devices.find((d) => d.device_id === id);
        if (dev) this.openDeviceDialog(dev, "info");
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

  renderCard(dev) {
    const activeJob = this._getActiveJob(dev.device_id);
    const latestJob = this._getLatestJob(dev.device_id);
    const { badgeKey, badgeClass } = this._getDeviceBadge(dev);

    const badgeText = t(this.hass, badgeKey);
    const isSelected = this.selectedDevices.has(dev.device_id);
    const needsInitialInstall = dev.status !== "unmanaged" && (dev.status === "needs_initial_install"
      || (!dev.has_http_ota && !dev.last_installed_version));
    const canChangeBinaryVisibility = !!dev.last_published_version && !activeJob;
    const expiryLabel = dev.has_public_binary
      ? (dev.expires_at
        ? `${new Date(dev.expires_at).toLocaleString()} · <span class="expiry-remaining" data-expiry="${escapeHtml(dev.expires_at)}">${escapeHtml(this._remainingTime(dev.expires_at))}</span>`
        : escapeHtml(t(this.hass, "expiry_disabled")))
      : "";
    const name = dev.friendly_name || dev.name || "";
    const id = escapeHtml(dev.device_id);
    const rowClass = {
      "badge-initial": "row-initial",
      "badge-update": "row-update",
      "badge-installed": "row-installed",
      "badge-building": "row-building",
      "badge-failed": "row-failed",
    }[badgeClass] || "";
    const label = (key) => escapeHtml(t(this.hass, key));
    const aria = (key) => `${escapeHtml(t(this.hass, key))}: ${escapeHtml(name)}`;

    const btn = (cls, slot, extra, key) =>
      `<button class="${cls} ${slot}" ${extra} aria-label="${aria(key)}">${label(key)}</button>`;
    const failed = latestJob && (latestJob.stage === "failed" || latestJob.stage === "cancelled");
    let primaryButton = "";
    let auxButton = "";
    let logLink = "";
    if (activeJob) {
      primaryButton = btn("btn-progress", "slot-primary", `data-id="${id}"`, "btn_view_logs");
    } else if (failed) {
      primaryButton = btn("btn-build", "slot-primary", `data-id="${id}"`, "btn_build");
      logLink = `<button type="button" class="btn-view-logs btn-log-link" data-job-id="${escapeHtml(latestJob.job_id)}" aria-label="${aria("btn_logs_link")}">${label("btn_logs_link")}</button>`;
    } else if (dev.status === "unmanaged") {
      primaryButton = btn("btn-prepare", "slot-primary", `data-id="${id}"`, "btn_prepare");
    } else {
      primaryButton = btn("btn-build", "slot-primary", `data-id="${id}"`, "btn_build");
    }
    if (canChangeBinaryVisibility) {
      auxButton = dev.has_public_binary
        ? btn("btn-hide", "slot-aux", `data-id="${id}"`, "btn_hide")
        : btn("btn-republish", "slot-aux", `data-id="${id}"`, "btn_republish");
    }

    const visibilityPill = dev.last_published_version
      ? (dev.has_public_binary
        ? `<span class="binary-status binary-active"><span class="status-dot-sm ok"></span> ${label("status_active")}</span>`
        : `<span class="binary-status binary-hidden"><span class="status-dot-sm neutral"></span> ${label("status_hidden")}</span>`)
      : "";

    const dateParts = [];
    if (dev.last_installed_at) dateParts.push(`${label("installed_date")}: ${escapeHtml(this._formatDeviceDate(dev.last_installed_at))}`);
    if (dev.last_published_at) dateParts.push(`${label("published_date")}: ${escapeHtml(this._formatDeviceDate(dev.last_published_at))}`);
    if (expiryLabel) dateParts.push(`${label("publication_expiry")}: ${expiryLabel}`);
    const datesLine = dateParts.join(" · ");

    return `
      <div class="card ${rowClass}" role="listitem" data-id="${id}">
        <label class="card-select-wrap">
          <input type="checkbox" class="card-select" data-id="${id}" aria-label="${aria("select_device")}" ${isSelected ? "checked" : ""}>
        </label>
        <div class="card-head">
        <div class="card-main">
          <div class="card-title-line">
            <h3 class="card-title" title="${escapeHtml(name)}">${escapeHtml(name)}</h3>
            <span class="badge ${badgeClass}">${escapeHtml(badgeText)}</span>
          </div>
        </div>
        <div class="card-versions">
          <span class="ver-flow">
            <span class="sr-only">${label("installed_version")}: </span><span class="ver-installed">${escapeHtml(dev.last_installed_version || "—")}</span>
            <span class="ver-arrow" aria-hidden="true">→</span>
            <span class="sr-only">${label("published_version")}: </span><span class="ver-published">${escapeHtml(dev.last_published_version || "—")}</span>
          </span>
          ${visibilityPill}
        </div>
        </div>
        <div class="card-bottom">
        <div class="card-meta">
          <div class="card-sub"><span class="card-sub-text">${escapeHtml(dev.configuration)} • ${escapeHtml(dev.chip_family)}</span>${logLink}</div>
          ${datesLine ? `<div class="card-dates">${datesLine}</div>` : ""}
          ${needsInitialInstall ? `<div class="initial-install-guidance">${label("initial_install_card_help")}</div>` : ""}
        </div>
        <div class="card-actions">
          ${auxButton}
          ${btn("btn-details", "slot-details", `data-id="${id}"`, "btn_details")}
          ${primaryButton}
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

  _formatDeviceDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    const options = { year: "numeric", month: "short", day: "numeric" };
    const timeZone = this.hass?.config?.time_zone;
    if (timeZone) options.timeZone = timeZone;
    try {
      return new Intl.DateTimeFormat(this.hass?.locale?.language || "en", options).format(date);
    } catch (_err) {
      return date.toLocaleDateString();
    }
  }

  _updateExpiryCountdowns() {
    this.shadowRoot?.querySelectorAll(".expiry-remaining[data-expiry]").forEach((el) => {
      el.textContent = this._remainingTime(el.dataset.expiry);
    });
  }
}

definePanelElement("esphome-ota-manager", EsphomeOtaManager);
