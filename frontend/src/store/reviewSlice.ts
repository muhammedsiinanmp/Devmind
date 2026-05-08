import { create } from "zustand";
import { Review, ReviewDetail, reviewsApi } from "../api/reviews";

interface ReviewState {
  reviews: Review[];
  currentReview: ReviewDetail | null;
  isLoading: boolean;
  error: string | null;
  totalCount: number;
  page: number;

  fetchReviews: (page?: number) => Promise<void>;
  fetchReview: (id: number) => Promise<void>;
  createReview: (data: { repository: number; pr_number: number }) => Promise<Review>;
  setPage: (page: number) => void;
  clearError: () => void;
}

export const useReviewStore = create<ReviewState>((set, get) => ({
  reviews: [],
  currentReview: null,
  isLoading: false,
  error: null,
  totalCount: 0,
  page: 1,

  fetchReviews: async (page = 1) => {
    set({ isLoading: true, error: null });
    try {
      const response = await reviewsApi.list({ page, page_size: 10 });
      set({
        reviews: response.results,
        totalCount: response.count,
        page,
        isLoading: false,
      });
    } catch (error) {
      set({
        isLoading: false,
        error: error instanceof Error ? error.message : "Failed to fetch reviews",
      });
    }
  },

  fetchReview: async (id: number) => {
    set({ isLoading: true, error: null });
    try {
      const review = await reviewsApi.get(id);
      set({ currentReview: review, isLoading: false });
    } catch (error) {
      set({
        isLoading: false,
        error: error instanceof Error ? error.message : "Failed to fetch review",
      });
    }
  },

  createReview: async (data) => {
    set({ isLoading: true, error: null });
    try {
      const review = await reviewsApi.create(data);
      set((state) => ({
        reviews: [review, ...state.reviews],
        isLoading: false,
      }));
      return review;
    } catch (error) {
      set({
        isLoading: false,
        error: error instanceof Error ? error.message : "Failed to create review",
      });
      throw error;
    }
  },

  setPage: (page: number) => {
    set({ page });
    get().fetchReviews(page);
  },

  clearError: () => {
    set({ error: null });
  },
}));
