import { useEffect, useState } from "react";
import { supabase } from "../../lib/supabase";
import { Database } from "../../lib/supabase";
import { RefreshCw, CheckCircle, Clock, XCircle, AlertCircle } from "lucide-react";

type ReviewStatus = "pending" | "processing" | "completed" | "failed";

interface ReviewStatusProps {
  reviewId: number;
  initialStatus?: ReviewStatus;
}

export default function ReviewStatus({ reviewId, initialStatus }: ReviewStatusProps) {
  const [status, setStatus] = useState<ReviewStatus>(initialStatus || "pending");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!reviewId) return;

    setLoading(true);

    const channel = supabase
      .channel(`review-${reviewId}`)
      .on(
        "postgres_changes" as never,
        {
          event: "*",
          schema: "public",
          table: "review_status_updates",
          filter: `review_id=eq.${reviewId}`,
        },
        (payload: { new: Database["public"]["Tables"]["review_status_updates"]["Row"] }) => {
          if (payload.new) {
            setStatus(payload.new.status as ReviewStatus);
          }
        }
      )
      .subscribe((err) => {
        if (err) {
          console.error("Supabase subscription error:", err);
          setError("Failed to connect to live updates");
        } else {
          setLoading(false);
        }
      });

    return () => {
      supabase.removeChannel(channel);
    };
  }, [reviewId]);

  const getStatusConfig = (s: ReviewStatus) => {
    switch (s) {
      case "pending":
        return {
          icon: Clock,
          label: "Pending",
          className: "badge-info",
        };
      case "processing":
        return {
          icon: RefreshCw,
          label: "Processing",
          className: "badge-warning",
        };
      case "completed":
        return {
          icon: CheckCircle,
          label: "Completed",
          className: "badge-success",
        };
      case "failed":
        return {
          icon: XCircle,
          label: "Failed",
          className: "badge-error",
        };
    }
  };

  const config = getStatusConfig(status);
  const Icon = config.icon;

  return (
    <span
      className={`badge inline-flex items-center gap-2 px-3 py-1.5 ${config.className}`}
      title={error || undefined}
    >
      <Icon className={`w-3.5 h-3.5 ${status === "processing" ? "animate-spin" : ""}`} />
      {config.label}
      {error && <AlertCircle className="w-3.5 h-3.5 text-warning ml-1" />}
    </span>
  );
}
