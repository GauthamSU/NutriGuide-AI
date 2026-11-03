import base64
import json
import logging
import mimetypes
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from django.conf import settings
from ninja import File, Form, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile

from backend.assistant.graph.workflow import run_nutrition_workflow
from backend.assistant.services import (
    delete_chat_message,
    delete_conversation,
    get_chat_attachment,
    get_conversation,
    list_conversations,
    save_chat_message,
)
from backend.common.schemas import (
    ErrorResponseSchema,
    HealthCheckResponseSchema,
    NutrientAnalysisResponseSchema,
    TextAnalyzeRequestSchema,
)
from nutrition.services.llama_client import LlamaCppClient
from backend.food_database.models import Food
from backend.profile.services import (
    build_profile_context_for_ai,
    get_user_from_request,
)
from backend.tracker.services import (
    has_explicit_log_intent,
    log_meal_to_tracker,
)

assistant_router = Router(tags=["Assistant & Multimodal Dish Analysis"])
conversations_router = Router(tags=["Chat Conversations & History"])
logger = logging.getLogger(__name__)


def _write_api_response_debug(status_code: int, response_body) -> None:
    nut_mod = sys.modules.get("nutrition.api")
    if nut_mod and hasattr(nut_mod, "_write_api_response_debug") and nut_mod._write_api_response_debug is not _write_api_response_debug:
        try:
            return nut_mod._write_api_response_debug(status_code, response_body)
        except Exception:
            pass

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


