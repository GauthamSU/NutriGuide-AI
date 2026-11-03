import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from ninja.errors import HttpError

from backend.assistant.models import ChatMessage
from backend.profile.models import UserProfile
from backend.tracker.models import TrackedMeal
from backend.food_database.services import (
    resolve_dish_nutrition_from_db,
    resolve_single_ingredient_from_db,
)

DATABASE_ALIAS = "default"

MACRO_KEYS = (
    "calories_kcal",
    "protein_g",
    "carbohydrates_g",
    "dietary_fiber_g",
    "total_sugars_g",
    "added_sugars_g",
    "total_fat_g",
    "saturated_fat_g",
    "monounsaturated_fat_g",
    "polyunsaturated_fat_g",
    "unsaturated_fat_g",
    "trans_fat_g",
    "cholesterol_mg",
    "sodium_mg",
    "water_g",
)

DAILY_MACRO_TARGETS = {
    "calories_kcal": 2000.0,
    "protein_g": 60.0,
    "carbohydrates_g": 275.0,
    "dietary_fiber_g": 30.0,
    "total_sugars_g": 50.0,
    "added_sugars_g": 25.0,
    "total_fat_g": 65.0,
    "saturated_fat_g": 20.0,
    "monounsaturated_fat_g": 29.0,
    "polyunsaturated_fat_g": 15.0,
    "unsaturated_fat_g": 44.0,
    "trans_fat_g": 2.0,
    "cholesterol_mg": 300.0,
    "sodium_mg": 2000.0,
    "water_g": 2500.0,
}

PERIOD_DAYS_MAP = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}

EXPLICIT_LOG_PATTERNS = [
    re.compile(
        r"\b(?:please\s+)?log\s+(?:this|it|my|the|these|meal|dish|breakfast|lunch|dinner|snack|snacks|food|items?|into|to|in)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\badd\s+(?:this|it|my|the|these|meal|dish|breakfast|lunch|dinner|snack|food)?\s*(?:to|into|in)\s+(?:my\s+|the\s+)?(?:nutrient\s+|nutrition\s+)?(?:tracker|log|daily\s+log|profile|diary)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\btrack\s+(?:this|it|my\s+meal|this\s+meal|this\s+dish|my\s+breakfast|my\s+lunch|my\s+dinner|my\s+snack|in\s+my\s+tracker|to\s+tracker)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:record|save|include)\s+(?:this|it|my\s+meal|this\s+meal|this\s+dish)\s+(?:in|into|to)\s+(?:my\s+|the\s+)?(?:tracker|log|profile)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\blog\s*(?:to|into|in)\s*(?:my\s+|the\s+)?tracker\b",
        re.IGNORECASE,
    ),
]


def has_explicit_log_intent(
    text: Optional[str] = None,
    transcription: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Return (True, 'voice_intent' | 'text_intent') ONLY if the user explicitly mentions
    logging/tracking/adding the meal to their tracker in their text or voice note.
    """
    clean_voice = (transcription or "").strip()
    if clean_voice:
        for pattern in EXPLICIT_LOG_PATTERNS:
            if pattern.search(clean_voice):
                return True, "voice_intent"

    clean_text = (text or "").strip()
    if clean_text:
        for pattern in EXPLICIT_LOG_PATTERNS:
            if pattern.search(clean_text):
                return True, "text_intent"

    return False, ""


def aggregate_micronutrients_from_items(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Aggregate vitamin and mineral lists across a list of food items."""
    totals: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]] = {"vitamins": {}, "minerals": {}}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        micros = item.get("micronutrients") or {}
        for category in ("vitamins", "minerals"):
            for nutrient in micros.get(category) or []:
                if not isinstance(nutrient, dict):
                    continue
                name = str(nutrient.get("name") or "Unknown")
                unit = str(nutrient.get("unit") or "")
                key = (name, unit)
                entry = totals[category].setdefault(
                    key,
                    {
                        "name": name,
                        "unit": unit,
                        "amount": 0.0,
                        "daily_value_percent": 0.0,
                    },
                )
                entry["amount"] += float(nutrient.get("amount") or 0.0)
                entry["daily_value_percent"] += float(nutrient.get("daily_value_percent") or 0.0)

    return {
        category: [
            {
                "name": v["name"],
                "unit": v["unit"],
                "amount": round(v["amount"], 2),
                "daily_value_percent": round(v["daily_value_percent"], 1),
            }
            for v in sorted(cat_map.values(), key=lambda x: (-x["daily_value_percent"], x["name"]))
        ]
        for category, cat_map in totals.items()
    }


