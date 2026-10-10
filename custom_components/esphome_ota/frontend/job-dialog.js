/**
 * Job progress and log streaming dialog modal.
 */

import { t } from "./i18n.js";
import { definePanelElement } from "./elements.js";

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
.body {
  padding: 16px 20px;
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.stage-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 8px;
  font-weight: 500;
  font-size: 0.9rem;
  background: var(--secondary-background-color, #f3f4f6);
}
.stage-building {
  background: #dbeafe;
  color: #1e40af;
}
.stage-published {
  background: #dcfce7;
  color: #166534;
}
.stage-failed {
  background: #fee2e2;
  color: #991b1b;
}
.stage-recovery {
  background: #fef3c7;
  color: #92400e;
}
.terminal {
  background: #0f172a;
  color: #cbd5e1;
  font-family: ui-monospace, SFMono-Regular, "Pretendard", -apple-system, BlinkMacSystemFont, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 0.8rem;
  line-height: 1.45;
  padding: 14px;
  border-radius: 8px;
  height: 380px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  overflow-wrap: anywhere;
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
button.secondary {
  background: var(--secondary-background-color, #f1f5f9);
  color: var(--primary-text-color, #1e293b);
  border-color: var(--divider-color, #cbd5e1);
}
button.secondary:hover {
  background: #e2e8f0;
}
button.danger {
  background: #dc2626;
  color: #ffffff;
  border-color: #dc2626;
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

const ANSI_STYLES = {
  1: "font-weight: 600;",
  2: "opacity: 0.75;",
  3: "font-style: italic;",
  4: "text-decoration: underline;",
  30: "color: #64748b;",
  31: "color: #f87171;",
  32: "color: #4ade80;",
  33: "color: #facc15;",
  34: "color: #60a5fa;",
  35: "color: #e879f9;",
  36: "color: #38bdf8;",
  37: "color: #f1f5f9;",
  40: "background-color: #0f172a;",
  41: "background-color: #7f1d1d;",
  42: "background-color: #14532d;",
  43: "background-color: #713f12;",
  44: "background-color: #1e3a8a;",
  45: "background-color: #701a75;",
  46: "background-color: #164e63;",
  47: "background-color: #334155;",
  90: "color: #94a3b8;",
  91: "color: #fca5a5;",
  92: "color: #86efac;",
  93: "color: #fde047;",
  94: "color: #93c5fd;",
  95: "color: #f0abfc;",
  96: "color: #7dd3fc;",
  97: "color: #ffffff;",
};

export function ansiToHtml(rawText) {
  if (!rawText) return "";

  // Normalize literal escape representations (\033, \\033, \e, \ufffd) to \x1b
  let text = String(rawText)
    .replace(/\\033/g, "\x1b")
    .replace(/\033/g, "\x1b")
    .replace(/\\e/g, "\x1b")
    .replace(/\ufffd/g, "\x1b");

  let safe = escapeHtml(text);

  // Strip CSI escape sequences other than SGR (e.g. \x1b[K, \x1b[2K, cursor commands)
  safe = safe.replace(/\x1b\[[0-9;?]*[a-ln-zA-LN-Z]/g, "");

  // Strip OSC escape sequences (\x1b] ... \x07 or \x1b\)
  safe = safe.replace(/\x1b\][^\x07\x1b]*(\x07|\x1b\\)/g, "");

  // Strip other escape sequences
  safe = safe.replace(/\x1b[@-Z\\-_]/g, "");

  // Parse SGR color/style sequences (\x1b[...m)
  let openSpan = false;
  safe = safe.replace(/\x1b\[([0-9;]*)m/g, (_match, codeStr) => {
    let result = "";
    if (openSpan) {
      result += "</span>";
      openSpan = false;
    }
    if (!codeStr || codeStr === "0") {
      return result;
    }

    const codes = codeStr.split(";").map((c) => parseInt(c, 10));
    const styles = [];
    for (let i = 0; i < codes.length; i++) {
      const code = codes[i];
      if (isNaN(code) || code === 0) {
        styles.length = 0;
      } else if (ANSI_STYLES[code]) {
        styles.push(ANSI_STYLES[code]);
      }
    }
    if (styles.length > 0) {
      openSpan = true;
      result += `<span style="${styles.join(" ")}">`;
    }
    return result;
  });

  if (openSpan) {
    safe += "</span>";
  }

  // Strip any leftover ESC characters and non-printable control characters
  safe = safe.replace(/\x1b/g, "");
  safe = safe.replace(/[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]/g, "");
  return safe;
}

class EsphomeOtaJobDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.job = null;
    this.hass = null;
    this.isOpen = false;
    this._hasInitialScrolled = false;
  }

  open(job, hass) {
    this.job = job;
    this.hass = hass;
    this.isOpen = true;
    this._hasInitialScrolled = false;
    this.render();
  }

  close() {
    this.isOpen = false;
    this.render();
  }

  updateJob(job) {
    if (!this.isOpen) return;
    if (this.job && this.job.job_id === job.job_id) {
      this.job = job;
      this.render();
    }
  }

  async cancelJob() {
    if (!this.job || !this.hass) return;
    try {
      await this.hass.callWS({
        type: "esphome_ota/cancel_job",
        job_id: this.job.job_id,
      });
    } catch (err) {
      console.error("Cancel job error:", err);
    }
  }

  async recheckJob() {
    if (!this.job || !this.hass) return;
    try {
      await this.hass.callWS({
        type: "esphome_ota/reconnect",
      });
    } catch (err) {
      console.error("Recheck job error:", err);
    }
  }

  render() {
    if (!this.isOpen || !this.job) {
      this.shadowRoot.innerHTML = "";
      return;
    }

    const stage = this.job.stage || "preparing";
    const stageText = t(this.hass, `stage_${stage}`) || stage;
    const logLines = (this.job.log_tail || []).join("\n").trim();
    let logs = logLines;
    if (this.job.error && (stage === "failed" || stage === "cancelled")) {
      if (logs) {
        logs += `\n\n\x1b[31;1m[ERROR] ${this.job.error}\x1b[0m`;
      } else {
        logs = `\x1b[31;1m[ERROR] ${this.job.error}\x1b[0m`;
      }
    } else if (!logs) {
      logs = "Waiting for compiler output...";
    }

    let stageClass = "stage-banner";
    if (stage === "building" || stage === "downloading" || stage === "submitting") {
      stageClass += " stage-building";
    } else if (stage === "published") {
      stageClass += " stage-published";
    } else if (stage === "failed" || stage === "cancelled") {
      stageClass += " stage-failed";
    } else if (stage === "recovery_required") {
      stageClass += " stage-recovery";
    }

    const isRunning = ["preparing", "validating", "submitting", "queued", "building", "downloading", "verifying", "publishing"].includes(stage);
    const isRecovery = stage === "recovery_required";

    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <div class="backdrop" id="backdrop">
        <div class="modal">
          <div class="header">
            <h2>${escapeHtml(t(this.hass, "logs_title"))} - ${escapeHtml(this.job.configuration)}</h2>
            <button id="close-x">✕</button>
          </div>
          <div class="body">
            <div class="${stageClass}">
              <span><strong>Status:</strong> ${escapeHtml(stageText)}</span>
              ${this.job.reserved_version ? `<span>(Target Version: ${escapeHtml(this.job.reserved_version)})</span>` : ""}
              ${this.job.error ? `<span> — ${escapeHtml(this.job.error)}</span>` : ""}
            </div>
            <div class="terminal" id="terminal"></div>
          </div>
          <div class="footer">
            ${isRecovery ? `<button class="secondary" id="btn-recheck">${escapeHtml(t(this.hass, "logs_retry_btn"))}</button>` : ""}
            ${(isRunning || isRecovery) ? `<button class="danger" id="btn-cancel">${escapeHtml(t(this.hass, "logs_cancel_btn"))}</button>` : ""}
            <button class="primary" id="btn-close">${escapeHtml(t(this.hass, "close"))}</button>
          </div>
        </div>
      </div>
    `;

    const terminalEl = this.shadowRoot.getElementById("terminal");
    if (terminalEl) {
      const isAtBottom =
        terminalEl.scrollHeight - terminalEl.scrollTop - terminalEl.clientHeight < 60;
      terminalEl.innerHTML = ansiToHtml(logs);
      if (isAtBottom || !this._hasInitialScrolled) {
        terminalEl.scrollTop = terminalEl.scrollHeight;
        this._hasInitialScrolled = true;
      }
    }

    this.shadowRoot.getElementById("close-x")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("btn-close")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("btn-recheck")?.addEventListener("click", () => this.recheckJob());
    this.shadowRoot.getElementById("btn-cancel")?.addEventListener("click", () => this.cancelJob());
    this.shadowRoot.getElementById("backdrop")?.addEventListener("click", (e) => {
      if (e.target.id === "backdrop") this.close();
    });
  }
}

definePanelElement("esphome-ota-job-dialog", EsphomeOtaJobDialog);
