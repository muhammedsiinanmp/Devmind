import { useEffect, useState, useRef } from "react";
import { CheckCircle, Clock, XCircle, RefreshCw } from "lucide-react";

type ReviewStatusType = "pending" | "processing" | "completed" | "failed";

interface ReviewStatusProps {
  reviewId?: number;
  initialStatus?: ReviewStatusType;
  onStatusChange?: (status: ReviewStatusType) => void;
}

export default function ReviewStatus({ reviewId, initialStatus, onStatusChange }: ReviewStatusProps) {
  const [status, setStatus] = useState<ReviewStatusType>(initialStatus || "pending");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!reviewId || status === "completed" || status === "failed") return;

    const token = localStorage.getItem("access_token");
    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/reviews/${reviewId}/?token=${token}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.status && data.status !== status) {
            setStatus(data.status);
            onStatusChange?.(data.status);
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onerror = () => {
        // WebSocket failed — component remains static
        ws.close();
      };

      return () => {
        ws.close();
        wsRef.current = null;
      };
    } catch {
      // WebSocket not available, component remains static
    }
  }, [reviewId, status]);

  const configs: Record<ReviewStatusType, { icon: typeof Clock; label: string; className: string }> = {
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