def _get_meal_local_datetime(meal: TrackedMeal) -> datetime:
    dt = meal.consumed_at or meal.created_at
    return timezone.localtime(dt) if timezone.is_aware(dt) else dt


def serialize_tracked_meal(meal: TrackedMeal) -> Dict[str, Any]:
    """Serialize a TrackedMeal model instance into a dictionary."""
    macros = dict(meal.macronutrients or {})
    for k in MACRO_KEYS:
        macros[k] = round(float(macros.get(k) or 0.0), 2)

    # Check for legacy meals where monounsaturated/polyunsaturated fats were 0 or missing
    if float(macros.get("monounsaturated_fat_g") or 0.0) == 0.0 and float(macros.get("polyunsaturated_fat_g") or 0.0) == 0.0 and meal.items:
        mufa = 0.0
        pufa = 0.0
        for it in meal.items:
            it_m = (it.get("macronutrients") or {})
            mufa += float(it_m.get("monounsaturated_fat_g") or 0.0)
            pufa += float(it_m.get("polyunsaturated_fat_g") or 0.0)
        if mufa > 0 or pufa > 0:
            macros["monounsaturated_fat_g"] = round(mufa, 2)
            macros["polyunsaturated_fat_g"] = round(pufa, 2)
            if not macros.get("unsaturated_fat_g"):
                macros["unsaturated_fat_g"] = round(mufa + pufa, 2)

    micros = meal.micronutrients or {"vitamins": [], "minerals": []}

    local_dt = _get_meal_local_datetime(meal)
    now_local = timezone.localtime(timezone.now()) if timezone.is_aware(timezone.now()) else timezone.now()

    time_str = local_dt.strftime("%I:%M %p").lstrip("0") or "12:00 AM"
    is_today = (local_dt.date() == now_local.date())
    if is_today:
        time_display = f"Today, {time_str}"
    elif local_dt.date() == (now_local - timedelta(days=1)).date():
        time_display = f"Yesterday, {time_str}"
    elif local_dt.year == now_local.year:
        time_display = f"{local_dt.strftime('%b %d')}, {time_str}"
    else:
        time_display = f"{local_dt.strftime('%b %d, %Y')}, {time_str}"

    conv_id = getattr(meal, "conversation_id", "") or ""
    clean_msg_id = (meal.source_message_id or "").strip()
    if not conv_id and clean_msg_id:
        try:
            msg_uuid = uuid.UUID(clean_msg_id)
            c_msg = ChatMessage.objects.using(DATABASE_ALIAS).filter(id=msg_uuid).first()
            if c_msg and c_msg.conversation_id:
                conv_id = str(c_msg.conversation_id)
                try:
                    meal.conversation_id = conv_id
                    meal.save(update_fields=["conversation_id"])
                except Exception:
                    pass
        except Exception:
            pass

    return {
        "id": str(meal.id),
        "owner_id": meal.owner_id,
        "conversation_id": conv_id,
        "source_message_id": clean_msg_id,
        "has_chat_source": bool(conv_id and clean_msg_id),
        "meal_title": meal.meal_title,
        "meal_type": meal.meal_type,
        "recognized_summary": meal.recognized_summary,
        "macronutrients": macros,
        "micronutrients": micros,
        "items": meal.items or [],
        "logged_via": meal.logged_via,
        "consumed_at": (meal.consumed_at or meal.created_at).isoformat(),
        "consumed_date": local_dt.date().isoformat(),
        "consumed_time": time_str,
        "consumed_display": time_display,
        "is_today": is_today,
        "created_at": meal.created_at.isoformat(),
    }


