// Remembers per device whether this person prefers simple mode. Storage can be blocked (private mode),
// so every access is guarded and the full view is the fallback.
const KEY = "msme.ui-mode";

export type UiMode = "simple" | "full";

export function getUiMode(): UiMode {
  try {
    return window.localStorage.getItem(KEY) === "simple" ? "simple" : "full";
  } catch {
    return "full";
  }
}

export function setUiMode(mode: UiMode) {
  try {
    window.localStorage.setItem(KEY, mode);
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
}
