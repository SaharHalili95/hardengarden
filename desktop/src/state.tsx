import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { ApiClient } from "./api/client";
import type { AiStatus, CheckMeta, ScanResponse } from "./api/types";

export type View =
  | { name: "garden" }
  | { name: "weeds" }
  | { name: "weed"; checkId: string }
  | { name: "ask" }
  | { name: "settings" };

interface AppState {
  client: ApiClient;
  checks: CheckMeta[];
  scan: ScanResponse | null;
  scanning: boolean;
  scanError: string | null;
  runScan: () => Promise<void>;
  ai: AiStatus | null;
  refreshAi: () => Promise<void>;
  view: View;
  go: (view: View) => void;
}

const Context = createContext<AppState | null>(null);

export function useApp(): AppState {
  const value = useContext(Context);
  if (!value) throw new Error("useApp must be used inside <AppProvider>");
  return value;
}

export function AppProvider({
  client,
  checks,
  initialAi = null,
  initialScan = null,
  initialView = { name: "garden" },
  children,
}: {
  client: ApiClient;
  checks: CheckMeta[];
  initialAi?: AiStatus | null;
  initialScan?: ScanResponse | null;
  initialView?: View;
  children: ReactNode;
}) {
  const [scan, setScan] = useState<ScanResponse | null>(initialScan);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<string | null>(null);
  const [ai, setAi] = useState<AiStatus | null>(initialAi);
  const [view, setView] = useState<View>(initialView);

  const runScan = useCallback(async () => {
    setScanning(true);
    setScanError(null);
    try {
      setScan(await client.scan());
    } catch (error) {
      setScanError(error instanceof Error ? error.message : "The scan failed.");
    } finally {
      setScanning(false);
    }
  }, [client]);

  const refreshAi = useCallback(async () => {
    try {
      setAi(await client.aiStatus());
    } catch {
      setAi(null);
    }
  }, [client]);

  const value = useMemo(
    () => ({
      client,
      checks,
      scan,
      scanning,
      scanError,
      runScan,
      ai,
      refreshAi,
      view,
      go: setView,
    }),
    [client, checks, scan, scanning, scanError, runScan, ai, refreshAi, view],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
