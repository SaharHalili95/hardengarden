import { useState } from "react";

import type { AiState } from "../api/types";
import { useApp } from "../state";

export const AI_LABELS: Record<AiState, string> = {
  ready: "AI ready",
  reduced_quality: "AI: reduced quality",
  not_enough_memory: "AI: not enough memory",
  model_not_downloaded: "AI: model not downloaded",
  ollama_not_installed: "AI: Ollama not installed",
  disabled: "AI disabled",
};

export function AiIndicator() {
  const { ai, go } = useApp();
  const [open, setOpen] = useState(false);
  const state: AiState = ai?.state ?? "ollama_not_installed";
  return (
    <div className="ai-status">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => {
          setOpen((v) => !v);
        }}
      >
        <span className={`dot ${state}`} aria-hidden="true" />
        {AI_LABELS[state]}
      </button>
      {open && (
        <div className="panel">
          <p>{ai?.message ?? "Checking for a local AI model."}</p>
          <button
            className="button quiet"
            type="button"
            onClick={() => {
              go({ name: "settings" });
            }}
          >
            Open AI settings
          </button>
        </div>
      )}
    </div>
  );
}