@assistant_router.get(
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


@assistant_router.post(
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
        else ""
    )
    clean_owner_id = (
        payload.owner_id.strip()
        if payload.owner_id and payload.owner_id.strip() and payload.owner_id.strip().lower() != "string"
        else clean_user_id
    )
    clean_conv_id = (
        payload.conversation_id.strip()
        if payload.conversation_id and payload.conversation_id.strip() and payload.conversation_id.strip().lower() != "string"
        else None
    )

    if not clean_text:
        err = ErrorResponseSchema(error_code="INVALID_INPUT", detail="text field cannot be empty.")
        _write_api_response_debug(400, err)
        return 400, err

    run_wf = run_nutrition_workflow
    nut_mod = sys.modules.get("nutrition.api")
    if nut_mod and hasattr(nut_mod, "run_nutrition_workflow"):
        run_wf = nut_mod.run_nutrition_workflow

    try:
        final_state = run_wf(
            input_text=clean_text,
            user_id=clean_user_id or clean_owner_id,
        )
    except Exception as exc:
        err = ErrorResponseSchema(error_code="WORKFLOW_ERROR", detail=str(exc))
        _write_api_response_debug(502, err)
        return 502, err

    if final_state.get("status") == "failed" or not final_state.get("nutrient_analysis"):
        errors = final_state.get("errors") or ["Unknown error during nutrient analysis."]
        status_code = 400 if not final_state.get("input_modalities") else 502
        err = ErrorResponseSchema(
            detail=errors[0],
            errors=errors,
        )
        _write_api_response_debug(status_code, err)
        return status_code, err

    should_log, log_source = has_explicit_log_intent(clean_text, None)
    tracker_log_id: Optional[str] = None
    msg_id_str: Optional[str] = None

    if clean_owner_id and clean_conv_id:
        try:
            created_msg = save_chat_message(
                owner_id=clean_owner_id,
                conversation_id=clean_conv_id,
                user_query=clean_text,
                transcription=None,
                modalities=["text"],
                ai_response=final_state.get("ai_generated_response") or final_state.get("nutrient_analysis") or {},
                logged_to_tracker=should_log,
            )
            if created_msg:
                msg_id_str = str(created_msg.id)
        except Exception as exc:
            logger.warning("Could not persist message to chat history: %s", exc)

    if should_log and clean_owner_id:
        try:
            tracker_result = log_meal_to_tracker(
                owner_id=clean_owner_id,
                message_id=msg_id_str,
                conversation_id=clean_conv_id,
                analysis=final_state.get("nutrient_analysis"),
                logged_via=log_source or "text_intent",
                meal_title=(final_state.get("nutrient_analysis") or {}).get("meal_title") or clean_text,
            )
            tracker_log_id = str((tracker_result.get("meal") or {}).get("id") or "")
        except Exception as exc:
            logger.warning("Could not automatically log meal to tracker for owner=%s: %s", clean_owner_id, exc)

    success_response = NutrientAnalysisResponseSchema(
        request_id=final_state["request_id"],
        status=final_state["status"],
        input_modalities=final_state.get("input_modalities", []),
        analysis=final_state["nutrient_analysis"],
        dietary_warnings=final_state.get("dietary_warnings", []),
        message_id=msg_id_str,
        logged_to_tracker=should_log,
        tracker_log_id=tracker_log_id,
    )
    _write_api_response_debug(200, success_response)
    return 200, success_response


@assistant_router.post(
    "/analyze",
    response={200: NutrientAnalysisResponseSchema, 400: ErrorResponseSchema, 502: ErrorResponseSchema},
    summary="Analyze food nutrients from multimodal form data (Text, Image, Voice)",
)
def analyze_multimodal(
    request,
    text: Optional[str] = Form(None, description="Optional text describing the meal"),
    user_id: Optional[str] = Form(None, description="Optional user identifier"),
    owner_id: Optional[str] = Form(None, description="Persistent user identifier"),
    conversation_id: Optional[str] = Form(None, description="Persistent conversation UUID"),
    image: Optional[UploadedFile] = File(None, description="Optional food photo (JPEG/PNG/WebP)"),
    voice: Optional[UploadedFile] = File(None, description="Optional voice recording (WAV/MP3/WebM)"),
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
    effective_owner_id = (
        owner_id.strip()
        if owner_id and owner_id.strip() and owner_id.strip().lower() != "string"
        else clean_user_id
    )
    clean_conversation_id = (
        conversation_id.strip()
        if conversation_id and conversation_id.strip() and conversation_id.strip().lower() != "string"
        else None
    )

    if not clean_text and not image and not voice:
        err = ErrorResponseSchema(
            detail="At least one input modality (text, image, or voice) must be provided.",
            errors=["At least one input modality (text, image, or voice) must be provided."],
        )
        _write_api_response_debug(400, err)
        return 400, err

    image_base64: Optional[str] = None
    image_mime_type: Optional[str] = None
    raw_image_data: Optional[bytes] = None
    image_file_name: str = ""

    if image is not None:
        raw_image_data = image.read()
        if not raw_image_data:
            raise HttpError(400, "Uploaded image file is empty.")
        image_base64 = base64.b64encode(raw_image_data).decode("utf-8")
        guessed_mime, _ = mimetypes.guess_type(image.name or "")
        image_mime_type = image.content_type or guessed_mime or "image/jpeg"
        image_file_name = image.name or "meal.jpg"

    raw_audio_data: Optional[bytes] = None
    audio_base64: Optional[str] = None
    audio_format: Optional[str] = None
    transcription: Optional[str] = None
    audio_file_name: str = ""
    audio_content_type: str = ""

    if voice is not None:
        raw_audio_data = voice.read()
        if not raw_audio_data:
            raise HttpError(400, "Uploaded voice audio file is empty.")
        audio_base64 = base64.b64encode(raw_audio_data).decode("utf-8")
        ext = Path(voice.name or "audio.wav").suffix.lower().lstrip(".")
        audio_format = ext if ext in {"wav", "mp3"} else "wav"
        audio_file_name = voice.name or f"voice-note.{audio_format}"
        audio_content_type = voice.content_type or f"audio/{audio_format}"

        client_cls = LlamaCppClient
        nut_mod = sys.modules.get("nutrition.api")
        if nut_mod and hasattr(nut_mod, "LlamaCppClient"):
            client_cls = nut_mod.LlamaCppClient
        transcription = client_cls().transcribe_audio(audio_base64, audio_format)

    run_wf = run_nutrition_workflow
    nut_mod = sys.modules.get("nutrition.api")
    if nut_mod and hasattr(nut_mod, "run_nutrition_workflow"):
        run_wf = nut_mod.run_nutrition_workflow

    try:
        final_state = run_wf(
            input_text=clean_text,
            image_base64=image_base64,
            image_mime_type=image_mime_type,
            audio_base64=audio_base64,
            audio_format=audio_format,
            user_id=clean_user_id or effective_owner_id,
        )
    except Exception as exc:
        err = ErrorResponseSchema(detail=str(exc), errors=[str(exc)])
        _write_api_response_debug(502, err)
        return 502, err

    if final_state.get("status") == "failed" or not final_state.get("nutrient_analysis"):
        errors = final_state.get("errors") or ["Unknown error during nutrient analysis."]
        status_code = 400 if not final_state.get("input_modalities") else 502
        err = ErrorResponseSchema(
            detail=errors[0],
            errors=errors,
        )
        _write_api_response_debug(status_code, err)
        return status_code, err

    if not transcription and final_state.get("transcription"):
        transcription = final_state.get("transcription")

    should_log, log_source = has_explicit_log_intent(clean_text, transcription)
    tracker_log_id: Optional[str] = None
    created_msg = None
    msg_id_str: Optional[str] = None

    if effective_owner_id and clean_conversation_id:
        try:
            created_msg = save_chat_message(
                owner_id=effective_owner_id,
                conversation_id=clean_conversation_id,
                user_query=clean_text or "",
                transcription=transcription,
                modalities=final_state.get("input_modalities", []),
                ai_response=final_state.get("ai_generated_response") or final_state.get("nutrient_analysis") or {},
                image_data=raw_image_data,
                image_name=image_file_name,
                image_content_type=image_mime_type or "",
                audio_data=raw_audio_data,
                audio_name=audio_file_name,
                audio_content_type=audio_content_type,
                logged_to_tracker=should_log,
            )
            if created_msg:
                msg_id_str = str(created_msg.id)
        except Exception as exc:
            logger.warning("Could not persist message to chat history: %s", exc)

    if should_log and effective_owner_id:
        try:
            tracker_result = log_meal_to_tracker(
                owner_id=effective_owner_id,
                message_id=msg_id_str,
                conversation_id=clean_conversation_id,
                analysis=final_state.get("nutrient_analysis"),
                logged_via=log_source or "button",
                meal_title=(final_state.get("nutrient_analysis") or {}).get("meal_title") or clean_text or "Logged Meal",
            )
            tracker_log_id = str((tracker_result.get("meal") or {}).get("id") or "")
        except Exception as exc:
            logger.warning("Could not automatically log meal to tracker for owner=%s: %s", effective_owner_id, exc)

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


# ─── Chat Conversations Endpoints ─────────────────────────────────────────────


@conversations_router.get("/conversations", summary="List user chat conversations")
def conversations(request, owner_id: str):
    return list_conversations(owner_id)


@conversations_router.get("/conversations/{conversation_id}", summary="Get conversation messages")
def conversation(request, conversation_id: str, owner_id: str):
    return get_conversation(owner_id, conversation_id)


@conversations_router.delete("/conversations/{conversation_id}", summary="Delete conversation")
@conversations_router.post("/conversations/{conversation_id}/delete", summary="Delete conversation (POST)")
def remove_conversation(request, conversation_id: str, owner_id: str):
    return delete_conversation(owner_id, conversation_id)


@conversations_router.delete("/conversations/{conversation_id}/messages/{message_id}", summary="Delete message")
@conversations_router.post("/conversations/{conversation_id}/messages/{message_id}/delete", summary="Delete message (POST)")
def remove_chat_message(
    request,
    conversation_id: str,
    message_id: str,
    owner_id: str,
):
    return delete_chat_message(owner_id, conversation_id, message_id)


@conversations_router.delete("/messages/{message_id}", summary="Delete message directly")
@conversations_router.post("/messages/{message_id}/delete", summary="Delete message directly (POST)")
def remove_chat_message_direct(
    request,
    message_id: str,
    owner_id: str,
):
    return delete_chat_message(owner_id, None, message_id)


@conversations_router.get("/conversations/{conversation_id}/messages/{message_id}/{kind}", summary="Get message attachment")
def attachment(
    request,
    conversation_id: str,
    message_id: str,
    kind: str,
    owner_id: str,
):
    return get_chat_attachment(owner_id, conversation_id, message_id, kind)
