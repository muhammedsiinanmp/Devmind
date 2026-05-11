import { useMemo, useState } from "react";
import { CommentData } from "./CommentOverlay";
import { MessageSquare, FileCode, ChevronRight, XCircle, AlertTriangle, AlertCircle, Info } from "lucide-react";

interface CommentThreadProps {
  comments: CommentData[];
  onCommentClick?: (comment: CommentData) => void;
}

const severityIcon = (severity: string) => {
  switch (severity) {
    case "critical": return XCircle;
    case "error": return AlertTriangle;
    case "warning": return AlertCircle;
    default: return Info;
  }
};

const severityColor = (severity: string) => {
  switch (severity) {
    case "critical": return "var(--error)";
    case "error": return "#fb923c";
    case "warning": return "var(--warning)";
    default: return "var(--info)";
  }
};

export default function CommentThread({ comments, onCommentClick }: CommentThreadProps) {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const files = useMemo(() => {
    const map: Record<string, CommentData[]> = {};
    for (const c of comments) {
      if (!map[c.file_path]) map[c.file_path] = [];
      map[c.file_path].push(c);
    }
    return Object.entries(map).map(([path, cs]) => ({
      path,
      count: cs.length,
      criticalCount: cs.filter((c) => c.severity === "critical" || c.severity === "error").length,
      comments: cs,
    }));
  }, [comments]);

  const totalCritical = comments.filter(
    (c) => c.severity === "critical" || c.severity === "error"
  ).length;
  const totalWarning = comments.filter((c) => c.severity === "warning").length;
  const totalInfo = comments.filter((c) => c.severity === "info").length;

  if (comments.length === 0) {
    return (
      <div className="p-6 text-center" style={{ color: "var(--text-muted)" }}>
        <MessageSquare className="w-8 h-8 mx-auto mb-3 opacity-40" />
        <p className="text-sm">No AI comments for this review</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="glass-card p-4 space-y-2">
        <div className="flex items-center gap-2 mb-3">
          <MessageSquare className="w-4 h-4" style={{ color: "var(--accent)" }} />
          <span className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
            Comments by File
          </span>
          <span className="badge badge-info ml-auto" style={{ fontSize: "10px" }}>
            {comments.length}
          </span>
        </div>

        <div className="flex flex-wrap gap-2 mb-3">
          {totalCritical > 0 && (
            <span className="badge badge-error" style={{ fontSize: "10px" }}>
              <XCircle className="w-3 h-3" /> {totalCritical}
            </span>
          )}
          {totalWarning > 0 && (
            <span className="badge badge-warning" style={{ fontSize: "10px" }}>
              <AlertTriangle className="w-3 h-3" /> {totalWarning}
            </span>
          )}
          {totalInfo > 0 && (
            <span className="badge badge-info" style={{ fontSize: "10px" }}>
              <Info className="w-3 h-3" /> {totalInfo}
            </span>
          )}
        </div>

        <div className="space-y-1">
          {files.map(({ path, count, criticalCount, comments: fileComments }) => (
            <div key={path}>
              <button
                onClick={() => setSelectedFile(selectedFile === path ? null : path)}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-all text-left"
                style={{
                  backgroundColor: selectedFile === path ? "var(--bg-tertiary)" : "transparent",
                  border: "1px solid transparent",
                }}
              >
                <ChevronRight
                  className="w-3 h-3 flex-shrink-0 transition-transform"
                  style={{
                    transform: selectedFile === path ? "rotate(90deg)" : "none",
                    color: "var(--text-muted)",
                  }}
                />
                <FileCode className="w-4 h-4 flex-shrink-0" style={{ color: "var(--accent)" }} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>
                    {path.split("/").pop()}
                  </p>
                  <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                    {path}
                  </p>
                </div>
                {criticalCount > 0 && (
                  <span className="badge badge-error" style={{ fontSize: "9px", padding: "1px 5px" }}>
                    {criticalCount}
                  </span>
                )}
                <span className="badge badge-info" style={{ fontSize: "9px", padding: "1px 5px" }}>
                  {count}
                </span>
              </button>

              {selectedFile === path && (
                <div className="ml-8 mt-1 space-y-2">
                  {fileComments.map((comment) => {
                    const Icon = severityIcon(comment.severity);
                    const color = severityColor(comment.severity);
                    return (
                      <button
                        key={comment.id}
                        onClick={() => onCommentClick?.(comment)}
                        className="w-full text-left p-3 rounded-lg border transition-all"
                        style={{
                          backgroundColor: "rgba(0,0,0,0.2)",
                          borderColor: "var(--border)",
                        }}
                      >
                        <div className="flex items-center gap-2 mb-1">
                          <Icon className="w-3 h-3" style={{ color }} />
                          <span className="text-[10px] font-bold uppercase" style={{ color }}>
                            {comment.severity}
                          </span>
                          <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                            L{comment.line_number}
                          </span>
                          <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                            {comment.category}
                          </span>
                        </div>
                        <p className="text-xs leading-relaxed line-clamp-2" style={{ color: "var(--text-secondary)" }}>
                          {comment.body}
                        </p>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
