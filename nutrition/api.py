import base64
import json
import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from django.conf import settings
from ninja import File, Form, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile

from nutrition.models import Food
from nutrition.graph.meal_plan import run_meal_plan_workflow
from nutrition.graph.workflow import run_nutrition_workflow
from nutrition.schemas import (
    ErrorResponseSchema,
    GroupAddMemberRequestSchema,
    GroupCreateRequestSchema,
    GroupMealLogRequestSchema,
    GroupRequestRespondSchema,
    HealthCheckResponseSchema,
    LoginRequestSchema,
    MEAL_PLAN_DIET_TYPES,
    MEAL_PLAN_DURATIONS,
    MEAL_PLAN_PREFERENCES,
    MealPlanRequestSchema,
    NutrientAnalysisResponseSchema,
    SignupRequestSchema,
    TextAnalyzeRequestSchema,
    TrackerLogRequestSchema,
    UserProfileUpdateSchema,
)
from nutrition.services.llama_client import LlamaCppClient
from nutrition.services.tracker_service import (
    delete_tracked_meal,
    get_tracker_summary,
    has_explicit_log_intent,
    log_meal_to_tracker,
)
from nutrition.services.user_group_service import (
    add_member_to_group,
    build_profile_context_for_ai,
    create_nutrition_group,
    get_group_detail,
    get_profile_avatar,
    get_user_from_request,
    join_public_group,
    list_groups_for_user,
    list_user_group_notifications,
    log_meal_to_group,
    login_user,
    respond_to_group_request,
    serialize_user_profile,
    signup_user,
    update_user_profile,
)
from chat_history.services import save_chat_message, save_meal_plan

router = Router(tags=["Nutrition Analysis"])
auth_router = Router(tags=["Authentication"])
profile_router = Router(tags=["User Profile"])
groups_router = Router(tags=["Nutrition Groups"])
tracker_router = Router(tags=["Nutrient Tracker"])
logger = logging.getLogger(__name__)


def _write_api_response_debug(status_code: int, response_body) -> None:
    """Save the serialized response payload returned by a nutrition endpoint."""
    debug_path = Path(
        getattr(
            settings,
            "API_RESPONSE_DEBUG_FILE",
            settings.BASE_DIR / "api_response_debug.json",
        )
    )
    if hasattr(response_body, "model_dump"):
        serialized_body = response_body.model_dump(mode="json")
    else:
        serialized_body = response_body

    record = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "status_code": status_code,
        "response": serialized_body,
    }
    try:
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("Could not write API response diagnostics to %s: %s", debug_path, exc)


@router.get(
    "/health",
    response=HealthCheckResponseSchema,
    summary="Check API and active inference backend health",
)
def health_check(request):
    client = LlamaCppClient()
    backend_health = client.check_health()
    try:
        food_count = Food.objects.count()
    except Exception:
        food_count = None

    return HealthCheckResponseSchema(
        api_status="ok",
        inference_backend=settings.INFERENCE_BACKEND,
        llama_server_url=settings.LLAMA_SERVER_BASE_URL if settings.INFERENCE_BACKEND == "local" else settings.GEMINI_BASE_URL,
        llama_server_reachable=backend_health["reachable"],
        llama_server_status=backend_health["status"],
        model_name=backend_health.get("model_name", client.model_name),
        model_file_exists=Path(settings.LLAMA_MODEL_PATH).exists() if settings.INFERENCE_BACKEND == "local" else True,
        mmproj_file_exists=Path(settings.LLAMA_MMPROJ_PATH).exists() if settings.INFERENCE_BACKEND == "local" else True,
        startup_command_hint=(
            r".\scripts\start_llama_server.ps1"
            if settings.INFERENCE_BACKEND == "local"
            else "Set INFERENCE_BACKEND=gemini in .env (no local server needed)"
        ),
        database_food_count=food_count,
    )


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


@router.post("/meal-plans/generate", summary="Generate and save a personalized meal plan")
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

    try:
        plan = run_meal_plan_workflow(
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
        # Backward compatibility if run_meal_plan_workflow is replaced by a 2-arg stub
        plan = run_meal_plan_workflow(preferences, effective_custom_request)
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
    )
    saved["duration"] = duration
    saved["diet_type"] = diet_type
    if transcription:
        saved["transcription"] = transcription
    return saved


