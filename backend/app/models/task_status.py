"""
Fine-grained task status machine (4 states → 7 states).
Maps Pipeline stages to user-visible progress.
"""


class TaskStatus:
    CREATED = "created"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    EXECUTING = "executing"
    REPAIRING = "repairing"
    SUCCESS = "success"
    FAILED = "failed"

    TERMINAL = {SUCCESS, FAILED}

    TRANSITIONS = {
        CREATED:    {ANALYZING, FAILED},
        ANALYZING:  {GENERATING, SUCCESS, FAILED},
        GENERATING: {EXECUTING, FAILED},
        EXECUTING:  {REPAIRING, SUCCESS, FAILED},
        REPAIRING:  {EXECUTING, SUCCESS, FAILED},
        SUCCESS:    set(),
        FAILED:     set(),
    }

    ALL = set(TRANSITIONS.keys())

    @classmethod
    def is_valid_transition(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.TRANSITIONS.get(from_status, set())


LEGACY_STATUS_MAP = {
    "pending": TaskStatus.CREATED,
    "running": TaskStatus.ANALYZING,
}

STAGE_STATUS_MAP = {
    "code_review": TaskStatus.ANALYZING,
    "change_intelligence": TaskStatus.ANALYZING,
    "context": TaskStatus.ANALYZING,
    "generator": TaskStatus.GENERATING,
    "validate_repair": TaskStatus.EXECUTING,
    "quality_scorer": TaskStatus.EXECUTING,
    "mr_feedback": TaskStatus.SUCCESS,
}
