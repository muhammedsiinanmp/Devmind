import { describe, expect, it } from "vitest";
import { feedbackBadge, type CommentFeedback } from "./commentFeedback";

function feedback(signal: string, source: string): CommentFeedback {
  return { signal, source, updated_at: "2026-11-07T10:00:00Z" } as CommentFeedback;
}

describe("feedbackBadge", () => {
  it("shows nothing when developers gave no verdict", () => {
    expect(feedbackBadge(null)).toBeNull();
    expect(feedbackBadge(undefined)).toBeNull();
  });

  it("marks accepted comments green and names the source", () => {
    expect(feedbackBadge(feedback("accepted", "reaction"))).toEqual({
      label: "Accepted",
      className: "badge-success",
      title: "Accepted: more 👍 than 👎 reactions when the PR closed",
    });
    expect(feedbackBadge(feedback("accepted", "resolved"))?.title).toBe(
      "Accepted: the comment's thread was resolved",
    );
  });

  it("marks rejected comments red and names the source", () => {
    expect(feedbackBadge(feedback("rejected", "reply"))).toEqual({
      label: "Rejected",
      className: "badge-error",
      title: "Rejected: a reply said so (for example \"false positive\")",
    });
    expect(feedbackBadge(feedback("rejected", "reaction"))?.title).toBe(
      "Rejected: more 👎 than 👍 reactions when the PR closed",
    );
  });

  it("ignores signals it doesn't know", () => {
    expect(feedbackBadge(feedback("maybe", "reaction"))).toBeNull();
  });

  it("still shows a known signal from an unknown source", () => {
    expect(feedbackBadge(feedback("accepted", "emoji"))).toEqual({
      label: "Accepted",
      className: "badge-success",
      title: "Accepted",
    });
  });
});
