import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ReviewStatus from "../components/review/ReviewStatus";
import apiClient from "../api/client";
import { ChevronLeft, ChevronRight, Loader2, GitPullRequest } from "lucide-react";

interface Review {
  id: number;
  repository: number;
  repository_name: string;
  pr_number: number;
  pr_title: string;
  head_sha: string | null;
  status: "pending" | "processing" | "completed" | "failed";
  risk_score: number | null;
  created_at: string;
  completed_at: string | null;
}

interface ReviewListResponse {
  count: number;
  next: string | null;
  previous: string | null;
  results: Review[];
}

export default function Dashboard() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  const fetchReviews = async (pageNum: number) => {
    setIsLoading(true);
    try {
      const res = await apiClient.get<ReviewListResponse>("/reviews/", { params: { page: pageNum, page_size: 10 } });
      setReviews(res.data.results);
      setTotalCount(res.data.count);
      setTotalPages(Math.ceil(res.data.count / 10));
    } catch {
      // handle error
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { fetchReviews(page); }, [page]);

  if (isLoading && reviews.length === 0) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin" style={{ color: "var(--accent)" }} />
        <p className="animate-pulse" style={{ color: "var(--text-secondary)" }}>Loading reviews...</p>
      </div>
    );
  }

  const riskColor = (score: number | null) => {
    if (score === null) return { bg: "var(--bg-tertiary)", color: "var(--text-muted)", border: "var(--border)" };
    if (score >= 80) return { bg: "rgba(239,68,68,0.1)", color: "var(--error)", border: "rgba(239,68,68,0.2)" };
    if (score >= 40) return { bg: "rgba(245,158,11,0.1)", color: "var(--warning)", border: "rgba(245,158,11,0.2)" };
    return { bg: "rgba(16,185,129,0.1)", color: "var(--success)", border: "rgba(16,185,129,0.2)" };
  };

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold mb-2 text-gradient">Code Reviews</h1>
          <p className="text-lg" style={{ color: "var(--text-secondary)" }}>
            Monitor and manage AI-powered pull request analysis.
          </p>
        </div>
        <div className="flex items-center gap-4 p-1 rounded-xl border" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-secondary)" }}>
          <div className="px-4 py-2 text-center">
            <p className="text-xs font-bold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Total Reviews</p>
            <p className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>{totalCount}</p>
          </div>
        </div>
      </div>

      {reviews.length === 0 ? (
        <div className="glass-card p-12 text-center flex flex-col items-center justify-center space-y-4">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center border" style={{ backgroundColor: "var(--bg-tertiary)", borderColor: "var(--border)" }}>
            <GitPullRequest className="w-8 h-8" style={{ color: "var(--text-muted)" }} />
          </div>
          <h3 className="text-xl font-semibold" style={{ color: "var(--text-primary)" }}>No reviews yet</h3>
          <p className="max-w-md" style={{ color: "var(--text-secondary)" }}>
            Connect a repository and open a Pull Request on GitHub to see the AI review agent in action.
          </p>
          <Link to="/repositories" className="btn-primary mt-4">Connect Repository</Link>
        </div>
      ) : (
        <>
          <div className="glass-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b" style={{ borderColor: "var(--border)", backgroundColor: "rgba(255,255,255,0.05)" }}>
                    {["Pull Request", "Status", "Risk Score", "Date"].map((h) => (
                      <th key={h} className="px-6 py-4 text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {reviews.map((review) => {
                    const rc = riskColor(review.risk_score);
                    return (
                      <tr key={review.id} className="border-b transition-colors" style={{ borderColor: "rgba(255,255,255,0.05)" }}>
                        <td className="px-6 py-6">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-lg flex items-center justify-center border transition-colors group"
                              style={{ backgroundColor: "var(--bg-tertiary)", borderColor: "var(--border)" }}>
                              <GitPullRequest className="w-5 h-5" style={{ color: "var(--accent)" }} />
                            </div>
                            <div>
                              <Link to={`/reviews/${review.id}`} className="font-bold block hover:opacity-80 transition-opacity" style={{ color: "var(--text-primary)" }}>
                                #{review.pr_number} {review.pr_title}
                              </Link>
                              <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--text-muted)" }}>
                                {review.head_sha ? review.head_sha.slice(0, 7) : "—"}
                              </span>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-6">
                          <ReviewStatus initialStatus={review.status} />
                        </td>
                        <td className="px-6 py-6">
                          <div className="flex justify-center">
                            <div className="w-12 h-12 rounded-xl flex items-center justify-center font-bold text-lg border"
                              style={{ backgroundColor: rc.bg, color: rc.color, borderColor: rc.border }}>
                              {review.risk_score === null ? "—" : review.risk_score}
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-6 text-sm whitespace-nowrap" style={{ color: "var(--text-muted)" }}>
                          {new Date(review.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-6 mt-10">
              <button onClick={() => setPage(p => p - 1)} disabled={page === 1} className="btn-secondary flex items-center gap-2">
                <ChevronLeft className="w-4 h-4" /> Previous
              </button>
              <div className="flex items-center gap-2">
                {Array.from({ length: Math.min(totalPages, 10) }, (_, i) => {
                  const p = i + 1;
                  return (
                    <button key={p} onClick={() => setPage(p)}
                      className="w-10 h-10 rounded-lg transition-all"
                      style={page === p
                        ? { backgroundColor: "var(--accent)", color: "white", fontWeight: "bold", boxShadow: "0 0 8px rgba(139,92,246,0.4)" }
                        : { color: "var(--text-secondary)" }
                      }>
                      {p}
                    </button>
                  );
                })}
              </div>
              <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages} className="btn-secondary flex items-center gap-2">
                Next <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
