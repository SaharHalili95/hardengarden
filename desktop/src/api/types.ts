// Mirrors the backend's Pydantic models (backend/hardengarden/core/models.py, api/app.py).

export type Severity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
export type Status = "PASS" | "FAIL" | "WARN" | "ERROR" | "SKIPPED" | "NOT_APPLICABLE";

export interface CheckMeta {
  id: string;
  title: string;
  category: string;
  severity: Severity;
  rationale: string;
  requires_root: boolean;
  platforms: string[];
  kb_doc: string;
  remediation_template: string | null;
}

export interface CheckResult {
  check_id: string;
  status: Status;
  evidence: string[];
  reason: string | null;
  duration_ms: number;
}

export interface Coverage {
  total: number;
  evaluated: number;
  skipped: number;
  errors: number;
  not_applicable: number;
  skipped_for_privileges: number;
  percent: number | null;
}

export interface ScanReport {
  tool_version: string;
  scanned_root: string;
  platform: { distro_id: string; version_id: string; pretty_name: string; is_root: boolean };
  platform_supported: boolean;
  results: CheckResult[];
  summary: { score: number | null; coverage: Coverage };
  privilege_hint: string | null;
}

export interface ScanResponse {
  id: string;
  report: ScanReport;
}

export type AnswerOutcome =
  | "answered"
  | "not_enough_information"
  | "ungrounded"
  | "ollama_unavailable"
  | "insufficient_memory"
  | "timeout"
  | "cancelled"
  | "error";

export interface Answer {
  outcome: AnswerOutcome;
  text: string;
  citations: string[];
  model: string | null;
  cached: boolean;
}

export type AnswerEvent =
  | { type: "delta"; text: string }
  | { type: "final"; answer: Answer }
  | { type: "error"; detail: string };

export type AiState =
  | "ready"
  | "reduced_quality"
  | "not_enough_memory"
  | "model_not_downloaded"
  | "ollama_not_installed"
  | "disabled";

export interface AiStatus {
  state: AiState;
  tier: string;
  model: string | null;
  model_download_bytes: number | null;
  model_required_free_bytes: number | null;
  reduced_quality: boolean;
  memory_total_bytes: number | null;
  memory_available_bytes: number | null;
  cpu_cores: number;
  gpu: boolean | null;
  installed_models: string[];
  message: string;
  tier_overridden: boolean;
}

export type PullEvent =
  | { type: "progress"; status: string; completed: number | null; total: number | null }
  | { type: "done"; cancelled: boolean }
  | { type: "error"; detail: string };

export interface Settings {
  ollama_url: string;
  embed_model: string;
  retrieval_threshold: number;
  chat_model: string | null;
  generation_timeout_s: number;
  max_tokens: number;
}

export interface SettingsUpdate {
  ollama_url?: string;
  chat_model?: string;
  clear_chat_model?: boolean;
  generation_timeout_s?: number;
  max_tokens?: number;
}

export interface IngestResult {
  kb_version: string;
  chunks: number;
  vectors: number[];
  note: string | null;
}

export const CHAT_MODELS = [
  { name: "qwen2.5:7b-instruct", label: "Qwen 2.5 7B (16 GB RAM or more)" },
  { name: "qwen2.5:3b-instruct", label: "Qwen 2.5 3B (8 to 16 GB RAM)" },
  { name: "qwen2.5:1.5b-instruct", label: "Qwen 2.5 1.5B (4 to 8 GB RAM, reduced quality)" },
] as const;
