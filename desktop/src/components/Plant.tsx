import type { Status } from "../api/types";

/** One plant per check: sprout (pass), thistle (fail), drooping (warn), seed (skipped),
 *  withered (error), bare soil (not applicable). Decorative: the parent carries the label. */
export function Plant({ status, size = 44 }: { status: Status; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      {status === "PASS" && (
        <g fill="var(--fern)" stroke="var(--fern)" strokeWidth="2" strokeLinecap="round">
          <path d="M20 38V18" fill="none" />
          <path d="M20 24c-7 0-11-4-11-10 6 0 11 3 11 10Z" stroke="none" />
          <path d="M20 20c0-7 4-12 11-12 0 7-4 12-11 12Z" stroke="none" />
        </g>
      )}
      {status === "FAIL" && (
        <g stroke="var(--thistle)" strokeWidth="2" strokeLinecap="round" fill="none">
          <path d="M20 38V16M20 30l-6-5M20 27l6-4" />
          <circle cx="20" cy="12" r="5" fill="var(--thistle)" />
          <path d="M20 7V2M15 8l-3-4M25 8l3-4M14 12h-5M26 12h5" />
        </g>
      )}
      {status === "WARN" && (
        <g stroke="var(--pollen)" strokeWidth="2" strokeLinecap="round" fill="none">
          <path d="M20 38V22c0-6 4-9 9-10" />
          <path d="M29 12c2 4 1 8-3 10-2-4-1-8 3-10Z" fill="var(--pollen)" />
          <path d="M20 30c-5 0-8-2-9-6 4 0 8 1 9 6Z" fill="var(--pollen)" />
        </g>
      )}
      {status === "SKIPPED" && (
        <ellipse
          cx="20"
          cy="33"
          rx="5"
          ry="3.5"
          fill="none"
          stroke="var(--stone)"
          strokeWidth="2"
        />
      )}
      {status === "ERROR" && (
        <path
          d="M20 38V26l-6-6M20 26l5-3"
          stroke="var(--stone)"
          strokeWidth="2"
          strokeLinecap="round"
          fill="none"
        />
      )}
      {status === "NOT_APPLICABLE" && (
        <path d="M12 36h16" stroke="var(--stone)" strokeWidth="2" strokeDasharray="2 3" />
      )}
    </svg>
  );
}

export const STATUS_WORDS: Record<Status, string> = {
  PASS: "Healthy",
  FAIL: "Weed",
  WARN: "Needs care",
  SKIPPED: "Not checked",
  ERROR: "Check failed",
  NOT_APPLICABLE: "Not applicable",
};
