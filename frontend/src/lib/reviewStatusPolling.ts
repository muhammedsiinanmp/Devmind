import type { Review } from "../api/reviews";

export type ReviewStatusValue = Review["status"];

export const REVIEW_POLL_INTERVAL_MS = 3000;
export const REVIEW_POLL_MAX_INTERVAL_MS = 60_000;
export const REVIEW_POLL_MAX_FAILURES = 10;

/**
 * Why polling stopped without reaching a terminal status:
 * - `forbidden`: the API answered 403
 * - `not_found`: the API answered 404
 * - `gave_up`: too many consecutive 5xx or network failures
 */
export type ReviewPollError = "forbidden" | "not_found" | "gave_up";

export function isTerminalStatus(status: ReviewStatusValue): boolean {
  return status === "completed" || status === "failed";
}

/**
 * Return a status callback that calls `onTerminal` when the status becomes
 * `completed` or `failed`. ReviewDetail uses it to refetch the review.
 */
export function createTerminalStatusHandler(onTerminal: () => void): (status: ReviewStatusValue) => void {
  return (status) => {
    if (isTerminalStatus(status)) onTerminal();
  };
}

function httpStatusOf(error: unknown): number | undefined {
  if (typeof error !== "object" || error === null) return undefined;
  const status = (error as { response?: { status?: unknown } }).response?.status;
  return typeof status === "number" ? status : undefined;
}

interface PollOptions {
  fetchStatus: () => Promise<ReviewStatusValue>;
  onStatus: (status: ReviewStatusValue) => void;
  onError?: (error: ReviewPollError) => void;
  intervalMs?: number;
  maxIntervalMs?: number;
  maxFailures?: number;
}

/**
 * Fetch the review status every `intervalMs` until it is terminal or the
 * returned stop function is called. The next request is scheduled only after
 * the previous one settles, so slow responses never overlap.
 *
 * A 403 or 404 stops polling at once. Any other failure (5xx, network) backs
 * off: after the nth consecutive failure the next request waits
 * `intervalMs * 2^(n-1)`, capped at `maxIntervalMs`. After `maxFailures`
 * consecutive failures polling stops. A successful request resets the count.
 * When polling stops on an error, `onError` is called once with the reason.
 * 401 is left to the API client's token-refresh interceptor.
 */
export function startReviewStatusPolling({
  fetchStatus,
  onStatus,
  onError,
  intervalMs = REVIEW_POLL_INTERVAL_MS,
  maxIntervalMs = REVIEW_POLL_MAX_INTERVAL_MS,
  maxFailures = REVIEW_POLL_MAX_FAILURES,
}: PollOptions): () => void {
  let stopped = false;
  let failures = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const fail = (reason: ReviewPollError) => {
    stopped = true;
    onError?.(reason);
  };

  const tick = async () => {
    let status: ReviewStatusValue;
    try {
      status = await fetchStatus();
    } catch (error) {
      if (stopped) return;
      const httpStatus = httpStatusOf(error);
      if (httpStatus === 403) return fail("forbidden");
      if (httpStatus === 404) return fail("not_found");
      failures += 1;
      if (failures >= maxFailures) return fail("gave_up");
      timer = setTimeout(tick, Math.min(intervalMs * 2 ** (failures - 1), maxIntervalMs));
      return;
    }
    if (stopped) return;
    failures = 0;
    onStatus(status);
    if (isTerminalStatus(status)) {
      stopped = true;
      return;
    }
    timer = setTimeout(tick, intervalMs);
  };

  timer = setTimeout(tick, intervalMs);

  return () => {
    stopped = true;
    if (timer !== undefined) clearTimeout(timer);
  };
}
