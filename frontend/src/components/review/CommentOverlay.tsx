import { AlertTriangle, XCircle, Info, AlertCircle } from "lucide-react";

export interface CommentData {
  id: number;
  file_path: string;
  line_number: number;
  category: string;
  severity: "info" | "warning" | "error" | "critical";
  body: string;
  suggested_fix: string | null;
}

interface CommentOverlayProps {
  comment: CommentData;
}

const severityColors = {
  critical: {
    bg: "rgba(239, 68, 68, 0.08)",
    border: "rgba(239, 68, 68, 0.25)",
    text: "#f87171",
    badgeBg: "rgba(239, 68, 68, 0.15)",
    badgeText: "#fca5a5",
  },
  error: {
    bg: "rgba(249, 115, 22, 0.08)",
    border: "rgba(249, 115, 22, 0.25)",
    text: "#fb923c",
    badgeBg: "rgba(249, 115, 22, 0.15)",
    badgeText: "#fdba74",
  },
  warning: {
    bg: "rgba(245, 158, 11, 0.08)",
    border: "rgba(245, 158, 11, 0.25)",
    text: "#fbbf24",
    badgeBg: "rgba(245, 158, 11, 0.15)",
    badgeText: "#fde68a",
  },
  info: {
    bg: "rgba(59, 130, 246, 0.08)",
    border: "rgba(59, 130, 246, 0.25)",
    text: "#60a5fa",
    badgeBg: "rgba(59, 130, 246, 0.15)",
    badgeText: "#93c5fd",
  },
};

const iconMap = {
  critical: XCircle,
  error: AlertTriangle,
  warning: AlertCircle,
  info: Info,
};

export default function CommentOverlay({ comment }: CommentOverlayProps) {
  const cfg = severityColors[comment.severity] || severityColors.info;
  const Icon = iconMap[comment.severity] || Info;

  return (
    <div
      className="p-4 rounded-xl border text-sm"
      style={{
        backgroundColor: cfg.bg,
        borderColor: cfg.border,
        color: cfg.text,
      }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4 flex-shrink-0" />
        <span
          className="text-[10px] px-2 py-0.5 rounded font-bold uppercase tracking-wider"
          style={{ backgroundColor: cfg.badgeBg, color: cfg.badgeText }}
        >
          {comment.severity}
        </span>
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>
          {comment.category}
        </span>
      </div>
      <p className="mb-3 leading-relaxed" style={{ color: "var(--text-primary)" }}>
        {comment.body}
      </p>
      {comment.suggested_fix && (
        <div
          className="pt-3 mt-3 border-t"
          style={{ borderColor: cfg.border }}
        >
          <span className="text-[10px] font-bold uppercase tracking-widest" style={{ color: cfg.text }}>
            Suggested Fix
          </span>
          <pre
            className="mt-2 text-xs font-mono whitespace-pre-wrap p-3 rounded-lg"
            style={{
              backgroundColor: "rgba(0,0,0,0.3)",
              color: "var(--text-secondary)",
            }}
          >
            {comment.suggested_fix}
          </pre>
        </div>
      )}
    </div>
  );
}
