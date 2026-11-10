from enum import Enum


class LikeResult(str, Enum):
    LIKED             = "LIKED"
    ALREADY_LIKED     = "ALREADY_LIKED"
    BLOCKED_BY_TIKTOK = "BLOCKED_BY_TIKTOK"
    NOT_LOGGED_IN     = "NOT_LOGGED_IN"
    NOT_FOUND         = "NOT_FOUND"
    CAPTCHA           = "CAPTCHA"
    RATE_LIMITED      = "RATE_LIMITED"
    NAVIGATION_ERROR  = "NAVIGATION_ERROR"
    TIMEOUT           = "TIMEOUT"
    FAILED            = "FAILED"
    ERROR             = "ERROR"


class FollowResult(str, Enum):
    FOLLOWED          = "FOLLOWED"
    ALREADY_FOLLOWED  = "ALREADY_FOLLOWED"
    BLOCKED_BY_TIKTOK = "BLOCKED_BY_TIKTOK"
    COOKIE_EXPIRED    = "COOKIE_EXPIRED"
    NOT_FOUND         = "NOT_FOUND"
    ACCESS_DENIED     = "ACCESS_DENIED"
    CAPTCHA           = "CAPTCHA"
    NAVIGATION_ERROR  = "NAVIGATION_ERROR"
    TIMEOUT           = "TIMEOUT"
    FAILED            = "FAILED"
    ERROR             = "ERROR"


class TaskState(str, Enum):
    PENDING    = "PENDING"
    OPENING    = "OPENING"
    PROCESSING = "PROCESSING"
    SUCCESS    = "SUCCESS"
    FAILED     = "FAILED"
    SKIPPED    = "SKIPPED"
    CANCELLED  = "CANCELLED"


LIKE_RESULT_TO_STATE = {
    LikeResult.LIKED:             TaskState.SUCCESS,
    LikeResult.ALREADY_LIKED:     TaskState.SKIPPED,
    LikeResult.BLOCKED_BY_TIKTOK: TaskState.FAILED,
    LikeResult.NOT_LOGGED_IN:     TaskState.FAILED,
    LikeResult.NOT_FOUND:         TaskState.FAILED,
    LikeResult.CAPTCHA:           TaskState.FAILED,
    LikeResult.RATE_LIMITED:      TaskState.FAILED,
    LikeResult.NAVIGATION_ERROR:  TaskState.FAILED,
    LikeResult.TIMEOUT:           TaskState.FAILED,
    LikeResult.FAILED:            TaskState.FAILED,
    LikeResult.ERROR:             TaskState.FAILED,
}

FOLLOW_RESULT_TO_STATE = {
    FollowResult.FOLLOWED:          TaskState.SUCCESS,
    FollowResult.ALREADY_FOLLOWED:  TaskState.SKIPPED,
    FollowResult.BLOCKED_BY_TIKTOK: TaskState.FAILED,
    FollowResult.COOKIE_EXPIRED:    TaskState.FAILED,
    FollowResult.NOT_FOUND:         TaskState.FAILED,
    FollowResult.ACCESS_DENIED:     TaskState.FAILED,
    FollowResult.CAPTCHA:           TaskState.FAILED,
    FollowResult.NAVIGATION_ERROR:  TaskState.FAILED,
    FollowResult.TIMEOUT:           TaskState.FAILED,
    FollowResult.FAILED:            TaskState.FAILED,
    FollowResult.ERROR:             TaskState.FAILED,
}

RESULT_GUI_COLOR = {
    TaskState.SUCCESS:    "SUCCESS",
    TaskState.SKIPPED:    "WARNING",
    TaskState.FAILED:     "ERROR",
    TaskState.PENDING:    "PENDING",
    TaskState.OPENING:    "PROCESSING",
    TaskState.PROCESSING: "PROCESSING",
    TaskState.CANCELLED:  "WARNING",
}