@router.post(
    "/meal-plans/generate/upload",
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


@router.post(
    "/analyze/text",
    response={200: NutrientAnalysisResponseSchema, 400: ErrorResponseSchema, 502: ErrorResponseSchema},
    summary="Analyze food nutrients from text input (JSON)",
)
def analyze_text(request, payload: TextAnalyzeRequestSchema):
    clean_text = (
        payload.text.strip()
        if payload.text and payload.text.strip() and payload.text.strip().lower() != "string"
        else ""
    )
    clean_user_id = (
        payload.user_id.strip()
        if payload.user_id and payload.user_id.strip() and payload.user_id.strip().lower() != "string"
        else None
    )

    final_state = run_nutrition_workflow(
        input_text=clean_text,
        user_id=clean_user_id,
    )

    if final_state.get("status") == "failed" or not final_state.get("nutrient_analysis"):
        errors = final_state.get("errors") or ["Unknown error during nutrient analysis."]
        status_code = 400 if not final_state.get("input_modalities") else 502
        error_response = ErrorResponseSchema(detail=errors[0], errors=errors)
        _write_api_response_debug(status_code, error_response)
        return status_code, error_response

    should_log, logged_via = has_explicit_log_intent(text=clean_text, transcription=None)
    saved_msg = save_chat_message(
        owner_id=payload.owner_id,
        conversation_id=payload.conversation_id,
        user_query=clean_text,
        transcription=None,
        modalities=final_state.get("input_modalities", ["text"]),
        ai_response=final_state.get("ai_generated_response") or {},
        logged_to_tracker=should_log,
    )
    msg_id_str = str(saved_msg.id) if saved_msg is not None else None
    tracker_log_id = None
    if should_log:
        effective_owner = (payload.owner_id or "").strip() or str(uuid.uuid4())
        log_result = log_meal_to_tracker(
            owner_id=effective_owner,
            message_id=msg_id_str,
            conversation_id=payload.conversation_id,
            analysis=final_state["nutrient_analysis"],
            logged_via=logged_via or "text_intent",
        )
        tracker_log_id = (log_result.get("meal") or {}).get("id")

    success_response = NutrientAnalysisResponseSchema(
        request_id=final_state["request_id"],
        status=final_state["status"],
        input_modalities=final_state.get("input_modalities", ["text"]),
        analysis=final_state["nutrient_analysis"],
        dietary_warnings=final_state.get("dietary_warnings", []),
        message_id=msg_id_str,
        logged_to_tracker=should_log,
        tracker_log_id=tracker_log_id,
    )
    _write_api_response_debug(200, success_response)
    return 200, success_response


@router.post(
    "/analyze",
    response={200: NutrientAnalysisResponseSchema, 400: ErrorResponseSchema, 502: ErrorResponseSchema},
    summary="Analyze food nutrients from multimodal input (Text, Image, and/or Voice)",
)
def analyze_multimodal(
    request,
    text: Optional[str] = Form(None, description="Optional text description or question about the meal"),
    user_id: Optional[str] = Form(None, description="Optional user ID for personalization"),
    owner_id: Optional[str] = Form(None, description="Browser history owner identifier"),
    conversation_id: Optional[str] = Form(None, description="Conversation identifier"),
    image: Optional[UploadedFile] = File(None, description="Optional food image (JPEG, PNG, WebP)"),
    voice: Optional[UploadedFile] = File(None, description="Optional voice audio recording (WAV, MP3)"),
):
    clean_text = (
        text.strip()
        if text and text.strip() and text.strip().lower() != "string"
        else None
    )
    clean_user_id = (
        user_id.strip()
        if user_id and user_id.strip() and user_id.strip().lower() != "string"
        else None
    )

    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None
    audio_base64: Optional[str] = None
    audio_format: Optional[str] = None
    transcription: Optional[str] = None
    raw_image: Optional[bytes] = None
    raw_audio: Optional[bytes] = None

    if image is not None:
        raw_img = image.read()
        if not raw_img:
            raise HttpError(400, "Uploaded image file is empty.")
        raw_image = raw_img
        image_base64 = base64.b64encode(raw_img).decode("utf-8")
        guessed_mime, _ = mimetypes.guess_type(image.name or "")
        image_mime_type = image.content_type or guessed_mime or "image/jpeg"

    if voice is not None:
        raw_audio = voice.read()
        if not raw_audio:
            raise HttpError(400, "Uploaded voice audio file is empty.")
        audio_base64 = base64.b64encode(raw_audio).decode("utf-8")
        ext = Path(voice.name or "audio.wav").suffix.lower().lstrip(".")
        audio_format = ext if ext in {"wav", "mp3"} else "wav"
        transcription = LlamaCppClient().transcribe_audio(audio_base64, audio_format)

    final_state = run_nutrition_workflow(
        input_text=clean_text,
        image_base64=image_base64,
        image_mime_type=image_mime_type,
        audio_base64=audio_base64,
        audio_format=audio_format,
        user_id=clean_user_id,
    )

    if final_state.get("status") == "failed" or not final_state.get("nutrient_analysis"):
        errors = final_state.get("errors") or ["Unknown error during nutrient analysis."]
        status_code = 400 if not final_state.get("input_modalities") else 502
        error_response = ErrorResponseSchema(detail=errors[0], errors=errors)
        _write_api_response_debug(status_code, error_response)
        return status_code, error_response

    should_log, logged_via = has_explicit_log_intent(text=clean_text, transcription=transcription)
    saved_msg = save_chat_message(
        owner_id=owner_id,
        conversation_id=conversation_id,
        user_query=clean_text or "",
        transcription=transcription,
        modalities=final_state.get("input_modalities", []),
        ai_response=final_state.get("ai_generated_response") or {},
        image_data=raw_image,
        image_name=image.name if image is not None else "",
        image_content_type=image.content_type if image is not None else "",
        audio_data=raw_audio,
        audio_name=voice.name if voice is not None else "",
        audio_content_type=voice.content_type if voice is not None else "",
        logged_to_tracker=should_log,
    )
    msg_id_str = str(saved_msg.id) if saved_msg is not None else None
    tracker_log_id = None
    if should_log:
        effective_owner = (owner_id or "").strip() or str(uuid.uuid4())
        log_result = log_meal_to_tracker(
            owner_id=effective_owner,
            message_id=msg_id_str,
            conversation_id=conversation_id,
            analysis=final_state["nutrient_analysis"],
            logged_via=logged_via or "voice_intent",
        )
        tracker_log_id = (log_result.get("meal") or {}).get("id")

    success_response = NutrientAnalysisResponseSchema(
        request_id=final_state["request_id"],
        status=final_state["status"],
        input_modalities=final_state.get("input_modalities", []),
        analysis=final_state["nutrient_analysis"],
        dietary_warnings=final_state.get("dietary_warnings", []),
        transcription=transcription,
        message_id=msg_id_str,
        logged_to_tracker=should_log,
        tracker_log_id=tracker_log_id,
    )
    _write_api_response_debug(200, success_response)
    return 200, success_response


# ─── Authentication Endpoints ─────────────────────────────────────────────────


@auth_router.post("/signup", summary="Create a new user account with username, email, and password")
def api_signup(request, payload: SignupRequestSchema):
    return signup_user(
        username=payload.username,
        email=payload.email,
        password=payload.password,
        name=payload.name or "",
        owner_id=payload.owner_id,
    )


@auth_router.post("/login", summary="Authenticate user with username/email and password")
def api_login(request, payload: LoginRequestSchema):
    identifier = (payload.username_or_email or payload.username or payload.email or "").strip()
    return login_user(username_or_email=identifier, password=payload.password)


@auth_router.post("/logout", summary="Log out the current user")
def api_logout(request):
    return {"status": "ok", "message": "Logged out successfully."}


@auth_router.get("/me", summary="Get the currently authenticated user and profile")
def api_me(
    request,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=True)
    return {"user": serialize_user_profile(user)}


# ─── User Profile Endpoints ──────────────────────────────────────────────────


@profile_router.get("", summary="Retrieve user profile details")
def api_get_profile(
    request,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=True)
    return serialize_user_profile(user)


@profile_router.put("", summary="Update user profile (name, age, height, weight, gender, allergies, bio)")
@profile_router.post("", summary="Update user profile (name, age, height, weight, gender, allergies, bio)")
def api_update_profile(request, payload: UserProfileUpdateSchema):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=True,
    )
    height_val = payload.height_cm if payload.height_cm is not None else payload.height
    weight_val = payload.weight_kg if payload.weight_kg is not None else payload.weight
    pic_val = payload.profile_picture if payload.profile_picture is not None else payload.avatar_url
    return update_user_profile(
        user,
        name=payload.name,
        age=payload.age,
        height_cm=height_val,
        weight_kg=weight_val,
        gender=payload.gender,
        allergies=payload.allergies,
        bio=payload.bio,
        email=payload.email,
        profile_picture=pic_val,
    )


