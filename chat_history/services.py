"""
Backward-compatibility services facade for Django 'chat_history' app.
Implementations are modularly organized in:
- backend.assistant.services
- backend.meal_planner.services
"""

from backend.assistant.services import (
    DATABASE_ALIAS,
    customize_dish_recipe,
    delete_chat_message,
    delete_conversation,
    get_chat_attachment,
    get_conversation,
    list_conversations,
    reset_dish_recipe,
    save_chat_message,
)
from backend.food_database.services import resolve_dish_nutrition_from_db
from backend.meal_planner.services import (
    delete_meal_plan,
    list_meal_plans,
    save_meal_plan,
)

__all__ = [
    "DATABASE_ALIAS",
    "save_chat_message",
    "list_conversations",
    "get_conversation",
    "delete_conversation",
    "delete_chat_message",
    "customize_dish_recipe",
    "reset_dish_recipe",
    "get_chat_attachment",
    "save_meal_plan",
    "list_meal_plans",
    "delete_meal_plan",
    "resolve_dish_nutrition_from_db",
]
