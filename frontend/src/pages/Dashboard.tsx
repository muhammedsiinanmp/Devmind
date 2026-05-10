import { useEffect } from "react";
import { useReviewStore } from "../store/reviewSlice";
import { Link } from "react-router-dom";
import ReviewStatus from "../components/review/ReviewStatus";
import { ChevronLeft, ChevronRight, Loader2, GitPullRequest, ShieldAlert } from "lucide-react";

export default function Dashboard() {
  const { reviews, isLoading, totalCount, page, fetchReviews, setPage } = useReviewStore();

  useEffect(() => {
    fetchReviews(page);
  }, [page]);

  const totalPages = Math.ceil(totalCount / 10);

  if (isLoading && reviews.length === 0) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin text-accent" />
        <p className="text-text-secondary animate-pulse">Loading reviews...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold text-gradient mb-2">Code Reviews</h1>
          <p className="text-text-secondary text-lg">
            Monitor and manage AI-powered pull request analysis.
          </p>
        </div>
        <div className="flex items-center gap-4 bg-bg-secondary p-1 rounded-xl border border-border">
          <div className="px-4 py-2 text-center">
            <p className="text-xs text-text-muted uppercase font-bold tracking-wider">Total Reviews</p>
            <p className="text-xl font-bold">{totalCount}</p>
          </div>
        </div>
      </div>

      {reviews.length === 0 ? (
        <div className="glass-card p-12 text-center flex flex-col items-center justify-center space-y-4">
          <div className="w-16 h-16 bg-bg-tertiary rounded-2xl flex items-center justify-center border border-border">
            <GitPullRequest className="w-8 h-8 text-text-muted" />
          </div>
          <h3 className="text-xl font-semibold">No reviews yet</h3>
          <p className="text-text-secondary max-w-md">
            Connect a repository and open a Pull Request on GitHub to see the AI review agent in action.
          </p>
          <Link to="/repositories" className="btn-primary mt-4">
            Connect Repository
          </Link>
        </div>
      ) : (
        <>
          <div className="glass-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="border-b border-border bg-white/5">
                    <th className="px-6 py-4 text-sm font-semibold text-text-secondary">Pull Request</th>
                    <th className="px-6 py-4 text-sm font-semibold text-text-secondary">Status</th>
                    <th className="px-6 py-4 text-sm font-semibold text-text-secondary text-center">Risk Score</th>
                    <th className="px-6 py-4 text-sm font-semibold text-text-secondary">AI Summary</th>
                    <th className="px-6 py-4 text-sm font-semibold text-text-secondary">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {reviews.map((review) => (
                    <tr key={review.id} className="hover:bg-white/5 transition-colors group">
                      <td className="px-6 py-6">
                        <div className="flex items-center gap-3">
                          <div className="w-10 h-10 rounded-lg bg-bg-tertiary flex items-center justify-center border border-border group-hover:border-accent/30 transition-colors">
                            <GitPullRequest className="w-5 h-5 text-accent" />
                          </div>
                          <div>
                            <Link
                              to={`/reviews/${review.id}`}
                              className="font-bold text-text-primary hover:text-accent transition-colors block"
                            >
                              #{review.pr_number} {review.pr_title}
                            </Link>
                            <span className="text-xs text-text-muted font-mono uppercase tracking-widest">
                              {review.head_sha.slice(0, 7)}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-6">
                        <ReviewStatus reviewId={review.id} initialStatus={review.status} />
                      </td>
                      <td className="px-6 py-6">
                        <div className="flex justify-center">
                          <div className={`
                            w-12 h-12 rounded-xl flex items-center justify-center font-bold text-lg
                            ${review.risk_score === null
                              ? 'bg-bg-tertiary text-text-muted'
                              : review.risk_score >= 80
                                ? 'bg-error/10 text-error border border-error/20'
                                : review.risk_score >= 40
                                  ? 'bg-warning/10 text-warning border border-warning/20'
                                  : 'bg-success/10 text-success border border-success/20'}
                          `}>
                            {review.risk_score ?? "—"}
                          </div>
                        </div>
                      </td>
                      <td className="px-6 py-6">
                        <p className="text-sm text-text-secondary line-clamp-2 max-w-xs italic">
                          {review.summary || "Pending analysis..."}
                        </p>
                      </td>
                      <td className="px-6 py-6 text-sm text-text-muted whitespace-nowrap">
                        {new Date(review.created_at).toLocaleDateString(undefined, {
                          month: 'short',
                          day: 'numeric',
                          year: 'numeric'
                        })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

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
        </>
      )}
    </div>
  );
}
