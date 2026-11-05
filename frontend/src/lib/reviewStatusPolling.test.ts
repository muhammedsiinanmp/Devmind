import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { startReviewStatusPolling, type ReviewStatusValue } from "./reviewStatusPolling";

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
});
