import { useEffect, useState } from "react";
import apiClient from "../api/client";
import {
  GitBranch, RefreshCw, ExternalLink, Star, Clock, CheckCircle2,
  XCircle, AlertCircle, Loader2, ChevronLeft, ChevronRight
} from "lucide-react";

interface Repository {
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

export default function Repositories() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSyncing, setIsSyncing] = useState(false);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  const fetchRepositories = async (pageNum: number) => {
    setIsLoading(true);
    try {
      const res = await apiClient.get<{ count: number; results: Repository[] }>("/repositories/", { params: { page: pageNum, page_size: 10 } });
      setRepositories(res.data.results);
      setTotalPages(Math.ceil(res.data.count / 10));
    } catch {
      // handle error
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { fetchRepositories(page); }, [page]);

  const handleSync = async () => {
    setIsSyncing(true);
    try {
      await apiClient.post("/repositories/connect/");
      await fetchRepositories(page);
    } catch {
      // handle error
    } finally {
      setIsSyncing(false);
    }
  };

  const handleToggleReview = async (id: number, enabled: boolean) => {
    try {
      const res = await apiClient.patch<Repository>(`/repositories/${id}/`, { review_enabled: !enabled });
      setRepositories(repos => repos.map(r => r.id === id ? res.data : r));
    } catch {
      // handle error
    }
  };

  if (isLoading && repositories.length === 0) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin" style={{ color: "var(--accent)" }} />
        <p className="animate-pulse" style={{ color: "var(--text-secondary)" }}>Fetching your repositories...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold mb-2 text-gradient">Repositories</h1>
          <p className="text-lg" style={{ color: "var(--text-secondary)" }}>
            Manage your connected GitHub repositories and AI review settings.
          </p>
        </div>
        <button onClick={handleSync} disabled={isSyncing} className="btn-primary flex items-center gap-2">
          {isSyncing ? <><RefreshCw className="w-4 h-4 animate-spin" /> Syncing...</> : <><RefreshCw className="w-4 h-4" /> Sync with GitHub</>}
        </button>
      </div>

      {repositories.length === 0 ? (
        <div className="glass-card p-12 text-center flex flex-col items-center justify-center space-y-4">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center border" style={{ backgroundColor: "var(--bg-tertiary)", borderColor: "var(--border)" }}>
            <GitBranch className="w-8 h-8" style={{ color: "var(--text-muted)" }} />
          </div>
          <h3 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>No repositories found</h3>
          <p className="max-w-md" style={{ color: "var(--text-secondary)" }}>
            We couldn't find any repositories connected to your account. Click the button above to sync with your GitHub profile.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {repositories.map((repo) => (
            <div key={repo.id} className="glass-card p-6 flex flex-col md:flex-row md:items-center justify-between gap-6">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-xl flex items-center justify-center border transition-colors"
                  style={{ backgroundColor: "var(--bg-tertiary)", borderColor: "var(--border)" }}>
                  <GitBranch className="w-6 h-6" style={{ color: repo.is_active ? "var(--accent)" : "var(--text-muted)" }} />
                </div>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>{repo.full_name}</h3>
                    {repo.is_private && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded font-bold uppercase tracking-wider" style={{ backgroundColor: "var(--bg-tertiary)", color: "var(--text-muted)", border: "1px solid var(--border)" }}>
                        Private
                      </span>
                    )}
                  </div>
                  <p className="text-sm line-clamp-1 max-w-xl" style={{ color: "var(--text-secondary)" }}>
                    {repo.description || "No description provided."}
                  </p>
                  <div className="flex flex-wrap items-center gap-4 text-xs pt-1" style={{ color: "var(--text-muted)" }}>
                    {repo.language && (
                      <span className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: "var(--accent)" }} />
                        {repo.language}
                      </span>
                    )}
                    <span className="flex items-center gap-1.5"><Star className="w-3.5 h-3.5" /> {repo.stargazers_count}</span>
                    <span className="flex items-center gap-1.5">
                      <Clock className="w-3.5 h-3.5" />
                      Synced {repo.last_synced_at ? new Date(repo.last_synced_at).toLocaleDateString() : "Never"}
                    </span>
                    <a href={repo.html_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 hover:opacity-80 transition-opacity">
                      <ExternalLink className="w-3.5 h-3.5" /> View on GitHub
                    </a>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 p-3 rounded-2xl border" style={{ backgroundColor: "rgba(31,31,35,0.5)", borderColor: "var(--border)" }}>
                <div className="flex flex-col gap-1 pr-4 border-r" style={{ borderColor: "var(--border)" }}>
                  <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Webhook</span>
                  {repo.has_webhook ? (
                    <span className="flex items-center gap-1 text-xs font-semibold" style={{ color: "var(--success)" }}>
                      <CheckCircle2 className="w-3 h-3" /> Installed
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-xs font-semibold" style={{ color: "var(--warning)" }}>
                      <AlertCircle className="w-3 h-3" /> Missing
                    </span>
                  )}
                </div>

                <div className="flex flex-col gap-2 pl-2">
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>AI Review</span>
                    <button onClick={() => handleToggleReview(repo.id, repo.review_enabled)}
                      style={{ backgroundColor: repo.review_enabled ? "var(--accent)" : "var(--bg-tertiary)", border: "1px solid var(--border)" }}>
                      <span className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${repo.review_enabled ? 'translate-x-6' : 'translate-x-1'}`} />
                    </button>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-xs font-semibold" style={{ color: "var(--text-secondary)" }}>Active</span>
                    <div style={{ color: repo.is_active ? "var(--success)" : "var(--error)" }}>
                      {repo.is_active ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-6 mt-10">
          <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="btn-secondary flex items-center gap-2">
            <ChevronLeft className="w-4 h-4" /> Previous
          </button>
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>Page {page} of {totalPages}</span>
          <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages} className="btn-secondary flex items-center gap-2">
            Next <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
