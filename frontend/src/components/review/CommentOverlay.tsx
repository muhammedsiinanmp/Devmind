import { ReviewComment } from "../../api/reviews";
import { AlertTriangle, XCircle, Info, AlertCircle } from "lucide-react";

interface CommentOverlayProps {
  comment: ReviewComment;
}

export default function CommentOverlay({ comment }: CommentOverlayProps) {
  const getSeverityConfig = (severity: string) => {
    switch (severity) {
      case "critical":
        return {
          icon: XCircle,
          className: "bg-red-50 border-red-200 text-red-800",
          badge: "bg-red-100 text-red-700",
        };
      case "error":
        return {
          icon: AlertTriangle,
          className: "bg-orange-50 border-orange-200 text-orange-800",
          badge: "bg-orange-100 text-orange-700",
        };
      case "warning":
        return {
          icon: AlertCircle,
          className: "bg-yellow-50 border-yellow-200 text-yellow-800",
          badge: "bg-yellow-100 text-yellow-700",
        };
      default:
        return {
          icon: Info,
          className: "bg-blue-50 border-blue-200 text-blue-800",
          badge: "bg-blue-100 text-blue-700",
        };
    }
  };

  const config = getSeverityConfig(comment.severity);
  const Icon = config.icon;

  return (
    <div className={`p-3 rounded-lg border ${config.className} text-sm`}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 flex-shrink-0" />
        <span className={`text-xs px-1.5 py-0.5 rounded ${config.badge} uppercase font-medium`}>
          {comment.severity}
        </span>
        <span className="text-xs text-gray-500">{comment.category}</span>
      </div>
      <p className="mb-2">{comment.body}</p>
      {comment.suggested_fix && (
        <div className="mt-2 pt-2 border-t border-current/20">
          <span className="text-xs font-medium">Suggested fix:</span>
          <pre className="mt-1 text-xs whitespace-pre-wrap font-mono bg-white/50 p-2 rounded">
            {comment.suggested_fix}
          </pre>
        </div>
      )}
    </div>
  );
}
