import { useEffect, useState, useRef } from "react";
import { AlertTriangle, CheckCircle, Clock, XCircle, RefreshCw } from "lucide-react";
import { reviewsApi } from "../../api/reviews";
import {
  isTerminalStatus,
  startReviewStatusPolling,
  type ReviewPollError,
  type ReviewStatusValue,
} from "../../lib/reviewStatusPolling";

type ReviewStatusType = ReviewStatusValue;

const POLL_ERROR_MESSAGES: Record<ReviewPollError, string> = {
  forbidden: "You no longer have access to this review.",
  not_found: "This review no longer exists.",
  gave_up: "The server could not be reached. Reload the page to try again.",
};

interface ReviewStatusProps {
  reviewId?: number;
  initialStatus?: ReviewStatusType;
  onStatusChange?: (status: ReviewStatusType) => void;
}

export default function ReviewStatus({ reviewId, initialStatus, onStatusChange }: ReviewStatusProps) {
  const [status, setStatus] = useState<ReviewStatusType>(initialStatus || "pending");
  const [pollError, setPollError] = useState<ReviewPollError | null>(null);
  // Keep the latest callback without restarting the poll when it changes
  const onStatusChangeRef = useRef(onStatusChange);
  const statusRef = useRef(status);
  const done = isTerminalStatus(status);

  useEffect(() => {
    onStatusChangeRef.current = onStatusChange;
  }, [onStatusChange]);

  // Poll the review detail endpoint while the review is pending or processing.
  // Polling stops on a terminal status, on an error it can't recover from
  // (403, 404, or 10 consecutive failures) and when the component unmounts.
  useEffect(() => {
    if (!reviewId || done) return;

    return startReviewStatusPolling({
      fetchStatus: async () => (await reviewsApi.get(reviewId)).status,
      onStatus: (next) => {
        if (next === statusRef.current) return;
        statusRef.current = next;
        setStatus(next);
        onStatusChangeRef.current?.(next);
      },
      onError: setPollError,
    });
  }, [reviewId, done]);

  const configs: Record<ReviewStatusType, { icon: typeof Clock; label: string; className: string }> = {
    pending: { icon: Clock, label: "Pending", className: "badge-info" },
    processing: { icon: RefreshCw, label: "Processing", className: "badge-warning" },
    completed: { icon: CheckCircle, label: "Completed", className: "badge-success" },
    failed: { icon: XCircle, label: "Failed", className: "badge-error" },
  };

  const config = configs[status];
  const Icon = config.icon;

  const badge = (
    <span className={`badge inline-flex items-center gap-1.5 px-3 py-1.5 ${config.className}`}>
      <Icon className={`w-3.5 h-3.5 ${status === "processing" && !pollError ? "animate-spin" : ""}`} />
      {config.label}
    </span>
  );

  if (!pollError) return badge;

  return (
    <span className="inline-flex items-center gap-2">
      {badge}
      <span
        role="status"
        title={POLL_ERROR_MESSAGES[pollError]}
        className="inline-flex items-center gap-1 text-xs"
        style={{ color: "var(--error)" }}
      >
        <AlertTriangle className="w-3.5 h-3.5" />
        Status updates stopped
      </span>
    </span>
  );
}
