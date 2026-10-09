import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const API = "http://127.0.0.1:59999";
const TOKEN = "e2e-token-".padEnd(43, "x");

const checks = [
  ["HG-SSH-001", "SSH root login disabled", "HIGH", "ssh", "FAIL"],
  ["HG-SSH-002", "SSH password authentication disabled", "HIGH", "ssh", "PASS"],
  ["HG-FW-001", "Host firewall active", "HIGH", "firewall", "SKIPPED"],
  ["HG-FS-001", "/etc/shadow permissions and owner", "CRITICAL", "filesystem", "PASS"],
  ["HG-NET-001", "Listening services on non-loopback interfaces", "MEDIUM", "network", "WARN"],
  ["HG-KRN-001", "ASLR enabled", "MEDIUM", "kernel", "PASS"],
] as const;

const meta = checks.map(([id, title, severity, category]) => ({
  id,
  title,
  severity,
  category,
  rationale: `Why ${title} matters.`,
  requires_root: false,
  platforms: ["linux"],
  kb_doc: `knowledge/${id}.md`,
  remediation_template: `${id.toLowerCase()}.sh`,
}));

const scan = {
  id: "22222222-2222-2222-2222-222222222222",
  report: {
    tool_version: "0.1.0",
    scanned_root: "/",
    platform: {
      distro_id: "ubuntu",
      version_id: "24.04",
      pretty_name: "Ubuntu 24.04.1 LTS",
      is_root: false,
    },
    platform_supported: true,
    results: checks.map(([id, , , , status]) => ({
      check_id: id,
      status,
      reason: null,
      duration_ms: 1,
      evidence:
        id === "HG-SSH-001" ? ["PermitRootLogin yes (/etc/ssh/sshd_config.d/50-cloud.conf:1)"] : [],
    })),
    summary: {
      score: 74,
      coverage: {
        total: 6,
        evaluated: 5,
        skipped: 1,
        errors: 0,
        not_applicable: 0,
        skipped_for_privileges: 1,
        percent: 83,
      },
    },
    privilege_hint: "Run with sudo for full coverage (1 check(s) skipped: insufficient privileges)",
  },
};

const SCRIPT =
  "#!/usr/bin/env bash\n# HardenGarden remediation for HG-SSH-001\nset -euo pipefail\n" +
  // A long line like the real templates have: it must scroll inside the block, not the page.
  `printf '%s\\n' "${"PermitRootLogin no ".repeat(12)}"\n`;

async function expectNoHorizontalPageScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

async function mockApi(page: Page, requests: string[]) {
  await page.addInitScript(
    ([baseUrl, token]) => {
      (window as unknown as { __HG_TEST_BACKEND__: object }).__HG_TEST_BACKEND__ = {
        baseUrl,
        token,
      };
    },
    [API, TOKEN],
  );
  await page.route(`${API}/**`, async (route: Route) => {
    const url = new URL(route.request().url());
    requests.push(`${route.request().method()} ${url.pathname}`);
    expect(route.request().headers()["authorization"]).toBe(`Bearer ${TOKEN}`);
    const json = (body: unknown) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    switch (url.pathname) {
      case "/checks":
        return json(meta);
      case "/ai/status":
        return json({
          state: "ready",
          tier: "best",
          model: "qwen2.5:7b-instruct",
          model_download_bytes: 4.7e9,
          model_required_free_bytes: 6e9,
          reduced_quality: false,
          memory_total_bytes: 3.4e10,
          memory_available_bytes: 2e10,
          cpu_cores: 8,
          gpu: null,
          installed_models: ["qwen2.5:7b-instruct"],
          message: "Ready (qwen2.5:7b-instruct).",
          tier_overridden: false,
        });
      case "/scan":
        return json(scan);
      case "/remediation/HG-SSH-001":
        return route.fulfill({ status: 200, contentType: "text/plain", body: SCRIPT });
      case "/explain":
        return route.fulfill({
          status: 200,
          contentType: "application/x-ndjson",
          body:
            [
              { type: "delta", text: "Direct root login gives attackers a well-known target. " },
              {
                type: "final",
                answer: {
                  outcome: "answered",
                  text: "Direct root login gives attackers a well-known target. Use the HardenGarden remediation script.",
                  citations: ["ssh-root-login#why-it-matters"],
                  model: "qwen2.5:7b-instruct",
                  cached: false,
                },
              },
            ]
              .map((e) => JSON.stringify(e))
              .join("\n") + "\n",
        });
      default:
        return route.fulfill({
          status: 404,
          contentType: "application/json",
          body: '{"detail":"not found"}',
        });
    }
  });
}

