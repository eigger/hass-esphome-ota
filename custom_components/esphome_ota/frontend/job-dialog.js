/**
 * Job progress and log streaming dialog modal.
 */

import { t } from "./i18n.js";
import { escapeHtml } from "./html.js";
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
button.secondary:hover:not(:disabled) {
  background: color-mix(in srgb, var(--primary-text-color, #1e293b) 8%, var(--secondary-background-color, #f1f5f9));
}
/* Fixed neutral hover only for browsers without color-mix(). */
@supports not (background: color-mix(in srgb, red 10%, transparent)) {
  button.secondary:hover:not(:disabled) { background: var(--divider-color, #e2e8f0); }
}
/* Filled danger: same pairing as button.primary (darkened fill + fixed white text). */
button.danger {
  background: color-mix(in srgb, var(--error-color, #dc2626) 70%, #000);
  color: #ffffff;
  border-color: color-mix(in srgb, var(--error-color, #dc2626) 85%, var(--primary-text-color, #1e293b));
}
button.danger:hover:not(:disabled) {
  background: color-mix(in srgb, var(--error-color, #dc2626) 55%, #000);
  border-color: color-mix(in srgb, var(--error-color, #dc2626) 85%, var(--primary-text-color, #1e293b));
}
/* Fixed dark red only for browsers without color-mix(). */
@supports not (background: color-mix(in srgb, red 10%, transparent)) {
  button.danger { background: #b91c1c; border-color: #dc2626; }
  button.danger:hover:not(:disabled) { background: #991b1b; border-color: #dc2626; }
}
/* Filled single-CTA button: fill = brand colour darkened 30% (40% on hover) with fixed white
   text, independent of --text-primary-color. The default HA primary (#03a9f4) gets 5.0:1 (6.4:1
   on hover); very light brand colours can fall below 4.5:1 (known limitation). The border mixes
   toward the text colour so the edge keeps >= 3:1 against the card in light and dark themes. */
button.primary {
  background: color-mix(in srgb, var(--primary-color, #0284c7) 70%, #000);
  color: #ffffff;
  border-color: color-mix(in srgb, var(--primary-color, #0284c7) 85%, var(--primary-text-color, #1e293b));
}
button.primary:hover:not(:disabled) {
  background: color-mix(in srgb, var(--primary-color, #0284c7) 60%, #000);
  border-color: color-mix(in srgb, var(--primary-color, #0284c7) 85%, var(--primary-text-color, #1e293b));
}
/* Fixed dark primary only for browsers without color-mix(). */
@supports not (background: color-mix(in srgb, red 10%, transparent)) {
  button.primary { background: #0369a1; border-color: #0284c7; }
  button.primary:hover:not(:disabled) { background: #075985; border-color: #0284c7; }
}
`;

const ANSI_STYLES = {
  1: "font-weight: 600;",
  2: "opacity: 0.75;",
  3: "font-style: italic;",
  4: "text-decoration: underline;",
  30: "color: #94a3b8;",
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
    this._historyEpoch = 0;
    this._els = null;
    this._frame = null;
    this._resetRendered();
  }

  open(job, hass, returnFocus = undefined) {
    if (!this.isOpen) rememberModalFocus(this);
    else captureModalFocus(this);
    if (returnFocus !== undefined) this._modalReturnFocus = returnFocus;
    this._cancelFrame();
    this.job = job;
    this.hass = hass;
    this.isOpen = true;
    this._hasInitialScrolled = false;
    this._followLogs = true;
    this._historyJobId = job.job_id;
    this._logHistory = [...(job.log_tail || [])];
    this._historyTruncated = false;
    this._pendingRemovedLines = 0;
    this._historyEpoch += 1;
    this._buildSkeleton();
    this._patch();
    // Resolve focus only after conditional footer buttons exist.
    const focusTarget = this._modalFocusTarget;
    if (focusTarget) {
      const root = this.shadowRoot;
      const target = focusTarget.id
        ? root.getElementById(focusTarget.id)
        : root.querySelector(`[${focusTarget.attribute}="${focusTarget.value}"]`);
      if (!target) this._modalFocusTarget = { id: "btn-close" };
    }
    bindModalAccessibility(this, () => this.close());
  }

  close() {
    this._cancelFrame();
    this.isOpen = false;
    this._els = null;
    this._resetRendered();
    this.shadowRoot.innerHTML = "";
    restoreModalFocus(this);
  }

  updateJob(job) {
    if (!this.isOpen) return;
    if (this.job && this.job.job_id === job.job_id) {
      this._mergeLogSnapshot(job.log_tail || []);
      this.job = job;
      this._scheduleFrame();
    }
  }

  _scheduleFrame() {
    if (this._frame !== null) return;
    this._frame = requestAnimationFrame(() => {
      this._frame = null;
      this._patch();
    });
  }

  _cancelFrame() {
    if (this._frame === null) return;
    cancelAnimationFrame(this._frame);
    this._frame = null;
  }

  _mergeLogSnapshot(snapshot) {
    const incoming = Array.isArray(snapshot) ? snapshot : [];
    if (this._historyJobId !== this.job?.job_id) {
      this._historyJobId = this.job?.job_id || null;
      this._logHistory = [];
      this._historyTruncated = false;
      this._pendingRemovedLines = 0;
      this._historyEpoch += 1;
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

  _resetRendered() {
    this._renderedStrings = [];
    this._renderedEls = [];
    this._trailerEls = [];
    this._trailerKey = "";
    this._placeholderEl = null;
    this._renderedEpoch = -1;
  }

  /** Build the static dialog structure once; all listeners are bound here only. */
  _buildSkeleton() {
    this._resetRendered();
    this._bannerKey = null;
    this._titleText = null;
    this.shadowRoot.innerHTML = `
      <style>${css}</style>
      <div class="backdrop" id="backdrop">
        <div class="modal">
          <div class="header">
            <h2></h2>
            <button id="close-x" aria-label="Close">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
          <div class="body">
            <div class="stage-banner"></div>
            <div class="terminal-toolbar">
              <button class="secondary" id="btn-follow-logs" type="button" hidden>${escapeHtml(t(this.hass, "logs_jump_latest"))}</button>
            </div>
            <div class="terminal" id="terminal"></div>
          </div>
          <div class="footer">
            <button class="primary" id="btn-close">${escapeHtml(t(this.hass, "close"))}</button>
          </div>
        </div>
      </div>
    `;
    const root = this.shadowRoot;
    const els = {
      backdrop: root.getElementById("backdrop"),
      title: root.querySelector(".header h2"),
      banner: root.querySelector(".stage-banner"),
      body: root.querySelector(".body"),
      toolbar: root.querySelector(".terminal-toolbar"),
      follow: root.getElementById("btn-follow-logs"),
      terminal: root.getElementById("terminal"),
      footer: root.querySelector(".footer"),
      close: root.getElementById("btn-close"),
      notice: null,
      recheck: null,
      cancel: null,
    };
    this._els = els;

    els.terminal.addEventListener("scroll", () => {
      this._followLogs =
        els.terminal.scrollHeight - els.terminal.scrollTop - els.terminal.clientHeight < 60;
      els.follow.hidden = this._followLogs;
    }, { passive: true });
    els.follow.addEventListener("click", () => {
      els.terminal.scrollTop = els.terminal.scrollHeight;
      this._followLogs = true;
      els.follow.hidden = true;
    });
    root.getElementById("close-x").addEventListener("click", () => this.close());
    els.close.addEventListener("click", () => this.close());
    let mouseDownTarget = null;
    els.backdrop.addEventListener("mousedown", (e) => {
      mouseDownTarget = e.target;
    });
    els.backdrop.addEventListener("click", (e) => {
      if (e.target.id === "backdrop" && mouseDownTarget?.id === "backdrop") {
        this.close();
      }
      mouseDownTarget = null;
    });
  }

  /** Apply the latest job state to the existing DOM without replacing controls. */
  _patch() {
    if (!this.isOpen || !this.job || !this._els) return;
    const stage = this.job.stage || "preparing";

    this._patchHeader(stage);
    this._patchFooter(stage);
    this._patchTerminal(stage);
  }

  _patchHeader(stage) {
    const els = this._els;
    const title = `${t(this.hass, "logs_title")} - ${this.job.configuration}`;
    if (title !== this._titleText) {
      this._titleText = title;
      els.title.textContent = title;
    }

    const stageText = t(this.hass, `stage_${stage}`) || stage;
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
    const version = this.job.reserved_version || "";
    const error = this.job.error || "";
    const key = [stageClass, stageText, version, error].join("\u0000");
    if (key === this._bannerKey) return;
    this._bannerKey = key;
    els.banner.className = stageClass;
    els.banner.innerHTML = `
      <span><strong>${escapeHtml(t(this.hass, "job_status"))}:</strong> ${escapeHtml(stageText)}</span>
      ${version ? `<span>(${escapeHtml(t(this.hass, "target_version"))}: ${escapeHtml(version)})</span>` : ""}
      ${error ? `<span> — ${escapeHtml(error)}</span>` : ""}
    `;
  }

  _syncNotice() {
    const els = this._els;
    if (this._historyTruncated && !els.notice) {
      const notice = document.createElement("div");
      notice.className = "log-history-notice";
      notice.setAttribute("role", "status");
      notice.textContent = t(this.hass, "logs_history_truncated");
      els.body.insertBefore(notice, els.toolbar);
      els.notice = notice;
    } else if (!this._historyTruncated && els.notice) {
      els.notice.remove();
      els.notice = null;
    }
  }

  _patchFooter(stage) {
    const els = this._els;
    const isRunning = ["preparing", "validating", "submitting", "queued", "building", "downloading", "verifying", "publishing"].includes(stage);
    const isRecovery = stage === "recovery_required";
    const active = this.shadowRoot.activeElement;
    let focusLost = false;

    const sync = (name, id, cls, labelKey, visible, handler) => {
      if (visible && !els[name]) {
        const button = document.createElement("button");
        button.id = id;
        button.className = cls;
        button.textContent = t(this.hass, labelKey);
        button.addEventListener("click", handler);
        els.footer.insertBefore(button, name === "recheck" ? (els.cancel || els.close) : els.close);
        els[name] = button;
      } else if (!visible && els[name]) {
        if (active === els[name]) focusLost = true;
        els[name].remove();
        els[name] = null;
      }
    };
    sync("recheck", "btn-recheck", "secondary", "logs_retry_btn", isRecovery, () => this.recheckJob());
    sync("cancel", "btn-cancel", "danger", "logs_cancel_btn", isRunning || isRecovery, () => this.cancelJob());
    if (focusLost) els.close.focus();
  }

  _lineElement(line) {
    const el = document.createElement("div");
    el.className = "log-line";
    el.innerHTML = ansiToHtml(line) || "&nbsp;";
    return el;
  }

  _patchTerminal(stage) {
    const els = this._els;
    const term = els.terminal;
    const history = this._logHistory;

    if (this._hasInitialScrolled) {
      this._followLogs = term.scrollHeight - term.scrollTop - term.clientHeight < 60;
    }
    const previousScrollTop = term.scrollTop;

    // Drop lines that were trimmed from the head of the history.
    let removedHeight = 0;
    const removeCount = Math.min(this._pendingRemovedLines, this._renderedEls.length);
    if (removeCount > 0) {
      for (const el of this._renderedEls.slice(0, removeCount)) {
        removedHeight += el.getBoundingClientRect().height;
        el.remove();
      }
      this._renderedEls.splice(0, removeCount);
      this._renderedStrings.splice(0, removeCount);
    }
    this._pendingRemovedLines = 0;

    // Verify the rendered lines are still a prefix of the history; otherwise rebuild.
    const rendered = this._renderedStrings;
    const consistent =
      this._renderedEpoch === this._historyEpoch &&
      rendered.length <= history.length &&
      (rendered.length === 0 ||
        (rendered[0] === history[0] && rendered[rendered.length - 1] === history[rendered.length - 1]));
    let rebuilt = false;
    if (!consistent) {
      term.textContent = "";
      this._resetRendered();
      this._renderedEpoch = this._historyEpoch;
      removedHeight = 0;
      rebuilt = true;
    }

    const trailer =
      this.job.error && (stage === "failed" || stage === "cancelled")
        ? ["", "", `\x1b[31;1m[ERROR] ${this.job.error}\x1b[0m`]
        : [];
    const trailerKey = trailer.join("\n");
    const newLines = history.slice(this._renderedStrings.length);
    const needPlaceholder = !history.length && !trailer.length;
    const placeholderOk = needPlaceholder === Boolean(this._placeholderEl);

    if (newLines.length || trailerKey !== this._trailerKey || !placeholderOk) {
      // Trailer and placeholder always sit after the history lines.
      for (const el of this._trailerEls) el.remove();
      this._trailerEls = [];
      this._placeholderEl?.remove();
      this._placeholderEl = null;

      const fragment = document.createDocumentFragment();
      for (const line of newLines) {
        const el = this._lineElement(line);
        this._renderedEls.push(el);
        this._renderedStrings.push(line);
        fragment.appendChild(el);
      }
      for (const line of trailer) {
        const el = this._lineElement(line);
        this._trailerEls.push(el);
        fragment.appendChild(el);
      }
      if (needPlaceholder) {
        this._placeholderEl = this._lineElement(t(this.hass, "logs_waiting_output"));
        fragment.appendChild(this._placeholderEl);
      }
      term.appendChild(fragment);
      this._trailerKey = trailerKey;
    }

    if (this._followLogs || !this._hasInitialScrolled) {
      term.scrollTop = term.scrollHeight;
      this._hasInitialScrolled = true;
      this._followLogs = true;
    } else if (removedHeight > 0 || rebuilt) {
      const anchorExpired = previousScrollTop < removedHeight;
      term.scrollTop = Math.max(0, previousScrollTop - removedHeight);
      if (anchorExpired) this._historyTruncated = true;
    }
    this._syncNotice();
    els.follow.hidden = this._followLogs;
  }
}

definePanelElement("esphome-ota-job-dialog", EsphomeOtaJobDialog);
