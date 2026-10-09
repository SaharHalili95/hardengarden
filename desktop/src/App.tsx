import { useEffect, useState } from "react";

import { waitForBackend, type BackendStatus } from "./api/backend";
import { ApiClient } from "./api/client";
import type { AiStatus, CheckMeta } from "./api/types";
import { AiIndicator } from "./components/AiIndicator";
import { Ask } from "./screens/Ask";
import { BackendError } from "./screens/BackendError";
import { Garden } from "./screens/Garden";
import { SettingsScreen } from "./screens/SettingsScreen";
import { WeedDetail } from "./screens/WeedDetail";
import { Weeds } from "./screens/Weeds";
import { AppProvider, useApp, type View } from "./state";

type Boot =
  | { state: "starting" }
  | { state: "failed"; reason: string; logTail: string[] }
  | { state: "ready"; client: ApiClient; checks: CheckMeta[]; ai: AiStatus | null };

export function App({ discover = waitForBackend }: { discover?: () => Promise<BackendStatus> }) {
  const [boot, setBoot] = useState<Boot>({ state: "starting" });

  useEffect(() => {
    const life = { alive: true };
    // A function, so TypeScript does not narrow the flag across awaits.
    const alive = (): boolean => life.alive;
    void (async () => {
      const status = await discover();
      if (!alive()) return;
      if (status.state !== "ready") {
        setBoot(
          status.state === "failed"
            ? status
            : { state: "failed", reason: "The scanner did not start.", logTail: [] },
        );
        return;
      }
      const client = new ApiClient(status.baseUrl, status.token);
      try {
        const [checks, ai] = await Promise.all([
          client.checks(),
          client.aiStatus().catch(() => null),
        ]);
        if (alive()) setBoot({ state: "ready", client, checks, ai });
      } catch (error) {
        if (alive())
          setBoot({
            state: "failed",
            reason: error instanceof Error ? error.message : "The scanner did not answer.",
            logTail: [],
          });
      }
    })();
    return () => {
      life.alive = false;
    };
  }, [discover]);

  if (boot.state === "starting") {
    return (
      <main className="main" aria-busy="true">
        <p role="status">Starting the scanner…</p>
      </main>
    );
  }
  if (boot.state === "failed") return <BackendError reason={boot.reason} logTail={boot.logTail} />;
  return (
    <AppProvider client={boot.client} checks={boot.checks} initialAi={boot.ai}>
      <Shell />
    </AppProvider>
  );
}

const NAV: { view: View["name"]; label: string }[] = [
  { view: "garden", label: "Garden" },
  { view: "weeds", label: "Weeds" },
  { view: "ask", label: "Ask" },
  { view: "settings", label: "Settings" },
];

export function Shell() {
  const { view, go } = useApp();
  const active = view.name === "weed" ? "weeds" : view.name;
  // Every screen opens at its top, not at the previous screen's scroll position.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [view]);
  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <svg width="28" height="28" viewBox="0 0 40 40" aria-hidden="true">
            <path d="M20 38V18" stroke="var(--fern)" strokeWidth="3" strokeLinecap="round" />
            <path
              d="M20 24c-7 0-11-4-11-10 6 0 11 3 11 10Z M20 20c0-7 4-12 11-12 0 7-4 12-11 12Z"
              fill="var(--fern)"
            />
          </svg>
          HardenGarden
        </div>
        <nav aria-label="Main">
          <ul>
            {NAV.map((item) => (
              <li key={item.view}>
                <button
                  type="button"
                  aria-current={active === item.view ? "page" : undefined}
                  onClick={() => {
                    go({ name: item.view } as View);
                  }}
                >
                  {item.label}
                </button>
              </li>
            ))}
          </ul>
        </nav>
        <AiIndicator />
      </aside>
      <main className="main" id="content">
        {view.name === "garden" && <Garden />}
        {view.name === "weeds" && <Weeds />}
        {view.name === "weed" && <WeedDetail checkId={view.checkId} />}
        {view.name === "ask" && <Ask />}
        {view.name === "settings" && <SettingsScreen />}
      </main>
    </div>
  );
}
