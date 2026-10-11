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
.field input {
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
.field input:disabled {
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

function bumpPatchVersion(version) {
  const text = String(version || "").trim().replace(/"/g, "");
  if (!text) {
    return "1.0.0";
  }
  const sepMatch = text.match(DATE_SEP_RE);
  if (sepMatch) {
    const base = sepMatch[1];
    const seq = sepMatch[5];
    return seq !== undefined ? `${base}.${Number(seq) + 1}` : `${base}.1`;
  }
  const compactMatch = text.match(DATE_COMPACT_RE);
  if (compactMatch) {
    const base = compactMatch[1];
    const seq = compactMatch[4];
    return seq !== undefined ? `${base}.${Number(seq) + 1}` : `${base}.1`;
  }
  const dotParts = text.split(".");
  if (dotParts.length === 1 && /^\d+$/.test(dotParts[0])) {
    return `${dotParts[0]}.0.1`;
  }
  if (
    dotParts.length === 2 &&
    /^\d+$/.test(dotParts[0]) &&
    /^\d+$/.test(dotParts[1])
  ) {
    return `${dotParts[0]}.${dotParts[1]}.1`;
  }
  const parts = text.split(/(\d+)/);
  for (let i = parts.length - 1; i >= 0; i--) {
    if (/^\d+$/.test(parts[i])) {
      parts[i] = String(Number(parts[i]) + 1);
      return parts.join("");
    }
  }
  return `${text}.1`;
}

function suggestTargetVersion(device) {
  const own = device?.own_project_version;
  const published = device?.last_published_version;
  const installed = device?.last_installed_version;

  if (own) {
    // If own version is distinct from what is currently installed/published,
    // the user might have intentionally bumped it in YAML.
    if ((!installed || own !== installed) && (!published || own !== published)) {
      return own;
    }
    // If own version is what is currently running/published, suggest the next bump.
    return bumpPatchVersion(own);
  }
  if (published) return bumpPatchVersion(published);
  if (installed) return bumpPatchVersion(installed);
  return device?.managed_version || "1.0.0";
}

class EsphomeOtaBuildDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.isOpen = false;
    this.device = null;
    this.hass = null;
    this.targetVersion = "";
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
    this.targetVersion = suggestTargetVersion(device);
    this.render();
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

    this.submitting = true;
    this.error = "";
    this.render();

    try {
      const payload = {
        type: "esphome_ota/build",
        device_id: targetDevice.device_id,
        target_version: version,
      };
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
              <label for="target-version">${escapeHtml(t(this.hass, "build_target_version"))}</label>
              <input id="target-version" type="text" value="${escapeHtml(this.targetVersion)}" ${this.submitting ? "disabled" : ""} autocomplete="off" spellcheck="false">
            </div>
            <div class="hint">
              <span class="hint-title">${escapeHtml(t(this.hass, "build_version_hint"))}</span>
              <p>${escapeHtml(t(this.hass, "build_version_hint_details"))}</p>
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

    const input = this.shadowRoot.getElementById("target-version");
    input?.addEventListener("input", (e) => {
      this.targetVersion = e.target.value;
    });
    input?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") this.confirmBuild();
    });
    if (!this.submitting) {
      setTimeout(() => {
        input?.focus();
        input?.select();
      }, 0);
    }
  }
}

definePanelElement("esphome-ota-build-dialog", EsphomeOtaBuildDialog);
