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
  color: #38bdf8;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.8rem;
  line-height: 1.45;
  padding: 14px;
  border-radius: 8px;
  height: 380px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
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

class EsphomeOtaJobDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.job = null;
    this.hass = null;
    this.isOpen = false;
  }

  open(job, hass) {
    this.job = job;
    this.hass = hass;
    this.isOpen = true;
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
    if (!logs) {
      if ((stage === "failed" || stage === "cancelled") && this.job.error) {
        logs = this.job.error;
      } else if (stage === "failed" || stage === "cancelled") {
        logs = stageText;
      } else {
        logs = "Waiting for compiler output...";
      }
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
              ${this.job.error && stage !== "failed" && stage !== "cancelled" ? `<span> — ${escapeHtml(this.job.error)}</span>` : ""}
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
      terminalEl.textContent = logs;
      terminalEl.scrollTop = terminalEl.scrollHeight;
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
