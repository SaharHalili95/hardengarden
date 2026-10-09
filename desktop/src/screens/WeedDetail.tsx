import { useEffect, useState } from "react";

import { copyText } from "../api/backend";
import { StreamedAnswer } from "../components/Answer";
import { Plant, STATUS_WORDS } from "../components/Plant";
import { useApp } from "../state";

export function WeedDetail({ checkId }: { checkId: string }) {
  const { scan, checks, client, go } = useApp();
  const meta = checks.find((c) => c.id === checkId);
  const result = scan?.report.results.find((r) => r.check_id === checkId);
  const [script, setScript] = useState<string | null | undefined>(undefined);
  const [copied, setCopied] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    let alive = true;
    client.remediation(checkId).then(
      (text) => {
        if (alive) setScript(text);
      },
      () => {
        if (alive) setScript(null);
      },
    );
    return () => {
      alive = false;
    };
  }, [client, checkId]);

  if (!meta || !result || !scan) {
    return (
      <section>
        <h1>Check not found</h1>
        <button
          className="button"
          type="button"
          onClick={() => {
            go({ name: "weeds" });
          }}
        >
          Back to weeds
        </button>
      </section>
    );
  }

  async function copy(text: string) {
    try {
      await copyText(text);
      setCopied("copied");
    } catch {
      setCopied("failed");
    }
  }

  return (
    <article aria-labelledby="weed-title" className="stack">
      <div>
        <button
          className="button quiet"
          type="button"
          onClick={() => {
            go({ name: "weeds" });
          }}
        >
          Back to weeds
        </button>
      </div>
      <header className="row">
        <Plant status={result.status} size={56} />
        <div>
          <h1 id="weed-title">{meta.title}</h1>
          <p className="citations">
            <span className={`status-tag status-${result.status}`}>
              {STATUS_WORDS[result.status]}
            </span>
            {", "}
            {meta.severity.toLowerCase()} severity, {meta.id}
          </p>
        </div>
      </header>
      <p>{meta.rationale}</p>

      <section aria-labelledby="evidence-title">
        <h2 id="evidence-title">What the scan found</h2>
        {result.evidence.length === 0 ? (
          <p>No details recorded.</p>
        ) : (
          <ul className="evidence mono">
            {result.evidence.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
        {result.reason && <p className="citations">Reason: {result.reason.replaceAll("_", " ")}</p>}
      </section>

      <section aria-labelledby="explain-title" className="panel">
        <h2 id="explain-title">Explain this</h2>
        <p className="citations">
          A local model explains the finding using HardenGarden&apos;s knowledge base, with sources.
        </p>
        <StreamedAnswer
          label="Explain"
          start={(onEvent, signal) => client.explain(scan.id, checkId, onEvent, signal)}
        />
      </section>

      <section aria-labelledby="fix-title">
        <h2 id="fix-title">How to fix it</h2>
        {script === undefined && <p>Loading the remediation script…</p>}
        {script === null && (
          <p>
            There is no single safe script for this check. Read the explanation and fix each item by
            hand.
          </p>
        )}
        {script && (
          <>
            <p className="notice danger" role="note">
              Review before running. HardenGarden never runs this script. It changes nothing unless
              you run it as root with HG_APPLY=1, and it backs up every file it edits.
            </p>
            <div className="row spaced">
              <button className="button" type="button" onClick={() => void copy(script)}>
                Copy script
              </button>
              <span aria-live="polite" className="citations">
                {copied === "copied"
                  ? "Copied to the clipboard."
                  : copied === "failed"
                    ? "Copy failed: select the text instead."
                    : ""}
              </span>
            </div>
            <pre className="script" tabIndex={0} aria-label={`Remediation script for ${meta.id}`}>
              {script}
            </pre>
          </>
        )}
      </section>
    </article>
  );
}
