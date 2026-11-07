import { ThumbsDown, ThumbsUp } from "lucide-react";
import { feedbackBadge, type CommentFeedback } from "../../lib/commentFeedback";

interface FeedbackBadgeProps {
  feedback: CommentFeedback | null | undefined;
}

/** Small badge with a comment's developer verdict; renders nothing without one. */
export default function FeedbackBadge({ feedback }: FeedbackBadgeProps) {
  const badge = feedbackBadge(feedback);
  if (!badge) return null;
  const Icon = feedback?.signal === "rejected" ? ThumbsDown : ThumbsUp;
  return (
    <span className={`badge ${badge.className}`} title={badge.title} aria-label={badge.title}>
      <Icon className="w-3 h-3" aria-hidden="true" />
      {badge.label}
    </span>
  );
}
