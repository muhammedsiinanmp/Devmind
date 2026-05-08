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
          className: "bg-gray-100 text-gray-700",
        };
      case "processing":
        return {
          icon: RefreshCw,
          label: "Processing",
          className: "bg-blue-100 text-blue-700",
        };
      case "completed":
        return {
          icon: CheckCircle,
          label: "Completed",
          className: "bg-green-100 text-green-700",
        };
      case "failed":
        return {
          icon: XCircle,
          label: "Failed",
          className: "bg-red-100 text-red-700",
        };
    }
  };

  const config = getStatusConfig(status);
  const Icon = config.icon;

  if (loading) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-gray-100 text-gray-600 text-sm">
        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
        Loading...
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-sm ${config.className}`}
      title={error || undefined}
    >
      <Icon className={`w-3.5 h-3.5 ${status === "processing" ? "animate-spin" : ""}`} />
      {config.label}
      {error && <AlertCircle className="w-3.5 h-3.5 text-yellow-500 ml-1" />}
    </span>
  );
}
