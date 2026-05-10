import { useEffect } from "react";
import { useRepositoryStore } from "../store/repositorySlice";
import {
  GitBranch,
  RefreshCw,
  Settings2,
  ExternalLink,
  Star,
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Loader2,
  ChevronLeft,
  ChevronRight
} from "lucide-react";

export default function Repositories() {
  const {
    repositories,
    isLoading,
    isSyncing,
    totalCount,
    page,
    fetchRepositories,
    syncRepositories,
    toggleReview,
    setPage
  } = useRepositoryStore();

  useEffect(() => {
    fetchRepositories(page);
  }, [page]);

  const totalPages = Math.ceil(totalCount / 10);

  const handleSync = async () => {
    await syncRepositories();
  };

  const handleToggleReview = async (id: number, current: boolean) => {
    await toggleReview(id, !current);
  };

  if (isLoading && repositories.length === 0) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin text-accent" />
        <p className="text-text-secondary animate-pulse">Fetching your repositories...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold text-gradient mb-2">Repositories</h1>
          <p className="text-text-secondary text-lg">
            Manage your connected GitHub repositories and AI review settings.
          </p>
        </div>
        <button
          onClick={handleSync}
          disabled={isSyncing}
          className="btn-primary flex items-center gap-2"
        >
          {isSyncing ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              Syncing...
            </>
          ) : (
            <>
              <RefreshCw className="w-4 h-4" />
              Sync with GitHub
            </>
          )}
        </button>
      </div>

      {repositories.length === 0 ? (
        <div className="glass-card p-12 text-center flex flex-col items-center justify-center space-y-4">
          <div className="w-16 h-16 bg-bg-tertiary rounded-2xl flex items-center justify-center border border-border">
            <GitBranch className="w-8 h-8 text-text-muted" />
          </div>
          <h3 className="text-xl font-semibold">No repositories found</h3>
          <p className="text-text-secondary max-w-md">
            We couldn't find any repositories connected to your account. Click the button above to sync with your GitHub profile.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {repositories.map((repo) => (
            <div key={repo.id} className="glass-card p-6 flex flex-col md:flex-row md:items-center justify-between gap-6 group">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-xl bg-bg-tertiary flex items-center justify-center border border-border group-hover:border-accent/30 transition-colors">
                  <GitBranch className={`w-6 h-6 ${repo.is_active ? 'text-accent' : 'text-text-muted'}`} />
                </div>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-bold text-text-primary">{repo.full_name}</h3>
                    {repo.is_private && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-bg-tertiary text-text-muted border border-border font-bold uppercase tracking-wider">
                        Private
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-text-secondary line-clamp-1 max-w-xl">
                    {repo.description || "No description provided."}
                  </p>
                  <div className="flex flex-wrap items-center gap-4 text-xs text-text-muted pt-1">
                    {repo.language && (
                      <span className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full bg-accent" />
                        {repo.language}
                      </span>
                    )}
                    <span className="flex items-center gap-1.5">
                      <Star className="w-3.5 h-3.5" />
                      {repo.stargazers_count}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <Clock className="w-3.5 h-3.5" />
                      Synced {repo.last_synced_at ? new Date(repo.last_synced_at).toLocaleDateString() : "Never"}
                    </span>
                    <a
                      href={repo.html_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 hover:text-accent transition-colors"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      View on GitHub
                    </a>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3 bg-bg-tertiary/50 p-3 rounded-2xl border border-border">
                <div className="flex flex-col gap-1 pr-4 border-r border-border">
                  <span className="text-[10px] font-bold text-text-muted uppercase tracking-wider">Webhook</span>
                  {repo.has_webhook ? (
                    <span className="flex items-center gap-1 text-xs text-success font-semibold">
                      <CheckCircle2 className="w-3 h-3" /> Installed
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-xs text-warning font-semibold">
                      <AlertCircle className="w-3 h-3" /> Missing
                    </span>
                  )}
                </div>

                <div className="flex flex-col gap-2 pl-2">
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-xs font-semibold text-text-secondary">AI Review</span>
                    <button
                      onClick={() => handleToggleReview(repo.id, repo.review_enabled)}
                      className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors ${
                        repo.review_enabled ? 'bg-accent' : 'bg-bg-tertiary border border-border'
                      }`}
                    >
                      <span
                        className={`inline-block h-3 w-3 transform rounded-full bg-white transition-transform ${
                          repo.review_enabled ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-xs font-semibold text-text-secondary">Active</span>
                    <div className={repo.is_active ? 'text-success' : 'text-error'}>
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
          <button
            onClick={() => setPage(page - 1)}
            disabled={page === 1}
            className="btn-secondary flex items-center gap-2 disabled:opacity-30"
          >
            <ChevronLeft className="w-4 h-4" /> Previous
          </button>
          <div className="flex items-center gap-2">
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
              <button
                key={p}
                onClick={() => setPage(p)}
                className={`w-10 h-10 rounded-lg transition-all ${
                  page === p
                    ? "bg-accent text-white font-bold shadow-accent"
                    : "hover:bg-white/5 text-text-secondary"
                }`}
              >
                {p}
              </button>
            ))}
          </div>
          <button
            onClick={() => setPage(page + 1)}
            disabled={page >= totalPages}
            className="btn-secondary flex items-center gap-2 disabled:opacity-30"
          >
            Next <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  );
}
