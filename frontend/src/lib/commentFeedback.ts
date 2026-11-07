/**
 * A developer's verdict on a DevMind comment, as the review detail API
 * returns it (null when there is none). See docs/feedback-learning.md.
 */
export interface CommentFeedback {
  signal: "accepted" | "rejected";
  source: "reaction" | "reply" | "resolved";
  updated_at: string;
}

export interface FeedbackBadge {
  label: string;
  className: string;
  title: string;
}

const SIGNALS = {
  accepted: { label: "Accepted", className: "badge-success" },
  rejected: { label: "Rejected", className: "badge-error" },
} as const;

const SOURCE_TEXT: Record<string, Record<string, string>> = {
  reaction: {
    accepted: "more 👍 than 👎 reactions when the PR closed",
    rejected: "more 👎 than 👍 reactions when the PR closed",
  },
  reply: {
    accepted: 'a reply said so (for example "fixed")',
    rejected: 'a reply said so (for example "false positive")',
  },
  resolved: {
    accepted: "the comment's thread was resolved",
  },
};

/** The badge for a comment's feedback, or null when there is nothing to show. */
export function feedbackBadge(feedback: CommentFeedback | null | undefined): FeedbackBadge | null {
  if (!feedback || !Object.prototype.hasOwnProperty.call(SIGNALS, feedback.signal)) return null;
  const { label, className } = SIGNALS[feedback.signal];
  const reason = SOURCE_TEXT[feedback.source]?.[feedback.signal];
  return { label, className, title: reason ? `${label}: ${reason}` : label };
}
