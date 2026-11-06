export const REVIEW_LOAD_ERROR = "Failed to load review";
export const REVIEW_REFRESH_ERROR = "Couldn't load the final results. Reload to try again.";

export interface ReviewLoadState<T> {
  review: T | null;
  isLoading: boolean;
  /** Full-page error: the first load failed, so there is no review to show. */
  error: string | null;
  /** Inline notice: a refetch failed, so the review on screen may be stale. */
  refreshError: string | null;
}

export function initialReviewLoadState<T>(): ReviewLoadState<T> {
  return { review: null, isLoading: true, error: null, refreshError: null };
}

interface ReviewLoaderOptions<T> {
  fetchReview: (reviewId: number) => Promise<T>;
  update: (updater: (state: ReviewLoadState<T>) => ReviewLoadState<T>) => void;
}

/**
 * Load a review and refetch it in place.
 *
 * `load` shows the loading screen and, on failure, the full-page error.
 * `refresh` keeps the review on screen; on failure it only sets
 * `refreshError`. Each `load` supersedes everything started before it, so a
 * late response for a previous review id (from either call) is ignored.
 */
export function createReviewLoader<T>({ fetchReview, update }: ReviewLoaderOptions<T>) {
  let generation = 0;

  return {
    async load(reviewId: number): Promise<void> {
      const mine = ++generation;
      update((s) => ({ ...s, isLoading: true, error: null, refreshError: null }));
      try {
        const review = await fetchReview(reviewId);
        if (mine !== generation) return;
        update((s) => ({ ...s, review, isLoading: false }));
      } catch {
        if (mine !== generation) return;
        update((s) => ({ ...s, error: REVIEW_LOAD_ERROR, isLoading: false }));
      }
    },

    async refresh(reviewId: number): Promise<void> {
      const mine = generation;
      try {
        const review = await fetchReview(reviewId);
        if (mine !== generation) return;
        update((s) => ({ ...s, review, refreshError: null }));
      } catch {
        if (mine !== generation) return;
        update((s) => ({ ...s, refreshError: REVIEW_REFRESH_ERROR }));
      }
    },
  };
}
