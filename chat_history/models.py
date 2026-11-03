"""
Backward-compatibility model registry for Django 'chat_history' app.
All models are modularly defined and documented in backend/:
- backend.assistant.models (ChatConversation, ChatMessage)
- backend.tracker.models (TrackedMeal)
- backend.meal_planner.models (MealPlanHistory)
- backend.groups.models (NutritionGroup, GroupMembership, GroupMealLog, GroupMembershipRequest)
- backend.profile.models (UserProfile)
"""

from backend.assistant.models import ChatConversation, ChatMessage
from backend.groups.models import (
    GroupMealLog,
    GroupMembership,
    GroupMembershipRequest,
    NutritionGroup,
)
from backend.meal_planner.models import MealPlanHistory
from backend.profile.models import UserProfile
from backend.tracker.models import TrackedMeal

__all__ = [
    "ChatConversation",
    "ChatMessage",
    "MealPlanHistory",
    "UserProfile",
    "NutritionGroup",
    "GroupMembership",
    "GroupMealLog",
    "TrackedMeal",
    "GroupMembershipRequest",
]
