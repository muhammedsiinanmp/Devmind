import { describe, expect, it, vi } from "vitest";
import {
  REVIEW_LOAD_ERROR,
  REVIEW_REFRESH_ERROR,
  createReviewLoader,
  initialReviewLoadState,
  type ReviewLoadState,
} from "./reviewLoader";

interface FakeReview {
  id: number;
  status: string;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// Holds state the way useState would, so tests assert what the page renders from.
function setup(fetchReview: (id: number) => Promise<FakeReview>) {
  let state: ReviewLoadState<FakeReview> = initialReviewLoadState();
  const loader = createReviewLoader<FakeReview>({
    fetchReview,
    update: (updater) => {
      state = updater(state);
    },
  });
  return { loader, state: () => state };
}

function serverError() {
  return Object.assign(new Error("Request failed with status code 500"), { response: { status: 500 } });
}

describe("createReviewLoader", () => {
  it("loads a review", async () => {
    const { loader, state } = setup(async (id) => ({ id, status: "processing" }));

    await loader.load(5);

    expect(state()).toEqual({
      review: { id: 5, status: "processing" },
      isLoading: false,
      error: null,
      refreshError: null,
    });
  });

  it("shows the full-page error when the first load fails", async () => {
    const { loader, state } = setup(() => Promise.reject(serverError()));

    await loader.load(5);

    expect(state().review).toBeNull();
    expect(state().error).toBe(REVIEW_LOAD_ERROR);
    expect(state().isLoading).toBe(false);
  });

  it("keeps the review on screen and sets the inline notice when the refetch fails", async () => {
    const fetchReview = vi
      .fn<(id: number) => Promise<FakeReview>>()
      .mockResolvedValueOnce({ id: 5, status: "processing" })
      .mockRejectedValueOnce(serverError());
    const { loader, state } = setup(fetchReview);

    await loader.load(5);
    await loader.refresh(5);

    expect(state().review).toEqual({ id: 5, status: "processing" });
    expect(state().error).toBeNull();
    expect(state().isLoading).toBe(false);
    expect(state().refreshError).toBe(REVIEW_REFRESH_ERROR);
  });

  it("replaces the review and clears the notice when a refetch succeeds", async () => {
    const fetchReview = vi
      .fn<(id: number) => Promise<FakeReview>>()
      .mockResolvedValueOnce({ id: 5, status: "processing" })
      .mockRejectedValueOnce(serverError())
      .mockResolvedValueOnce({ id: 5, status: "completed" });
    const { loader, state } = setup(fetchReview);

    await loader.load(5);
    await loader.refresh(5);
    await loader.refresh(5);

    expect(state().review).toEqual({ id: 5, status: "completed" });
    expect(state().refreshError).toBeNull();
  });

  it("ignores a late refetch response for a previous review id", async () => {
    const lateRefresh = deferred<FakeReview>();
    const fetchReview = vi
      .fn<(id: number) => Promise<FakeReview>>()
      .mockResolvedValueOnce({ id: 5, status: "processing" })
      .mockReturnValueOnce(lateRefresh.promise)
      .mockResolvedValueOnce({ id: 6, status: "pending" });
    const { loader, state } = setup(fetchReview);

    await loader.load(5);
    const refreshing = loader.refresh(5);
    await loader.load(6);
    lateRefresh.resolve({ id: 5, status: "completed" });
    await refreshing;

    expect(state().review).toEqual({ id: 6, status: "pending" });
  });

  it("ignores a late refetch failure for a previous review id", async () => {
    const lateRefresh = deferred<FakeReview>();
    const fetchReview = vi
      .fn<(id: number) => Promise<FakeReview>>()
      .mockResolvedValueOnce({ id: 5, status: "processing" })
      .mockReturnValueOnce(lateRefresh.promise)
      .mockResolvedValueOnce({ id: 6, status: "pending" });
    const { loader, state } = setup(fetchReview);

    await loader.load(5);
    const refreshing = loader.refresh(5);
    await loader.load(6);
    lateRefresh.reject(serverError());
    await refreshing;

    expect(state().review).toEqual({ id: 6, status: "pending" });
    expect(state().error).toBeNull();
    expect(state().refreshError).toBeNull();
  });

  it("clears a refetch notice when another review loads", async () => {
    const fetchReview = vi
      .fn<(id: number) => Promise<FakeReview>>()
      .mockResolvedValueOnce({ id: 5, status: "processing" })
      .mockRejectedValueOnce(serverError())
      .mockResolvedValueOnce({ id: 6, status: "pending" });
    const { loader, state } = setup(fetchReview);

    await loader.load(5);
    await loader.refresh(5);
    await loader.load(6);

    expect(state().refreshError).toBeNull();
  });

  it("ignores a late load response for a previous review id", async () => {
    const lateLoad = deferred<FakeReview>();
    const fetchReview = vi
      .fn<(id: number) => Promise<FakeReview>>()
      .mockReturnValueOnce(lateLoad.promise)
      .mockResolvedValueOnce({ id: 6, status: "pending" });
    const { loader, state } = setup(fetchReview);

    const loadingFive = loader.load(5);
    await loader.load(6);
    lateLoad.resolve({ id: 5, status: "completed" });
    await loadingFive;

    expect(state().review).toEqual({ id: 6, status: "pending" });
    expect(state().isLoading).toBe(false);
  });

  it("ignores a late load failure for a previous review id", async () => {
    const lateLoad = deferred<FakeReview>();
    const fetchReview = vi
      .fn<(id: number) => Promise<FakeReview>>()
      .mockReturnValueOnce(lateLoad.promise)
      .mockResolvedValueOnce({ id: 6, status: "pending" });
    const { loader, state } = setup(fetchReview);

    const loadingFive = loader.load(5);
    await loader.load(6);
    lateLoad.reject(serverError());
    await loadingFive;

    expect(state().review).toEqual({ id: 6, status: "pending" });
    expect(state().error).toBeNull();
  });
});
