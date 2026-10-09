import { vi } from "vitest";

import type { ApiClient } from "../api/client";
import type {
  AiState,
  AiStatus,
  AnswerEvent,
  CheckMeta,
  CheckResult,
  PullEvent,
  ScanResponse,
  Settings,
  Status,
} from "../api/types";

const META: [string, string, CheckMeta["severity"], string][] = [
  ["HG-SSH-001", "SSH root login disabled", "HIGH", "ssh"],
  ["HG-SSH-002", "SSH password authentication disabled", "HIGH", "ssh"],
  ["HG-FW-001", "Host firewall active", "HIGH", "firewall"],
  ["HG-FS-001", "/etc/shadow permissions and owner", "CRITICAL", "filesystem"],
  ["HG-NET-001", "Listening services on non-loopback interfaces", "MEDIUM", "network"],
  ["HG-UPD-001", "Automatic security updates enabled", "MEDIUM", "updates"],
];

export const CHECKS: CheckMeta[] = META.map(([id, title, severity, category]) => ({
  id,
  title,
  category,
  severity,
  rationale: `Why ${title} matters.`,
  requires_root: false,
  platforms: ["linux"],
  kb_doc: `knowledge/${id}.md`,
  remediation_template: id === "HG-NET-001" ? null : `${id.toLowerCase()}.sh`,
}));

const STATUSES: Status[] = ["FAIL", "PASS", "SKIPPED", "WARN", "WARN", "NOT_APPLICABLE"];

export function result(id: string, status: Status, evidence: string[] = []): CheckResult {
  return { check_id: id, status, evidence, reason: null, duration_ms: 1 };
}

export function scanResponse(overrides: Partial<ScanResponse["report"]> = {}): ScanResponse {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    report: {
      tool_version: "0.0.1",
      scanned_root: "/",
      platform: {
        distro_id: "ubuntu",
        version_id: "24.04",
        pretty_name: "Ubuntu 24.04 LTS",
        is_root: false,
      },
      platform_supported: true,
      results: CHECKS.map((c, i) =>
        result(
          c.id,
          STATUSES[i] ?? "PASS",
          c.id === "HG-SSH-001" ? ["PermitRootLogin yes (/etc/ssh/sshd_config:3)"] : [],
        ),
      ),
      summary: {
        score: 61,
        coverage: {
          total: 6,
          evaluated: 4,
          skipped: 1,
          errors: 0,
          not_applicable: 1,
          skipped_for_privileges: 1,
          percent: 80,
        },
      },
      privilege_hint:
        "Run with sudo for full coverage (1 check(s) skipped: insufficient privileges)",
      ...overrides,
    },
  };
}

export function aiStatus(state: AiState, extra: Partial<AiStatus> = {}): AiStatus {
  return {
    state,
    tier: "best",
    model: state === "disabled" || state === "ollama_not_installed" ? null : "qwen2.5:7b-instruct",
    model_download_bytes: 4_700_000_000,
    model_required_free_bytes: 6_000_000_000,
    reduced_quality: state === "reduced_quality",
    memory_total_bytes: 16 * 1024 ** 3,
    memory_available_bytes: 8 * 1024 ** 3,
    cpu_cores: 8,
    gpu: null,
    installed_models: [],
    message: `Message for ${state}.`,
    tier_overridden: false,
    ...extra,
  };
}

export const SETTINGS: Settings = {
  ollama_url: "http://127.0.0.1:11434",
  embed_model: "nomic-embed-text",
  retrieval_threshold: 0.3,
  chat_model: null,
  generation_timeout_s: 120,
  max_tokens: 400,
};

type Emit<E> = (onEvent: (event: E) => void, signal: AbortSignal) => Promise<void>;

/** A fake ApiClient with sensible defaults; override any method per test. */
export function fakeClient(overrides: Partial<Record<keyof ApiClient, unknown>> = {}) {
  const explain: Emit<AnswerEvent> = async (onEvent) => {
    onEvent({ type: "delta", text: "Root login is risky. " });
    onEvent({
      type: "final",
      answer: {
        outcome: "answered",
        text: "Root login is risky.",
        citations: ["ssh-root-login#why-it-matters"],
        model: "m",
        cached: false,
      },
    });
  };
  const pull: Emit<PullEvent> = async (onEvent) => {
    onEvent({ type: "progress", status: "pulling", completed: 50, total: 100 });
    onEvent({ type: "done", cancelled: false });
  };
  const client = {
    baseUrl: "http://127.0.0.1:1",
    checks: vi.fn(async () => CHECKS),
    scan: vi.fn(async () => scanResponse()),
    result: vi.fn(),
    remediation: vi.fn(async (id: string) =>
      id === "HG-NET-001" ? null : `#!/usr/bin/env bash\n# fix ${id}\n`,
    ),
    aiStatus: vi.fn(async () => aiStatus("ready")),
    settings: vi.fn(async () => SETTINGS),
    saveSettings: vi.fn(async (u: object) => ({ ...SETTINGS, ...u })),
    ingest: vi.fn(async () => ({ kb_version: "v", chunks: 60, vectors: [], note: null })),
    explain: vi.fn(
      (_s: string, _c: string, onEvent: (e: AnswerEvent) => void, signal: AbortSignal) =>
        explain(onEvent, signal),
    ),
    chat: vi.fn((_q: string, onEvent: (e: AnswerEvent) => void, signal: AbortSignal) =>
      explain(onEvent, signal),
    ),
    pull: vi.fn((_m: string, onEvent: (e: PullEvent) => void, signal: AbortSignal) =>
      pull(onEvent, signal),
    ),
    ...overrides,
  };
  return client as unknown as ApiClient & typeof client;
}
