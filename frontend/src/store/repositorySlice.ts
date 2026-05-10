import { create } from "zustand";
import { Repository, repositoriesApi } from "../api/repositories";

interface RepositoryState {
  repositories: Repository[];
  isLoading: boolean;
  isSyncing: boolean;
  error: string | null;
  totalCount: number;
  page: number;

  fetchRepositories: (page?: number) => Promise<void>;
  syncRepositories: () => Promise<void>;
  toggleReview: (id: number, enabled: boolean) => Promise<void>;
  setPage: (page: number) => void;
  clearError: () => void;
}

export const useRepositoryStore = create<RepositoryState>((set, get) => ({
  repositories: [],
  isLoading: false,
  isSyncing: false,
  error: null,
  totalCount: 0,
  page: 1,

  fetchRepositories: async (page = 1) => {
    set({ isLoading: true, error: null });
    try {
      const response = await repositoriesApi.list({ page, page_size: 10 });
      set({
        repositories: response.results,
        totalCount: response.count,
        page,
        isLoading: false,
      });
    } catch (error) {
      set({
        isLoading: false,
        error: error instanceof Error ? error.message : "Failed to fetch repositories",
      });
    }
  },

  syncRepositories: async () => {
    set({ isSyncing: true, error: null });
    try {
      await repositoriesApi.connect();
      // Wait a bit for sync to start or just refetch
      await get().fetchRepositories(get().page);
      set({ isSyncing: false });
    } catch (error) {
      set({
        isSyncing: false,
        error: error instanceof Error ? error.message : "Failed to sync repositories",
      });
    }
  },

  toggleReview: async (id: number, enabled: boolean) => {
    try {
      const updated = await repositoriesApi.update(id, { review_enabled: enabled });
      set((state) => ({
        repositories: state.repositories.map((r) => (r.id === id ? updated : r)),
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : "Failed to update repository",
      });
      throw error;
    }
  },

  setPage: (page: number) => {
    set({ page });
    get().fetchRepositories(page);
  },

  clearError: () => {
    set({ error: null });
  },
}));
