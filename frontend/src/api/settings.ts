import apiClient from "./client";

export interface LLMProvider {
  id: number;
  name: string;
  provider_type: string;
  api_key: string;
  api_endpoint?: string;
  model_name: string;
  is_active: boolean;
  is_default: boolean;
}

export interface LLMSettings {
  providers: LLMProvider[];
  default_provider: number | null;
}

export const settingsApi = {
  getLLMSettings: async (): Promise<LLMSettings> => {
    const response = await apiClient.get<LLMSettings>("/settings/llm/");
    return response.data;
  },

  addProvider: async (data: Omit<LLMProvider, "id">): Promise<LLMProvider> => {
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

  testProvider: async (id: number): Promise<{ success: boolean; message: string }> => {
    const response = await apiClient.post<{ success: boolean; message: string }>(`/settings/llm/${id}/test/`);
    return response.data;
  },

  setDefaultProvider: async (id: number): Promise<LLMProvider> => {
    const response = await apiClient.post<LLMProvider>(`/settings/llm/${id}/set_default/`);
    return response.data;
  },
};
