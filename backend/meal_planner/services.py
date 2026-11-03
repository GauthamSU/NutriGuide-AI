import uuid
from typing import Optional
from ninja.errors import HttpError

from backend.meal_planner.models import MealPlanHistory
from backend.meal_planner.workflow import run_meal_plan_workflow

DATABASE_ALIAS = "default"


def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise HttpError(400, f"Invalid {label}.") from exc


def save_meal_plan(
    *,
    owner_id: str,
    preferences: list[str],
    custom_request: str,
    plan: dict,
    title: Optional[str] = None,
) -> dict:
    owner_uuid = _parse_uuid(owner_id, "owner_id")
    final_title = (title or (", ".join(preferences) or custom_request or "Personalized meal plan")).strip()
    history = MealPlanHistory.objects.using(DATABASE_ALIAS).create(
        owner_id=str(owner_uuid),
        title=final_title[:160],
        preferences=preferences or [],
        custom_request=custom_request or "",
        plan=plan or {},
    )
    return {
        "id": str(history.id),
        "title": history.title,
        "preferences": history.preferences,
        "custom_request": history.custom_request,
        "plan": history.plan,
        "created_at": history.created_at.isoformat(),
    }


def list_meal_plans(owner_id: str) -> list[dict]:
    owner_uuid = _parse_uuid(owner_id, "owner_id")
    return [
        {
            "id": str(history.id),
            "title": history.title,
            "preferences": history.preferences,
            "custom_request": history.custom_request,
            "plan": history.plan,
            "created_at": history.created_at.isoformat(),
        }
        for history in MealPlanHistory.objects.using(DATABASE_ALIAS)
        .filter(owner_id=str(owner_uuid))
        .order_by("-created_at")
    ]


def delete_meal_plan(owner_id: str, meal_plan_id: str) -> dict:
    owner_uuid = _parse_uuid(owner_id, "owner_id")
    plan_uuid = _parse_uuid(meal_plan_id, "meal_plan_id")
    record = (
        MealPlanHistory.objects.using(DATABASE_ALIAS)
        .filter(id=plan_uuid, owner_id=str(owner_uuid))
        .first()
    )
    if record is None:
        raise HttpError(404, "Meal plan not found.")
    record.delete(using=DATABASE_ALIAS)
    return {
        "status": "ok",
        "deleted_meal_plan_id": str(plan_uuid),
    }
