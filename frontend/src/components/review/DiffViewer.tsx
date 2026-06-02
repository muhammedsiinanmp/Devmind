import { useEffect, useMemo, useState } from "react";
import DiffViewerBase from "react-diff-viewer-continued";
import CommentOverlay, { type CommentData } from "./CommentOverlay";
import { Code2, MessageSquare } from "lucide-react";

export interface DiffFile {
  file_path: string;
  additions: number;
  deletions: number;
  patch: string;
  old_content?: string;
  new_content?: string;
}

interface DiffViewerProps {
  files: DiffFile[];
  comments: CommentData[];
  diffUrl?: string;
  isLoading?: boolean;
}

function normalizePath(path: string): string {
  return path.replace(/^a\//, "").replace(/^b\//, "");
}

export default function DiffViewer({ files, comments, diffUrl, isLoading }: DiffViewerProps) {
  const [selectedFile, setSelectedFile] = useState<string>("");

  useEffect(() => {
    if (files.length === 0) {
      setSelectedFile("");
      return;
    }

    const normalized = files.map((file) => normalizePath(file.file_path));
    if (!selectedFile || !normalized.includes(selectedFile)) {
      setSelectedFile(normalized[0]);
    }
  }, [files, selectedFile]);

  const commentsByFile = useMemo(() => {
    const map: Record<string, CommentData[]> = {};
    for (const c of comments) {
      const key = normalizePath(c.file_path);
      if (!map[key]) map[key] = [];
      map[key].push(c);
    }
    return map;
  }, [comments]);

  const filesByPath = useMemo(() => {
    const map: Record<string, DiffFile> = {};
    for (const f of files) map[normalizePath(f.file_path)] = f;
    return map;
  }, [files]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20" style={{ color: "var(--text-muted)" }}>
        <div className="flex flex-col items-center gap-3">
          <Code2 className="w-8 h-8 animate-pulse" style={{ color: "var(--accent)" }} />
          <p>Loading diff...</p>
        </div>
      </div>
    );
  }

  if (files.length === 0 && diffUrl) {
    return (
      <div className="glass-card p-8 text-center space-y-4">
        <Code2 className="w-10 h-10 mx-auto" style={{ color: "var(--text-muted)" }} />
        <p style={{ color: "var(--text-secondary)" }}>Diff content is not available for inline display.</p>
        <a href={diffUrl} target="_blank" rel="noopener noreferrer" className="btn-primary inline-flex items-center gap-2">
          <MessageSquare className="w-4 h-4" /> View on GitHub
        </a>
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className="glass-card p-12 text-center" style={{ color: "var(--text-muted)" }}>
        No diff files available for this review.
      </div>
    );
  }

  const fileComments = selectedFile ? (commentsByFile[selectedFile] || []) : [];
  const selectedFileData = filesByPath[selectedFile];
  const highlightLines = fileComments.flatMap((comment) =>
    comment.line_number > 0 ? [`R-${comment.line_number}`, `L-${comment.line_number}`] : []
  );

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      <div className="flex-1 min-w-0 space-y-4">
        <div className="flex items-center gap-2 overflow-x-auto pb-2">
          {files.map((file) => {
            const normalizedPath = normalizePath(file.file_path);
            const isSelected = normalizedPath === selectedFile;
            const fileComms = commentsByFile[normalizedPath] || [];
            return (
              <button
                key={file.file_path}
                onClick={() => setSelectedFile(normalizedPath)}
                className="flex-shrink-0 px-3 py-2 border text-xs font-mono transition-all max-w-[200px]"
                style={
                  isSelected
                    ? { backgroundColor: "var(--bg-tertiary)", borderColor: "var(--accent)", color: "var(--accent)" }
                    : { backgroundColor: "var(--bg-secondary)", borderColor: "var(--border)", color: "var(--text-secondary)" }
                }
                title={file.file_path}
              >
                <div className="flex items-center gap-2">
                  <span className="truncate max-w-[150px]">{file.file_path.split("/").pop()}</span>
                  {fileComms.length > 0 && (
                    <span className="badge badge-warning flex-shrink-0" style={{ fontSize: "8px", padding: "1px 5px" }}>
                      {fileComms.length}
                    </span>
                  )}
                </div>
                <div className="text-[10px] mt-0.5">
                  <span style={{ color: "var(--success)" }}>+{file.additions}</span>
                  {" · "}
                  <span style={{ color: "var(--error)" }}>-{file.deletions}</span>
                </div>
              </button>
            );
          })}
        </div>

        {selectedFileData && (
          <div style={{ border: "1px solid var(--border)", backgroundColor: "var(--bg-secondary)", overflowX: "auto" }}>
            <div className="px-4 py-2 border-b flex items-center gap-2" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-tertiary)" }}>
              <Code2 className="w-4 h-4" style={{ color: "var(--accent)" }} />
              <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>{normalizePath(selectedFileData.file_path)}</span>
            </div>
            <DiffViewerBase
                oldValue={selectedFileData.old_content || ""}
                newValue={selectedFileData.new_content || selectedFileData.patch}
                splitView={true}
                highlightLines={highlightLines}
                extraLinesSurroundingDiff={3}
                useDarkTheme={true}
                showDiffOnly={false}
                summary={normalizePath(selectedFileData.file_path)}
                leftTitle={<span style={{ color: "var(--text-muted)", fontSize: "12px" }}>Before</span>}
                rightTitle={<span style={{ color: "var(--text-muted)", fontSize: "12px" }}>After</span>}
                styles={{
                  variables: {
                    dark: {
                      diffViewerBackground: "var(--bg-primary)",
                      diffViewerColor: "var(--text-primary)",
                      diffViewerTitleBackground: "var(--bg-tertiary)",
                      diffViewerTitleColor: "var(--text-secondary)",
                      diffViewerTitleBorderColor: "var(--border)",
                      addedBackground: "rgba(16,185,129,0.1)",
                      addedColor: "var(--text-primary)",
                      removedBackground: "rgba(239,68,68,0.1)",
                      removedColor: "var(--text-primary)",
                      wordAddedBackground: "rgba(16,185,129,0.25)",
                      wordRemovedBackground: "rgba(239,68,68,0.25)",
                      addedGutterBackground: "rgba(16,185,129,0.15)",
                      removedGutterBackground: "rgba(239,68,68,0.15)",
                      gutterBackground: "var(--bg-tertiary)",
                      gutterBackgroundDark: "var(--bg-secondary)",
                      gutterColor: "var(--text-muted)",
                      addedGutterColor: "var(--success)",
                      removedGutterColor: "var(--error)",
                      codeFoldGutterBackground: "var(--bg-tertiary)",
                      codeFoldBackground: "var(--bg-tertiary)",
                      codeFoldContentColor: "var(--text-muted)",
                      emptyLineBackground: "var(--bg-primary)",
                      highlightBackground: "rgba(139,92,246,0.1)",
                      highlightGutterBackground: "rgba(139,92,246,0.15)",
                    },
                  },
                  diffContainer: { minWidth: 0 },
                  codeFoldExpandButton: { borderRadius: 0 },
                  titleBlock: { borderTop: "none" },
                }}
              />
          </div>
        )}
      </div>

      <div className="w-full lg:w-80 flex-shrink-0 space-y-3 overflow-y-auto max-h-[80vh]">
        <div className="flex items-center gap-2 px-1">
          <MessageSquare className="w-4 h-4" style={{ color: "var(--accent)" }} />
          <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>
            AI Comments
          </h3>
          <span className="badge badge-info ml-auto" style={{ fontSize: "10px" }}>{fileComments.length}</span>
        </div>

        {fileComments.length === 0 ? (
          <div className="glass-card p-6 text-center" style={{ color: "var(--text-muted)" }}>
            <MessageSquare className="w-6 h-6 mx-auto mb-2 opacity-50" />
            <p className="text-xs">No comments on this file</p>
          </div>
        ) : (
          fileComments.map((comment) => (
            <CommentOverlay key={comment.id} comment={comment} />
          ))
        )}
      </div>
    </div>
  );
}
