import base64
import json
import logging
import mimetypes
import sys
import uuid
from pathlib import Path
from typing import Optional

from django.conf import settings
from ninja import File, Form, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile

from backend.common.schemas import (
    MEAL_PLAN_DIET_TYPES,
    MEAL_PLAN_DURATIONS,
    MEAL_PLAN_PREFERENCES,
    MealPlanRequestSchema,
)
from nutrition.services.llama_client import LlamaCppClient
from backend.meal_planner.services import (
    delete_meal_plan,
    list_meal_plans,
    run_meal_plan_workflow,
    save_meal_plan,
)
from backend.profile.services import build_profile_context_for_ai

router = Router(tags=["Meal Planner"])
logger = logging.getLogger(__name__)


def _normalize_meal_plan_inputs(
    *,
    raw_preferences: list[str],
    custom_request: str,
    duration: str,
    diet_type: str,
    has_media: bool = False,
) -> tuple[list[str], str, str]:
    clean_duration = (duration or "daily").strip().lower()
    duration_aliases = {
        "day": "daily",
        "1-day": "daily",
        "daily": "daily",
        "week": "weekly",
        "7-day": "weekly",
        "weekly": "weekly",
        "month": "monthly",
        "30-day": "monthly",
        "monthly": "monthly",
    }
    canonical_duration = duration_aliases.get(clean_duration)
    if not canonical_duration or canonical_duration not in MEAL_PLAN_DURATIONS:
        raise HttpError(400, f"Unsupported meal-plan duration: {duration}")

    clean_diet = (diet_type or "").strip().lower()
    diet_aliases = {
        "": "",
        "veg": "veg",
        "vegetarian": "veg",
        "lacto-vegetarian": "veg",
        "non-veg": "non-veg",
        "non_veg": "non-veg",
        "nonveg": "non-veg",
        "non vegetarian": "non-veg",
        "non-vegetarian": "non-veg",
        "vegan": "vegan",
        "plant-based": "vegan",
        "egg": "egg",
        "eggetarian": "egg",
        "ovo-vegetarian": "egg",
    }
    if clean_diet not in diet_aliases:
        raise HttpError(400, f"Unsupported dietary preference: {diet_type}")
    canonical_diet = diet_aliases[clean_diet]

    if not raw_preferences and not custom_request and not canonical_diet and not has_media:
        raise HttpError(400, "Choose at least one preference or add a custom request.")

    valid_pref_map = {p.lower(): p for p in MEAL_PLAN_PREFERENCES}
    for p in MEAL_PLAN_PREFERENCES:
        valid_pref_map[p.lower().replace("-", " ")] = p
        valid_pref_map[p.lower().replace(" ", "-")] = p

    preferences = []
    for pref in raw_preferences:
        key = pref.lower()
        canonical = (
            valid_pref_map.get(key)
            or valid_pref_map.get(key.replace("-", " "))
            or valid_pref_map.get(key.replace(" ", "-"))
        )
        if not canonical:
            raise HttpError(400, f"Unsupported meal-planning preference: {pref}")
        if canonical not in preferences:
            preferences.append(canonical)

    return preferences, canonical_duration, canonical_diet


