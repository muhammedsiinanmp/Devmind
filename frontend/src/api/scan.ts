import apiClient from "./client";

export interface ScanResult {
  id: number;
  repository: number;
  scan_id: string;
  status: "pending" | "running" | "completed" | "failed";
  summary: string | null;
  health_score: number | null;
  findings: ScanFinding[];
  started_at: string | null;
  completed_at: string | null;
}

export interface ScanFinding {
  id: number;
  category: string;
  severity: "info" | "warning" | "error" | "critical";
  file_path: string;
  line_number: number | null;
  message: string;
  rule_id: string;
}

export const scanApi = {
  triggerScan: async (repositoryId: number): Promise<{ scan_id: string }> => {
    const response = await apiClient.post<{ scan_id: string }>(`/repositories/${repositoryId}/scan/`);
    return response.data;
  },

  getScanStatus: async (_repositoryId: number, scanId: string): Promise<ScanResult> => {
    const response = await apiClient.get<ScanResult>(`/reviews/scans/${scanId}/`);
    return response.data;
  },

  getLatestScan: async (repositoryId: number): Promise<ScanResult | null> => {
    // No dedicated latest-scan endpoint exists in backend contract yet.
    // Keep the API stable and return null until implemented.
    void repositoryId;
    return null;
  },

  listScans: async (repositoryId: number): Promise<{ results: ScanResult[] }> => {
    // No list-scans endpoint exists in backend contract yet.
    // Keep the API stable and return an empty list until implemented.
    void repositoryId;
    return { results: [] };
  },
};
