/**
 * Device details, YAML diff preview, and manual upload modal dialog.
 */

import { t } from "./i18n.js";
import {
  bindModalAccessibility,
  captureModalFocus,
  definePanelElement,
  rememberModalFocus,
  restoreModalFocus,
} from "./elements.js";

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
  height: min(580px, 85vh);
  max-height: 85vh;
  min-height: min(480px, 85vh);
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
.tabs-container {
  padding: 12px 20px 10px;
  background: var(--card-background-color, #ffffff);
  border-bottom: 1px solid var(--divider-color, #e5e7eb);
  display: flex;
}
.tabs {
  display: inline-flex;
  background: var(--secondary-background-color, #f1f5f9);
  padding: 4px;
  border-radius: 10px;
  gap: 3px;
  border: 1px solid rgba(0, 0, 0, 0.04);
}
.tab {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 15px;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  background: transparent;
  border: none;
  color: var(--secondary-text-color, #64748b);
  border-radius: 7px;
  transition: all 0.16s ease-in-out;
  user-select: none;
  line-height: 1;
}
.tab:hover:not(.active) {
  color: var(--primary-text-color, #0f172a);
  background: rgba(255, 255, 255, 0.65);
}
.tab.active {
  color: var(--primary-color, #0284c7);
  font-weight: 600;
  background: var(--card-background-color, #ffffff);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04);
}
.tab svg {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  stroke: currentColor;
}
.body {
  padding: 18px 20px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.notice {
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--warning-background-color, #fef3c7);
  color: var(--warning-color, #92400e);
  font-size: 0.85rem;
  line-height: 1.45;
  border: 1px solid var(--warning-color, #fde68a);
}
.notice.success {
  background: var(--success-background-color, #dcfce7);
  color: var(--success-color, #166534);
  border-color: var(--success-color, #86efac);
}
.notice.error {
  background: var(--error-background-color, #fee2e2);
  color: var(--error-color, #991b1b);
  border-color: var(--error-color, #fca5a5);
}
.diff-viewer {
  background: #0f172a;
  color: #f8fafc;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.8rem;
  line-height: 1.45;
  padding: 14px;
  border-radius: 8px;
  flex: 1;
  min-height: 0;
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
.selected-file {
  color: var(--secondary-text-color, #64748b);
  font-size: 0.82rem;
  overflow-wrap: anywhere;
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
  background: #dcfce7;
  color: #166534;
}
.binary-hidden {
  background: #f1f5f9;
  color: #64748b;
}
.status-dot-sm {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}
.status-dot-sm.ok { background: #16a34a; }
.status-dot-sm.neutral { background: #94a3b8; }
.footer {
  padding: 14px 20px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  border-top: 1px solid var(--divider-color, #e5e7eb);
  background: var(--card-background-color, #ffffff);
}
#close-x {
  background: transparent;
  border: none;
  font-size: 1.15rem;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 6px;
  color: var(--secondary-text-color, #6b7280);
  transition: all 0.15s ease-in-out;
}
#close-x:hover {
  background: var(--secondary-background-color, #f1f5f9);
  color: var(--primary-text-color, #1f2937);
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
  transition: all 0.15s ease-in-out;
}
button:hover {
  background: var(--secondary-background-color, #f1f5f9);
  border-color: var(--divider-color, #9ca3af);
}
button.primary {
  background: var(--primary-color, #0284c7);
  color: #ffffff;
  border-color: var(--primary-color, #0284c7);
}
button.primary:hover {
  opacity: 0.92;
  border-color: var(--primary-color, #0284c7);
}
button.danger {
  background: #ffffff;
  color: #b91c1c;
  border-color: #fca5a5;
}
button.danger:hover {
  background: #fef2f2;
  border-color: #f87171;
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  pointer-events: none;
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
    this.artifact = null;
    this.defaultCleanupHours = 12;
    this.hass = null;
    this.isOpen = false;
    this.currentTab = "diff"; // "diff" | "info" | "upload"
    this.diffData = null;
    this._diffDeviceId = null;
    this._diffRequest = 0;
    this._applyGeneration = 0;
    this._deviceRequest = 0;
    this.uploading = false;
    this.applying = false;
    this.selectedFirmwareFile = null;
    this.cleanupMode = "default";
    this.cleanupHours = 12;
    this.autoHideAfterInstall = true;
    this.statusMessage = "";
    this.statusType = "info";
  }

  connectedCallback() {
    this.expiryInterval = setInterval(() => this._updateExpiryCountdowns(), 60_000);
  }

  disconnectedCallback() {
    clearInterval(this.expiryInterval);
    this.expiryInterval = null;
  }

  async open(device, hass, tab = "diff") {
    if (!this.isOpen) rememberModalFocus(this);
    const changedDevice = this.device?.device_id !== device?.device_id;
    if (changedDevice) {
      this._deviceRequest++;
      this.artifact = null;
      this._applyGeneration++;
      this.uploading = false;
      this.applying = false;
      this.selectedFirmwareFile = null;
      this.cleanupMode = "default";
      this.cleanupHours = 12;
      this.autoHideAfterInstall = device?.auto_hide !== false;
    }
    this.device = device;
    this.hass = hass;
    this.isOpen = true;
    this.currentTab = tab;
    this.statusMessage = "";
    this.statusType = "info";
    if (changedDevice || tab === "diff") {
      this.diffData = null;
      this._diffDeviceId = null;
      this._diffRequest++;
    }
    this.render();

    if (tab === "info" && device?.last_published_version) this.loadPublicationDetails();

    if (tab === "diff") {
      await this.loadDiff();
    }
  }

  async loadPublicationDetails() {
    const deviceId = this.device?.device_id;
    if (!deviceId || !this.hass || !this.device?.last_published_version) return;
    const request = this._deviceRequest;
    try {
      const detail = await this.hass.callWS({
        type: "esphome_ota/device_detail",
        device_id: deviceId,
      });
      if (!this.isOpen || request !== this._deviceRequest || this.device?.device_id !== deviceId) return;
      this.artifact = detail?.artifact || null;
      this.defaultCleanupHours = Number(detail?.default_cleanup_hours ?? 12);
      this.device.expires_at = this.device.has_public_binary
        ? (this.artifact?.expires_at || null)
        : null;
      this.render();
    } catch (_err) {
      // The device summary still provides a useful fallback if detail lookup fails.
    }
  }

  close() {
    this.isOpen = false;
    this.uploading = false;
    this.applying = false;
    this._applyGeneration++;
    this._diffRequest++;
    this._deviceRequest++;
    this.render();
    restoreModalFocus(this);
  }

  async loadDiff() {
    const deviceId = this.device?.device_id;
    if (!deviceId || !this.hass) return;
    const request = ++this._diffRequest;
    this.diffData = null;
    this._diffDeviceId = null;
    this.statusMessage = "";
    this.render();
    try {
      const res = await this.hass.callWS({
        type: "esphome_ota/prepare_ota",
        device_id: deviceId,
      });
      if (
        !this.isOpen ||
        request !== this._diffRequest ||
        this.device?.device_id !== deviceId
      ) return;
      this.diffData = res;
      this._diffDeviceId = deviceId;
      this.render();
    } catch (err) {
      if (
        !this.isOpen ||
        request !== this._diffRequest ||
        this.device?.device_id !== deviceId
      ) return;
      this.statusMessage = `${t(this.hass, "prepare_error")}: ${err.message || err}`;
      this.statusType = "error";
      this.render();
    }
  }

  async applyDiff(andBuild = false) {
    if (this.applying || !this.diffData || this._diffDeviceId !== this.device?.device_id) return;
    const targetDevice = this.device;
    const targetDeviceId = targetDevice.device_id;
    const diffData = this.diffData;
    const operation = ++this._applyGeneration;
    this.applying = true;
    this.statusMessage = t(this.hass, "applying_changes");
    this.statusType = "info";
    this.render();
    try {
      await this.hass.callWS({
        type: "esphome_ota/apply_ota",
        device_id: targetDeviceId,
        content: diffData.modified,
        expected: diffData.expected || diffData.original,
      });
      const stillShowingTarget =
        this.isOpen &&
        this.device?.device_id === targetDeviceId &&
        this._applyGeneration === operation;
      if (andBuild && stillShowingTarget) {
        const returnFocus = this._modalReturnFocus;
        this.close();
        this.dispatchEvent(
          new CustomEvent("start-build", {
            detail: { device: targetDevice, returnFocus },
          }),
        );
      } else if (stillShowingTarget) {
        this.statusMessage = t(this.hass, "apply_success");
        this.statusType = "success";
        this.render();
      }
    } catch (err) {
      if (
        this.isOpen &&
        this.device?.device_id === targetDeviceId &&
        this._applyGeneration === operation
      ) {
        this.statusMessage = `${t(this.hass, "apply_error")}: ${err.message || err}`;
        this.statusType = "error";
        this.render();
      }
    } finally {
      if (
        this.isOpen &&
        this.device?.device_id === targetDeviceId &&
        this._applyGeneration === operation
      ) {
        this.applying = false;
        this.render();
      }
    }
  }

  async uploadFirmware(file) {
    if (this.uploading || !file || !this.device) return;
    if (this.cleanupMode === "custom") {
      const hours = Number(this.cleanupHours);
      if (!Number.isInteger(hours) || hours < 1 || hours > 168) {
        this.statusMessage = t(this.hass, "cleanup_hours_invalid");
        this.statusType = "error";
        this.render();
        return;
      }
    }
    const targetDeviceId = this.device.device_id;
    const request = this._deviceRequest;
    const stillShowingTarget = () => this.isOpen
      && this.device?.device_id === targetDeviceId
      && this._deviceRequest === request;
    this.uploading = true;
    this.selectedFirmwareFile = file;
    this.statusMessage = t(this.hass, "uploading_firmware");
    this.statusType = "info";
    this.render();

    const formData = new FormData();
    formData.append("file", file);
    if (this.cleanupMode === "none") formData.append("cleanup_hours", "0");
    else if (this.cleanupMode === "custom") formData.append("cleanup_hours", String(this.cleanupHours));
    formData.append("auto_hide", String(!!this.autoHideAfterInstall));

    try {
      const token = this.hass.auth?.accessToken || "";
      const resp = await fetch(`/api/esphome_ota/upload/${targetDeviceId}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      });
      const data = await resp.json();
      if (!stillShowingTarget()) return;
      if (resp.ok) {
        this.device.has_public_binary = true;
        this.statusMessage = `${t(this.hass, "upload_success")} ${data.version} (${data.size} bytes).`;
        this.statusType = "success";
        this.dispatchEvent(new CustomEvent("device-updated"));
        this.loadPublicationDetails();
      } else {
        this.statusMessage = `${t(this.hass, "upload_error")}: ${data.error || t(this.hass, "unknown_error")}`;
        this.statusType = "error";
      }
    } catch (err) {
      if (stillShowingTarget()) {
        this.statusMessage = `${t(this.hass, "upload_error")}: ${err.message || err}`;
        this.statusType = "error";
      }
    } finally {
      if (stillShowingTarget()) {
        this.uploading = false;
        this.render();
      }
    }
  }

  async removeOta() {
    if (!this.device?.is_managed) return;
    const targetDeviceId = this.device.device_id;
    const request = this._deviceRequest;
    const stillShowingTarget = () => this.isOpen
      && this.device?.device_id === targetDeviceId
      && this._deviceRequest === request;
    const confirmMsg = t(this.hass, "remove_ota_confirm");
    if (!window.confirm(confirmMsg)) return;
    try {
      await this.hass.callWS({
        type: "esphome_ota/remove_ota",
        device_id: targetDeviceId,
      });
      if (stillShowingTarget()) {
        this.dispatchEvent(
          new CustomEvent("device-updated", { bubbles: true, composed: true }),
        );
        this.close();
      }
    } catch (err) {
      if (stillShowingTarget()) {
        this.statusMessage = `${t(this.hass, "remove_ota_error")}: ${err.message || err}`;
        this.statusType = "error";
        this.render();
      }
    }
  }

  async hideBinary() {
    if (!this.device) return;
    const targetDevice = this.device;
    const targetDeviceId = targetDevice.device_id;
    const request = this._deviceRequest;
    const stillShowingTarget = () => this.isOpen
      && this.device?.device_id === targetDeviceId
      && this._deviceRequest === request;
    try {
      await this.hass.callWS({
        type: "esphome_ota/deactivate",
        device_id: targetDeviceId,
      });
      if (!stillShowingTarget()) return;
      targetDevice.has_public_binary = false;
      this.statusMessage = t(this.hass, "hide_success");
      this.statusType = "success";
      this.dispatchEvent(new CustomEvent("device-updated", { bubbles: true, composed: true }));
      this.render();
      this.loadPublicationDetails();
    } catch (err) {
      if (stillShowingTarget()) {
        this.statusMessage = `${t(this.hass, "binary_action_error")}: ${err.message || err}`;
        this.statusType = "error";
        this.render();
      }
    }
  }

  async savePublicationPolicy() {
    if (!this.device) return;
    const targetDevice = this.device;
    const targetDeviceId = targetDevice.device_id;
    const request = this._deviceRequest;
    const hours = Number(this.shadowRoot.getElementById("cleanup-hours")?.value);
    if (!Number.isInteger(hours) || hours < 0 || hours > 168) {
      this.statusMessage = t(this.hass, "cleanup_hours_invalid");
      this.statusType = "error";
      this.render();
      return;
    }
    try {
      const autoHide = !!this.shadowRoot.getElementById("auto-hide-installed")?.checked;
      const saveDefault = !!this.shadowRoot.getElementById("save-policy-default")?.checked;
      const res = await this.hass.callWS({
        type: "esphome_ota/set_publication_policy",
        device_id: targetDeviceId,
        cleanup_hours: hours,
        auto_hide: autoHide,
        save_as_default: saveDefault,
      });
      if (!this.isOpen || request !== this._deviceRequest || this.device?.device_id !== targetDeviceId) return;
      targetDevice.expires_at = res.expires_at;
      if (this.artifact) {
        this.artifact.cleanup_hours = hours;
        this.artifact.expires_at = res.expires_at;
        this.artifact.auto_hide = autoHide;
      }
      if (saveDefault) {
        targetDevice.publication_cleanup_hours = hours;
        targetDevice.auto_hide = autoHide;
        this.defaultCleanupHours = hours;
      }
      this.statusMessage = t(this.hass, "publication_policy_saved");
      this.statusType = "success";
      this.dispatchEvent(new CustomEvent("device-updated", { bubbles: true, composed: true }));
      this.render();
      this.loadPublicationDetails();
    } catch (err) {
      this.statusMessage = `${t(this.hass, "publication_policy_error")}: ${err.message || err}`;
      this.statusType = "error";
      this.render();
    }
  }

  _remainingTime(expiresAt) {
    const seconds = Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000));
    if (!seconds) return t(this.hass, "expiry_pending");
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
  }

  _updateExpiryCountdowns() {
    this.shadowRoot?.querySelectorAll(".expiry-remaining[data-expiry]").forEach((el) => {
      el.textContent = this._remainingTime(el.dataset.expiry);
    });
  }

  async republishBinary() {
    if (!this.device) return;
    const targetDevice = this.device;
    const targetDeviceId = targetDevice.device_id;
    const request = this._deviceRequest;
    const stillShowingTarget = () => this.isOpen
      && this.device?.device_id === targetDeviceId
      && this._deviceRequest === request;
    try {
      await this.hass.callWS({
        type: "esphome_ota/republish",
        device_id: targetDeviceId,
      });
      if (!stillShowingTarget()) return;
      targetDevice.has_public_binary = true;
      this.statusMessage = t(this.hass, "republish_success");
      this.statusType = "success";
      this.dispatchEvent(new CustomEvent("device-updated", { bubbles: true, composed: true }));
      this.render();
    } catch (err) {
      if (stillShowingTarget()) {
        this.statusMessage = `${t(this.hass, "binary_action_error")}: ${err.message || err}`;
        this.statusType = "error";
        this.render();
      }
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
      const needsInitial = this.device.status === "needs_initial_install"
        || (!this.device.has_http_ota && !this.device.last_installed_version);
      tabContent = `
        ${needsInitial ? `
          <div class="notice" role="status" aria-live="polite">
            <strong>${escapeHtml(t(this.hass, "initial_install_title"))}</strong><br>
            ${escapeHtml(t(this.hass, "initial_install_help"))}
          </div>
        ` : ""}
        <table class="info-table">
          <tr><td>${escapeHtml(t(this.hass, "device_name"))}</td><td>${escapeHtml(this.device.name)}</td></tr>
          <tr><td>${escapeHtml(t(this.hass, "configuration"))}</td><td>${escapeHtml(this.device.configuration)}</td></tr>
          <tr><td>${escapeHtml(t(this.hass, "chip_family_label"))}</td><td>${escapeHtml(this.device.chip_family)}</td></tr>
          <tr>
            <td>${escapeHtml(t(this.hass, "token"))}</td>
            <td>
              <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                <input type="text" id="token-input" aria-label="${escapeHtml(t(this.hass, "token"))}" value="${escapeHtml(this.device.token || "")}" placeholder="${escapeHtml(t(this.hass, "token_none"))}" style="flex: 1; min-width: 140px; font-family: monospace; font-size: 0.82rem; padding: 5px 8px; border-radius: 6px; border: 1px solid var(--divider-color, #cbd5e1); background: var(--card-background-color, #ffffff); color: inherit;">
                <button class="primary" id="btn-save-token" style="padding: 5px 12px; font-size: 0.8rem;">${escapeHtml(t(this.hass, "btn_save_token") || "Save")}</button>
              </div>
              <div style="font-size: 0.72rem; color: var(--secondary-text-color, #64748b); margin-top: 4px;">
                ${escapeHtml(t(this.hass, "token_hint") || "URL obfuscation token. Leave blank for legacy plain device name.")}
              </div>
            </td>
          </tr>
          <tr><td>${escapeHtml(t(this.hass, "public_slug"))}</td><td id="token-slug-val"><code>${escapeHtml(this.device.slug)}</code></td></tr>
          <tr><td>${escapeHtml(t(this.hass, "installed_version"))}</td><td>${escapeHtml(this.device.last_installed_version || t(this.hass, "version_not_detected"))}</td></tr>
          <tr><td>${escapeHtml(t(this.hass, "published_version"))}</td><td>${escapeHtml(this.device.last_published_version || t(this.hass, "version_none"))}</td></tr>
          ${this.device.last_published_version ? `
            <tr>
              <td>${escapeHtml(t(this.hass, "firmware_binary"))}</td>
              <td>
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                  <span class="binary-status ${this.device.has_public_binary ? "binary-active" : "binary-hidden"}">
                    <span class="status-dot-sm ${this.device.has_public_binary ? "ok" : "neutral"}"></span>
                    ${escapeHtml(t(this.hass, this.device.has_public_binary ? "status_active" : "status_hidden"))}
                  </span>
                  ${this.device.has_public_binary
                    ? `<button class="btn-hide" style="padding: 4px 10px; font-size: 0.8rem;">${escapeHtml(t(this.hass, "btn_hide"))}</button>`
                    : `<button class="btn-republish primary" style="padding: 4px 10px; font-size: 0.8rem;">${escapeHtml(t(this.hass, "btn_republish"))}</button>`
                  }
                </div>
              </td>
            </tr>
          ` : ""}
          ${this.device.update_entity_id ? `<tr><td>Update Entity</td><td><code>${escapeHtml(this.device.update_entity_id)}</code></td></tr>` : ""}
          ${this.device.last_published_version ? `
            <tr><td>${escapeHtml(t(this.hass, "publication_expiry"))}</td><td>${this.device.has_public_binary
              ? (this.device.expires_at
                ? `${escapeHtml(new Date(this.device.expires_at).toLocaleString())} · ${escapeHtml(t(this.hass, "time_remaining"))} <span class="expiry-remaining" data-expiry="${escapeHtml(this.device.expires_at)}">${escapeHtml(this._remainingTime(this.device.expires_at))}</span>`
                : escapeHtml(t(this.hass, "expiry_disabled")))
              : escapeHtml(t(this.hass, "status_hidden"))}</td></tr>
            <tr><td>${escapeHtml(t(this.hass, "publication_policy"))}</td><td>
              <label style="display:flex;align-items:center;gap:8px;margin:4px 0;">
                <span>${escapeHtml(t(this.hass, "auto_cleanup_hours"))}</span>
                <input id="cleanup-hours" type="number" min="0" max="168" step="1" value="${escapeHtml(String(this.artifact?.cleanup_hours ?? this.device.publication_cleanup_hours ?? this.defaultCleanupHours))}" style="width:76px;">
              </label>
              <label style="display:flex;align-items:center;gap:8px;margin:4px 0;">
                <input id="auto-hide-installed" type="checkbox" ${(this.artifact?.auto_hide ?? this.device.auto_hide) !== false ? "checked" : ""}>
                ${escapeHtml(t(this.hass, "hide_after_install"))}
              </label>
              <label style="display:flex;align-items:center;gap:8px;margin:4px 0;">
                <input id="save-policy-default" type="checkbox">
                ${escapeHtml(t(this.hass, "save_policy_default"))}
              </label>
              <div style="font-size:.72rem;color:var(--secondary-text-color,#64748b);margin:4px 0;">${escapeHtml(t(this.hass, "policy_restart_note"))}</div>
              <button id="btn-save-publication-policy" style="padding:4px 10px;font-size:.8rem;">${escapeHtml(t(this.hass, "apply_publication_policy"))}</button>
            </td></tr>
          ` : ""}
        </table>
      `;
    } else if (this.currentTab === "upload") {
      tabContent = `
        <div class="notice">
          <strong>${escapeHtml(t(this.hass, "upload_title"))}</strong><br>
          ${escapeHtml(t(this.hass, "upload_help"))}
        </div>
        <input type="file" id="firmware-file" accept=".bin,application/octet-stream" style="margin: 12px 0;" ${this.uploading ? "disabled" : ""}>
        <div class="selected-file" aria-live="polite">${escapeHtml(this.selectedFirmwareFile?.name || t(this.hass, "no_firmware_selected"))}</div>
        <label for="upload-cleanup-mode">${escapeHtml(t(this.hass, "publication_expiry"))}</label>
        <select id="upload-cleanup-mode" ${this.uploading ? "disabled" : ""}>
          <option value="default" ${this.cleanupMode === "default" ? "selected" : ""}>${escapeHtml(t(this.hass, "use_device_default"))}</option>
          <option value="none" ${this.cleanupMode === "none" ? "selected" : ""}>${escapeHtml(t(this.hass, "expiry_disabled"))}</option>
          <option value="custom" ${this.cleanupMode === "custom" ? "selected" : ""}>${escapeHtml(t(this.hass, "custom_expiry"))}</option>
        </select>
        ${this.cleanupMode === "custom" ? `<input id="upload-cleanup-hours" type="number" min="1" max="168" step="1" value="${escapeHtml(String(this.cleanupHours))}" ${this.uploading ? "disabled" : ""}>` : ""}
        <label style="display:flex;align-items:center;gap:8px;margin-top:8px;"><input id="upload-auto-hide" type="checkbox" ${this.autoHideAfterInstall ? "checked" : ""} ${this.uploading ? "disabled" : ""}>${escapeHtml(t(this.hass, "hide_after_install"))}</label>
      `;
    }

    captureModalFocus(this);
    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <div class="backdrop" id="backdrop">
        <div class="modal">
          <div class="header">
            <h2>${escapeHtml(this.device.friendly_name || this.device.name)}</h2>
            <button id="close-x" aria-label="${escapeHtml(t(this.hass, "close"))}">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
          <div class="tabs-container">
            <div class="tabs" role="tablist" aria-label="${escapeHtml(t(this.hass, "device_tabs"))}">
              <button role="tab" aria-selected="${this.currentTab === "diff"}" tabindex="${this.currentTab === "diff" ? "0" : "-1"}" aria-controls="device-tabpanel" id="tab-diff" class="tab ${this.currentTab === "diff" ? "active" : ""}" data-tab="diff">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line></svg>
                <span>${escapeHtml(t(this.hass, "tab_diff") || "OTA Diff")}</span>
              </button>
              <button role="tab" aria-selected="${this.currentTab === "info"}" tabindex="${this.currentTab === "info" ? "0" : "-1"}" aria-controls="device-tabpanel" id="tab-info" class="tab ${this.currentTab === "info" ? "active" : ""}" data-tab="info">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                <span>${escapeHtml(t(this.hass, "tab_info") || "Device Info")}</span>
              </button>
              <button role="tab" aria-selected="${this.currentTab === "upload"}" tabindex="${this.currentTab === "upload" ? "0" : "-1"}" aria-controls="device-tabpanel" id="tab-upload" class="tab ${this.currentTab === "upload" ? "active" : ""}" data-tab="upload">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                <span>${escapeHtml(t(this.hass, "tab_upload") || "Manual Upload")}</span>
              </button>
            </div>
          </div>
          <div class="body" role="tabpanel" id="device-tabpanel" aria-labelledby="tab-${this.currentTab}" tabindex="0">
            ${this.statusMessage ? `<div class="notice ${this.statusType}" role="${this.statusType === "error" ? "alert" : "status"}" aria-live="${this.statusType === "error" ? "assertive" : "polite"}">${escapeHtml(this.statusMessage)}</div>` : ""}
            ${tabContent}
          </div>
          <div class="footer">
            ${this.currentTab === "diff" ? `
              <button id="btn-apply" ${this.applying || !this.diffData || this._diffDeviceId !== this.device.device_id ? "disabled" : ""}>${escapeHtml(t(this.hass, this.applying ? "applying_changes" : "apply_changes"))}</button>
              <button class="primary" id="btn-apply-build" ${this.applying || !this.diffData || this._diffDeviceId !== this.device.device_id ? "disabled" : ""}>${escapeHtml(t(this.hass, this.applying ? "applying_changes" : "apply_and_build"))}</button>
            ` : ""}
            ${this.currentTab === "upload" ? `
              <button class="primary" id="btn-upload" ${this.uploading || !this.selectedFirmwareFile ? "disabled" : ""}>${escapeHtml(t(this.hass, this.uploading ? "uploading_firmware" : "upload_btn"))}</button>
            ` : ""}
            ${this.device.is_managed && this.currentTab === "info" ? `
              <button class="danger" id="btn-remove-ota">${escapeHtml(t(this.hass, "btn_remove_ota"))}</button>
            ` : ""}
            <button id="btn-close">${escapeHtml(t(this.hass, "close"))}</button>
          </div>
        </div>
      </div>
    `;

    bindModalAccessibility(this, () => this.close());

    this.shadowRoot.getElementById("close-x")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("btn-close")?.addEventListener("click", () => this.close());
    let mouseDownTarget = null;
    const backdrop = this.shadowRoot.getElementById("backdrop");
    backdrop?.addEventListener("mousedown", (e) => {
      mouseDownTarget = e.target;
    });
    backdrop?.addEventListener("click", (e) => {
      if (e.target.id === "backdrop" && mouseDownTarget?.id === "backdrop") {
        this.close();
      }
      mouseDownTarget = null;
    });

    this.shadowRoot.querySelectorAll(".tab").forEach((tabBtn) => {
      tabBtn.addEventListener("click", () => {
        const tab = tabBtn.getAttribute("data-tab");
          if (tab && tab !== this.currentTab) {
          this.currentTab = tab;
          this.statusMessage = "";
          this.statusType = "info";
          this.render();
          if (this.currentTab === "diff") this.loadDiff();
          if (this.currentTab === "info") this.loadPublicationDetails();
        }
      });
      tabBtn.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const tabs = [...this.shadowRoot.querySelectorAll('[role="tab"]')];
        const index = tabs.indexOf(tabBtn);
        const next = event.key === "Home" ? 0
          : event.key === "End" ? tabs.length - 1
            : (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
        const target = tabs[next];
        if (!target) return;
        const targetTab = target.dataset.tab;
        target.click();
        // Tab activation rerenders the dialog, so focus the replacement node.
        this.shadowRoot.querySelector(`[role="tab"][data-tab="${targetTab}"]`)
          ?.focus({ preventScroll: true });
      });
    });

    this.shadowRoot.getElementById("btn-apply")?.addEventListener("click", () => this.applyDiff(false));
    this.shadowRoot.getElementById("btn-apply-build")?.addEventListener("click", () => this.applyDiff(true));
    this.shadowRoot.getElementById("btn-remove-ota")?.addEventListener("click", () => this.removeOta());
    this.shadowRoot.getElementById("btn-save-token")?.addEventListener("click", () => this.saveToken());
    this.shadowRoot.getElementById("btn-save-publication-policy")?.addEventListener("click", () => this.savePublicationPolicy());
    this.shadowRoot.querySelector(".btn-hide")?.addEventListener("click", () => this.hideBinary());
    this.shadowRoot.querySelector(".btn-republish")?.addEventListener("click", () => this.republishBinary());
    this.shadowRoot.getElementById("btn-upload")?.addEventListener("click", () => {
      if (this.selectedFirmwareFile) this.uploadFirmware(this.selectedFirmwareFile);
    });
    this.shadowRoot.getElementById("firmware-file")?.addEventListener("change", (event) => {
      if (this.uploading) {
        this.render();
        return;
      }
      const file = event.target.files?.[0] || null;
      if (file && !file.name.toLowerCase().endsWith(".bin")) {
        this.selectedFirmwareFile = null;
        this.statusMessage = t(this.hass, "firmware_bin_required");
        this.statusType = "error";
      } else {
        this.selectedFirmwareFile = file;
        this.statusMessage = "";
        this.statusType = "info";
      }
      this.render();
    });
    this.shadowRoot.getElementById("upload-cleanup-mode")?.addEventListener("change", (event) => {
      this.cleanupMode = event.target.value;
      this.render();
    });
    this.shadowRoot.getElementById("upload-cleanup-hours")?.addEventListener("input", (event) => {
      this.cleanupHours = event.target.value;
    });
    this.shadowRoot.getElementById("upload-auto-hide")?.addEventListener("change", (event) => {
      this.autoHideAfterInstall = event.target.checked;
    });
  }

  async saveToken() {
    const input = this.shadowRoot.getElementById("token-input");
    if (!input || !this.device) return;
    const targetDevice = this.device;
    const targetDeviceId = targetDevice.device_id;
    const request = this._deviceRequest;
    const newToken = input.value.trim();
    const btn = this.shadowRoot.getElementById("btn-save-token");
    if (btn) btn.disabled = true;
    try {
      const res = await this.hass.callWS({
        type: "esphome_ota/set_token",
        device_id: targetDeviceId,
        token: newToken,
      });
      if (res?.success) {
        const stillShowingTarget = this.isOpen
          && this.device?.device_id === targetDeviceId
          && this._deviceRequest === request;
        if (!stillShowingTarget) return;
        targetDevice.token = res.token;
        targetDevice.slug = res.slug;
        const slugEl = this.shadowRoot.getElementById("token-slug-val");
        if (slugEl) slugEl.innerHTML = `<code>${escapeHtml(res.slug)}</code>`;
        this.dispatchEvent(new CustomEvent("device-updated", { bubbles: true, composed: true }));
        this.dispatchEvent(
          new CustomEvent("hass-notification", {
            detail: { message: t(this.hass, "token_updated") || "Token updated successfully." },
            bubbles: true,
            composed: true,
          })
        );
      }
    } catch (err) {
      if (
        this.isOpen &&
        this.device?.device_id === targetDeviceId &&
        this._deviceRequest === request
      ) {
        this.dispatchEvent(
          new CustomEvent("hass-notification", {
            detail: { message: `Token update failed: ${err.message || err}` },
            bubbles: true,
            composed: true,
          })
        );
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  }
}

definePanelElement("esphome-ota-device-dialog", EsphomeOtaDeviceDialog);
