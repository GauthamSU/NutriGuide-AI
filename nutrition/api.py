"""
Backward-compatibility Ninja router facade for nutrition, auth, profile, groups, tracker.
Each router is modularly defined in its respective backend/ domain package:
- backend.assistant.router (assistant_router)
- backend.meal_planner.router (meal_planner_router)
- backend.profile.router (auth_router, profile_router)
- backend.groups.router (groups_router)
- backend.tracker.router (tracker_router)
"""

from ninja import Router

from backend.assistant.graph.workflow import run_nutrition_workflow
from backend.assistant.router import _write_api_response_debug, assistant_router
from backend.food_database.llama_client import LlamaCppClient
from backend.groups.router import groups_router
from backend.meal_planner.router import router as meal_planner_router
from backend.meal_planner.workflow import run_meal_plan_workflow
from backend.profile.router import auth_router, profile_router
from backend.tracker.router import router as tracker_router

# Nutrition router hosts assistant dish analysis + meal plan generation endpoints
router = assistant_router
router.add_router("/meal-plans", meal_planner_router)

__all__ = [
    "router",
    "auth_router",
    "profile_router",
    "groups_router",
    "tracker_router",
    "LlamaCppClient",
    "run_meal_plan_workflow",
    "run_nutrition_workflow",
    "_write_api_response_debug",
]