@profile_router.post("/upload", summary="Update user profile with multipart file upload for profile picture")
def api_update_profile_upload(
    request,
    name: Optional[str] = Form(default=None),
    age: Optional[str] = Form(default=None),
    height_cm: Optional[str] = Form(default=None),
    height: Optional[str] = Form(default=None),
    weight_kg: Optional[str] = Form(default=None),
    weight: Optional[str] = Form(default=None),
    gender: Optional[str] = Form(default=None),
    allergies: Optional[str] = Form(default=None),
    bio: Optional[str] = Form(default=None),
    email: Optional[str] = Form(default=None),
    profile_picture: Optional[str] = Form(default=None),
    remove_profile_picture: Optional[str] = Form(default=None),
    owner_id: Optional[str] = Form(default=None),
    token: Optional[str] = Form(default=None),
    profile_picture_file: Optional[UploadedFile] = File(default=None),
):
    user = get_user_from_request(
        request,
        token=token,
        owner_id=owner_id,
        require_auth=True,
    )
    height_val = height_cm if height_cm is not None else height
    weight_val = weight_kg if weight_kg is not None else weight

    raw_avatar: Optional[bytes] = None
    avatar_name = ""
    avatar_content_type = ""
    if profile_picture_file is not None:
        raw_avatar = profile_picture_file.read()
        if not raw_avatar:
            raise HttpError(400, "Uploaded profile picture file is empty.")
        avatar_name = profile_picture_file.name or "avatar.png"
        guessed_mime, _ = mimetypes.guess_type(avatar_name)
        avatar_content_type = profile_picture_file.content_type or guessed_mime or "image/png"
    elif str(remove_profile_picture or "").strip().lower() in {"1", "true", "yes"}:
        profile_picture = ""

    return update_user_profile(
        user,
        name=name,
        age=age,
        height_cm=height_val,
        weight_kg=weight_val,
        gender=gender,
        allergies=allergies,
        bio=bio,
        email=email,
        profile_picture=profile_picture,
        profile_picture_data=raw_avatar,
        profile_picture_name=avatar_name,
        profile_picture_content_type=avatar_content_type,
    )


