"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

type Mode = "system" | "light" | "dark";
const ORDER: Mode[] = ["system", "light", "dark"];

function readMode(): Mode {
  const t = document.documentElement.dataset.theme;
  return t === "light" || t === "dark" ? t : "system";
}

function subscribe(onChange: () => void) {
  window.addEventListener("msme:theme", onChange);
  return () => window.removeEventListener("msme:theme", onChange);
}

export function ThemeToggle() {
  const mode = useSyncExternalStore<Mode>(subscribe, readMode, () => "system");
  const cycle = () => {
    const next = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
    const root = document.documentElement;
    try {
      if (next === "system") {
        delete root.dataset.theme;
        localStorage.removeItem("msme.theme");
      } else {
        root.dataset.theme = next;
        localStorage.setItem("msme.theme", next);
      }
    } catch {
      if (next === "system") delete root.dataset.theme;
      else root.dataset.theme = next;
    }
    window.dispatchEvent(new Event("msme:theme"));
  };
  const Icon = mode === "dark" ? Moon : mode === "light" ? Sun : Monitor;
  return (
    <button
      onClick={cycle}
      className="rounded-lg p-2 text-ink-2 hover:bg-surface-2 hover:text-ink"
      aria-label={`Theme: ${mode}. Click to change.`}
      title={`Theme: ${mode}`}
    >
      <Icon className="h-4 w-4" />
    </button>
  );
}