@router.post("/generate", summary="Generate and save a personalized meal plan")
def generate_meal_plan(request, payload: MealPlanRequestSchema):
    raw_preferences = [preference.strip() for preference in payload.preferences if preference.strip()]
    custom_request = payload.custom_request.strip()
    has_media = bool(payload.image_base64 or payload.audio_base64)
    effective_owner_id = (payload.owner_id or "").strip() or str(uuid.uuid4())

    preferences, duration, diet_type = _normalize_meal_plan_inputs(
        raw_preferences=raw_preferences,
        custom_request=custom_request,
        duration=payload.duration,
        diet_type=payload.diet_type,
        has_media=has_media,
    )

    transcription: Optional[str] = None
    if payload.audio_base64:
        fmt = (payload.audio_format or "wav").lower().lstrip(".")
        if fmt not in {"wav", "mp3"}:
            fmt = "wav"
        try:
            transcription = LlamaCppClient().transcribe_audio(payload.audio_base64, fmt)
        except Exception as exc:
            logger.exception("Meal plan voice transcription failed: %s", exc)
            raise HttpError(502, "Could not transcribe voice note. Please try again.") from exc

    profile_context = build_profile_context_for_ai(owner_id=effective_owner_id)
    effective_custom_request = custom_request
    if transcription:
        effective_custom_request = (
            f"{custom_request}\nVoice request: {transcription}".strip()
            if custom_request
            else transcription
        )

    run_wf = run_meal_plan_workflow
    nut_mod = sys.modules.get("nutrition.api")
    if nut_mod and hasattr(nut_mod, "run_meal_plan_workflow"):
        run_wf = nut_mod.run_meal_plan_workflow

    try:
        plan = run_wf(
            preferences,
            effective_custom_request,
            duration=duration,
            diet_type=diet_type,
            image_base64=payload.image_base64,
            image_mime_type=payload.image_mime_type,
            transcription=transcription,
            user_profile_context=profile_context,
        )
    except TypeError:
        plan = run_wf(preferences, effective_custom_request)
    except Exception as exc:
        logger.exception("Meal plan generation failed: %s", exc)
        raise HttpError(502, "Meal plan generation failed. Please try again.") from exc

    if isinstance(plan, dict):
        plan = dict(plan)
        plan["duration"] = duration
        if diet_type:
            plan["diet_type"] = diet_type
        if transcription:
            plan["transcription"] = transcription
        if payload.image_name:
            plan["image_name"] = payload.image_name
        if payload.image_base64:
            plan["has_image"] = True

    saved = save_meal_plan(
        owner_id=effective_owner_id,
        preferences=preferences,
        custom_request=effective_custom_request,
        plan=plan,
        title=f"{diet_type.capitalize() or 'Custom'} {duration.capitalize()} Meal Plan",
    )
    res = {
        "id": str(saved["id"]),
        "owner_id": str(effective_owner_id),
        "title": saved["title"],
        "preferences": saved["preferences"],
        "custom_request": saved["custom_request"],
        "plan": saved["plan"],
        "created_at": saved["created_at"],
        "duration": duration,
        "diet_type": diet_type,
    }
    if transcription:
        res["transcription"] = transcription
    return res


@router.post(
    "/generate/upload",
    summary="Generate and save a personalized meal plan from multimodal form data (Text, Image, Voice)",
)
def generate_meal_plan_multimodal(
    request,
    owner_id: Optional[str] = Form(None, description="Owner UUID"),
    preferences: Optional[str] = Form(None, description="JSON array or comma-separated list of preferences"),
    custom_request: Optional[str] = Form("", description="Custom meal plan instructions"),
    duration: Optional[str] = Form("daily", description="daily, weekly, or monthly"),
    diet_type: Optional[str] = Form("", description="veg, non-veg, vegan, or egg"),
    image: Optional[UploadedFile] = File(None, description="Optional food/ingredient photo"),
    voice: Optional[UploadedFile] = File(None, description="Optional voice recording (WAV/MP3)"),
):
    raw_prefs: list[str] = []
    if preferences:
        try:
            parsed = json.loads(preferences)
            if isinstance(parsed, list):
                raw_prefs = [str(item).strip() for item in parsed if str(item).strip()]
            else:
                raw_prefs = [s.strip() for s in preferences.split(",") if s.strip()]
        except ValueError:
            raw_prefs = [s.strip() for s in preferences.split(",") if s.strip()]

    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None
    image_name: Optional[str] = None
    audio_base64: Optional[str] = None
    audio_format: Optional[str] = None

    if image is not None:
        raw_img = image.read()
        if not raw_img:
            raise HttpError(400, "Uploaded image file is empty.")
        image_base64 = base64.b64encode(raw_img).decode("utf-8")
        guessed_mime, _ = mimetypes.guess_type(image.name or "")
        image_mime_type = image.content_type or guessed_mime or "image/jpeg"
        image_name = image.name

    if voice is not None:
        raw_audio = voice.read()
        if not raw_audio:
            raise HttpError(400, "Uploaded voice audio file is empty.")
        audio_base64 = base64.b64encode(raw_audio).decode("utf-8")
        ext = Path(voice.name or "audio.wav").suffix.lower().lstrip(".")
        audio_format = ext if ext in {"wav", "mp3"} else "wav"

    payload = MealPlanRequestSchema(
        preferences=raw_prefs,
        custom_request=custom_request or "",
        owner_id=owner_id,
        duration=duration or "daily",
        diet_type=diet_type or "",
        image_base64=image_base64,
        image_mime_type=image_mime_type,
        image_name=image_name,
        audio_base64=audio_base64,
        audio_format=audio_format,
    )
    return generate_meal_plan(request, payload)


@router.get("", summary="List previously generated meal plans")
def list_plans(request, owner_id: str):
    return list_meal_plans(owner_id)


@router.delete("/{meal_plan_id}", summary="Delete a generated meal plan")
@router.post("/{meal_plan_id}/delete", summary="Delete a generated meal plan (POST alternative)")
def remove_plan(request, meal_plan_id: str, owner_id: str):
    return delete_meal_plan(owner_id, meal_plan_id)
