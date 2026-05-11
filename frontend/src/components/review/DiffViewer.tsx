import { useMemo, useState } from "react";
import DiffViewerBase from "react-diff-viewer-continued";
import CommentOverlay, { type CommentData } from "./CommentOverlay";
import { Code2, MessageSquare } from "lucide-react";

export interface DiffFile {
  file_path: string;
  additions: number;
  deletions: number;
  patch: string;
}

interface DiffViewerProps {
  files: DiffFile[];
  comments: CommentData[];
  diffUrl?: string;
  isLoading?: boolean;
}

export default function DiffViewer({ files, comments, diffUrl, isLoading }: DiffViewerProps) {
  const [selectedFile, setSelectedFile] = useState<string>(files[0]?.file_path || "");

  const commentsByFile = useMemo(() => {
    const map: Record<string, CommentData[]> = {};
    for (const c of comments) {
      if (!map[c.file_path]) map[c.file_path] = [];
      map[c.file_path].push(c);
    }
    return map;
  }, [comments]);

  const filesByPath = useMemo(() => {
    const map: Record<string, DiffFile> = {};
    for (const f of files) map[f.file_path] = f;
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

  return (
    <div className="flex gap-6 h-full">
      <div className="flex-1 min-w-0 space-y-4">
        <div className="flex items-center gap-2 overflow-x-auto pb-2">
          {files.map((file) => {
            const isSelected = file.file_path === selectedFile;
            const fileComms = commentsByFile[file.file_path] || [];
            return (
              <button
                key={file.file_path}
                onClick={() => setSelectedFile(file.file_path)}
                className="flex-shrink-0 px-3 py-2 rounded-lg border text-xs font-mono transition-all max-w-[200px]"
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
          <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-secondary)" }}>
            <div className="px-4 py-2 border-b flex items-center gap-2" style={{ borderColor: "var(--border)", backgroundColor: "var(--bg-tertiary)" }}>
              <Code2 className="w-4 h-4" style={{ color: "var(--accent)" }} />
              <span className="text-xs font-mono" style={{ color: "var(--text-secondary)" }}>{selectedFile}</span>
            </div>
            <DiffViewerBase
              oldValue={""}
              newValue={selectedFileData.patch}
              splitView={false}
              highlightLines={fileComments.map((c) => String(c.line_number))}
              extraLinesSurroundingDiff={3}
              useDarkTheme={true}
              leftTitle={<span style={{ color: "var(--text-muted)", fontSize: "12px" }}>Before</span>}
              rightTitle={<span style={{ color: "var(--text-muted)", fontSize: "12px" }}>After</span>}
            />
          </div>
        )}
      </div>

      <div className="w-80 flex-shrink-0 space-y-3 overflow-y-auto max-h-[80vh]">
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
