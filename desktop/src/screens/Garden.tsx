import type { CheckMeta, CheckResult } from "../api/types";
import { Plant, STATUS_WORDS } from "../components/Plant";
import { useApp } from "../state";

export function Garden() {
  const { scan, scanning, scanError, runScan, checks, go } = useApp();
  const byId = new Map(checks.map((c) => [c.id, c]));

  if (!scan) {
    return (
      <section aria-labelledby="garden-title" className="stack">
        <h1 id="garden-title">Survey this garden</h1>
        <p>
          HardenGarden reads this computer&apos;s security settings and changes nothing. A scan
          takes a few seconds.
        </p>
        <div>
          <button
            className="button"
            type="button"
            onClick={() => void runScan()}
            disabled={scanning}
          >
            {scanning ? "Scanning…" : "Scan this computer"}
          </button>
        </div>
        {scanError && (
          <p className="error-text" role="alert">
            {scanError}
          </p>
        )}
      </section>
    );
  }

  const { report } = scan;
  const { score, coverage } = report.summary;
  const weeds = report.results.filter((r) => r.status === "FAIL" || r.status === "WARN").length;

  return (
    <section aria-labelledby="garden-title" className="stack">
      <div className="row spread">
        <h1 id="garden-title">{report.platform.pretty_name}</h1>
        <button
          className="button quiet"
          type="button"
          onClick={() => void runScan()}
          disabled={scanning}
        >
          {scanning ? "Scanning…" : "Scan again"}
        </button>
      </div>
      {!report.platform_supported && (
        <p className="notice">
          This system is not a supported platform. Checks that depend on Ubuntu or Debian are marked
          not applicable. Supported: Ubuntu 22.04, Ubuntu 24.04, Debian 12.
        </p>
      )}
      <div className="survey">
        <div className="stack">
          <div className="bed">
            <h2 className="visually-hidden">Checks</h2>
            <ul aria-label="Garden bed">
              {report.results.map((result) => (
                <PlantButton
                  key={result.check_id}
                  result={result}
                  meta={byId.get(result.check_id)}
                  onOpen={() => {
                    go({ name: "weed", checkId: result.check_id });
                  }}
                />
              ))}
            </ul>
          </div>
          <WeedsToPull />
        </div>
        <div>
          <h2>Garden Health</h2>
          <p className="score" data-testid="score">
            {score === null ? (
              "Not enough data"
            ) : (
              <>
                {score}
                <small> / 100</small>
              </>
            )}
          </p>
          <p>
            {weeds === 0
              ? "No weeds found."
              : `${String(weeds)} ${weeds === 1 ? "weed" : "weeds"} to look at.`}
          </p>
          <p className="citations">
            {coverage.evaluated} of {coverage.total} checks evaluated
            {coverage.percent === null ? "" : ` (${String(coverage.percent)}% coverage)`}.
          </p>
          {report.privilege_hint && <p className="notice">{report.privilege_hint}.</p>}
          <ul className="legend" aria-label="Legend">
            {(["PASS", "WARN", "FAIL", "SKIPPED", "NOT_APPLICABLE"] as const).map((s) => (
              <li key={s}>
                <Plant status={s} size={22} /> {STATUS_WORDS[s]}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function WeedsToPull() {
  const { scan, checks, go } = useApp();
  if (!scan) return null;
  const titles = new Map(checks.map((c) => [c.id, c.title]));
  const weeds = scan.report.results.filter((r) => r.status === "FAIL" || r.status === "WARN");
  return (
    <section aria-labelledby="pull-title">
      <h2 id="pull-title">Weeds to look at</h2>
      {weeds.length === 0 ? (
        <p>Nothing to pull. Scan again after you change the system.</p>
      ) : (
        <ul className="weeds">
          {weeds
            .sort((a, b) => (a.status === b.status ? 0 : a.status === "FAIL" ? -1 : 1))
            .map((r) => (
              <li key={r.check_id}>
                <button
                  type="button"
                  className="compact"
                  onClick={() => {
                    go({ name: "weed", checkId: r.check_id });
                  }}
                >
                  <Plant status={r.status} size={28} />
                  <span className={`status-tag status-${r.status}`}>{STATUS_WORDS[r.status]}</span>
                  <span>{titles.get(r.check_id) ?? r.check_id}</span>
                </button>
              </li>
            ))}
        </ul>
      )}
    </section>
  );
}

function PlantButton({
  result,
  meta,
  onOpen,
}: {
  result: CheckResult;
  meta: CheckMeta | undefined;
  onOpen: () => void;
}) {
  const label = `${result.check_id} ${meta?.title ?? ""}: ${STATUS_WORDS[result.status]}`;
  return (
    <li>
      <button className="plant" type="button" onClick={onOpen} aria-label={label} title={label}>
        <Plant status={result.status} size={68} />
        <span className="plant-id" aria-hidden="true">
          {result.check_id.replace("HG-", "")}
        </span>
      </button>
    </li>
  );
}
