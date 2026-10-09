// @vitest-environment node
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(import.meta.dirname, "..");

function cspFromIndex(): string {
  const html = readFileSync(join(ROOT, "index.html"), "utf8");
  const match = /http-equiv="Content-Security-Policy"\s+content="([^"]+)"/.exec(html);
  if (!match?.[1]) throw new Error("index.html has no CSP meta tag");
  return match[1];
}

function cspFromTauri(): Record<string, string> {
  const conf = JSON.parse(readFileSync(join(ROOT, "src-tauri", "tauri.conf.json"), "utf8")) as {
    app: { security: { csp: Record<string, string> } };
  };
  return conf.app.security.csp;
}

function sources(csp: string): string[] {
  return csp.split(/[\s;]+/).filter(Boolean);
}

const ALLOWED = new Set([
  "default-src",
  "script-src",
  "style-src",
  "img-src",
  "font-src",
  "connect-src",
  "object-src",
  "base-uri",
  "form-action",
  "frame-src",
  "'self'",
  "'none'",
  "data:",
  "ipc:",
  "http://ipc.localhost",
  "http://127.0.0.1:*",
]);

describe("Content Security Policy", () => {
  it.each([
    ["index.html", cspFromIndex()],
    [
      "tauri.conf.json",
      Object.entries(cspFromTauri())
        .map(([k, v]) => `${k} ${v}`)
        .join("; "),
    ],
  ])("%s allows no remote origins, no inline code and no eval", (_name, csp) => {
    expect(csp).not.toMatch(/unsafe-eval|unsafe-inline|unsafe-hashes|wasm-unsafe/);
    expect(csp).not.toMatch(/https?:\/\/(?!127\.0\.0\.1:\*|ipc\.localhost)/);
    expect(csp).not.toContain("*.");
    for (const token of sources(csp)) expect(ALLOWED).toContain(token);
    expect(csp).toMatch(/object-src 'none'/);
    expect(csp).toMatch(/script-src 'self'/);
  });

  it("the Tauri webview is locked down", () => {
    const conf = JSON.parse(readFileSync(join(ROOT, "src-tauri", "tauri.conf.json"), "utf8")) as {
      app: {
        withGlobalTauri: boolean;
        security: { freezePrototype: boolean; capabilities: string[] };
      };
    };
    expect(conf.app.withGlobalTauri).toBe(false);
    expect(conf.app.security.freezePrototype).toBe(true);
    expect(conf.app.security.capabilities).toEqual(["main"]);
  });

  it("the UI may only write to the clipboard", () => {
    const capability = JSON.parse(
      readFileSync(join(ROOT, "src-tauri", "capabilities", "main.json"), "utf8"),
    ) as {
      permissions: string[];
    };
    expect(capability.permissions).toEqual(["clipboard-manager:allow-write-text"]);
  });
});

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

describe("Shipped UI source", () => {
  const shipped = files(join(ROOT, "src")).filter(
    (f) => /\.(ts|tsx|css)$/.test(f) && !/(\.test\.|\/test\/)/.test(f),
  );

  it("references no remote URLs (R7)", () => {
    for (const file of shipped) {
      const text = readFileSync(file, "utf8");
      expect(text, file).not.toMatch(/https?:\/\/(?!127\.0\.0\.1|localhost|\[::1\])/);
    }
  });

  it("never renders HTML from strings (R15)", () => {
    for (const file of shipped) {
      const text = readFileSync(file, "utf8");
      expect(text, file).not.toMatch(
        /dangerouslySetInnerHTML|\.innerHTML|\.outerHTML|insertAdjacentHTML|document\.write/,
      );
    }
  });
});
