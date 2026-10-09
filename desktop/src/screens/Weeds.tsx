import { useState } from "react";

import type { Severity, Status } from "../api/types";
import { Plant, STATUS_WORDS } from "../components/Plant";
import { useApp } from "../state";

const SEVERITY_ORDER: Severity[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
const SEVERITY_WORDS: Record<Severity, string> = {
  CRITICAL: "Critical",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
  INFO: "Info",
};
const STATUS_RANK: Record<Status, number> = {
  FAIL: 0,
  WARN: 1,
  ERROR: 2,
  SKIPPED: 3,
  PASS: 4,
  NOT_APPLICABLE: 5,
};

export function Weeds() {
  const { scan, checks, go } = useApp();
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [category, setCategory] = useState("all");
  const [onlyWeeds, setOnlyWeeds] = useState(true);

  if (!scan) {
    return (
      <section aria-labelledby="weeds-title">
        <h1 id="weeds-title">Weeds</h1>
        <p>Run a scan from the Garden page first.</p>
        <button
          className="button"
          type="button"
          onClick={() => {
            go({ name: "garden" });
          }}
        >
          Go to Garden
        </button>
      </section>
    );
  }

  const meta = new Map(checks.map((c) => [c.id, c]));
  const categories = [...new Set(checks.map((c) => c.category))].sort();
  const rows = scan.report.results
    .filter((r) => !onlyWeeds || r.status === "FAIL" || r.status === "WARN")
    .filter((r) => severity === "all" || meta.get(r.check_id)?.severity === severity)
    .filter((r) => category === "all" || meta.get(r.check_id)?.category === category)
    .sort((a, b) => {
      const sa = SEVERITY_ORDER.indexOf(meta.get(a.check_id)?.severity ?? "INFO");
      const sb = SEVERITY_ORDER.indexOf(meta.get(b.check_id)?.severity ?? "INFO");
      return STATUS_RANK[a.status] - STATUS_RANK[b.status] || sa - sb;
    });

  return (
    <section aria-labelledby="weeds-title">
      <h1 id="weeds-title">Weeds</h1>
      <div className="filters">
        <div className="field">
          <label htmlFor="severity">Severity</label>
          <select
            id="severity"
            value={severity}
            onChange={(e) => {
              setSeverity(e.target.value as Severity | "all");
            }}
          >
            <option value="all">All severities</option>
            {SEVERITY_ORDER.map((s) => (
              <option key={s} value={s}>
                {SEVERITY_WORDS[s]}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="category">Area</label>
          <select
            id="category"
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
            }}
          >
            <option value="all">All areas</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="only-weeds">Show</label>
          <select
            id="only-weeds"
            value={onlyWeeds ? "weeds" : "all"}
            onChange={(e) => {
              setOnlyWeeds(e.target.value === "weeds");
            }}
          >
            <option value="weeds">Weeds only</option>
            <option value="all">Every check</option>
          </select>
        </div>
      </div>
      {rows.length === 0 ? (
        <p>Nothing matches these filters.</p>
      ) : (
        <ul className="weeds">
          {rows.map((r) => {
            const m = meta.get(r.check_id);
            return (
              <li key={r.check_id}>
                <button
                  type="button"
                  onClick={() => {
                    go({ name: "weed", checkId: r.check_id });
                  }}
                >
                  <Plant status={r.status} size={28} />
                  <span className={`status-tag status-${r.status}`}>{STATUS_WORDS[r.status]}</span>
                  <span>{m ? SEVERITY_WORDS[m.severity] : ""}</span>
                  <span>
                    {m?.title ?? r.check_id} <span className="mono citations">{r.check_id}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
