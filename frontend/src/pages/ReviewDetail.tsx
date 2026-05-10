import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useReviewStore } from "../store/reviewSlice";
import ReviewStatus from "../components/review/ReviewStatus";
import ReactDiffViewer from "react-diff-viewer-continued";
import {
  Loader2,
  FileCode,
  ShieldCheck,
  AlertTriangle,
  Info,
  Zap,
  ArrowLeft,
  ExternalLink,
  ChevronRight,
  GitPullRequest
} from "lucide-react";

export default function ReviewDetail() {
  const { id } = useParams<{ id: string }>();
  const { currentReview, isLoading, error, fetchReview } = useReviewStore();
  const [activeFilter, setActiveFilter] = useState<string>("all");

  useEffect(() => {
    if (id) {
      fetchReview(parseInt(id));
    }
  }, [id]);

  if (isLoading) {
    return (
      <div className="min-h-[60vh] flex flex-col items-center justify-center space-y-4">
        <Loader2 className="w-10 h-10 animate-spin text-accent" />
        <p className="text-text-secondary animate-pulse">Generating report details...</p>
      </div>
    );
  }

  if (error || !currentReview) {
    return (
      <div className="glass-card p-12 text-center flex flex-col items-center justify-center space-y-4">
        <AlertTriangle className="w-12 h-12 text-error" />
        <h3 className="text-xl font-semibold">{error || "Review not found"}</h3>
        <Link to="/dashboard" className="btn-secondary flex items-center gap-2">
          <ArrowLeft className="w-4 h-4" /> Back to Dashboard
        </Link>
      </div>
    );
  }

  const filteredComments = activeFilter === "all"
    ? currentReview.comments
    : currentReview.comments.filter(c => c.severity === activeFilter);

  const severityCounts = currentReview.comments.reduce((acc, c) => {
    acc[c.severity] = (acc[c.severity] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  return (
    <div className="space-y-8 animate-fade-in pb-20">
      {/* Breadcrumbs & Actions */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <nav className="flex items-center gap-2 text-sm font-medium text-text-muted">
          <Link to="/dashboard" className="hover:text-accent transition-colors">Reviews</Link>
          <ChevronRight className="w-4 h-4" />
          <span className="text-text-primary">PR #{currentReview.pr_number}</span>
        </nav>
        <div className="flex items-center gap-3">
          <a
            href={currentReview.diff_url}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-secondary flex items-center gap-2"
          >
            <ExternalLink className="w-4 h-4" /> View on GitHub
          </a>
          <button className="btn-primary">Retrigger Analysis</button>
        </div>
      </div>

      {/* Header Info */}
      <div className="glass-card p-8 bg-gradient-to-br from-bg-tertiary/20 to-transparent">
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-6">
          <div className="space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-2xl bg-accent/10 flex items-center justify-center border border-accent/20">
                <GitPullRequest className="w-6 h-6 text-accent" />
              </div>
              <div>
                <h1 className="text-3xl font-bold text-white leading-tight">{currentReview.pr_title}</h1>
                <p className="text-text-secondary font-mono text-sm tracking-wider uppercase">{currentReview.head_sha}</p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-4 pt-2">
              <ReviewStatus reviewId={currentReview.id} initialStatus={currentReview.status} />
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-bg-tertiary border border-border">
                <span className="text-xs text-text-muted uppercase font-bold tracking-wider">Risk Score</span>
                <span className={`text-sm font-bold ${
                  currentReview.risk_score >= 80 ? 'text-error' : currentReview.risk_score >= 40 ? 'text-warning' : 'text-success'
                }`}>
                  {currentReview.risk_score}%
                </span>
              </div>
            </div>
          </div>

          <div className="w-full md:w-64 space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-text-secondary font-medium">Critical Issues</span>
              <span className="text-error font-bold">{severityCounts.critical || 0}</span>
            </div>
            <div className="w-full h-2 bg-bg-tertiary rounded-full overflow-hidden">
              <div
                className="h-full bg-error"
                style={{ width: `${((severityCounts.critical || 0) / currentReview.comments.length) * 100}%` }}
              />
            </div>
            <p className="text-[10px] text-text-muted uppercase font-bold tracking-widest pt-1">
              AI Security Sentiment: {currentReview.risk_score > 70 ? 'Concerned' : 'Positive'}
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Summary & Filters */}
        <div className="lg:col-span-2 space-y-6">
          {currentReview.summary && (
            <section className="glass-card p-6 border-l-4 border-l-accent">
              <div className="flex items-center gap-2 mb-4">
                <Zap className="w-5 h-5 text-accent" />
                <h2 className="text-lg font-bold">Executive Summary</h2>
              </div>
              <p className="text-text-secondary leading-relaxed italic">
                "{currentReview.summary}"
              </p>
            </section>
          )}

          {/* Comments List */}
          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold">Audit Findings</h2>
              <div className="flex items-center gap-2 bg-bg-tertiary p-1 rounded-xl border border-border">
                {['all', 'critical', 'warning', 'info'].map(filter => (
                  <button
                    key={filter}
                    onClick={() => setActiveFilter(filter)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${
                      activeFilter === filter ? 'bg-accent text-white shadow-sm' : 'text-text-muted hover:text-text-primary'
                    }`}
                  >
                    {filter}
                  </button>
                ))}
              </div>
            </div>

            {filteredComments.length === 0 ? (
              <div className="glass-card p-12 text-center space-y-2 opacity-60">
                <ShieldCheck className="w-8 h-8 mx-auto text-success" />
                <p className="font-semibold">No issues found for this filter</p>
              </div>
            ) : (
              <div className="space-y-4">
                {filteredComments.map((comment) => (
                  <div key={comment.id} className="glass-card overflow-hidden group border-l-4 border-l-bg-tertiary hover:border-l-accent transition-all">
                    <div className="p-5 space-y-4">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <span className={`
                            badge ${
                              comment.severity === 'critical' ? 'badge-error' :
                              comment.severity === 'warning' ? 'badge-warning' : 'badge-info'
                            }
                          `}>
                            {comment.severity}
                          </span>
                          <span className="text-[10px] uppercase font-bold tracking-widest text-text-muted px-2 py-0.5 rounded bg-bg-tertiary">
                            {comment.category}
                          </span>
                        </div>
                        <span className="text-xs font-mono text-text-muted">
                          {comment.file_path.split('/').pop()}:{comment.line_number}
                        </span>
                      </div>

                      <p className="text-text-primary leading-relaxed">
                        {comment.body}
                      </p>

                      {comment.suggested_fix && (
                        <div className="rounded-xl overflow-hidden border border-border bg-black/30">
                          <div className="px-4 py-2 bg-white/5 border-b border-border flex items-center justify-between">
                            <span className="text-[10px] font-bold text-accent uppercase tracking-widest">Suggested Fix</span>
                            <button className="text-[10px] font-bold hover:text-accent transition-colors">Copy Diff</button>
                          </div>
                          <pre className="p-4 text-xs font-mono text-text-secondary overflow-x-auto whitespace-pre-wrap">
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

        {/* Sidebar Info */}
        <div className="space-y-6">
          <section className="glass-card p-6">
            <h3 className="font-bold mb-4 flex items-center gap-2">
              <Info className="w-4 h-4 text-accent" /> Metadata
            </h3>
            <div className="space-y-4">
              <div>
                <p className="text-[10px] uppercase font-bold text-text-muted tracking-widest mb-1">Created At</p>
                <p className="text-sm font-medium">{new Date(currentReview.created_at).toLocaleString()}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase font-bold text-text-muted tracking-widest mb-1">Status</p>
                <p className="text-sm font-medium capitalize">{currentReview.status}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase font-bold text-text-muted tracking-widest mb-1">Issues Found</p>
                <p className="text-sm font-medium">{currentReview.comments.length} items</p>
              </div>
            </div>
          </section>

          <section className="glass-card p-6 bg-accent/5 border-accent/20">
            <h3 className="font-bold mb-2 text-accent">AI Auditor</h3>
            <p className="text-xs text-text-secondary leading-relaxed">
              This report was generated using DevMind's proprietary code analysis engine using the latest LLM models. All security findings should be verified by a human maintainer.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
