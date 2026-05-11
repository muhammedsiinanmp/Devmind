import { CheckCircle, Clock, XCircle, RefreshCw } from "lucide-react";

type ReviewStatus = "pending" | "processing" | "completed" | "failed";

interface ReviewStatusProps {
  reviewId?: number;
  initialStatus?: ReviewStatus;
}

export default function ReviewStatus({ initialStatus }: ReviewStatusProps) {
  const status: ReviewStatus = initialStatus || "pending";

  const configs: Record<ReviewStatus, { icon: typeof Clock; label: string; className: string }> = {
    pending: { icon: Clock, label: "Pending", className: "badge-info" },
    processing: { icon: RefreshCw, label: "Processing", className: "badge-warning" },
    completed: { icon: CheckCircle, label: "Completed", className: "badge-success" },
    failed: { icon: XCircle, label: "Failed", className: "badge-error" },
  };

  const config = configs[status];
  const Icon = config.icon;

  return (
    <span className={`badge inline-flex items-center gap-1.5 px-3 py-1.5 ${config.className}`}>
      <Icon className={`w-3.5 h-3.5 ${status === "processing" ? "animate-spin" : ""}`} />
      {config.label}
    </span>
  );
}
