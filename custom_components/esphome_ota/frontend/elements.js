/**
 * Safe custom element registration for panel modules that may load more than once
 * (integration reload, version bump, or HA frontend module cache).
 */

export function definePanelElement(name, constructor) {
  if (customElements.get(name)) {
    return;
  }
  customElements.define(name, constructor);
}

export function rememberModalFocus(host) {
  if (host._modalReturnFocus) return;
  const root = host.getRootNode();
  host._modalReturnFocus = root.activeElement || host.ownerDocument?.activeElement || null;
  host._modalNeedsFocus = true;
}

export function captureModalFocus(host) {
  const modal = host.shadowRoot?.querySelector(".modal");
  const active = host.shadowRoot?.activeElement;
  if (!modal || !active || !modal.contains(active) || active === modal) return;
  const tab = active.getAttribute?.("data-tab");
  host._modalFocusTarget = active.id
    ? { id: active.id }
    : tab
      ? { attribute: "data-tab", value: tab }
      : null;
}

export function restoreModalFocus(host) {
  const target = host._modalReturnFocus;
  host._modalReturnFocus = null;
  if (target?.isConnected && typeof target.focus === "function") {
    queueMicrotask(() => target.focus());
  }
}

export function bindModalAccessibility(host, onClose) {
  const modal = host.shadowRoot?.querySelector(".modal");
  if (!modal) return;
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("tabindex", "-1");
  const title = modal.querySelector("h1, h2, h3");
  if (title) {
    title.id ||= "modal-title";
    modal.setAttribute("aria-labelledby", title.id);
  }
  modal.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...modal.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter((element) => element.getClientRects().length > 0);
    if (!focusable.length) {
      event.preventDefault();
      modal.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (host.shadowRoot.activeElement === first || host.shadowRoot.activeElement === modal || !modal.contains(host.shadowRoot.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (host.shadowRoot.activeElement === last || host.shadowRoot.activeElement === modal || !modal.contains(host.shadowRoot.activeElement))) {
      event.preventDefault();
      first.focus();
    }
  });
  if (host._modalNeedsFocus) {
    host._modalNeedsFocus = false;
    queueMicrotask(() => {
      const currentModal = host.shadowRoot?.querySelector(".modal");
      if (!currentModal) return;
      const first = currentModal.querySelector(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      );
      (first || currentModal).focus();
    });
    return;
  }
  if (host._modalFocusTarget) {
    const target = host._modalFocusTarget;
    host._modalFocusTarget = null;
    const element = target.id
      ? host.shadowRoot.getElementById(target.id)
      : host.shadowRoot.querySelector(`[${target.attribute}="${target.value}"]`);
    element?.focus();
  }
}