@profile_router.get("/avatar/{owner_id}", summary="Serve stored profile picture from MEDIA_ROOT / object storage")
def api_get_profile_avatar(request, owner_id: str):
    return get_profile_avatar(owner_id)


# ─── Nutrition Groups Endpoints ──────────────────────────────────────────────


@groups_router.get("", summary="List user's nutrition groups and public groups")
def api_list_groups(
    request,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
    q: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=False)
    return list_groups_for_user(current_user=user, search_query=q)


@groups_router.post("", summary="Create a public or private nutrition group")
def api_create_group(request, payload: GroupCreateRequestSchema):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=True,
    )
    combined_members = list(payload.member_identifiers or []) + list(payload.members or [])
    return create_nutrition_group(
        user,
        name=payload.name,
        description=payload.description,
        is_public=payload.is_public,
        visibility=payload.visibility,
        member_identifiers=combined_members,
    )


@groups_router.get("/notifications", summary="List user's group invitations and pending requests")
def api_group_notifications(
    request,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=True)
    return list_user_group_notifications(user)


@groups_router.post("/requests/{request_id}/respond", summary="Accept, decline, or cancel a group membership request or invitation")
def api_respond_group_request(
    request,
    request_id: str,
    payload: GroupRequestRespondSchema,
):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=True,
    )
    return respond_to_group_request(user, request_id=request_id, action=payload.action)


