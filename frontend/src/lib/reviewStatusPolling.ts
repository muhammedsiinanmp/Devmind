import type { Review } from "../api/reviews";

export type ReviewStatusValue = Review["status"];

export const REVIEW_POLL_INTERVAL_MS = 3000;

export function isTerminalStatus(status: ReviewStatusValue): boolean {
  return status === "completed" || status === "failed";
}

interface PollOptions {
  fetchStatus: () => Promise<ReviewStatusValue>;
  onStatus: (status: ReviewStatusValue) => void;
  intervalMs?: number;
}

/**
 * Fetch the review status every `intervalMs` until it is terminal or the
 * returned stop function is called. The next request is scheduled only after
 * the previous one settles, so slow responses never overlap. A failed request
 * is skipped and retried on the next tick.
 */
export function startReviewStatusPolling({
  fetchStatus,
  onStatus,
  intervalMs = REVIEW_POLL_INTERVAL_MS,
}: PollOptions): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const tick = async () => {
    let status: ReviewStatusValue | undefined;
    try {
      status = await fetchStatus();
    } catch {
      // Transient error: try again on the next tick
    }
    if (stopped) return;
    if (status) {
      onStatus(status);
      if (isTerminalStatus(status)) {
        stopped = true;
        return;
      }
    }
    timer = setTimeout(tick, intervalMs);
  };

  timer = setTimeout(tick, intervalMs);

  return () => {
    stopped = true;
    if (timer !== undefined) clearTimeout(timer);
  };
}
