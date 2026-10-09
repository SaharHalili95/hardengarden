/** Shown when the scanner process cannot start (R35). Never a blank window. */
export function BackendError({ reason, logTail }: { reason: string; logTail: string[] }) {
  return (
    <main className="main stack" aria-labelledby="error-title">
      <h1 id="error-title">The scanner did not start</h1>
      <p className="notice danger" role="alert">
        {reason}
      </p>
      {logTail.length > 0 && (
        <section aria-labelledby="log-title">
          <h2 id="log-title">Last lines from the scanner</h2>
          <pre className="script" tabIndex={0}>
            {logTail.join("\n")}
          </pre>
        </section>
      )}
      <section aria-labelledby="fallback-title">
        <h2 id="fallback-title">Use the command-line version instead</h2>
        <p>
          The same scanner runs without the desktop app. Install uv from its documentation at
          docs.astral.sh/uv (it also provides Python 3.12), then install and run HardenGarden:
        </p>
        <pre className="script" tabIndex={0}>
          {[
            "uv tool install hardengarden-<version>-py3-none-any.whl",
            "hardengarden scan",
            "sudo $(command -v hardengarden) scan   # full coverage",
          ].join("\n")}
        </pre>
        <p>
          With pipx and Python 3.12:{" "}
          <code>
            pipx install --python python3.12 hardengarden-&lt;version&gt;-py3-none-any.whl
          </code>
          . The wheel is attached to every GitHub release.
        </p>
      </section>
    </main>
  );
}
