/**
 * Job progress and log streaming dialog modal.
 */

import { t } from "./i18n.js";
import { bindModalAccessibility, captureModalFocus, definePanelElement, rememberModalFocus, restoreModalFocus } from "./elements.js";

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
.terminal-toolbar {
  display: flex;
  justify-content: flex-end;
  min-height: 30px;
}
.terminal-toolbar button {
  padding: 4px 10px;
  font-size: 0.8rem;
}
.terminal-toolbar button[hidden] {
  display: none;
}
.log-history-notice {
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--secondary-background-color, #f1f5f9);
  color: var(--secondary-text-color, #64748b);
  font-size: 0.82rem;
}
.log-line {
  min-height: 1.45em;
}
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
button.secondary {
  background: var(--secondary-background-color, #f1f5f9);
  color: var(--primary-text-color, #1e293b);
  border-color: var(--divider-color, #cbd5e1);
}
button.secondary:hover {
  background: #e2e8f0;
}
button.danger {
  background: color-mix(in srgb, var(--error-color, #dc2626) 70%, #000);
  color: var(--text-primary-color, #ffffff);
  border-color: color-mix(in srgb, var(--error-color, #dc2626) 70%, #000);
}
button.danger:hover {
  background: color-mix(in srgb, var(--error-color, #dc2626) 55%, #000);
  border-color: color-mix(in srgb, var(--error-color, #dc2626) 55%, #000);
}
/* Fixed dark red only for browsers without color-mix(). */
@supports not (background: color-mix(in srgb, red 10%, transparent)) {
  button.danger { background: #b91c1c; border-color: #b91c1c; }
  button.danger:hover { background: #991b1b; border-color: #991b1b; }
}
button.primary {
  background: color-mix(in srgb, var(--primary-color, #0284c7) 70%, #000);
  color: var(--text-primary-color, #ffffff);
  border-color: color-mix(in srgb, var(--primary-color, #0284c7) 70%, #000);
}
button.primary:hover {
  opacity: 0.92;
  border-color: color-mix(in srgb, var(--primary-color, #0284c7) 70%, #000);
}
/* Fixed dark primary only for browsers without color-mix(). */
@supports not (background: color-mix(in srgb, red 10%, transparent)) {
  button.primary, button.primary:hover { background: #0369a1; border-color: #0369a1; }
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
    this._followLogs = true;
    this._logHistory = [];
    this._historyJobId = null;
    this._historyTruncated = false;
    this._pendingRemovedLines = 0;
  }

  open(job, hass, returnFocus = undefined) {
    if (!this.isOpen) rememberModalFocus(this);
    if (returnFocus !== undefined) this._modalReturnFocus = returnFocus;
    this.job = job;
    this.hass = hass;
    this.isOpen = true;
    this._hasInitialScrolled = false;
    this._followLogs = true;
    this._historyJobId = job.job_id;
    this._logHistory = [...(job.log_tail || [])];
    this._historyTruncated = false;
    this._pendingRemovedLines = 0;
    this.render();
  }

  close() {
    this.isOpen = false;
    this.render();
    restoreModalFocus(this);
  }

  updateJob(job) {
    if (!this.isOpen) return;
    if (this.job && this.job.job_id === job.job_id) {
      this._mergeLogSnapshot(job.log_tail || []);
      this.job = job;
      this.render();
    }
  }

  _mergeLogSnapshot(snapshot) {
    const incoming = Array.isArray(snapshot) ? snapshot : [];
    if (this._historyJobId !== this.job?.job_id) {
      this._historyJobId = this.job?.job_id || null;
      this._logHistory = [];
      this._historyTruncated = false;
      this._pendingRemovedLines = 0;
    }
    if (!incoming.length) return;
    if (!this._logHistory.length) {
      this._logHistory = [...incoming];
      return;
    }

    // The server sends a rolling 200-line snapshot. Merge its longest overlap
    // with our accumulated tail so repeated snapshots do not duplicate lines.
    const maxOverlap = Math.min(this._logHistory.length, incoming.length);
    let overlap = 0;
    for (let size = maxOverlap; size > 0; size -= 1) {
      const historyStart = this._logHistory.length - size;
      let matches = true;
      for (let i = 0; i < size; i += 1) {
        if (this._logHistory[historyStart + i] !== incoming[i]) {
          matches = false;
          break;
        }
      }
      if (matches) {
        overlap = size;
        break;
      }
    }

    if (overlap === 0) this._historyTruncated = true;
    this._logHistory.push(...incoming.slice(overlap));
    const maxHistoryLines = 2000;
    if (this._logHistory.length > maxHistoryLines) {
      const removed = this._logHistory.length - maxHistoryLines;
      this._logHistory.splice(0, removed);
      this._pendingRemovedLines += removed;
      this._historyTruncated = true;
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

    const previousTerminal = this.shadowRoot.getElementById("terminal");
    const previousScrollTop = previousTerminal?.scrollTop || 0;
    let removedHeight = 0;
    if (previousTerminal && this._pendingRemovedLines > 0) {
      const oldLines = [...previousTerminal.querySelectorAll(".log-line")];
      removedHeight = oldLines
        .slice(0, this._pendingRemovedLines)
        .reduce((height, line) => height + line.getBoundingClientRect().height, 0);
    }
    if (previousTerminal) {
      this._followLogs =
        previousTerminal.scrollHeight - previousTerminal.scrollTop - previousTerminal.clientHeight < 60;
    }

    const stage = this.job.stage || "preparing";
    const stageText = t(this.hass, `stage_${stage}`) || stage;
    const logLines = [...this._logHistory];
    if (this.job.error && (stage === "failed" || stage === "cancelled")) {
      logLines.push("", "", `\x1b[31;1m[ERROR] ${this.job.error}\x1b[0m`);
    }
    if (!logLines.length) logLines.push(t(this.hass, "logs_waiting_output"));

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

    captureModalFocus(this);
    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <div class="backdrop" id="backdrop">
        <div class="modal">
          <div class="header">
            <h2>${escapeHtml(t(this.hass, "logs_title"))} - ${escapeHtml(this.job.configuration)}</h2>
            <button id="close-x" aria-label="Close">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
          <div class="body">
            <div class="${stageClass}">
              <span><strong>${escapeHtml(t(this.hass, "job_status"))}:</strong> ${escapeHtml(stageText)}</span>
              ${this.job.reserved_version ? `<span>(${escapeHtml(t(this.hass, "target_version"))}: ${escapeHtml(this.job.reserved_version)})</span>` : ""}
              ${this.job.error ? `<span> — ${escapeHtml(this.job.error)}</span>` : ""}
            </div>
            ${this._historyTruncated ? `<div class="log-history-notice" role="status">${escapeHtml(t(this.hass, "logs_history_truncated"))}</div>` : ""}
            <div class="terminal-toolbar">
              <button class="secondary" id="btn-follow-logs" type="button" hidden>${escapeHtml(t(this.hass, "logs_jump_latest"))}</button>
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
    const followButton = this.shadowRoot.getElementById("btn-follow-logs");
    if (terminalEl) {
      terminalEl.innerHTML = logLines
        .map((line) => `<div class="log-line">${ansiToHtml(line) || "&nbsp;"}</div>`)
        .join("");
      if (this._followLogs || !this._hasInitialScrolled) {
        terminalEl.scrollTop = terminalEl.scrollHeight;
        this._hasInitialScrolled = true;
        this._followLogs = true;
      } else {
        const anchorExpired = previousScrollTop < removedHeight;
        terminalEl.scrollTop = Math.max(0, previousScrollTop - removedHeight);
        if (anchorExpired) {
          this._historyTruncated = true;
          const notice = this.shadowRoot.querySelector(".log-history-notice");
          if (notice) notice.textContent = t(this.hass, "logs_history_truncated");
          else {
            const body = this.shadowRoot.querySelector(".body");
            const newNotice = document.createElement("div");
            newNotice.className = "log-history-notice";
            newNotice.setAttribute("role", "status");
            newNotice.textContent = t(this.hass, "logs_history_truncated");
            body?.insertBefore(newNotice, this.shadowRoot.querySelector(".terminal-toolbar"));
          }
        }
      }
      this._pendingRemovedLines = 0;

      followButton.hidden = this._followLogs;
      terminalEl.addEventListener("scroll", () => {
        this._followLogs =
          terminalEl.scrollHeight - terminalEl.scrollTop - terminalEl.clientHeight < 60;
        followButton.hidden = this._followLogs;
      }, { passive: true });
      followButton.addEventListener("click", () => {
        terminalEl.scrollTop = terminalEl.scrollHeight;
        this._followLogs = true;
        followButton.hidden = true;
      });
    }

    const focusTarget = this._modalFocusTarget;
    if (focusTarget) {
      const target = focusTarget.id
        ? this.shadowRoot.getElementById(focusTarget.id)
        : this.shadowRoot.querySelector(`[${focusTarget.attribute}="${focusTarget.value}"]`);
      if (!target || target.hidden || target.getAttribute("aria-hidden") === "true") {
        this._modalFocusTarget = { id: "btn-close" };
      }
    }
    bindModalAccessibility(this, () => this.close());

    this.shadowRoot.getElementById("close-x")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("btn-close")?.addEventListener("click", () => this.close());
    this.shadowRoot.getElementById("btn-recheck")?.addEventListener("click", () => this.recheckJob());
    this.shadowRoot.getElementById("btn-cancel")?.addEventListener("click", () => this.cancelJob());
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
  }
}

definePanelElement("esphome-ota-job-dialog", EsphomeOtaJobDialog);
