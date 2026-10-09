import { invoke, isTauri } from "@tauri-apps/api/core";

export type BackendStatus =
  | { state: "starting" }
  | { state: "ready"; baseUrl: string; token: string }
  | { state: "failed"; reason: string; logTail: string[] };

interface NativeStatus {
  state: "starting" | "ready" | "failed";
  port?: number;
  token?: string;
  reason?: string;
  log_tail?: string[];
}

declare global {
  interface Window {
    /** Set only by the end-to-end test harness, which serves a mocked API. */
    __HG_TEST_BACKEND__?: { baseUrl: string; token: string };
  }
}

export async function backendStatus(): Promise<BackendStatus> {
  if (isTauri()) {
    const native = await invoke<NativeStatus>("backend_status");
    if (native.state === "ready" && native.port !== undefined && native.token !== undefined) {
      return {
        state: "ready",
        baseUrl: `http://127.0.0.1:${String(native.port)}`,
        token: native.token,
      };
    }
    if (native.state === "failed") {
      return {
        state: "failed",
        reason: native.reason ?? "The scanner did not start.",
        logTail: native.log_tail ?? [],
      };
    }
    return { state: "starting" };
  }
  const test = window.__HG_TEST_BACKEND__;
  if (test) return { state: "ready", ...test };
  return {
    state: "failed",
    reason: "This page is the HardenGarden desktop app and must run inside it.",
    logTail: [],
  };
}

/** Polls until the backend is ready or failed. The native side enforces the 15 s limit (R35). */
export async function waitForBackend(intervalMs = 250): Promise<BackendStatus> {
  for (;;) {
    const status = await backendStatus();
    if (status.state !== "starting") return status;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

export async function copyText(text: string): Promise<void> {
  if (isTauri()) {
    const { writeText } = await import("@tauri-apps/plugin-clipboard-manager");
    await writeText(text);
    return;
  }
  await navigator.clipboard.writeText(text);
}
