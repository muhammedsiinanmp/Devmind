import apiClient from "./client";

export interface Repository {
  id: number;
  github_id: number;
  full_name: string;
  name: string;
  description: string;
  is_private: boolean;
  default_branch: string;
  html_url: string;
  language: string;
  topics: string[];
  stargazers_count: number;
  is_active: boolean;
  review_enabled: boolean;
  has_webhook: boolean;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface RepositoriesListResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: Repository[];
}

export const repositoriesApi = {
  list: async (params?: { page?: number; page_size?: number }): Promise<RepositoriesListResponse> => {
    const response = await apiClient.get<RepositoriesListResponse>("/repositories/", { params });
    return response.data;
  },

  get: async (id: number): Promise<Repository> => {
    const response = await apiClient.get<Repository>(`/repositories/${id}/`);
    return response.data;
  },

  update: async (id: number, data: Partial<Repository>): Promise<Repository> => {
    const response = await apiClient.patch<Repository>(`/repositories/${id}/`, data);
    return response.data;
  },

  connect: async (): Promise<{ message: string; task_id: string }> => {
    const response = await apiClient.post("/repositories/connect/");
    return response.data;
  },

  triggerScan: async (id: number): Promise<{ message: string; scan_id: number }> => {
    const response = await apiClient.post(`/repositories/${id}/scan/`);
    return response.data;
  },
};