@groups_router.get("/{group_id}", summary="Get group details, members, and collective nutrition")
def api_get_group(
    request,
    group_id: str,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=False)
    return get_group_detail(group_id, current_user=user)


@groups_router.post("/{group_id}/members", summary="Add a member to a nutrition group by username or email")
def api_add_group_member(request, group_id: str, payload: GroupAddMemberRequestSchema):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=True,
    )
    ident = (payload.identifier or payload.username or payload.email or "").strip()
    return add_member_to_group(user, group_id=group_id, identifier=ident)


@groups_router.post("/{group_id}/join", summary="Join a public nutrition group")
def api_join_group(
    request,
    group_id: str,
    token: Optional[str] = None,
    owner_id: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=True)
    return join_public_group(user, group_id=group_id)


@groups_router.post("/{group_id}/meals", summary="Log a meal to a group for collective nutrition tracking")
def api_log_group_meal(request, group_id: str, payload: GroupMealLogRequestSchema):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=True,
    )
    fat_val = payload.total_fat_g if payload.total_fat_g is not None else payload.fat_g
    fiber_val = payload.dietary_fiber_g if payload.dietary_fiber_g is not None else payload.fiber_g
    notes_val = payload.serving_notes or ""
    if payload.serving_grams is not None and not notes_val:
        notes_val = f"{payload.serving_grams}g"
    return log_meal_to_group(
        user,
        group_id=group_id,
        meal_title=payload.meal_title,
        meal_type=payload.meal_type,
        calories_kcal=payload.calories_kcal,
        protein_g=payload.protein_g,
        carbohydrates_g=payload.carbohydrates_g,
        total_fat_g=fat_val,
        dietary_fiber_g=fiber_val,
        serving_grams=payload.serving_grams,
        serving_notes=notes_val,
    )


# ─── Nutrient Tracker Endpoints ──────────────────────────────────────────────


@tracker_router.get("", summary="Get aggregated Daily, Weekly, and Monthly nutrient tracker summary")
@tracker_router.get("/summary", summary="Get aggregated Daily, Weekly, and Monthly nutrient tracker summary")
def api_get_tracker_summary(
    request,
    period: str = "daily",
    owner_id: Optional[str] = None,
    token: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=False)
    return get_tracker_summary(owner_id=owner_id, period=period, user=user)


@tracker_router.post("/log", summary="Explicitly log a meal or chat dish analysis into the Nutrient Tracker")
def api_log_to_tracker(request, payload: TrackerLogRequestSchema):
    user = get_user_from_request(
        request,
        token=payload.token,
        owner_id=payload.owner_id,
        require_auth=False,
    )
    analysis_payload = payload.analysis
    if not analysis_payload and not payload.message_id and any(
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
        analysis_payload = {
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
    return log_meal_to_tracker(
        owner_id=payload.owner_id,
        user=user,
        message_id=payload.message_id,
        conversation_id=payload.conversation_id,
        meal_title=payload.meal_title,
        meal_type=payload.meal_type,
        recognized_summary=payload.recognized_summary,
        analysis=analysis_payload,
        logged_via=payload.logged_via or ("chat_button" if payload.message_id else "manual"),
        consumed_at=payload.consumed_at,
        time_option=payload.time_option or "now",
    )


@tracker_router.delete("/meals/{log_id}", summary="Remove a logged meal from the Nutrient Tracker")
@tracker_router.post("/meals/{log_id}/delete", summary="Remove a logged meal from the Nutrient Tracker")
def api_delete_tracked_meal(
    request,
    log_id: str,
    owner_id: Optional[str] = None,
    token: Optional[str] = None,
):
    user = get_user_from_request(request, token=token, owner_id=owner_id, require_auth=False)
    return delete_tracked_meal(owner_id=owner_id or "", log_id=log_id, user=user)


