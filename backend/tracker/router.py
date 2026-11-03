from typing import Optional
from ninja import Router
from ninja.errors import HttpError

from backend.common.schemas import (
    ErrorResponseSchema,
    NutrientAnalysisResponseSchema,
    TrackerLogRequestSchema,
)
from backend.profile.services import get_user_from_request
from backend.tracker.services import (
    delete_tracked_meal,
    get_tracker_summary,
    log_meal_to_tracker,
)

router = Router(tags=["Nutrient Tracker"])


@router.get("", summary="Retrieve aggregated nutrient tracker logs for daily, weekly, and monthly periods")
@router.get("/summary", summary="Retrieve aggregated nutrient tracker logs for daily, weekly, and monthly periods")
def tracker_summary(
    request,
    owner_id: Optional[str] = None,
    period: str = "daily",
    date: Optional[str] = None,
    token: Optional[str] = None,
):
    """
    Returns nutrient summary.
    STRICT TODAY DATE LOGIC:
    When period='daily', automatically fetches today's date (or target date) and strictly
    displays ONLY today's logs. Yesterday's logs are not included.
    """
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=False)
    return get_tracker_summary(
        owner_id=owner_id,
        period=period,
        target_date=date,
        user=user,
    )


@router.post("/log", summary="Explicitly record a meal entry to the nutrient tracker")
def log_meal(
    request,
    payload: TrackerLogRequestSchema,
    token: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=payload.owner_id, require_auth=False)
    analysis_dict = payload.analysis.model_dump(mode="json") if payload.analysis else None
    if not analysis_dict and not payload.message_id and any(
        val is not None
        for val in (
            payload.calories_kcal,
            payload.protein_g,
            payload.carbohydrates_g,
            payload.total_fat_g,
            payload.dietary_fiber_g,
            payload.total_sugars_g,
        )
    ):
        analysis_dict = {
            "meal_title": payload.meal_title or "Manual Meal Entry",
            "total_macronutrients": {
                "calories_kcal": payload.calories_kcal or 0.0,
                "protein_g": payload.protein_g or 0.0,
                "carbohydrates_g": payload.carbohydrates_g or 0.0,
                "total_fat_g": payload.total_fat_g or 0.0,
                "dietary_fiber_g": payload.dietary_fiber_g or 0.0,
                "total_sugars_g": payload.total_sugars_g or 0.0,
            },
            "items": [],
        }
    logged_via = payload.logged_via or ("chat_button" if payload.message_id else "manual")
    return log_meal_to_tracker(
        owner_id=payload.owner_id,
        user=user,
        message_id=payload.message_id,
        conversation_id=payload.conversation_id,
        meal_title=payload.meal_title,
        meal_type=payload.meal_type or "Meal",
        recognized_summary=payload.recognized_summary or "",
        analysis=analysis_dict,
        logged_via=logged_via,
        consumed_at=payload.consumed_at,
        time_option=payload.time_option or "now",
    )


@router.delete("/meals/{log_id}", summary="Delete a tracked meal entry from the personal tracker")
@router.post("/meals/{log_id}/delete", summary="Delete a tracked meal entry from the personal tracker (POST alternative)")
def delete_meal(
    request,
    log_id: str,
    owner_id: Optional[str] = None,
    token: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=False)
    effective_owner = (owner_id or "").strip()
    if not effective_owner and user and hasattr(user, "profile"):
        effective_owner = str(user.profile.owner_id)
    return delete_tracked_meal(owner_id=effective_owner, log_id=log_id, user=user)
