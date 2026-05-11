import apiClient from "./client";

export interface LLMProvider {
  id: number;
  name: string;
  provider: string;
  model_name: string;
  masked_key: string;
  base_url: string;
  is_active: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
}

export const settingsApi = {
  getLLMSettings: async (): Promise<LLMProvider[]> => {
    const response = await apiClient.get<LLMProvider[]>("/settings/llm/");
    return response.data;
  },

  addProvider: async (data: {
    name: string;
    provider: string;
    model_name: string;
    api_key: string;
    base_url?: string;
    is_active?: boolean;
  }): Promise<LLMProvider> => {
    const response = await apiClient.post<LLMProvider>("/settings/llm/", data);
    return response.data;
  },

  updateProvider: async (id: number, data: Partial<LLMProvider>): Promise<LLMProvider> => {
    const response = await apiClient.patch<LLMProvider>(`/settings/llm/${id}/`, data);
    return response.data;
  },

  deleteProvider: async (id: number): Promise<void> => {
    await apiClient.delete(`/settings/llm/${id}/`);
  },

  testProvider: async (data: {
    provider: string;
    model_name: string;
    api_key: string;
    base_url?: string;
  }): Promise<{ status: string; message: string }> => {
    const response = await apiClient.post<{ status: string; message: string }>("/settings/llm/test/", data);
    return response.data;
  },

  setDefaultProvider: async (id: number): Promise<LLMProvider> => {
    const response = await apiClient.post<LLMProvider>(`/settings/llm/${id}/set_default/`);
    return response.data;
  },
};
