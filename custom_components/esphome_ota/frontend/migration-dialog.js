/**
 * Migration modal dialog for importing legacy ESPHome OTA Publisher data.
 */

import { t } from "./i18n.js";

const css = `
:host {
  display: block;
}
.backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.modal {
  background: var(--card-background-color, #ffffff);
  color: var(--primary-text-color, #1f2937);
  width: 100%;
  max-width: 600px;
  max-height: 85vh;
  border-radius: 14px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--divider-color, #e5e7eb);
}
.header {
  padding: 16px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--divider-color, #e5e7eb);
}
.header h2 {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 600;
}
.body {
  padding: 20px;
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.help-text {
  font-size: 0.9rem;
  color: var(--secondary-text-color, #4b5563);
  line-height: 1.5;
  margin: 0;
}
.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.stat-card {
  padding: 14px;
  background: var(--secondary-background-color, #f8fafc);
  border: 1px solid var(--divider-color, #e2e8f0);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-label {
  font-size: 0.78rem;
  color: var(--secondary-text-color, #64748b);
  text-transform: uppercase;
  font-weight: 600;
  letter-spacing: 0.05em;
}
.stat-value {
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--primary-text-color, #1e293b);
}
.device-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 120px;
  overflow-y: auto;
  padding: 8px 10px;
  background: var(--secondary-background-color, #f1f5f9);
  border-radius: 8px;
  font-size: 0.8rem;
}
.device-tag {
  background: #ffffff;
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid #cbd5e1;
  font-family: monospace;
}
.status-box {
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 0.88rem;
  line-height: 1.4;
}
.status-box.success {
  background: #dcfce7;
  color: #166534;
  border: 1px solid #86efac;
}
.status-box.info {
  background: #eff6ff;
  color: #1e40af;
  border: 1px solid #bfdbfe;
}
.status-box.error {
  background: #fef2f2;
  color: #991b1b;
  border: 1px solid #fecaca;
}
.footer {
  padding: 14px 20px;
  border-top: 1px solid var(--divider-color, #e5e7eb);
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  background: var(--secondary-background-color, #fafafa);
}
button {
  padding: 8px 16px;
  font-size: 0.875rem;
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
button.primary:hover:not(:disabled) {
  opacity: 0.92;
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.btn-close {
  background: none;
  border: none;
  font-size: 1.25rem;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
}
.btn-close:hover {
  background: var(--secondary-background-color, #f3f4f6);
}
`;

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

class EsphomeOtaMigrationDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.isOpen = false;
    this.loading = false;
    this.executing = false;
    this.preview = null;
    this.result = null;
    this.error = null;
  }

  async open(hass) {
    this._hass = hass;
    this.isOpen = true;
    this.loading = true;
    this.executing = false;
    this.result = null;
    this.error = null;
    this.render();

    try {
      this.preview = await this._hass.callWS({ type: "esphome_ota/migrate_preview" });
    } catch (err) {
      console.error("Migration preview error:", err);
      this.preview = null;
      this.error = err.message || String(err);
    } finally {
      this.loading = false;
      this.render();
    }
  }

  close() {
    this.isOpen = false;
    this.render();
  }

  async executeMigration() {
    if (this.executing || !this._hass) return;
    this.executing = true;
    this.error = null;
    this.render();

    try {
      const res = await this._hass.callWS({ type: "esphome_ota/migrate_execute" });
      this.result = res;
      this.dispatchEvent(new CustomEvent("migration-completed", { detail: res, bubbles: true, composed: true }));
    } catch (err) {
      console.error("Migration execution failed:", err);
      this.error = err.message || String(err);
    } finally {
      this.executing = false;
      this.render();
    }
  }

  render() {
    if (!this.isOpen) {
      this.shadowRoot.innerHTML = "";
      return;
    }

    const title = t(this._hass, "migration_dialog_title");
    const help = t(this._hass, "migration_dialog_help");
    const closeTxt = t(this._hass, "close");

    let bodyContent = "";

    const errorBox = this.error
      ? `<div class="status-box error"><strong>${escapeHtml(t(this._hass, "migration_error"))}</strong><div style="margin-top: 6px;">${escapeHtml(this.error)}</div></div>`
      : "";

    if (this.loading) {
      bodyContent = `
        <div style="text-align: center; padding: 36px 0; color: var(--secondary-text-color, #64748b);">
          ${escapeHtml(t(this._hass, "stage_preparing"))}...
        </div>
      `;
    } else if (this.result) {
      const devCount = this.result.migrated_devices?.length || 0;
      const artCount = this.result.migrated_artifacts?.length || 0;
      bodyContent = `
        <div class="status-box success">
          <strong>${escapeHtml(t(this._hass, "migration_success"))}</strong>
          <div style="margin-top: 6px;">
            ${escapeHtml(t(this._hass, "migration_devices_found"))}: <strong>${devCount}</strong> • 
            ${escapeHtml(t(this._hass, "migration_binaries_found"))}: <strong>${artCount}</strong>
          </div>
        </div>
      `;
    } else if (this.preview) {
      const p = this.preview;
      const hasData = p.has_legacy_registry && p.device_count > 0;

      let statusMsg = "";
      if (p.already_migrated) {
        statusMsg = `
          <div class="status-box info">
            ✓ ${escapeHtml(t(this._hass, "migration_already_done"))}${p.migrated_at ? ` (${escapeHtml(new Date(p.migrated_at).toLocaleString())})` : ""}
          </div>
        `;
      }

      if (!hasData) {
        bodyContent = `
          <p class="help-text">${escapeHtml(help)}</p>
          ${statusMsg}
          ${errorBox}
          <div style="text-align: center; padding: 24px; color: var(--secondary-text-color, #64748b); background: var(--secondary-background-color, #f8fafc); border-radius: 8px;">
            ${escapeHtml(t(this._hass, "migration_no_data"))}
          </div>
        `;
      } else {
        const deviceList = (p.devices || []).map((d) => `<span class="device-tag">${escapeHtml(d)}</span>`).join("");
        bodyContent = `
          <p class="help-text">${escapeHtml(help)}</p>
          ${statusMsg}
          ${errorBox}
          <div class="stats-grid">
            <div class="stat-card">
              <span class="stat-label">${escapeHtml(t(this._hass, "migration_devices_found"))}</span>
              <span class="stat-value">${p.device_count}</span>
            </div>
            <div class="stat-card">
              <span class="stat-label">${escapeHtml(t(this._hass, "migration_binaries_found"))}</span>
              <span class="stat-value">${p.binary_count}</span>
            </div>
          </div>
          ${deviceList ? `<div><div class="stat-label" style="margin-bottom: 6px;">${escapeHtml(t(this._hass, "migration_device_list"))}</div><div class="device-tags">${deviceList}</div></div>` : ""}
        `;
      }
    } else if (this.error) {
      bodyContent = errorBox;
    }

    const canMigrate = this.preview && this.preview.has_legacy_registry && this.preview.device_count > 0 && !this.result;
    const startBtnText = this.preview?.already_migrated ? t(this._hass, "migration_reimport_btn") : t(this._hass, "migration_start_btn");

    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <div class="backdrop" id="backdrop">
        <div class="modal">
          <div class="header">
            <h2>${escapeHtml(title)}</h2>
            <button class="btn-close" id="btn-close">✕</button>
          </div>
          <div class="body">
            ${bodyContent}
          </div>
          <div class="footer">
            <button id="btn-cancel">${escapeHtml(closeTxt)}</button>
            ${canMigrate ? `<button class="primary" id="btn-start" ${this.executing ? "disabled" : ""}>${escapeHtml(this.executing ? t(this._hass, "migration_importing") + "..." : startBtnText)}</button>` : ""}
          </div>
        </div>
      </div>
    `;

    this.shadowRoot.getElementById("backdrop")?.addEventListener("click", (e) => {
      if (e.target.id === "backdrop") this.close();
    });
    this.shadowRoot.getElementById("btn-close")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("btn-cancel")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("btn-start")?.addEventListener("click", () => this.executeMigration());
  }
}

customElements.define("esphome-ota-migration-dialog", EsphomeOtaMigrationDialog);
