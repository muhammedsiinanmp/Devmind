import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import apiClient, { authApi } from "../api/client";
import ReviewStatus from "../components/review/ReviewStatus";
import DiffViewer, { type DiffFile } from "../components/review/DiffViewer";
import {
  Loader2, CheckCircle, AlertTriangle, Info, ArrowLeft, ExternalLink,
  ChevronRight, GitPullRequest, RefreshCw
} from "lucide-react";

interface ReviewComment {
  id: number;
  file_path: string;
  line_number: number;
  category: string;
  severity: "info" | "warning" | "error" | "critical";
  body: string;
  suggested_fix: string | null;
}

interface ReviewDetail {
  id: number;
  repository: number;
  repository_name: string;
  pr_number: number;
  pr_title: string;
  head_sha: string;
  base_sha: string;
  diff_url: string;
  status: "pending" | "processing" | "completed" | "failed";
  risk_score: number | null;
  summary: string | null;
  created_at: string;
  completed_at: string | null;
  comments: ReviewComment[];
  run?: { diff_text?: string };
}

function normalizePath(path: string): string {
  return path.replace(/^a\//, "").replace(/^b\//, "");
}

function parseUnifiedDiff(diffText: string): DiffFile[] {
  type MutableDiffFile = {
    file_path: string;
    additions: number;
    deletions: number;
    patchLines: string[];
    oldLines: string[];
    newLines: string[];
    inHunk: boolean;
  };

  const lines = diffText.replace(/\r\n/g, "\n").split("\n");
  const files: DiffFile[] = [];
  let current: MutableDiffFile | null = null;

  const pushCurrent = () => {
    if (!current) return;
    files.push({
      file_path: normalizePath(current.file_path),
      additions: current.additions,
      deletions: current.deletions,
      patch: current.patchLines.join("\n"),
      old_content: current.oldLines.join("\n"),
      new_content: current.newLines.join("\n"),
    });
    current = null;
  };

  for (const line of lines) {
    if (line.startsWith("diff --git ")) {
      pushCurrent();
      const match = line.match(/^diff --git a\/(.+?) b\/(.+)$/);
      current = {
        file_path: match?.[2] || "",
        additions: 0,
        deletions: 0,
        patchLines: [],
        oldLines: [],
        newLines: [],
        inHunk: false,
      };
      continue;
    }

    if (!current) continue;

    if (line.startsWith("@@")) {
      current.inHunk = true;
      current.patchLines.push(line);
      continue;
    }

    if (!current.inHunk) continue;

    if (line.startsWith("+") && !line.startsWith("+++")) {
      current.additions += 1;
      current.patchLines.push(line);
      current.newLines.push(line.slice(1));
      continue;
    }

    if (line.startsWith("-") && !line.startsWith("---")) {
      current.deletions += 1;
      current.patchLines.push(line);
      current.oldLines.push(line.slice(1));
      continue;
    }

    if (line.startsWith(" ")) {
      const content = line.slice(1);
      current.patchLines.push(line);
      current.oldLines.push(content);
      current.newLines.push(content);
      continue;
    }

    if (line.startsWith("\\ No newline at end of file")) {
      current.patchLines.push(line);
    }
  }

  pushCurrent();
  return files.filter((file) => file.file_path);
}

export default function ReviewDetail() {
  const { id } = useParams<{ id: string }>();
  const [review, setReview] = useState<ReviewDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState("all");
  const [retriggering, setRetriggering] = useState(false);
  const [diffFiles, setDiffFiles] = useState<DiffFile[]>([]);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);

  useEffect(() => {
    if (id) fetchReview(parseInt(id, 10));
  }, [id]);

  const fetchReview = async (reviewId: number) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.get<ReviewDetail>(`/reviews/${reviewId}/`);
      setReview(res.data);
    } catch {
      setError("Failed to load review");
    } finally {
      setIsLoading(false);
    }
  };

  const fetchDiffFiles = async (reviewData: ReviewDetail) => {
    setDiffLoading(true);
    setDiffError(null);

    try {
      let diffText = "";

      // Prefer diff stored at review time — zero extra API calls
      if (reviewData.run?.diff_text && reviewData.run.diff_text.includes("diff --git")) {
        diffText = reviewData.run.diff_text;
      }

      // Fallback: fetch from GitHub if the stored diff is missing (older reviews)
      if (!diffText) {
        if (reviewData.diff_url) {
          try {
            const direct = await fetch(reviewData.diff_url);
            if (direct.ok) {
              diffText = await direct.text();
            }
          } catch {
            // ignore and fall through to authenticated GitHub API call
          }
        }

        if (!diffText || !diffText.includes("diff --git")) {
          const tokenData = await authApi.getGithubToken();
          const ghRes = await fetch(
            `https://api.github.com/repos/${reviewData.repository_name}/pulls/${reviewData.pr_number}`,
            {
              headers: {
                Accept: "application/vnd.github.v3.diff",
                Authorization: `Bearer ${tokenData.access_token}`,
                "X-GitHub-Api-Version": "2022-11-28",
              },
            }
          );

          if (!ghRes.ok) {
            throw new Error(`GitHub API returned ${ghRes.status}`);
          }
          diffText = await ghRes.text();
        }
      }

      const parsed = parseUnifiedDiff(diffText);
      setDiffFiles(parsed);

      if (parsed.length === 0) {
        setDiffError("Diff was fetched, but no file hunks could be parsed for inline view.");
      }
    } catch {
      setDiffFiles([]);
      setDiffError("Unable to load inline diff. You can still review issues and open GitHub diff.");
    } finally {
      setDiffLoading(false);
    }
  };

  useEffect(() => {
    if (!review) return;
    fetchDiffFiles(review);
  }, [review?.id]);

  const handleRetrigger = async () => {
    if (!id || !review) return;
    setRetriggering(true);
    try {
      await apiClient.post(`/reviews/${id}/retrigger/`);
      await fetchReview(parseInt(id, 10));
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error || "Failed to retrigger";
      alert(msg);
    } finally {
      setRetriggering(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin" style={{ color: "var(--accent)" }} />
        <p className="animate-pulse" style={{ color: "var(--text-secondary)" }}>Generating report details...</p>
      </div>
    );
  }

  if (error || !review) {
    return (
      <div className="glass-card p-12 text-center flex flex-col items-center justify-center space-y-4">
        <AlertTriangle className="w-12 h-12" style={{ color: "var(--error)" }} />
        <h3 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>{error || "Review not found"}</h3>
        <Link to="/dashboard" className="btn-secondary flex items-center gap-2">
          <ArrowLeft className="w-4 h-4" /> Back to Dashboard
        </Link>
      </div>
    );
  }

  const severityCounts = review.comments.reduce((acc, c) => {
    acc[c.severity] = (acc[c.severity] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const filteredComments = activeFilter === "all" ? review.comments : review.comments.filter(c => c.severity === activeFilter);

  const riskColor = (score: number | null) => {
    if (score === null) return "var(--text-muted)";
    if (score >= 80) return "var(--error)";
    if (score >= 40) return "var(--warning)";
    return "var(--success)";
  };

  const badgeSeverity = (s: string) => {
    switch (s) {
      case "critical": case "error": return "badge-error";
      case "warning": return "badge-warning";
      default: return "badge-info";
    }
  };

  return (
    <div className="space-y-8 animate-fade-in pb-20">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <nav className="flex items-center gap-2 text-sm font-medium" style={{ color: "var(--text-muted)" }}>
          <Link to="/dashboard" className="hover:opacity-80 transition-opacity" style={{ color: "var(--text-muted)" }}>Reviews</Link>
          <ChevronRight className="w-4 h-4" />
          <span style={{ color: "var(--text-primary)" }}>PR #{review.pr_number}</span>
        </nav>
        <div className="flex items-center gap-3">
          {review.diff_url && (
            <a href={review.diff_url} target="_blank" rel="noopener noreferrer" className="btn-secondary flex items-center gap-2">
              <ExternalLink className="w-4 h-4" /> View on GitHub
            </a>
          )}
          <button onClick={handleRetrigger} disabled={retriggering} className="btn-primary flex items-center gap-2">
            {retriggering ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            {retriggering ? "Queuing..." : "Retrigger"}
          </button>
        </div>
      </div>

      <div className="glass-card p-8" style={{ background: "linear-gradient(135deg, rgba(31,31,35,0.2) 0%, transparent 100%)" }}>
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 flex items-center justify-center border" style={{ backgroundColor: "rgba(139,92,246,0.1)", borderColor: "rgba(139,92,246,0.2)" }}>
                <GitPullRequest className="w-6 h-6" style={{ color: "var(--accent)" }} />
              </div>
              <div>
                <h1 className="text-3xl font-bold leading-tight" style={{ color: "var(--text-primary)" }}>{review.pr_title}</h1>
                <span className="text-sm font-mono uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>{review.head_sha?.slice(0, 12)}</span>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-4 pt-2">
              <ReviewStatus reviewId={review.id} initialStatus={review.status} />
              <div className="flex items-center gap-2 px-3 py-1.5 border" style={{ backgroundColor: "var(--bg-tertiary)", borderColor: "var(--border)" }}>
                <span className="text-xs font-bold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Risk Score</span>
                <span className="text-sm font-bold" style={{ color: riskColor(review.risk_score) }}>
                  {review.risk_score !== null ? `${review.risk_score}%` : "—"}
                </span>
              </div>
            </div>
          </div>

          <div className="w-full md:w-64 space-y-3">
            <div className="flex justify-between text-sm">
              <span className="font-medium" style={{ color: "var(--text-secondary)" }}>Critical Issues</span>
              <span className="font-bold" style={{ color: "var(--error)" }}>{severityCounts.critical || 0}</span>
            </div>
                            <div className="w-full h-2" style={{ backgroundColor: "var(--bg-tertiary)" }}>
              <div className="h-full" style={{ width: `${((severityCounts.critical || 0) / Math.max(review.comments.length, 1)) * 100}%`, backgroundColor: "var(--error)" }} />
            </div>
            <p className="text-[10px] font-bold uppercase tracking-widest pt-1" style={{ color: "var(--text-muted)" }}>
              AI Sentiment: {(review.risk_score !== null && review.risk_score > 70) ? 'Concerned' : 'Positive'}
            </p>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-6">
        <section className="glass-card p-6 flex-1 min-w-[200px]">
          <h3 className="font-bold mb-4 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
            <Info className="w-4 h-4" style={{ color: "var(--accent)" }} /> Metadata
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              ["Created At", new Date(review.created_at).toLocaleString()],
              ["Status", review.status],
              ["Repository", review.repository_name],
              ["Issues Found", `${review.comments.length} items`],
            ].map(([label, value]) => (
              <div key={label}>
                <p className="text-[10px] font-bold uppercase tracking-widest mb-1" style={{ color: "var(--text-muted)" }}>{label}</p>
                <p className="text-sm font-medium capitalize" style={{ color: "var(--text-primary)" }}>{value}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="glass-card p-6 max-w-sm flex-1 min-w-[200px]" style={{ backgroundColor: "rgba(139,92,246,0.05)", borderColor: "rgba(139,92,246,0.2)" }}>
          <h3 className="font-bold mb-2" style={{ color: "var(--accent)" }}>AI Auditor</h3>
          <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
            This report was generated using DevMind's proprietary code analysis engine using the latest LLM models. All security findings should be verified by a human maintainer.
          </p>
        </section>
      </div>

      {review.summary && (
        <section className="glass-card p-6 border-l-4" style={{ borderColor: "var(--accent)" }}>
          <div className="flex items-center gap-2 mb-4">
            <Info className="w-5 h-5" style={{ color: "var(--accent)" }} />
            <h2 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>Executive Summary</h2>
          </div>
          <p className="leading-relaxed italic" style={{ color: "var(--text-secondary)" }}>"{review.summary}"</p>
        </section>
      )}

      <section className="glass-card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>Diff + AI Overlays</h2>
          {diffError && (
            <span className="text-xs" style={{ color: "var(--warning)" }}>
              {diffError}
            </span>
          )}
        </div>
        <DiffViewer
          files={diffFiles}
          comments={review.comments}
          diffUrl={review.diff_url}
          isLoading={diffLoading}
        />
      </section>

      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>Audit Findings</h2>
          <div className="flex items-center gap-2 p-1 border" style={{ backgroundColor: "var(--bg-tertiary)", borderColor: "var(--border)" }}>
            {["all", "critical", "error", "warning", "info"].map(filter => (
                <button key={filter} onClick={() => setActiveFilter(filter)}
                  className="px-3 py-1.5 text-xs font-bold uppercase tracking-wider transition-all"
                  style={activeFilter === filter
                    ? { backgroundColor: "var(--accent)", color: "white" }
                    : { color: "var(--text-muted)" }
                  }>
                {filter}
              </button>
            ))}
          </div>
        </div>

        {filteredComments.length === 0 ? (
          <div className="glass-card p-12 text-center space-y-2 opacity-60">
            <CheckCircle className="w-8 h-8 mx-auto" style={{ color: "var(--success)" }} />
            <p className="font-semibold" style={{ color: "var(--text-primary)" }}>No issues found for this filter</p>
          </div>
        ) : (
          <div className="space-y-4">
            {filteredComments.map((comment) => (
              <div key={comment.id} className="glass-card overflow-hidden border-l-4 transition-all"
                style={{ borderLeftColor: comment.severity === "critical" || comment.severity === "error" ? "var(--error)" : comment.severity === "warning" ? "var(--warning)" : "var(--info)" }}>
                <div className="p-5 space-y-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className={`badge ${badgeSeverity(comment.severity)}`}>{comment.severity}</span>
                      <span className="text-[10px] font-bold uppercase px-2 py-0.5" style={{ backgroundColor: "var(--bg-tertiary)", color: "var(--text-muted)" }}>
                        {comment.category}
                      </span>
                    </div>
                    <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                      {comment.file_path.split('/').pop()}:{comment.line_number}
                    </span>
                  </div>
                  <p className="leading-relaxed" style={{ color: "var(--text-primary)" }}>{comment.body}</p>
                  {comment.suggested_fix && (
                    <div className="border" style={{ borderColor: "var(--border)", backgroundColor: "rgba(0,0,0,0.3)" }}>
                      <div className="px-4 py-2 border-b flex items-center justify-between" style={{ borderColor: "var(--border)", backgroundColor: "rgba(255,255,255,0.05)" }}>
                        <span className="text-[10px] font-bold uppercase tracking-widest" style={{ color: "var(--accent)" }}>Suggested Fix</span>
                      </div>
                      <pre className="p-4 text-xs font-mono overflow-x-auto whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                        {comment.suggested_fix}
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