def log_meal_to_tracker(
    *,
    owner_id: Optional[str] = None,
    user=None,
    message_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    meal_title: Optional[str] = None,
    meal_type: str = "Meal",
    recognized_summary: str = "",
    analysis: Optional[Dict[str, Any]] = None,
    logged_via: str = "button",
    consumed_at: Optional[Any] = None,
    time_option: str = "now",
) -> Dict[str, Any]:
    """
    Explicitly log a meal into TrackedMeal.
    Supports logging from a ChatMessage (by message_id), from an analysis payload,
    or from a manual food description resolved against the IFCT 2017 database.
    """
    effective_owner_id = (owner_id or "").strip()
    if user is not None and not getattr(user, "username", "").startswith("guest_"):
        profile = UserProfile.objects.filter(user=user).first()
        if profile:
            effective_owner_id = str(profile.owner_id)
    elif effective_owner_id and user is None:
        try:
            owner_uuid = uuid.UUID(effective_owner_id)
            prof = UserProfile.objects.select_related("user").filter(owner_id=owner_uuid).first()
            if prof and not prof.user.username.startswith("guest_"):
                user = prof.user
        except (ValueError, TypeError):
            pass

    if not effective_owner_id:
        raise HttpError(400, "owner_id or authenticated user is required to log a meal to the tracker.")

    clean_msg_id = (message_id or "").strip()
    if clean_msg_id:
        existing = TrackedMeal.objects.filter(
            owner_id=effective_owner_id,
            source_message_id=clean_msg_id,
        ).first()
        if existing is not None:
            return {
                "status": "ok",
                "already_logged": True,
                "meal": serialize_tracked_meal(existing),
            }

    resolved_analysis = analysis
    chat_msg = None

    if clean_msg_id:
        try:
            msg_uuid = uuid.UUID(clean_msg_id)
            qs = ChatMessage.objects.using(DATABASE_ALIAS).filter(id=msg_uuid)
            if conversation_id:
                try:
                    conv_uuid = uuid.UUID(str(conversation_id))
                    qs = qs.filter(conversation_id=conv_uuid)
                except (ValueError, TypeError):
                    pass
            chat_msg = qs.first()
        except Exception:
            chat_msg = None

        if chat_msg is not None and not resolved_analysis:
            resolved_analysis = resolve_dish_nutrition_from_db(chat_msg.ai_response or {})
            if (not resolved_analysis or not resolved_analysis.get("items")) and isinstance(chat_msg.ai_response, dict) and chat_msg.ai_response.get("total_macronutrients"):
                resolved_analysis = chat_msg.ai_response
            if not meal_title:
                meal_title = (
                    resolved_analysis.get("meal_title")
                    or (chat_msg.ai_response or {}).get("dish_name")
                    or chat_msg.user_query
                    or "Logged Meal"
                )
            if not recognized_summary:
                recognized_summary = (
                    resolved_analysis.get("recognized_input_summary")
                    or chat_msg.user_query
                    or chat_msg.transcription
                    or ""
                )

    if resolved_analysis and isinstance(resolved_analysis, dict):
        raw_macros = resolved_analysis.get("total_macronutrients") or resolved_analysis.get("macronutrients") or {}
        items = resolved_analysis.get("items") or []
        raw_micros = resolved_analysis.get("total_micronutrients")
        if not raw_micros:
            raw_micros = aggregate_micronutrients_from_items(items)
        final_title = (
            meal_title
            or resolved_analysis.get("meal_title")
            or "Logged Meal"
        )
        final_summary = (
            recognized_summary
            or resolved_analysis.get("recognized_input_summary")
            or ""
        )
    else:
        # Manual food text resolution via IFCT 2017 reference database
        clean_title = (meal_title or "").strip()
        if not clean_title:
            raise HttpError(400, "Provide a meal_title, message_id, or analysis payload to log to tracker.")

        raw_macros = {k: 0.0 for k in MACRO_KEYS}
        items = []
        parts = [p.strip() for p in re.split(r"[,;+]+|\band\b", clean_title) if p.strip()]
        for part in parts:
            weight_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gm|grams|ml)\b", part, flags=re.I)
            weight_g = float(weight_match.group(1)) if weight_match else 100.0
            food_name = re.sub(r"\b\d+(?:\.\d+)?\s*(?:g|gm|grams|ml)\b", "", part, flags=re.I).strip() or part
            resolved_item, is_found = resolve_single_ingredient_from_db({
                "ingredient_name": food_name,
                "estimated_weight_grams": weight_g,
                "serving_size_description": f"{int(weight_g)}g",
            })
            items.append(resolved_item)
            if is_found:
                item_macros = resolved_item.get("macronutrients") or {}
                for k in MACRO_KEYS:
                    raw_macros[k] += float(item_macros.get(k) or 0.0)

        raw_micros = aggregate_micronutrients_from_items(items)
        final_title = clean_title
        final_summary = recognized_summary or f"Logged: {clean_title}"

    clean_macros = {
        k: round(float(raw_macros.get(k) or 0.0), 2)
        for k in MACRO_KEYS
    }

    # Resolve consumed_at timestamp
    consumed_dt = None
    clean_time_opt = str(time_option or "").strip().lower()
    if clean_time_opt != "now" and consumed_at:
        if isinstance(consumed_at, datetime):
            consumed_dt = consumed_at
        elif isinstance(consumed_at, str) and consumed_at.strip():
            raw_val = consumed_at.strip()
            parsed = parse_datetime(raw_val)
            if not parsed:
                try:
                    parsed = datetime.fromisoformat(raw_val)
                except Exception:
                    parsed = None
            if parsed:
                consumed_dt = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
    if not consumed_dt:
        consumed_dt = timezone.now()

    effective_conv_id = str(
        conversation_id or (getattr(chat_msg, "conversation_id", "") if chat_msg else "") or ""
    ).strip()

    tracked = TrackedMeal.objects.create(
        owner_id=effective_owner_id,
        user=user if (user is not None and getattr(user, "pk", None)) else None,
        conversation_id=effective_conv_id,
        source_message_id=clean_msg_id,
        meal_title=str(final_title)[:255],
        meal_type=(meal_type or "Meal").strip()[:32],
        recognized_summary=str(final_summary)[:2000],
        macronutrients=clean_macros,
        micronutrients=raw_micros or {"vitamins": [], "minerals": []},
        items=items,
        logged_via=logged_via or "button",
        consumed_at=consumed_dt,
    )

    if chat_msg is not None:
        try:
            ai_resp = dict(chat_msg.ai_response or {})
            ai_resp["logged_to_tracker"] = True
            ai_resp["tracker_log_id"] = str(tracked.id)
            chat_msg.ai_response = ai_resp
            chat_msg.save(using=DATABASE_ALIAS, update_fields=["ai_response"])
        except Exception:
            pass

    return {
        "status": "ok",
        "already_logged": False,
        "meal": serialize_tracked_meal(tracked),
    }


