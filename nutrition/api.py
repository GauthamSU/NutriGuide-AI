import base64
import json
import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from django.conf import settings
from ninja import File, Form, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile

from nutrition.models import Food
from nutrition.graph.workflow import run_nutrition_workflow
from nutrition.schemas import (
    ErrorResponseSchema,
    HealthCheckResponseSchema,
    NutrientAnalysisResponseSchema,
    TextAnalyzeRequestSchema,
)
from nutrition.services.llama_client import LlamaCppClient

router = Router(tags=["Nutrition Analysis"])
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

    success_response = NutrientAnalysisResponseSchema(
        request_id=final_state["request_id"],
        status=final_state["status"],
        input_modalities=final_state.get("input_modalities", ["text"]),
        analysis=final_state["nutrient_analysis"],
        dietary_warnings=final_state.get("dietary_warnings", []),
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

    if image is not None:
        raw_img = image.read()
        if not raw_img:
            raise HttpError(400, "Uploaded image file is empty.")
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

    success_response = NutrientAnalysisResponseSchema(
        request_id=final_state["request_id"],
        status=final_state["status"],
        input_modalities=final_state.get("input_modalities", []),
        analysis=final_state["nutrient_analysis"],
        dietary_warnings=final_state.get("dietary_warnings", []),
    )
    _write_api_response_debug(200, success_response)
    return 200, success_response
