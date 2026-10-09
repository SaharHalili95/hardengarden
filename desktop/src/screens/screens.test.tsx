import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App, Shell } from "../App";
import type { AiState, AnswerEvent } from "../api/types";
import { AI_LABELS, AiIndicator } from "../components/AiIndicator";
import { aiStatus, fakeClient, scanResponse } from "../test/fixtures";
import { renderWithApp, seriousViolations } from "../test/render";
import { Ask } from "./Ask";
import { BackendError } from "./BackendError";
import { Garden } from "./Garden";
import { SettingsScreen } from "./SettingsScreen";
import { WeedDetail } from "./WeedDetail";
import { Weeds } from "./Weeds";

describe("Garden", () => {
  it("offers a scan, then shows the bed, score, coverage and privilege hint", async () => {
    const client = fakeClient();
    const { container } = renderWithApp(<Garden />, { client });
    await userEvent.click(screen.getByRole("button", { name: "Scan this computer" }));
    expect(client.scan).toHaveBeenCalledOnce();
    expect(await screen.findByTestId("score")).toHaveTextContent("61 / 100");
    expect(screen.getByText(/4 of 6 checks evaluated \(80% coverage\)/)).toBeInTheDocument();
    expect(screen.getByText(/Run with sudo for full coverage/)).toBeInTheDocument();
    const plants = within(
      screen.getByRole("list", { name: "Garden bed" }).closest(".bed") as HTMLElement,
    ).getAllByRole("button");
    expect(plants).toHaveLength(6);
    expect(plants[0]).toHaveAccessibleName("HG-SSH-001 SSH root login disabled: Weed");
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("shows 'Not enough data' instead of a fake 100", () => {
    const scan = scanResponse({
      summary: {
        score: null,
        coverage: {
          total: 6,
          evaluated: 0,
          skipped: 6,
          errors: 0,
          not_applicable: 0,
          skipped_for_privileges: 6,
          percent: 0,
        },
      },
    });
    renderWithApp(<Garden />, { client: fakeClient(), scan });
    expect(screen.getByTestId("score")).toHaveTextContent("Not enough data");
  });

  it("warns on unsupported platforms and reports scan errors", async () => {
    renderWithApp(<Garden />, {
      client: fakeClient(),
      scan: scanResponse({ platform_supported: false }),
    });
    expect(screen.getByText(/not a supported platform/)).toBeInTheDocument();
    const failing = fakeClient({
      scan: vi.fn(async () => Promise.reject(new Error("Scan blew up"))),
    });
    render(<></>);
    renderWithApp(<Garden />, { client: failing });
    await userEvent.click(screen.getByRole("button", { name: "Scan this computer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Scan blew up");
  });
});

describe("Weeds", () => {
  it("lists only weeds by default, filters, and opens a weed", async () => {
    const client = fakeClient();
    const { container } = renderWithApp(<Shell />, {
      client,
      scan: scanResponse(),
      view: { name: "weeds" },
    });
    const list = screen.getAllByRole("listitem").filter((li) => li.closest(".weeds"));
    expect(list).toHaveLength(3); // one FAIL + two WARN
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "MEDIUM");
    // Only HG-NET-001 is both a weed (WARN) and MEDIUM; HG-FS-001 is a CRITICAL weed.
    expect(screen.getAllByRole("listitem").filter((li) => li.closest(".weeds"))).toHaveLength(1);
    await userEvent.selectOptions(screen.getByLabelText("Area"), "firewall");
    expect(screen.getByText("Nothing matches these filters.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "all");
    await userEvent.selectOptions(screen.getByLabelText("Area"), "all");
    await userEvent.selectOptions(screen.getByLabelText("Show"), "all");
    expect(screen.getAllByRole("listitem").filter((li) => li.closest(".weeds"))).toHaveLength(6);
    expect(await seriousViolations(container)).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: /SSH root login disabled/ }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "SSH root login disabled" }),
    ).toBeInTheDocument();
  });

  it("asks for a scan first", () => {
    renderWithApp(<Weeds />, { client: fakeClient() });
    expect(screen.getByText("Run a scan from the Garden page first.")).toBeInTheDocument();
  });
});

describe("Weed detail", () => {
  it("shows evidence as text, explains with sources, and copies the script", async () => {
    const writeText = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    const scan = scanResponse();
    scan.report.results[0] = {
      ...scan.report.results[0]!,
      evidence: ['<img src=x onerror="alert(1)"> PermitRootLogin yes'],
    };
    const client = fakeClient();
    const { container } = renderWithApp(<WeedDetail checkId="HG-SSH-001" />, { client, scan });
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x onerror/)).toBeInTheDocument();
    expect(await screen.findByText(/Review before running/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Explain" }));
    expect(await screen.findByText("Sources: ssh-root-login#why-it-matters")).toBeInTheDocument();
    expect(client.explain).toHaveBeenCalledWith(
      scan.id,
      "HG-SSH-001",
      expect.any(Function),
      expect.any(AbortSignal),
    );
    await userEvent.click(screen.getByRole("button", { name: "Copy script" }));
    expect(writeText).toHaveBeenCalledWith("#!/usr/bin/env bash\n# fix HG-SSH-001\n");
    expect(await screen.findByText("Copied to the clipboard.")).toBeInTheDocument();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("says when there is no script", async () => {
    renderWithApp(<WeedDetail checkId="HG-NET-001" />, {
      client: fakeClient(),
      scan: scanResponse(),
    });
    expect(await screen.findByText(/no single safe script/)).toBeInTheDocument();
  });

  it("Stop aborts a streaming explanation", async () => {
    let seen: AbortSignal | null = null;
    const slow = vi.fn(
      (_s: string, _c: string, onEvent: (e: AnswerEvent) => void, signal: AbortSignal) =>
        new Promise<void>((_resolve, reject) => {
          seen = signal;
          onEvent({ type: "delta", text: "Thinking " });
          signal.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        }),
    );
    renderWithApp(<WeedDetail checkId="HG-SSH-001" />, {
      client: fakeClient({ explain: slow }),
      scan: scanResponse(),
    });
    await userEvent.click(screen.getByRole("button", { name: "Explain" }));
    expect(await screen.findByText("Thinking")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(seen!.aborted).toBe(true);
    expect(await screen.findByText("Stopped.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
  });

  it.each([
    ["not_enough_information", "Not enough information in the knowledge base to answer this."],
    ["ollama_unavailable", "AI explanations need Ollama running on this computer."],
    ["ungrounded", "The answer could not be checked against the knowledge base, so it is hidden."],
    ["insufficient_memory", "Not enough free memory for model qwen2.5:7b-instruct"],
  ])("shows the %s outcome plainly", async (outcome, text) => {
    const explain = vi.fn(async (_s: string, _c: string, onEvent: (e: AnswerEvent) => void) => {
      onEvent({
        type: "final",
        answer: {
          outcome: outcome as never,
          text: outcome === "ungrounded" ? "" : text,
          citations: [],
          model: null,
          cached: false,
        },
      });
    });
    renderWithApp(<WeedDetail checkId="HG-SSH-001" />, {
      client: fakeClient({ explain }),
      scan: scanResponse(),
    });
    await userEvent.click(screen.getByRole("button", { name: "Explain" }));
    expect(await screen.findByText(text, { exact: false })).toBeInTheDocument();
  });
});

describe("Ask", () => {
  it("answers with sources", async () => {
    const client = fakeClient();
    const { container } = renderWithApp(<Ask />, { client });
    await userEvent.type(screen.getByLabelText("Your question"), "Should root log in over SSH?");
    await userEvent.click(screen.getByRole("button", { name: "Use this question" }));
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/Sources:/)).toBeInTheDocument();
    expect(client.chat).toHaveBeenCalledWith(
      "Should root log in over SSH?",
      expect.any(Function),
      expect.any(AbortSignal),
    );
    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("Settings", () => {
  it("refuses a non-loopback Ollama address before saving", async () => {
    const client = fakeClient();
    const { container } = renderWithApp(<SettingsScreen />, { client, ai: aiStatus("ready") });
    const input = await screen.findByDisplayValue("http://127.0.0.1:11434");
    await userEvent.clear(input);
    await userEvent.type(input, "http://192.168.1.20:11434");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must be on this computer");
    expect(client.saveSettings).not.toHaveBeenCalled();
    await userEvent.clear(input);
    await userEvent.type(input, "http://localhost:11434");
    await userEvent.selectOptions(screen.getByLabelText("Chat model"), "qwen2.5:1.5b-instruct");
    expect(screen.getByText(/may be slow or refuse to start/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(client.saveSettings).toHaveBeenCalledWith({
      ollama_url: "http://localhost:11434",
      chat_model: "qwen2.5:1.5b-instruct",
    });
    expect(await screen.findByText("Settings saved.")).toBeInTheDocument();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("downloads a model only after an explicit click, with size and progress", async () => {
    const client = fakeClient();
    renderWithApp(<SettingsScreen />, { client, ai: aiStatus("model_not_downloaded") });
    await screen.findByDisplayValue("http://127.0.0.1:11434");
    expect(client.pull).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Download qwen2.5:7b-instruct" }));
    expect(screen.getByText(/about 4.7 GB/)).toBeInTheDocument();
    expect(client.pull).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => {
      expect(client.pull).toHaveBeenCalledOnce();
    });
    await waitFor(() => {
      expect(client.aiStatus).toHaveBeenCalled();
    });
  });

  it("rebuilds the search index and switches theme", async () => {
    const client = fakeClient();
    renderWithApp(<SettingsScreen />, { client, ai: aiStatus("ready") });
    await userEvent.click(screen.getByRole("button", { name: "Rebuild search index" }));
    expect(await screen.findByText("Search index rebuilt: 60 passages.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Theme"), "dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    await userEvent.selectOptions(screen.getByLabelText("Theme"), "system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });
});

describe("AI status indicator", () => {
  it.each(Object.keys(AI_LABELS) as AiState[])("explains the %s state", async (state) => {
    const { container } = renderWithApp(<AiIndicator />, {
      client: fakeClient(),
      ai: aiStatus(state),
    });
    const toggle = screen.getByRole("button", { name: AI_LABELS[state] });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByText(`Message for ${state}.`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open AI settings" })).toBeInTheDocument();
    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("Startup", () => {
  it("shows a specific error with log lines and the fallback, never a blank window", async () => {
    const { container } = render(
      <App
        discover={async () => ({
          state: "failed",
          reason: "The scanner exited with code 1.",
          logTail: ["ImportError: libz.so.1"],
        })}
      />,
    );
    expect(
      await screen.findByRole("heading", { name: "The scanner did not start" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("The scanner exited with code 1.");
    expect(screen.getByText(/ImportError: libz.so.1/)).toBeInTheDocument();
    expect(screen.getByText(/uv tool install/)).toBeInTheDocument();
    expect(await seriousViolations(container)).toEqual([]);
  });

  it("shows a status while starting, then the app", async () => {
    let resolve: (value: { state: "ready"; baseUrl: string; token: string }) => void = () =>
      undefined;
    const pending = new Promise<{ state: "ready"; baseUrl: string; token: string }>((r) => {
      resolve = r;
    });
    const fetchMock = vi.fn(async (url: string) => {
      const body = url.endsWith("/checks") ? [] : aiStatus("ready");
      return new Response(JSON.stringify(body), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App discover={() => pending} />);
    expect(screen.getByRole("status")).toHaveTextContent("Starting the scanner");
    await act(async () => {
      resolve({ state: "ready", baseUrl: "http://127.0.0.1:5", token: "t" });
      await pending;
    });
    expect(await screen.findByRole("navigation", { name: "Main" })).toBeInTheDocument();
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer t");
    vi.unstubAllGlobals();
  });

  it("reports an unreachable scanner", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))),
    );
    render(
      <App
        discover={async () => ({ state: "ready", baseUrl: "http://127.0.0.1:5", token: "t" })}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to fetch");
    vi.unstubAllGlobals();
  });

  it("renders the standalone error screen", () => {
    render(<BackendError reason="Timed out after 15 seconds." logTail={[]} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Timed out after 15 seconds.");
  });
});
