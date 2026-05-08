import apiClient from "./client";

export interface Review {
  id: number;
  repository: number;
  pr_number: number;
  pr_title: string;
  head_sha: string;
  status: "pending" | "processing" | "completed" | "failed";
  risk_score: number;
  summary: string;
  created_at: string;
  completed_at: string | null;
}

export interface ReviewComment {
  id: number;
  file_path: string;
  line_number: number;
  category: string;
  severity: "info" | "warning" | "error" | "critical";
  body: string;
  suggested_fix: string | null;
}

export interface ReviewDetail extends Review {
  comments: ReviewComment[];
}

export interface ReviewsListResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: Review[];
}

export const reviewsApi = {
  list: async (params?: { page?: number; page_size?: number }): Promise<ReviewsListResponse> => {
    const response = await apiClient.get<ReviewsListResponse>("/reviews/", { params });
    return response.data;
  },

  get: async (id: number): Promise<ReviewDetail> => {
    const response = await apiClient.get<ReviewDetail>(`/reviews/${id}/`);
    return response.data;
  },

  create: async (data: { repository: number; pr_number: number }): Promise<Review> => {
    const response = await apiClient.post<Review>("/reviews/", data);
    return response.data;
  },

  getComments: async (reviewId: number): Promise<ReviewComment[]> => {
    const response = await apiClient.get<ReviewComment[]>(`/reviews/${reviewId}/comments/`);
    return response.data;
  },
};