def delete_tracked_meal(*, owner_id: str, log_id: str, user=None) -> Dict[str, Any]:
    """Delete a logged meal from the user's tracker."""
    try:
        log_uuid = uuid.UUID(str(log_id))
    except (ValueError, TypeError) as exc:
        raise HttpError(400, "Invalid tracker log ID.") from exc

    effective_owner_id = (owner_id or "").strip()
    if user is not None and not getattr(user, "username", "").startswith("guest_"):
        prof = UserProfile.objects.filter(user=user).first()
        if prof:
            effective_owner_id = str(prof.owner_id)

    tracked = TrackedMeal.objects.filter(id=log_uuid, owner_id=effective_owner_id).first()
    if tracked is None and user is not None:
        tracked = TrackedMeal.objects.filter(id=log_uuid, user=user).first()
    if tracked is None:
        raise HttpError(404, "Tracked meal entry not found.")

    source_msg_id = tracked.source_message_id
    tracked.delete()

    if source_msg_id:
        try:
            msg_uuid = uuid.UUID(source_msg_id)
            chat_msg = ChatMessage.objects.using(DATABASE_ALIAS).filter(id=msg_uuid).first()
            if chat_msg and isinstance(chat_msg.ai_response, dict):
                ai_resp = dict(chat_msg.ai_response)
                ai_resp["logged_to_tracker"] = False
                ai_resp.pop("tracker_log_id", None)
                chat_msg.ai_response = ai_resp
                chat_msg.save(using=DATABASE_ALIAS, update_fields=["ai_response"])
        except Exception:
            pass

    return {"status": "ok", "deleted_id": str(log_uuid)}


