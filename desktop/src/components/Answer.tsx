import { useEffect, useRef, useState } from "react";

import type { Answer, AnswerEvent } from "../api/types";

export type Streamer = (
  onEvent: (event: AnswerEvent) => void,
  signal: AbortSignal,
) => Promise<void>;

const OUTCOME_HELP: Partial<Record<Answer["outcome"], string>> = {
  ungrounded: "The answer could not be checked against the knowledge base, so it is hidden.",
  timeout: "The model took too long. A smaller model answers faster (Settings).",
  cancelled: "Stopped.",
};

/** Runs a streamed answer with a working Stop button (R38). Text is rendered as plain text. */
export function StreamedAnswer({
  start,
  label,
  onDone,
}: {
  start: Streamer;
  label: string;
  onDone?: (answer: Answer | null) => void;
}) {
  const [draft, setDraft] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  async function run() {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setDraft("");
    setAnswer(null);
    setError(null);
    setRunning(true);
    let final: Answer | null = null;
    try {
      await start((event) => {
        if (event.type === "delta") setDraft((text) => text + event.text);
        else if (event.type === "final") {
          final = event.answer;
          setAnswer(event.answer);
        } else setError(event.detail);
      }, current.signal);
    } catch (caught) {
      if (current.signal.aborted) {
        final = {
          outcome: "cancelled",
          text: "Stopped.",
          citations: [],
          model: null,
          cached: false,
        };
        setAnswer(final);
      } else setError(caught instanceof Error ? caught.message : "The request failed.");
    } finally {
      setRunning(false);
      onDone?.(final);
    }
  }

  const shown = answer
    ? answer.outcome === "answered"
      ? answer.text
      : answer.text || draft
    : draft;
  const help = answer ? OUTCOME_HELP[answer.outcome] : undefined;

  return (
    <div>
      <div className="row">
        <button className="button" type="button" onClick={() => void run()} disabled={running}>
          {running ? "Answering…" : label}
        </button>
        {running && (
          <button
            className="button quiet"
            type="button"
            onClick={() => controller.current?.abort()}
          >
            Stop
          </button>
        )}
      </div>
      <div aria-live="polite" aria-busy={running}>
        {shown && <p className="answer">{shown}</p>}
        {help && answer?.outcome !== "cancelled" && <p className="citations">{help}</p>}
        {answer && answer.citations.length > 0 && (
          <p className="citations">
            Sources: {answer.citations.join(", ")}
            {answer.cached ? " (saved answer)" : ""}
          </p>
        )}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
