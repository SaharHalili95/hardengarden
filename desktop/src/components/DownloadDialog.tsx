import { useEffect, useRef, useState } from "react";

import type { PullEvent } from "../api/types";
import { useApp } from "../state";

function gigabytes(bytes: number): string {
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

/** Explicit, cancellable model download (R37). Nothing downloads until "Download" is clicked. */
export function DownloadDialog({
  model,
  sizeBytes,
  onClose,
}: {
  model: string;
  sizeBytes: number | null;
  onClose: (downloaded: boolean) => void;
}) {
  const { client } = useApp();
  const dialog = useRef<HTMLDialogElement>(null);
  const controller = useRef<AbortController | null>(null);
  const [progress, setProgress] = useState<{ completed: number; total: number } | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const element = dialog.current;
    // jsdom (unit tests) has no showModal; real webviews always do.
    if (element && !element.open && "showModal" in element) element.showModal();
    return () => controller.current?.abort();
  }, []);

  async function download() {
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setError(null);
    const outcome = { finished: false };
    try {
      await client.pull(
        model,
        (event: PullEvent) => {
          if (event.type === "progress") {
            setStatus(event.status);
            if (event.total) setProgress({ completed: event.completed ?? 0, total: event.total });
          } else if (event.type === "done") outcome.finished = !event.cancelled;
          else setError(event.detail);
        },
        current.signal,
      );
    } catch (caught) {
      if (!current.signal.aborted)
        setError(caught instanceof Error ? caught.message : "Download failed.");
    } finally {
      setBusy(false);
    }
    if (outcome.finished) onClose(true);
  }

  return (
    <dialog
      ref={dialog}
      aria-labelledby="download-title"
      onCancel={() => {
        onClose(false);
      }}
    >
      <h2 id="download-title">Download {model}</h2>
      <p>
        Ollama downloads this model to your computer
        {sizeBytes ? ` (about ${gigabytes(sizeBytes)})` : ""}. It runs locally; HardenGarden sends
        nothing anywhere.
      </p>
      {busy && (
        <div>
          <p>{status ?? "Starting"}</p>
          <progress
            max={progress?.total ?? 1}
            value={progress?.completed ?? 0}
            aria-label="Download progress"
          />
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="row">
        {busy ? (
          <button
            className="button quiet"
            type="button"
            onClick={() => controller.current?.abort()}
          >
            Cancel download
          </button>
        ) : (
          <>
            <button className="button" type="button" onClick={() => void download()}>
              Download
            </button>
            <button
              className="button quiet"
              type="button"
              onClick={() => {
                onClose(false);
              }}
            >
              Not now
            </button>
          </>
        )}
      </div>
    </dialog>
  );
}