def _build_period_aggregation(meals: List[TrackedMeal], period_key: str, period_label: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate all macronutrients, micronutrients, and meal records for a given period."""
    period_days = PERIOD_DAYS_MAP.get(period_key, 1)
    macro_totals = {k: 0.0 for k in MACRO_KEYS}
    micro_totals: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]] = {"vitamins": {}, "minerals": {}}
    active_dates = set()
    daily_breakdown_map: Dict[str, Dict[str, Any]] = {}
    serialized_meals = []

    for meal in meals:
        serialized = serialize_tracked_meal(meal)
        serialized_meals.append(serialized)
        m_local = _get_meal_local_datetime(meal)
        day_key = m_local.date().isoformat()
        active_dates.add(day_key)

        day_entry = daily_breakdown_map.setdefault(
            day_key,
            {
                "date": day_key,
                "label": m_local.strftime("%a, %b %d"),
                "short_label": m_local.strftime("%b %d"),
                "calories_kcal": 0.0,
                "protein_g": 0.0,
                "carbohydrates_g": 0.0,
                "total_fat_g": 0.0,
                "dietary_fiber_g": 0.0,
                "meals_count": 0,
            },
        )

        m_macros = dict(meal.macronutrients or {})
        if float(m_macros.get("monounsaturated_fat_g") or 0.0) == 0.0 and float(serialized["macronutrients"].get("monounsaturated_fat_g") or 0.0) > 0:
            m_macros["monounsaturated_fat_g"] = serialized["macronutrients"]["monounsaturated_fat_g"]
            m_macros["polyunsaturated_fat_g"] = serialized["macronutrients"]["polyunsaturated_fat_g"]
            if float(m_macros.get("unsaturated_fat_g") or 0.0) == 0.0:
                m_macros["unsaturated_fat_g"] = serialized["macronutrients"]["unsaturated_fat_g"]
        day_entry["calories_kcal"] += float(m_macros.get("calories_kcal") or 0.0)
        day_entry["protein_g"] += float(m_macros.get("protein_g") or 0.0)
        day_entry["carbohydrates_g"] += float(m_macros.get("carbohydrates_g") or 0.0)
        day_entry["total_fat_g"] += float(m_macros.get("total_fat_g") or 0.0)
        day_entry["dietary_fiber_g"] += float(m_macros.get("dietary_fiber_g") or 0.0)
        day_entry["meals_count"] += 1

        for k in MACRO_KEYS:
            macro_totals[k] += float(m_macros.get(k) or 0.0)

        m_micros = meal.micronutrients or {}
        if not m_micros.get("vitamins") and not m_micros.get("minerals") and meal.items:
            m_micros = aggregate_micronutrients_from_items(meal.items)

        for category in ("vitamins", "minerals"):
            for n in m_micros.get(category) or []:
                if not isinstance(n, dict):
                    continue
                name = str(n.get("name") or "Unknown")
                unit = str(n.get("unit") or "")
                key = (name, unit)
                entry = micro_totals[category].setdefault(
                    key,
                    {
                        "name": name,
                        "unit": unit,
                        "amount": 0.0,
                        "daily_value_percent": 0.0,
                    },
                )
                entry["amount"] += float(n.get("amount") or 0.0)
                entry["daily_value_percent"] += float(n.get("daily_value_percent") or 0.0)

    rounded_macros = {k: round(macro_totals[k], 1) for k in MACRO_KEYS}
    divisor = max(len(active_dates), 1) if period_days > 1 else 1
    daily_average_macros = {
        k: round(macro_totals[k] / divisor, 1)
        for k in MACRO_KEYS
    }
    macro_target_percents = {}
    for k, daily_target in DAILY_MACRO_TARGETS.items():
        period_target = daily_target * period_days
        pct = (macro_totals[k] / period_target * 100.0) if period_target > 0 else 0.0
        macro_target_percents[k] = round(pct, 1)

    aggregated_micros = {
        category: [
            {
                "name": item["name"],
                "unit": item["unit"],
                "amount": round(item["amount"], 2),
                "daily_value_percent": round(item["daily_value_percent"], 1),
                "avg_daily_value_percent": round(item["daily_value_percent"] / period_days, 1),
            }
            for item in sorted(
                cat_map.values(),
                key=lambda x: (-x["daily_value_percent"], x["name"]),
            )
        ]
        for category, cat_map in micro_totals.items()
    }

    timeline = sorted(
        [
            {
                **item,
                "calories_kcal": round(item["calories_kcal"], 1),
                "protein_g": round(item["protein_g"], 1),
                "carbohydrates_g": round(item["carbohydrates_g"], 1),
                "total_fat_g": round(item["total_fat_g"], 1),
                "dietary_fiber_g": round(item["dietary_fiber_g"], 1),
            }
            for item in daily_breakdown_map.values()
        ],
        key=lambda x: x["date"],
    )

    label_to_use = period_label or f"{period_key.capitalize()} Tracker"

    return {
        "period": period_key,
        "label": label_to_use,
        "period_label": label_to_use,
        "period_days": period_days,
        "meals_count": len(serialized_meals),
        "active_days": len(active_dates),
        "daily_average_calories_kcal": daily_average_macros.get("calories_kcal", 0.0),
        "macronutrients": rounded_macros,
        "total_macronutrients": rounded_macros,
        "daily_average_macronutrients": daily_average_macros,
        "macro_target_percents": macro_target_percents,
        "micronutrients": aggregated_micros,
        "total_micronutrients": aggregated_micros,
        "meals": serialized_meals,
        "timeline": timeline,
        "daily_breakdown": timeline,
    }


def get_tracker_summary(
    *,
    owner_id: Optional[str] = None,
    period: str = "daily",
    target_date: Optional[Union[str, datetime, date]] = None,
    user=None,
) -> Dict[str, Any]:
    """
    Return aggregated nutrient information for Daily, Weekly, and Monthly windows.

    STRICT DATE FILTERING FIX:
    The Daily Tracker automatically fetches today's local date and ONLY displays
    meals consumed today. Yesterday's logs are NEVER included in the Daily Tracker.
    """
    clean_period = (period or "daily").strip().lower()
    if clean_period not in PERIOD_DAYS_MAP:
        clean_period = "daily"

    effective_owner_id = (owner_id or "").strip()
    if user is not None and not getattr(user, "username", "").startswith("guest_"):
        prof = UserProfile.objects.filter(user=user).first()
        if prof:
            effective_owner_id = str(prof.owner_id)

    now_local = timezone.localtime(timezone.now()) if timezone.is_aware(timezone.now()) else timezone.now()

    # Resolve target_date (defaults to today's local date)
    date_obj: date
    if isinstance(target_date, datetime):
        date_obj = target_date.date()
    elif isinstance(target_date, date):
        date_obj = target_date
    elif isinstance(target_date, str) and target_date.strip():
        try:
            date_obj = datetime.strptime(target_date.strip()[:10], "%Y-%m-%d").date()
        except Exception:
            date_obj = now_local.date()
    else:
        date_obj = now_local.date()

    # Build 30-day window bounded by target_date
    start_of_target_day = datetime.combine(date_obj, datetime.min.time())
    end_of_target_day = datetime.combine(date_obj, datetime.max.time())
    if timezone.is_aware(now_local):
        tz = timezone.get_current_timezone()
        start_of_target_day = timezone.make_aware(start_of_target_day, tz)
        end_of_target_day = timezone.make_aware(end_of_target_day, tz)

    cutoff_weekly = start_of_target_day - timedelta(days=6)
    cutoff_monthly = start_of_target_day - timedelta(days=29)

    if effective_owner_id:
        all_monthly_meals = list(
            TrackedMeal.objects.filter(
                owner_id=effective_owner_id,
                consumed_at__gte=cutoff_monthly,
                consumed_at__lte=end_of_target_day,
            ).order_by("-consumed_at", "-created_at")
        )
    elif user is not None and getattr(user, "pk", None):
        all_monthly_meals = list(
            TrackedMeal.objects.filter(
                user=user,
                consumed_at__gte=cutoff_monthly,
                consumed_at__lte=end_of_target_day,
            ).order_by("-consumed_at", "-created_at")
        )
    else:
        all_monthly_meals = []

    # STRICT DAILY FILTERING: Only meals consumed on date_obj!
    # Yesterday's logs will have meal_date != date_obj, so they are excluded.
    daily_meals = [
        m for m in all_monthly_meals
        if _get_meal_local_datetime(m).date() == date_obj
    ]
    weekly_meals = [
        m for m in all_monthly_meals
        if _get_meal_local_datetime(m) >= cutoff_weekly and _get_meal_local_datetime(m).date() <= date_obj
    ]

    is_today = (date_obj == now_local.date())
    daily_label = f"Daily Tracker (Today - {date_obj.strftime('%b %d, %Y')})" if is_today else f"Daily Tracker ({date_obj.strftime('%b %d, %Y')})"

    periods_data = {
        "daily": _build_period_aggregation(daily_meals, "daily", daily_label),
        "weekly": _build_period_aggregation(weekly_meals, "weekly", "Weekly Tracker (Last 7 Days)"),
        "monthly": _build_period_aggregation(all_monthly_meals, "monthly", "Monthly Tracker (Last 30 Days)"),
    }

    active_summary = periods_data[clean_period]
    return {
        "active_period": clean_period,
        "owner_id": effective_owner_id,
        "current_date": date_obj.isoformat(),
        "is_today": is_today,
        **active_summary,
        "periods": periods_data,
    }
