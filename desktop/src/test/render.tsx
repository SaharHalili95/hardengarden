import { render, type RenderResult } from "@testing-library/react";
import axe from "axe-core";
import type { ReactNode } from "react";

import type { ApiClient } from "../api/client";
import type { AiStatus, ScanResponse } from "../api/types";
import { AppProvider, type View } from "../state";
import { CHECKS } from "./fixtures";

export function renderWithApp(
  ui: ReactNode,
  {
    client,
    scan = null,
    ai = null,
    view = { name: "garden" },
  }: { client: ApiClient; scan?: ScanResponse | null; ai?: AiStatus | null; view?: View },
): RenderResult {
  return render(
    <AppProvider
      client={client}
      checks={CHECKS}
      initialScan={scan}
      initialAi={ai}
      initialView={view}
    >
      {ui}
    </AppProvider>,
  );
}

/** Serious or critical axe violations. Colour contrast needs real layout, so it runs in the
 *  Playwright suite instead of jsdom. */
export async function seriousViolations(container: Element): Promise<string[]> {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help}`);
}
