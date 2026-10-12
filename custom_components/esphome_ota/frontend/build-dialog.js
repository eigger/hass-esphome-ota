/**
 * Build confirmation dialog: review current versions and edit target version.
 */

import { t } from "./i18n.js";
import { bindModalAccessibility, captureModalFocus, definePanelElement, rememberModalFocus, restoreModalFocus } from "./elements.js";

const css = `
:host { display: block; }
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
  max-width: 480px;
  max-height: calc(100vh - 32px);
  max-height: calc(100dvh - 32px);
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
  font-size: 1.1rem;
  font-weight: 600;
}
.body {
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.device-name {
  font-weight: 600;
  font-size: 0.95rem;
}
.device-sub {
  font-size: 0.8rem;
  color: var(--secondary-text-color, #64748b);
  margin-top: 2px;
}
.version-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.version-card {
  padding: 12px;
  background: var(--secondary-background-color, #f8fafc);
  border: 1px solid var(--divider-color, #e2e8f0);
  border-radius: 10px;
}
.version-label {
  display: block;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--secondary-text-color, #64748b);
  margin-bottom: 4px;
}
.version-value {
  font-size: 1.05rem;
  font-weight: 600;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
.field label {
  display: block;
  font-size: 0.85rem;
  font-weight: 600;
  margin-bottom: 6px;
}
.field input[type="text"] {
  width: 100%;
  padding: 10px 12px;
  font-size: 1rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  border-radius: 8px;
  border: 1px solid var(--divider-color, #cbd5e1);
  background: var(--card-background-color, #ffffff);
  color: inherit;
  box-sizing: border-box;
}
.field select {
  width: 100%;
  padding: 9px 10px;
  font-size: 0.9rem;
  border-radius: 8px;
  border: 1px solid var(--divider-color, #cbd5e1);
  background: var(--card-background-color, #ffffff);
  color: inherit;
}
.template-options { display: grid; gap: 8px; }
.template-option {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--secondary-background-color, #f8fafc);
  border: 1px solid var(--divider-color, #e2e8f0);
  font-size: 0.8rem;
  line-height: 1.45;
}
.template-option.selected { border-color: var(--primary-color, #0284c7); box-shadow: inset 0 0 0 1px var(--primary-color, #0284c7); }
.template-option input[type="radio"] { flex: none; width: auto; padding: 0; margin: 3px 0 0; accent-color: var(--primary-color, #0284c7); }
.template-option-content { flex: 1; min-width: 0; }
.template-option label { display: block; font-weight: 600; cursor: pointer; }
.template-example, .template-next { display: block; margin-top: 2px; color: var(--secondary-text-color, #64748b); }
.template-next code { color: var(--primary-text-color, #1f2937); font-size: 0.88rem; font-weight: 600; overflow-wrap: anywhere; }
.template-option select { max-width: 150px; margin-top: 7px; }
.field input[type="text"]:disabled {
  opacity: 0.7;
  background: var(--secondary-background-color, #f1f5f9);
}
.hint {
  padding: 12px 14px;
  border: 1px solid var(--primary-color, #0284c7);
  border-left-width: 3px;
  border-radius: 8px;
  background: var(--secondary-background-color, #f8fafc);
  line-height: 1.45;
}
.hint-title {
  display: block;
  margin-bottom: 3px;
  font-size: 0.85rem;
  font-weight: 600;
}
.hint p {
  margin: 0;
  color: var(--secondary-text-color, #64748b);
  font-size: 0.8rem;
}
.notice {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--warning-background-color, #fef3c7);
  color: var(--warning-color, #92400e);
  font-size: 0.82rem;
  line-height: 1.4;
  border: 1px solid var(--warning-color, #fde68a);
}
.error {
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--error-background-color, #fef2f2);
  color: var(--error-color, #991b1b);
  font-size: 0.82rem;
  border: 1px solid var(--error-color, #fecaca);
}
.footer {
  padding: 14px 20px;
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  border-top: 1px solid var(--divider-color, #e5e7eb);
  background: var(--secondary-background-color, #fafafa);
  flex: none;
}
@media (max-height: 560px) {
  .backdrop { align-items: flex-start; padding: 8px; overflow-y: auto; }
  .modal { max-height: calc(100vh - 16px); max-height: calc(100dvh - 16px); }
  .header, .footer { padding: 10px 14px; }
  .body { padding: 12px 14px; gap: 10px; }
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
button:hover:not(:disabled) {
  background: var(--secondary-background-color, #f1f5f9);
  border-color: var(--divider-color, #9ca3af);
}
button.primary {
  background: var(--primary-color, #0284c7);
  color: #ffffff;
  border-color: var(--primary-color, #0284c7);
}
button.primary:hover:not(:disabled) {
  opacity: 0.92;
  border-color: var(--primary-color, #0284c7);
}
button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.btn-close {
  background: none;
  border: none;
  font-size: 1.2rem;
  padding: 4px 8px;
  border-radius: 6px;
  color: var(--secondary-text-color, #6b7280);
  transition: all 0.15s ease-in-out;
}
.btn-close:hover {
  background: var(--secondary-background-color, #f1f5f9);
  color: var(--primary-text-color, #1f2937);
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

const DATE_SEP_RE =
  /^(20\d\d([-.])(0?[1-9]|1[0-2])\2(0?[1-9]|[12]\d|3[01]))(?:\.(\d+))?$/;
const DATE_COMPACT_RE =
  /^(20\d\d(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01]))(?:\.(\d+))?$/;

function parseDateVersion(version) {
  const text = String(version || "").trim().replace(/^['"]|['"]$/g, "");
  let year, month, day, revision;
  let match = text.match(/^(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:\.(\d+))?$/);
  if (match) {
    year = 2000 + Number(match[1]);
    month = Number(match[2]);
    day = Number(match[3]);
    revision = Number(match[4] || 0);
  } else {
    const compactMatch = text.match(DATE_COMPACT_RE);
    const separatedMatch = text.match(DATE_SEP_RE);
    if (compactMatch) {
      match = compactMatch;
      const date = match[1].replace(/[-.]/g, "");
      year = Number(date.slice(0, 4));
      month = Number(match[2]);
      day = Number(match[3]);
      revision = Number(match[4] || 0);
    } else if (separatedMatch) {
      match = separatedMatch;
      year = Number(match[1].slice(0, 4));
      month = Number(match[3]);
      day = Number(match[4]);
      revision = Number(match[5] || 0);
    } else {
      match = text.match(/^v(\d{2})(\d{2})(\d{2})\s+rev\.(\d+)$/i);
      if (!match) return null;
      year = 2000 + Number(match[1]);
      month = Number(match[2]);
      day = Number(match[3]);
      revision = Number(match[4]);
    }
  }
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return { key: `${String(year).slice(-2)}${String(month).padStart(2, "0")}${String(day).padStart(2, "0")}`, revision };
}

function parseSemver(version) {
  const text = String(version || "").trim().replace(/^['"]|['"]$/g, "");
  if (parseDateVersion(text)) return null;
  const match = text.match(/^(\d+)\.(\d+)\.(\d+)$/);
  return match ? match.slice(1).map(Number) : null;
}

function currentDateKey(timeZone) {
  const options = { year: "numeric", month: "2-digit", day: "2-digit" };
  if (timeZone) options.timeZone = timeZone;
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", options).formatToParts(new Date()).map(({ type, value }) => [type, value])
  );
  return `${parts.year.slice(-2)}${parts.month}${parts.day}`;
}

function currentYamlVersion(device) {
  return device?.own_project_version || device?.last_published_version || device?.last_installed_version || device?.managed_version || "1.0.0";
}

function suggestDateVersion(device, today) {
  const revisions = [device?.last_installed_version, device?.last_published_version, device?.own_project_version]
    .map(parseDateVersion)
    .filter((version) => version?.key === today)
    .map((version) => version.revision);
  return `${today}.${Math.max(0, ...revisions) + 1}`;
}

function suggestSemver(device, increment) {
  const versions = [device?.last_installed_version, device?.last_published_version, device?.own_project_version]
    .map(parseSemver)
    .filter(Boolean)
    .sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2]);
  if (!versions.length) return "1.0.0";
  const [major, minor, patch] = versions[versions.length - 1];
  if (increment === "major") return `${major + 1}.0.0`;
  if (increment === "minor") return `${major}.${minor + 1}.0`;
  return `${major}.${minor}.${patch + 1}`;
}

class EsphomeOtaBuildDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.isOpen = false;
    this.device = null;
    this.hass = null;
    this.targetVersion = "";
    this.manualVersion = "";
    this.versionTemplate = "date";
    this.versionIncrement = "patch";
    this.cleanupMode = "default";
    this.cleanupHours = 12;
    this.autoHideAfterInstall = true;
    this.submitting = false;
    this.error = "";
    this._sessionId = 0;
  }

  open(device, hass, returnFocus = undefined) {
    if (!this.isOpen) rememberModalFocus(this);
    if (returnFocus !== undefined) this._modalReturnFocus = returnFocus;
    this._sessionId++;
    this.device = device;
    this.hass = hass;
    this.isOpen = true;
    this.submitting = false;
    this.error = "";
    this.versionTemplate = "date";
    this.versionIncrement = "patch";
    this.cleanupMode = "default";
    this.cleanupHours = 12;
    this.autoHideAfterInstall = device?.auto_hide !== false;
    this.manualVersion = currentYamlVersion(device);
    this.targetVersion = suggestDateVersion(device, currentDateKey(hass?.config?.time_zone));
    this.render();
    const sessionId = this._sessionId;
    setTimeout(() => {
      if (!this.isOpen || this._sessionId !== sessionId) return;
      const target = this.versionTemplate === "manual"
        ? this.shadowRoot.getElementById("target-version")
        : this.shadowRoot.getElementById(`template-${this.versionTemplate}`);
      target?.focus();
      if (target?.id === "target-version") target.select();
    }, 0);
  }

  close() {
    this._sessionId++;
    this.isOpen = false;
    this.render();
    restoreModalFocus(this);
  }

  async confirmBuild() {
    if (this.submitting || !this.device || !this.hass) return;
    const targetDevice = this.device;
    const sessionId = this._sessionId;
    const version = (this.targetVersion || "").trim();
    if (!version) {
      this.error = t(this.hass, "build_version_required");
      this.render();
      return;
    }
    if (this.cleanupMode === "custom") {
      const hours = Number(this.cleanupHours);
      if (!Number.isInteger(hours) || hours < 1 || hours > 168) {
        this.error = t(this.hass, "cleanup_hours_invalid");
        this.render();
        return;
      }
    }

    this.submitting = true;
    this.error = "";
    this.render();

    try {
      const payload = {
        type: "esphome_ota/build",
        device_id: targetDevice.device_id,
        target_version: version,
        auto_hide: !!this.autoHideAfterInstall,
      };
      if (this.cleanupMode === "none") payload.cleanup_hours = 0;
      else if (this.cleanupMode === "custom") payload.cleanup_hours = Number(this.cleanupHours);
      const res = await this.hass.callWS(payload);
      const stillShowingTarget = this.isOpen
        && this._sessionId === sessionId
        && this.device?.device_id === targetDevice.device_id;
      if (!stillShowingTarget) return;
      const returnFocus = this._modalReturnFocus;
      this.close();
      this.dispatchEvent(
        new CustomEvent("build-started", {
          detail: {
            device: targetDevice,
            job_id: res.job_id,
            target_version: version,
            returnFocus,
          },
          bubbles: true,
          composed: true,
        })
      );
    } catch (err) {
      const stillShowingTarget = this.isOpen
        && this._sessionId === sessionId
        && this.device?.device_id === targetDevice.device_id;
      if (!stillShowingTarget) return;
      this.error = err.message || String(err);
      this.submitting = false;
      this.render();
    }
  }

  render() {
    if (!this.isOpen || !this.device) {
      this.shadowRoot.innerHTML = "";
      return;
    }

    const d = this.device;
    const installed = d.last_installed_version || "—";
    const published = d.last_published_version || "—";
    const dateExample = "261012.1";
    const semverExample = "1.2.3";
    const dateSuggestion = suggestDateVersion(d, currentDateKey(this.hass?.config?.time_zone));
    const semverSuggestion = suggestSemver(d, this.versionIncrement);
    const isManual = this.versionTemplate === "manual";
    const dateSelected = this.versionTemplate === "date";
    const semverSelected = this.versionTemplate === "semver";

    captureModalFocus(this);
    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <div class="backdrop" id="backdrop">
        <div class="modal">
          <div class="header">
            <h2>${escapeHtml(t(this.hass, "build_confirm_title"))}</h2>
            <button class="btn-close" id="btn-close" aria-label="${escapeHtml(t(this.hass, "close"))}">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
          <div class="body">
            <div>
              <div class="device-name">${escapeHtml(d.friendly_name || d.name)}</div>
              <div class="device-sub">${escapeHtml(d.configuration)}</div>
            </div>
            <div class="version-grid">
              <div class="version-card">
                <span class="version-label">${escapeHtml(t(this.hass, "installed_version"))}</span>
                <span class="version-value">${escapeHtml(installed)}</span>
              </div>
              <div class="version-card">
                <span class="version-label">${escapeHtml(t(this.hass, "published_version"))}</span>
                <span class="version-value">${escapeHtml(published)}</span>
              </div>
            </div>
            <div class="field">
              <span class="version-label">${escapeHtml(t(this.hass, "version_template_label"))}</span>
              <div class="template-options" role="radiogroup" aria-label="${escapeHtml(t(this.hass, "version_template_label"))}">
                <div class="template-option ${dateSelected ? "selected" : ""}">
                  <input type="radio" id="template-date" name="version-template" value="date" ${dateSelected ? "checked" : ""} ${this.submitting ? "disabled" : ""}>
                  <div class="template-option-content">
                    <label for="template-date">${escapeHtml(t(this.hass, "version_template_date"))}</label>
                    <span class="template-example">${escapeHtml(t(this.hass, "version_template_example"))}: ${escapeHtml(dateExample)}</span>
                    <span class="template-next">${escapeHtml(t(this.hass, "version_template_suggestion"))}: <code>${escapeHtml(dateSuggestion)}</code></span>
                    ${dateSelected ? `<span class="template-example">${escapeHtml(t(this.hass, "version_template_date_help"))}</span>` : ""}
                  </div>
                </div>
                <div class="template-option ${semverSelected ? "selected" : ""}">
                  <input type="radio" id="template-semver" name="version-template" value="semver" ${semverSelected ? "checked" : ""} ${this.submitting ? "disabled" : ""}>
                  <div class="template-option-content">
                    <label for="template-semver">${escapeHtml(t(this.hass, "version_template_semver"))}</label>
                    <span class="template-example">${escapeHtml(t(this.hass, "version_template_example"))}: ${escapeHtml(semverExample)}</span>
                    <span class="template-next">${escapeHtml(t(this.hass, "version_template_suggestion"))}: <code>${escapeHtml(semverSuggestion)}</code></span>
                    ${semverSelected ? `<select id="version-increment" aria-label="${escapeHtml(t(this.hass, "version_increment_label"))}" ${this.submitting ? "disabled" : ""}>
                      <option value="patch" ${this.versionIncrement === "patch" ? "selected" : ""}>${escapeHtml(t(this.hass, "version_increment_patch"))}</option>
                      <option value="minor" ${this.versionIncrement === "minor" ? "selected" : ""}>${escapeHtml(t(this.hass, "version_increment_minor"))}</option>
                      <option value="major" ${this.versionIncrement === "major" ? "selected" : ""}>${escapeHtml(t(this.hass, "version_increment_major"))}</option>
                    </select>` : ""}
                  </div>
                </div>
                <div class="template-option ${isManual ? "selected" : ""}">
                  <input type="radio" id="template-manual" name="version-template" value="manual" ${isManual ? "checked" : ""} ${this.submitting ? "disabled" : ""}>
                  <div class="template-option-content">
                    <label for="template-manual">${escapeHtml(t(this.hass, "version_template_manual"))}</label>
                    <span class="template-example">${escapeHtml(t(this.hass, "version_template_example"))}: ${escapeHtml(t(this.hass, "version_template_manual_example"))}</span>
                    <span class="template-example">${escapeHtml(t(this.hass, "version_template_manual_help"))}</span>
                  </div>
                </div>
              </div>
            </div>
            ${isManual ? `<div class="field">
              <label for="target-version">${escapeHtml(t(this.hass, "build_target_version"))}</label>
              <input id="target-version" type="text" value="${escapeHtml(this.manualVersion)}" ${this.submitting ? "disabled" : ""} autocomplete="off" spellcheck="false">
            </div>` : `<div class="field"><span class="version-label">${escapeHtml(t(this.hass, "build_target_version"))}</span><div class="version-value">${escapeHtml(this.targetVersion)}</div></div>`}
            <div class="hint">
              <span class="hint-title">${escapeHtml(t(this.hass, "build_version_hint"))}</span>
              <p>${escapeHtml(t(this.hass, "build_version_hint_details"))}</p>
            </div>
            <div class="field">
              <label for="cleanup-mode">${escapeHtml(t(this.hass, "publication_expiry"))}</label>
              <select id="cleanup-mode" ${this.submitting ? "disabled" : ""}>
                <option value="default" ${this.cleanupMode === "default" ? "selected" : ""}>${escapeHtml(t(this.hass, "use_device_default"))}</option>
                <option value="none" ${this.cleanupMode === "none" ? "selected" : ""}>${escapeHtml(t(this.hass, "expiry_disabled"))}</option>
                <option value="custom" ${this.cleanupMode === "custom" ? "selected" : ""}>${escapeHtml(t(this.hass, "custom_expiry"))}</option>
              </select>
              ${this.cleanupMode === "custom" ? `<input id="cleanup-hours" type="number" min="1" max="168" step="1" value="${escapeHtml(String(this.cleanupHours))}" ${this.submitting ? "disabled" : ""}>` : ""}
              <label style="display:flex;align-items:center;gap:8px;margin-top:8px;"><input id="auto-hide-installed" type="checkbox" ${this.autoHideAfterInstall ? "checked" : ""} ${this.submitting ? "disabled" : ""}>${escapeHtml(t(this.hass, "hide_after_install"))}</label>
            </div>
            ${this.error ? `<div class="error">${escapeHtml(this.error)}</div>` : ""}
          </div>
          <div class="footer">
            <button id="btn-cancel">${escapeHtml(t(this.hass, "cancel"))}</button>
            <button class="primary" id="btn-start" ${this.submitting ? "disabled" : ""}>
              ${escapeHtml(this.submitting ? t(this.hass, "stage_preparing") + "..." : t(this.hass, "btn_build"))}
            </button>
          </div>
        </div>
      </div>
    `;

    bindModalAccessibility(this, () => this.close());

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
    this.shadowRoot.getElementById("btn-close")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("btn-cancel")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("btn-start")?.addEventListener("click", () => this.confirmBuild());
    this.shadowRoot.getElementById("cleanup-mode")?.addEventListener("change", (event) => {
      this.cleanupMode = event.target.value;
      this.render();
      this.shadowRoot.getElementById("cleanup-mode")?.focus();
    });
    this.shadowRoot.getElementById("cleanup-hours")?.addEventListener("input", (event) => {
      this.cleanupHours = event.target.value;
    });
    this.shadowRoot.getElementById("auto-hide-installed")?.addEventListener("change", (event) => {
      this.autoHideAfterInstall = event.target.checked;
    });

    this.shadowRoot.querySelectorAll('input[name="version-template"]').forEach((radio) => radio.addEventListener("change", (event) => {
      this.versionTemplate = event.target.value;
      this.targetVersion = this.versionTemplate === "date"
        ? suggestDateVersion(this.device, currentDateKey(this.hass?.config?.time_zone))
        : this.versionTemplate === "semver"
          ? suggestSemver(this.device, this.versionIncrement)
          : this.manualVersion;
      this.render();
      this.shadowRoot.getElementById(`template-${this.versionTemplate}`)?.focus();
    }));
    const incrementSelect = this.shadowRoot.getElementById("version-increment");
    incrementSelect?.addEventListener("change", (event) => {
      this.versionIncrement = event.target.value;
      this.targetVersion = suggestSemver(this.device, this.versionIncrement);
      this.render();
      this.shadowRoot.getElementById("version-increment")?.focus();
    });

    const input = this.shadowRoot.getElementById("target-version");
    input?.addEventListener("input", (e) => {
      this.targetVersion = e.target.value;
      this.manualVersion = e.target.value;
    });
    input?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") this.confirmBuild();
    });
  }
}

definePanelElement("esphome-ota-build-dialog", EsphomeOtaBuildDialog);
