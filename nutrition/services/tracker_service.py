"""
Backward-compatibility facade for tracker service.
Implementation is modularly organized in backend/tracker/services.py.
"""

from backend.tracker.services import (
    DAILY_MACRO_TARGETS,
    EXPLICIT_LOG_PATTERNS,
    MACRO_KEYS,
    PERIOD_DAYS_MAP,
    aggregate_micronutrients_from_items,
    delete_tracked_meal,
    get_tracker_summary,
    has_explicit_log_intent,
    log_meal_to_tracker,
    serialize_tracked_meal,
)

__all__ = [
    "MACRO_KEYS",
    "DAILY_MACRO_TARGETS",
    "PERIOD_DAYS_MAP",
    "EXPLICIT_LOG_PATTERNS",
    "has_explicit_log_intent",
    "aggregate_micronutrients_from_items",
    "serialize_tracked_meal",
    "log_meal_to_tracker",
    "delete_tracked_meal",
    "get_tracker_summary",
]
