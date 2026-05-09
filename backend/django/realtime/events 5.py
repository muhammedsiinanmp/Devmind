class ReviewEventType:
    STATUS_CHANGED = "review.status_changed"
    COMPLETED = "review.completed"
    FAILED = "review.failed"
    PROGRESS = "review.progress"


class NotificationEventType:
    NEW = "notification.new"
    READ = "notification.read"
    DELETED = "notification.deleted"


def get_review_group(review_id: int) -> str:
    return f"review_{review_id}"


def get_user_notifications_group(user_id: int) -> str:
    return f"notifications_{user_id}"