async function expectNoSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );
  expect(
    serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
  ).toEqual([]);
}

for (const colorScheme of ["light", "dark"] as const) {
  test(`scan, open a weed, explain it, copy the script (${colorScheme})`, async ({
    page,
    context,
  }) => {
    await page.emulateMedia({ colorScheme });
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const requests: string[] = [];
    const violations: string[] = [];
    const origins = new Set<string>();
    page.on("console", (msg) => {
      if (msg.text().includes("Content Security Policy")) violations.push(msg.text());
    });
    page.on("request", (req) => origins.add(new URL(req.url()).origin));
    await mockApi(page, requests);

    await page.goto("/");
    await page.getByRole("button", { name: "Scan this computer" }).click();
    await expect(page.getByTestId("score")).toHaveText("74 / 100");
    await expect(page.getByText(/Run with sudo for full coverage/)).toBeVisible();
    await expectNoSeriousA11yIssues(page);
    await expectNoHorizontalPageScroll(page);
    await page.screenshot({ path: `test-results/garden-${colorScheme}.png`, fullPage: true });

    await page.getByRole("button", { name: "HG-SSH-001 SSH root login disabled: Weed" }).click();
    await expect(
      page.getByRole("heading", { level: 1, name: "SSH root login disabled" }),
    ).toBeVisible();
    await expect(
      page.getByText("PermitRootLogin yes (/etc/ssh/sshd_config.d/50-cloud.conf:1)"),
    ).toBeVisible();
    await expect(page.getByText(/Review before running/)).toBeVisible();

    await page.getByRole("button", { name: "Explain" }).click();
    await expect(page.getByText("Sources: ssh-root-login#why-it-matters")).toBeVisible();
    await page.getByRole("button", { name: "Copy script" }).click();
    await expect(page.getByText("Copied to the clipboard.")).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(SCRIPT);
    await expectNoSeriousA11yIssues(page);
    await expectNoHorizontalPageScroll(page);
    // Navigation stays reachable on a long page.
    await page.evaluate(() => {
      window.scrollTo(0, document.documentElement.scrollHeight);
    });
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await expect(page.getByRole("navigation", { name: "Main" })).toBeInViewport();
    await page.screenshot({ path: `test-results/weed-detail-scrolled-${colorScheme}.png` });
    await page.screenshot({ path: `test-results/weed-detail-${colorScheme}.png`, fullPage: true });

    // A new screen opens at its top, not at the previous screen's scroll position.
    await page
      .getByRole("navigation", { name: "Main" })
      .getByRole("button", { name: "Settings" })
      .click();
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeInViewport();
    expect(await page.evaluate(() => window.scrollY)).toBe(0);

    expect(requests).toEqual(
      expect.arrayContaining([
        "GET /checks",
        "POST /scan",
        "POST /explain",
        "GET /remediation/HG-SSH-001",
      ]),
    );
    expect(violations).toEqual([]);
    expect([...origins].every((o) => o === "http://127.0.0.1:4173" || o === API)).toBe(true);
  });
}

test("keyboard users can reach every main section", async ({ page }) => {
  await mockApi(page, []);
  await page.goto("/");
  await page.getByRole("button", { name: "Garden" }).focus();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Weeds" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: "Weeds" })).toBeVisible();
});

test("without a backend the app explains instead of showing a blank window", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "The scanner did not start" })).toBeVisible();
  await expect(page.getByText(/uv tool install/)).toBeVisible();
  await expectNoSeriousA11yIssues(page);
});
