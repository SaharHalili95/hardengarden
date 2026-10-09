import { useEffect, useState } from "react";

import { CHAT_MODELS, type Settings } from "../api/types";
import { AI_LABELS } from "../components/AiIndicator";
import { DownloadDialog } from "../components/DownloadDialog";
import { useApp } from "../state";
import { applyTheme, readTheme, type Theme } from "../theme";

const LOOPBACK = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?\/?$/i;

function gib(bytes: number | null): string {
  return bytes === null ? "unknown" : `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
}

export function SettingsScreen() {
  const { client, ai, refreshAi } = useApp();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [url, setUrl] = useState("");
  const [model, setModel] = useState("auto");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [ingest, setIngest] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(readTheme());

  useEffect(() => {
    void client.settings().then((s) => {
      setSettings(s);
      setUrl(s.ollama_url);
      setModel(s.chat_model ?? "auto");
    });
  }, [client]);

  async function save() {
    setMessage(null);
    setError(null);
    if (!LOOPBACK.test(url.trim())) {
      setError(
        "The Ollama address must be on this computer: http://127.0.0.1, http://localhost or http://[::1].",
      );
      return;
    }
    try {
      const saved = await client.saveSettings(
        model === "auto"
          ? { ollama_url: url.trim(), clear_chat_model: true }
          : { ollama_url: url.trim(), chat_model: model },
      );
      setSettings(saved);
      setMessage("Settings saved.");
      await refreshAi();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Saving failed.");
    }
  }

  async function reingest() {
    setIngest("Rebuilding the search index…");
    try {
      const result = await client.ingest();
      setIngest(result.note ?? `Search index rebuilt: ${String(result.chunks)} passages.`);
    } catch (caught) {
      setIngest(caught instanceof Error ? caught.message : "Rebuilding failed.");
    }
  }

  const downloadTarget = ai?.state === "model_not_downloaded" ? ai.model : null;

  return (
    <section aria-labelledby="settings-title" className="stack">
      <h1 id="settings-title">Settings</h1>

      <section className="panel" aria-labelledby="ai-title">
        <h2 id="ai-title">Local AI</h2>
        <p>
          <strong>{ai ? AI_LABELS[ai.state] : "Checking…"}</strong>
        </p>
        {ai && (
          <>
            <p>{ai.message}</p>
            <p className="citations">
              Memory: {gib(ai.memory_total_bytes)} total, {gib(ai.memory_available_bytes)} free. CPU
              cores: {ai.cpu_cores}.{ai.gpu === true ? " GPU in use." : ""}
              {ai.model ? ` Model: ${ai.model}.` : ""}
            </p>
          </>
        )}
        {downloadTarget && (
          <button
            className="button"
            type="button"
            onClick={() => {
              setDownloading(downloadTarget);
            }}
          >
            Download {downloadTarget}
          </button>
        )}
      </section>

      <form
        className="panel"
        aria-labelledby="model-title"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <h2 id="model-title">Model and connection</h2>
        <div className="field">
          <label htmlFor="ollama-url">Ollama address</label>
          <input
            id="ollama-url"
            value={url}
            onChange={(e) => {
              setUrl(e.target.value);
            }}
            spellCheck={false}
            aria-describedby="ollama-url-hint"
          />
          <span id="ollama-url-hint" className="hint">
            Only addresses on this computer are allowed.
          </span>
        </div>
        <div className="field">
          <label htmlFor="model">Chat model</label>
          <select
            id="model"
            value={model}
            onChange={(e) => {
              setModel(e.target.value);
            }}
            aria-describedby="model-hint"
          >
            <option value="auto">Choose automatically for this computer</option>
            {CHAT_MODELS.map((m) => (
              <option key={m.name} value={m.name}>
                {m.label}
              </option>
            ))}
          </select>
          {model !== "auto" && (
            <span id="model-hint" className="hint">
              A model larger than this computer can hold may be slow or refuse to start.
            </span>
          )}
        </div>
        <button className="button" type="submit" disabled={!settings}>
          Save settings
        </button>
        <div aria-live="polite">
          {message && <p>{message}</p>}
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
        </div>
      </form>

      <section className="panel" aria-labelledby="kb-title">
        <h2 id="kb-title">Knowledge base</h2>
        <p>
          Rebuild the search index after installing a new version or downloading the embedding
          model.
        </p>
        <button className="button quiet" type="button" onClick={() => void reingest()}>
          Rebuild search index
        </button>
        <p aria-live="polite" className="citations">
          {ingest}
        </p>
      </section>

      <section className="panel" aria-labelledby="look-title">
        <h2 id="look-title">Appearance</h2>
        <div className="field">
          <label htmlFor="theme">Theme</label>
          <select
            id="theme"
            value={theme}
            onChange={(e) => {
              const t = e.target.value as Theme;
              setTheme(t);
              applyTheme(t);
            }}
          >
            <option value="system">Same as the system</option>
            <option value="light">Light</option>
            <option value="dark">Dark</option>
          </select>
        </div>
      </section>

      {downloading && (
        <DownloadDialog
          model={downloading}
          sizeBytes={ai?.model_download_bytes ?? null}
          onClose={(done) => {
            setDownloading(null);
            if (done) void refreshAi();
          }}
        />
      )}
    </section>
  );
}
