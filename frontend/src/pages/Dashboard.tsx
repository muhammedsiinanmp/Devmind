import { useEffect } from "react";
import { useReviewStore } from "../store/reviewSlice";
import { Link } from "react-router-dom";
import ReviewStatus from "../components/review/ReviewStatus";
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";

export default function Dashboard() {
  const { reviews, isLoading, totalCount, page, fetchReviews, setPage } = useReviewStore();

  useEffect(() => {
    fetchReviews(page);
  }, [page]);

  const totalPages = Math.ceil(totalCount / 10);

  if (isLoading && reviews.length === 0) {
    return (
      <div className="p-6 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Reviews</h1>

      {reviews.length === 0 ? (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 text-center">
          <p className="text-gray-500">No reviews yet. Trigger a review from a repository.</p>
        </div>
      ) : (
        <>
          <div className="bg-white border rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">PR</th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Risk Score</th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Summary</th>
                  <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {reviews.map((review) => (
                  <tr key={review.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <Link
                        to={`/reviews/${review.id}`}
                        className="font-medium text-blue-600 hover:text-blue-800"
                      >
                        #{review.pr_number}
                      </Link>
                      <p className="text-sm text-gray-500 truncate max-w-xs">{review.pr_title}</p>
                    </td>
                    <td className="px-6 py-4">
                      <ReviewStatus reviewId={review.id} initialStatus={review.status} />
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`px-2 py-1 rounded text-sm font-medium ${
                          review.risk_score >= 70
                            ? "bg-green-100 text-green-700"
                            : review.risk_score >= 40
                            ? "bg-yellow-100 text-yellow-700"
                            : "bg-red-100 text-red-700"
                        }`}
                      >
                        {review.risk_score}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600 max-w-xs truncate">
                      {review.summary || "—"}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-500">
                      {new Date(review.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-4">
              <button
                onClick={() => setPage(page - 1)}
                disabled={page === 1}
                className="p-2 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronLeft className="w-5 h-5" />
              </button>
              <span className="text-sm text-gray-600">
                Page {page} of {totalPages}
              </span>
              <button
                onClick={() => setPage(page + 1)}
                disabled={page >= totalPages}
                className="p-2 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <ChevronRight className="w-5 h-5" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
