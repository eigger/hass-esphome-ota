/**
 * Device details, YAML diff preview, and manual upload modal dialog.
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
  z-index: 998;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.modal {
  background: var(--card-background-color, #ffffff);
  color: var(--primary-text-color, #1f2937);
  width: 100%;
  max-width: 780px;
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
.tabs {
  display: flex;
  background: var(--secondary-background-color, #f9fafb);
  border-bottom: 1px solid var(--divider-color, #e5e7eb);
}
.tab {
  padding: 10px 18px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--secondary-text-color, #6b7280);
}
.tab.active {
  color: var(--primary-color, #0284c7);
  border-bottom-color: var(--primary-color, #0284c7);
  background: var(--card-background-color, #ffffff);
}
.body {
  padding: 18px 20px;
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.notice {
  padding: 12px 14px;
  border-radius: 8px;
  background: #fef3c7;
  color: #92400e;
  font-size: 0.85rem;
  line-height: 1.45;
  border: 1px solid #fde68a;
}
.diff-viewer {
  background: #0f172a;
  color: #f8fafc;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.8rem;
  line-height: 1.45;
  padding: 14px;
  border-radius: 8px;
  max-height: 380px;
  overflow-y: auto;
  white-space: pre;
}
.diff-add {
  color: #4ade80;
}
.diff-del {
  color: #f87171;
}
.info-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}
.info-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--divider-color, #e5e7eb);
}
.info-table td:first-child {
  font-weight: 600;
  color: var(--secondary-text-color, #6b7280);
  width: 35%;
}
.footer {
  padding: 14px 20px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  border-top: 1px solid var(--divider-color, #e5e7eb);
  background: var(--card-background-color, #ffffff);
}
button {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid var(--divider-color, #d1d5db);
  background: var(--card-background-color, #ffffff);
  color: var(--primary-text-color, #1f2937);
}
button.primary {
  background: var(--primary-color, #0284c7);
  color: #ffffff;
  border-color: var(--primary-color, #0284c7);
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

class EsphomeOtaDeviceDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.device = null;
    this.hass = null;
    this.isOpen = false;
    this.currentTab = "diff"; // "diff" | "info" | "upload"
    this.diffData = null;
    this.uploading = false;
    this.statusMessage = "";
  }

  async open(device, hass, tab = "diff") {
    this.device = device;
    this.hass = hass;
    this.isOpen = true;
    this.currentTab = tab;
    this.statusMessage = "";
    this.render();

    if (tab === "diff") {
      await this.loadDiff();
    }
  }

  close() {
    this.isOpen = false;
    this.render();
  }

  async loadDiff() {
    try {
      const res = await this.hass.callWS({
        type: "esphome_ota/prepare_ota",
        device_id: this.device.device_id,
      });
      this.diffData = res;
      this.render();
    } catch (err) {
      this.statusMessage = `Failed preparing diff: ${err.message || err}`;
      this.render();
    }
  }

  async applyDiff(andBuild = false) {
    if (!this.diffData) return;
    try {
      await this.hass.callWS({
        type: "esphome_ota/apply_ota",
        device_id: this.device.device_id,
        content: this.diffData.modified,
        expected: this.diffData.expected || this.diffData.original,
      });
      this.statusMessage = "Successfully applied OTA configuration to YAML!";
      if (andBuild) {
        this.dispatchEvent(new CustomEvent("start-build", { detail: { device: this.device } }));
        this.close();
      } else {
        this.render();
      }
    } catch (err) {
      this.statusMessage = `Apply error: ${err.message || err}`;
      this.render();
    }
  }

  async uploadFirmware(file) {
    if (!file) return;
    this.uploading = true;
    this.statusMessage = "Uploading and validating binary...";
    this.render();

    const formData = new FormData();
    formData.append("file", file);

    try {
      const token = this.hass.auth?.accessToken || "";
      const resp = await fetch(`/api/esphome_ota/upload/${this.device.device_id}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      });
      const data = await resp.json();
      if (resp.ok) {
        this.statusMessage = `Success! Published version ${data.version} (${data.size} bytes).`;
        this.dispatchEvent(new CustomEvent("device-updated"));
      } else {
        this.statusMessage = `Upload error: ${data.error || "Unknown error"}`;
      }
    } catch (err) {
      this.statusMessage = `Upload failed: ${err.message || err}`;
    } finally {
      this.uploading = false;
      this.render();
    }
  }

  render() {
    if (!this.isOpen || !this.device) {
      this.shadowRoot.innerHTML = "";
      return;
    }

    let tabContent = "";
    if (this.currentTab === "diff") {
      const rawDiff = this.diffData?.diff || "Loading configuration diff...";
      const diffFormatted = rawDiff
        .split("\n")
        .map((l) => {
          const escaped = escapeHtml(l);
          if (l.startsWith("+")) return `<span class="diff-add">${escaped}</span>`;
          if (l.startsWith("-")) return `<span class="diff-del">${escaped}</span>`;
          return escaped;
        })
        .join("\n");

      tabContent = `
        <div class="notice">
          <strong>${escapeHtml(t(this.hass, "yaml_diff_title"))}:</strong> ${escapeHtml(t(this.hass, "yaml_diff_help"))}
        </div>
        <div class="diff-viewer">${diffFormatted}</div>
      `;
    } else if (this.currentTab === "info") {
      const needsInitial = !this.device.has_http_ota && !this.device.last_installed_version;
      tabContent = `
        ${needsInitial ? `
          <div class="notice">
            <strong>${escapeHtml(t(this.hass, "initial_install_title"))}</strong><br>
            ${escapeHtml(t(this.hass, "initial_install_help"))}
          </div>
        ` : ""}
        <table class="info-table">
          <tr><td>Name</td><td>${escapeHtml(this.device.name)}</td></tr>
          <tr><td>Configuration</td><td>${escapeHtml(this.device.configuration)}</td></tr>
          <tr><td>Chip Family</td><td>${escapeHtml(this.device.chip_family)}</td></tr>
          <tr><td>Token</td><td>${escapeHtml(this.device.token || "None (Legacy)")}</td></tr>
          <tr><td>Public Slug</td><td>${escapeHtml(this.device.slug)}</td></tr>
          <tr><td>Installed Version</td><td>${escapeHtml(this.device.last_installed_version || "Not detected")}</td></tr>
          <tr><td>Published Version</td><td>${escapeHtml(this.device.last_published_version || "None")}</td></tr>
        </table>
      `;
    } else if (this.currentTab === "upload") {
      tabContent = `
        <div class="notice">
          <strong>${escapeHtml(t(this.hass, "upload_title"))}</strong><br>
          ${escapeHtml(t(this.hass, "upload_help"))}
        </div>
        <input type="file" id="firmware-file" accept=".bin" style="margin: 12px 0;">
      `;
    }

    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <div class="backdrop" id="backdrop">
        <div class="modal">
          <div class="header">
            <h2>${escapeHtml(this.device.friendly_name || this.device.name)}</h2>
            <button id="close-x">✕</button>
          </div>
          <div class="tabs">
            <button class="tab ${this.currentTab === "diff" ? "active" : ""}" data-tab="diff">${escapeHtml(t(this.hass, "btn_prepare"))}</button>
            <button class="tab ${this.currentTab === "info" ? "active" : ""}" data-tab="info">Device Info</button>
            <button class="tab ${this.currentTab === "upload" ? "active" : ""}" data-tab="upload">Manual Upload</button>
          </div>
          <div class="body">
            ${this.statusMessage ? `<div class="notice">${escapeHtml(this.statusMessage)}</div>` : ""}
            ${tabContent}
          </div>
          <div class="footer">
            ${this.currentTab === "diff" ? `
              <button id="btn-apply">${escapeHtml(t(this.hass, "apply_changes"))}</button>
              <button class="primary" id="btn-apply-build">${escapeHtml(t(this.hass, "apply_and_build"))}</button>
            ` : ""}
            ${this.currentTab === "upload" ? `
              <button class="primary" id="btn-upload" ${this.uploading ? "disabled" : ""}>${escapeHtml(t(this.hass, "upload_btn"))}</button>
            ` : ""}
            <button id="btn-close">${escapeHtml(t(this.hass, "close"))}</button>
          </div>
        </div>
      </div>
    `;

    this.shadowRoot.getElementById("close-x")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("btn-close")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("backdrop")?.addEventListener("click", (e) => {
      if (e.target.id === "backdrop") this.close();
    });

    this.shadowRoot.querySelectorAll(".tab").forEach((tabBtn) => {
      tabBtn.addEventListener("click", (e) => {
        this.currentTab = e.target.getAttribute("data-tab");
        this.statusMessage = "";
        this.render();
        if (this.currentTab === "diff") this.loadDiff();
      });
    });

    this.shadowRoot.getElementById("btn-apply")?.addEventListener("click", () => this.applyDiff(false));
    this.shadowRoot.getElementById("btn-apply-build")?.addEventListener("click", () => this.applyDiff(true));
    this.shadowRoot.getElementById("btn-upload")?.addEventListener("click", () => {
      const fileInput = this.shadowRoot.getElementById("firmware-file");
      if (fileInput && fileInput.files && fileInput.files[0]) {
        this.uploadFirmware(fileInput.files[0]);
      }
    });
  }
}

customElements.define("esphome-ota-device-dialog", EsphomeOtaDeviceDialog);
