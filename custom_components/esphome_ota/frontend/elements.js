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
