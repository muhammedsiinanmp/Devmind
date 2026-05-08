import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useReviewStore } from "../store/reviewSlice";
import ReviewStatus from "../components/review/ReviewStatus";
import ReactDiffViewer from "react-diff-viewer-continued";
import { Loader2, FileCode } from "lucide-react";

const MOCK_DIFF = `--- a/src/index.js
+++ b/src/index.js
@@ -1,5 +1,7 @@
 console.log("Hello World");
+
+// This is a new line
+const x = 42;

 function test() {
   return true;
@@ -10,3 +12,4 @@ function test() {
   return true;
 }
+
+// End of file
`;

export default function ReviewDetail() {
  const { id } = useParams<{ id: string }>();
  const { currentReview, isLoading, error, fetchReview } = useReviewStore();

  useEffect(() => {
    if (id) {
      fetchReview(parseInt(id));
    }
  }, [id]);

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">{error}</div>
      </div>
    );
  }

  if (!currentReview) {
    return (
      <div className="p-6">
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">Review not found</div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <div className="flex items-center gap-4 mb-2">
          <h1 className="text-2xl font-bold text-gray-900">#{currentReview.pr_number}</h1>
          <ReviewStatus reviewId={currentReview.id} initialStatus={currentReview.status} />
          <span
            className={`px-2 py-1 rounded text-sm font-medium ${
              currentReview.risk_score >= 70
                ? "bg-green-100 text-green-700"
                : currentReview.risk_score >= 40
                ? "bg-yellow-100 text-yellow-700"
                : "bg-red-100 text-red-700"
            }`}
          >
            Risk: {currentReview.risk_score}
          </span>
        </div>
        <p className="text-gray-600">{currentReview.pr_title}</p>
        <p className="text-sm text-gray-500 font-mono mt-1">{currentReview.head_sha}</p>
      </div>

      {currentReview.summary && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          <h3 className="font-medium text-blue-900">Summary</h3>
          <p className="text-blue-800 mt-1">{currentReview.summary}</p>
        </div>
      )}

      <div className="border rounded-lg overflow-hidden">
        <div className="bg-gray-50 px-4 py-2 border-b flex items-center gap-2">
          <FileCode className="w-4 h-4 text-gray-500" />
          <span className="font-medium text-gray-700">Changes</span>
        </div>
        <ReactDiffViewer
          oldValue={MOCK_DIFF}
          newValue={MOCK_DIFF}
          splitView={true}
          hideLineNumbers={false}
        />
      </div>

      {currentReview.comments && currentReview.comments.length > 0 && (
        <div className="mt-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">All Comments ({currentReview.comments.length})</h2>
          <div className="space-y-4">
            {currentReview.comments.map((comment) => (
              <div key={comment.id} className="bg-white border rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-mono text-sm bg-gray-100 px-2 py-1 rounded">
                    {comment.file_path}:{comment.line_number}
                  </span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded uppercase ${
                      comment.severity === "critical"
                        ? "bg-red-100 text-red-700"
                        : comment.severity === "error"
                        ? "bg-orange-100 text-orange-700"
                        : comment.severity === "warning"
                        ? "bg-yellow-100 text-yellow-700"
                        : "bg-blue-100 text-blue-700"
                    }`}
                  >
                    {comment.severity}
                  </span>
                  <span className="text-sm text-gray-500">{comment.category}</span>
                </div>
                <p className="text-gray-700">{comment.body}</p>
                {comment.suggested_fix && (
                  <div className="mt-3 pt-3 border-t">
                    <span className="text-sm font-medium text-gray-600">Suggested fix:</span>
                    <pre className="mt-1 text-sm whitespace-pre-wrap font-mono bg-gray-50 p-3 rounded">
                      {comment.suggested_fix}
                    </pre>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
