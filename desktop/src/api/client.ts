import type {
  AiStatus,
  AnswerEvent,
  CheckMeta,
  IngestResult,
  PullEvent,
  ScanReport,
  ScanResponse,
  Settings,
  SettingsUpdate,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function detailOf(body: unknown, fallback: string): string {
  if (typeof body === "object" && body !== null && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

/** Reads an NDJSON body line by line and hands each parsed object to `onEvent`. */
export async function readNdjson(
  response: Response,
  onEvent: (event: unknown) => void,
): Promise<void> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf("\n");
    while (newline !== -1) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line) as unknown);
      newline = buffer.indexOf("\n");
    }
  }
  const rest = buffer.trim();
  if (rest) onEvent(JSON.parse(rest) as unknown);
}

export class ApiClient {
  constructor(
    readonly baseUrl: string,
    private readonly token: string,
  ) {}

  private headers(withBody: boolean): Headers {
    const headers = new Headers({ Authorization: `Bearer ${this.token}` });
    if (withBody) headers.set("Content-Type", "application/json");
    return headers;
  }

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: this.headers(init.body !== undefined),
    });
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null);
      throw new ApiError(
        response.status,
        detailOf(body, `Request failed (${String(response.status)})`),
      );
    }
    return response;
  }

  private async json<T>(path: string, init?: RequestInit): Promise<T> {
    return (await (await this.request(path, init)).json()) as T;
  }

  checks(): Promise<CheckMeta[]> {
    return this.json("/checks");
  }

  scan(): Promise<ScanResponse> {
    return this.json("/scan", { method: "POST" });
  }

  result(id: string): Promise<ScanReport> {
    return this.json(`/results/${encodeURIComponent(id)}`);
  }

  async remediation(checkId: string): Promise<string | null> {
    try {
      return await (await this.request(`/remediation/${encodeURIComponent(checkId)}`)).text();
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  }

  aiStatus(): Promise<AiStatus> {
    return this.json("/ai/status");
  }

  settings(): Promise<Settings> {
    return this.json("/settings");
  }

  saveSettings(update: SettingsUpdate): Promise<Settings> {
    return this.json("/settings", { method: "PUT", body: JSON.stringify(update) });
  }

  ingest(): Promise<IngestResult> {
    return this.json("/kb/ingest", { method: "POST" });
  }

  /** Streams an explanation. Aborting the signal disconnects, which cancels it on the backend. */
  async explain(
    scanId: string,
    checkId: string,
    onEvent: (event: AnswerEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const body = JSON.stringify({ scan_id: scanId, check_id: checkId });
    await readNdjson(await this.request("/explain", { method: "POST", body, signal }), (event) => {
      onEvent(event as AnswerEvent);
    });
  }

  async chat(
    question: string,
    onEvent: (event: AnswerEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const body = JSON.stringify({ question });
    await readNdjson(await this.request("/chat", { method: "POST", body, signal }), (event) => {
      onEvent(event as AnswerEvent);
    });
  }

  /** Downloads a model. Only ever called after the user confirmed the size (R37). */
  async pull(
    model: string,
    onEvent: (event: PullEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const body = JSON.stringify({ model, consent: true });
    await readNdjson(await this.request("/ai/pull", { method: "POST", body, signal }), (event) => {
      onEvent(event as PullEvent);
    });
  }
}
