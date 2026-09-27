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

// Whether simple mode reads its screens aloud (on unless the person turned it off on this device).
const SPEECH_KEY = "msme.simple-speech";

export function getSpeechOn(): boolean {
  try {
    return window.localStorage.getItem(SPEECH_KEY) !== "off";
  } catch {
    return true;
  }
}

export function setSpeechOn(on: boolean) {
  try {
    window.localStorage.setItem(SPEECH_KEY, on ? "on" : "off");
  } catch {
    /* storage unavailable: the choice lasts for this page only */
  }
}
