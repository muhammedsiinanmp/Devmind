import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createTerminalStatusHandler,
  startReviewStatusPolling,
  type ReviewStatusValue,
} from "./reviewStatusPolling";

function httpError(status: number) {
  return Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } });
}

function failing(error: unknown) {
  return vi.fn<() => Promise<ReviewStatusValue>>().mockRejectedValue(error);
}

function sequence(...statuses: ReviewStatusValue[]) {
  const fetchStatus = vi.fn<() => Promise<ReviewStatusValue>>();
  for (const status of statuses) fetchStatus.mockResolvedValueOnce(status);
  return fetchStatus;
}

describe("startReviewStatusPolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls every 3 seconds and reports each status", async () => {
    const fetchStatus = sequence("pending", "processing", "processing");
    const onStatus = vi.fn();
    const stop = startReviewStatusPolling({ fetchStatus, onStatus });

    await vi.advanceTimersByTimeAsync(2999);
    expect(fetchStatus).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(fetchStatus).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(6000);
    expect(fetchStatus).toHaveBeenCalledTimes(3);
    expect(onStatus.mock.calls.map(([s]) => s)).toEqual(["pending", "processing", "processing"]);
    stop();
  });

  it.each(["completed", "failed"] as const)("stops polling once the status is %s", async (terminal) => {
    const fetchStatus = sequence("processing", terminal);
    const onStatus = vi.fn();
    startReviewStatusPolling({ fetchStatus, onStatus });

    await vi.advanceTimersByTimeAsync(6000);
    expect(onStatus).toHaveBeenLastCalledWith(terminal);

    await vi.advanceTimersByTimeAsync(30000);
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stops polling when stop is called (component unmount)", async () => {
    const fetchStatus = vi.fn<() => Promise<ReviewStatusValue>>().mockResolvedValue("processing");
    const stop = startReviewStatusPolling({ fetchStatus, onStatus: vi.fn() });

    await vi.advanceTimersByTimeAsync(3000);
    expect(fetchStatus).toHaveBeenCalledTimes(1);

    stop();
    await vi.advanceTimersByTimeAsync(30000);
    expect(fetchStatus).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not report a status that arrives after stop", async () => {
    let resolve: (s: ReviewStatusValue) => void = () => {};
    const fetchStatus = vi.fn(() => new Promise<ReviewStatusValue>((r) => (resolve = r)));
    const onStatus = vi.fn();
    const stop = startReviewStatusPolling({ fetchStatus, onStatus });

    await vi.advanceTimersByTimeAsync(3000);
    stop();
    resolve("completed");
    await vi.advanceTimersByTimeAsync(3000);

    expect(onStatus).not.toHaveBeenCalled();
    expect(fetchStatus).toHaveBeenCalledTimes(1);
  });

  it("keeps polling after a failed request", async () => {
    const fetchStatus = vi
      .fn<() => Promise<ReviewStatusValue>>()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce("completed");
    const onStatus = vi.fn();
    startReviewStatusPolling({ fetchStatus, onStatus });

    await vi.advanceTimersByTimeAsync(6000);
    expect(fetchStatus).toHaveBeenCalledTimes(2);
    expect(onStatus).toHaveBeenCalledTimes(1);
    expect(onStatus).toHaveBeenCalledWith("completed");
  });

  it.each([
    [404, "not_found"],
    [403, "forbidden"],
  ] as const)("stops after one request on HTTP %i and reports %s", async (code, reason) => {
    const fetchStatus = failing(httpError(code));
    const onStatus = vi.fn();
    const onError = vi.fn();
    startReviewStatusPolling({ fetchStatus, onStatus, onError });

    await vi.advanceTimersByTimeAsync(3000);
    expect(fetchStatus).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(reason);

    await vi.advanceTimersByTimeAsync(10 * 60_000);
    expect(fetchStatus).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onStatus).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([
    ["HTTP 500", httpError(500)],
    ["HTTP 503", httpError(503)],
    ["a network error", new Error("Network Error")],
  ])("backs off exponentially after %s, capped at 60 seconds", async (_label, error) => {
    const fetchStatus = failing(error);
    const stop = startReviewStatusPolling({ fetchStatus, onStatus: vi.fn() });

    // First request after the normal 3 s interval.
    await vi.advanceTimersByTimeAsync(3000);
    expect(fetchStatus).toHaveBeenCalledTimes(1);

    // Delays after consecutive failures: 3 s, 6 s, 12 s, 24 s, 48 s, then 60 s.
    for (const delay of [3000, 6000, 12000, 24000, 48000, 60000, 60000]) {
      const calls = fetchStatus.mock.calls.length;
      await vi.advanceTimersByTimeAsync(delay - 1);
      expect(fetchStatus).toHaveBeenCalledTimes(calls);
      await vi.advanceTimersByTimeAsync(1);
      expect(fetchStatus).toHaveBeenCalledTimes(calls + 1);
    }
    stop();
  });

  it("gives up after 10 consecutive failures and reports it", async () => {
    const fetchStatus = failing(httpError(502));
    const onError = vi.fn();
    startReviewStatusPolling({ fetchStatus, onStatus: vi.fn(), onError });

    await vi.advanceTimersByTimeAsync(60 * 60_000);
    expect(fetchStatus).toHaveBeenCalledTimes(10);
    expect(onError).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith("gave_up");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("resets the backoff and failure count after a successful request", async () => {
    const fetchStatus = vi.fn<() => Promise<ReviewStatusValue>>();
    for (let i = 0; i < 9; i++) fetchStatus.mockRejectedValueOnce(httpError(500));
    fetchStatus.mockResolvedValueOnce("processing");
    fetchStatus.mockRejectedValue(httpError(500));
    const onError = vi.fn();
    startReviewStatusPolling({ fetchStatus, onStatus: vi.fn(), onError });

    // 9 failures, then the success on request 10.
    await vi.advanceTimersByTimeAsync(3000 + 3000 + 6000 + 12000 + 24000 + 48000 + 60000 * 4);
    expect(fetchStatus).toHaveBeenCalledTimes(10);

    // After the success the next request is back on the 3 s interval.
    await vi.advanceTimersByTimeAsync(2999);
    expect(fetchStatus).toHaveBeenCalledTimes(10);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchStatus).toHaveBeenCalledTimes(11);

    // The failure count restarted, so polling continues past 10 total failures.
    expect(onError).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(60 * 60_000);
    expect(fetchStatus).toHaveBeenCalledTimes(20);
    expect(onError).toHaveBeenCalledWith("gave_up");
  });

  it("does not report an error that arrives after stop", async () => {
    let reject: (e: unknown) => void = () => {};
    const fetchStatus = vi.fn(() => new Promise<ReviewStatusValue>((_, r) => (reject = r)));
    const onError = vi.fn();
    const stop = startReviewStatusPolling({ fetchStatus, onStatus: vi.fn(), onError });

    await vi.advanceTimersByTimeAsync(3000);
    stop();
    reject(httpError(404));
    await vi.advanceTimersByTimeAsync(3000);

    expect(onError).not.toHaveBeenCalled();
  });
});

describe("createTerminalStatusHandler (ReviewDetail refetch on completion)", () => {
  it.each(["completed", "failed"] as const)("calls the refetch when the status becomes %s", (terminal) => {
    const refetch = vi.fn();
    const onStatusChange = createTerminalStatusHandler(refetch);

    onStatusChange("processing");
    expect(refetch).not.toHaveBeenCalled();

    onStatusChange(terminal);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("ignores non-terminal statuses", () => {
    const refetch = vi.fn();
    const onStatusChange = createTerminalStatusHandler(refetch);

    onStatusChange("pending");
    onStatusChange("processing");
    expect(refetch).not.toHaveBeenCalled();
  });
});
