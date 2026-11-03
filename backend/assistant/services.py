import sys
import uuid
from pathlib import Path
from typing import Optional

from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse
from ninja.errors import HttpError

from backend.assistant.models import ChatConversation, ChatMessage
from backend.food_database.services import resolve_dish_nutrition_from_db

DATABASE_ALIAS = "default"


def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (AttributeError, TypeError, ValueError) as exc:
        raise HttpError(400, f"Invalid {label}.") from exc


def save_chat_message(
    *,
    owner_id: Optional[str],
    conversation_id: Optional[str],
    user_query: str,
    transcription: Optional[str],
    modalities: list[str],
    ai_response: dict,
    image_data: Optional[bytes] = None,
    image_name: str = "",
    image_content_type: str = "",
    audio_data: Optional[bytes] = None,
    audio_name: str = "",
    audio_content_type: str = "",
    logged_to_tracker: bool = False,
    tracker_log_id: Optional[str] = None,
) -> Optional[ChatMessage]:
    if not owner_id and not conversation_id:
        return None
    if not owner_id or not conversation_id:
        raise HttpError(400, "Both owner_id and conversation_id are required for chat history.")

    owner_uuid = _parse_uuid(owner_id, "owner_id")
    conversation_uuid = _parse_uuid(conversation_id, "conversation_id")
    if not ai_response:
        raise HttpError(500, "The AI response could not be saved to chat history.")

    generated_ingredients = [
        {
            "ingredient_name": str(item.get("ingredient_name") or ""),
            "serving_size_description": str(item.get("serving_size_description") or "1 serving"),
            "estimated_weight_grams": float(item.get("estimated_weight_grams") or 0),
            "confidence": float(item.get("confidence") or 0),
        }
        for item in ai_response.get("ingredients", [])
        if isinstance(item, dict)
    ]
    stored_ai_response = {
        "dish_name": str(ai_response.get("dish_name") or "Meal analysis"),
        "recognized_input_summary": str(
            ai_response.get("recognized_input_summary") or ""
        ),
        "ingredients": generated_ingredients,
        "dietary_tags": [
            str(tag) for tag in ai_response.get("dietary_tags", []) if tag is not None
        ],
        "health_insights": [
            str(insight)
            for insight in ai_response.get("health_insights", [])
            if insight is not None
        ],
        "logged_to_tracker": bool(logged_to_tracker or ai_response.get("logged_to_tracker")),
    }
    if tracker_log_id or ai_response.get("tracker_log_id"):
        stored_ai_response["tracker_log_id"] = str(
            tracker_log_id or ai_response.get("tracker_log_id")
        )

    title = (user_query or transcription or stored_ai_response["dish_name"]).strip()
    title = title[:160] or "New chat"

    with transaction.atomic(using=DATABASE_ALIAS):
        conversation, created = ChatConversation.objects.using(
            DATABASE_ALIAS
        ).get_or_create(
            id=conversation_uuid,
            defaults={"owner_id": str(owner_uuid), "title": title},
        )
        if not created and conversation.owner_id != str(owner_uuid):
            raise HttpError(404, "Chat not found.")

        message = ChatMessage(
            conversation=conversation,
            user_query=user_query,
            transcription=transcription or "",
            input_modalities=modalities,
            ai_response=stored_ai_response,
            image_name=Path(image_name.replace("\\", "/")).name if image_name else "",
            image_content_type=image_content_type,
            audio_name=Path(audio_name.replace("\\", "/")).name if audio_name else "",
            audio_content_type=audio_content_type,
        )
        if image_data:
            message.image.save(
                Path(image_name or "meal-image").name,
                ContentFile(image_data),
                save=False,
            )
        if audio_data:
            message.audio.save(
                Path(audio_name or "voice-note.wav").name,
                ContentFile(audio_data),
                save=False,
            )
        message.save(using=DATABASE_ALIAS)
        conversation.save(using=DATABASE_ALIAS, update_fields=["updated_at"])

    return message


def list_conversations(owner_id: str) -> list[dict]:
    owner_uuid = _parse_uuid(owner_id, "owner_id")
    return [
        {
            "id": str(conversation.id),
            "title": conversation.title,
            "updated_at": conversation.updated_at.isoformat(),
        }
        for conversation in ChatConversation.objects.using(DATABASE_ALIAS)
        .filter(owner_id=str(owner_uuid))
        .order_by("-updated_at")
    ]


def get_conversation(owner_id: str, conversation_id: str) -> dict:
    resolve_func = resolve_dish_nutrition_from_db
    ch_mod = sys.modules.get("chat_history.services")
    if ch_mod and hasattr(ch_mod, "resolve_dish_nutrition_from_db"):
        resolve_func = ch_mod.resolve_dish_nutrition_from_db

    owner_uuid = _parse_uuid(owner_id, "owner_id")
    conversation_uuid = _parse_uuid(conversation_id, "conversation_id")
    conversation = (
        ChatConversation.objects.using(DATABASE_ALIAS)
        .filter(id=conversation_uuid, owner_id=str(owner_uuid))
        .first()
    )
    if conversation is None:
        raise HttpError(404, "Chat not found.")

    messages = []
    for message in conversation.messages.using(DATABASE_ALIAS).all():
        ai_resp = message.ai_response or {}
        analysis = resolve_func(ai_resp)
        warnings = []
        if analysis.get("missing_ingredients"):
            warnings.append(
                "Missing database nutrients for: "
                + ", ".join(analysis["missing_ingredients"])
                + ". Their nutrients are excluded from totals."
            )
        is_logged = bool(ai_resp.get("logged_to_tracker"))
        tracker_log_id = ai_resp.get("tracker_log_id")
        messages.append({
            "id": str(message.id),
            "user_query": message.user_query,
            "transcription": message.transcription,
            "input_modalities": message.input_modalities,
            "result": {
                "dish_name": ai_resp.get("dish_name", ""),
                "recognized_input_summary": ai_resp.get("recognized_input_summary", ""),
                "ingredients": ai_resp.get("ingredients", []),
                "dietary_tags": ai_resp.get("dietary_tags", []),
                "health_insights": ai_resp.get("health_insights", []),
                "analysis": analysis,
                "warnings": warnings,
                "logged_to_tracker": is_logged,
                "tracker_log_id": tracker_log_id,
            },
            "created_at": message.created_at.isoformat(),
            "has_image": bool(message.image),
            "image_name": message.image_name,
            "has_audio": bool(message.audio),
            "audio_name": message.audio_name,
        })

    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "messages": messages,
    }


def delete_conversation(owner_id: str, conversation_id: str) -> dict:
    owner_uuid = _parse_uuid(owner_id, "owner_id")
    conversation_uuid = _parse_uuid(conversation_id, "conversation_id")
    conversation = (
        ChatConversation.objects.using(DATABASE_ALIAS)
        .filter(id=conversation_uuid, owner_id=str(owner_uuid))
        .first()
    )
    if conversation is None:
        raise HttpError(404, "Chat not found.")

    for msg in conversation.messages.all():
        if msg.image:
            msg.image.delete(save=False)
        if msg.audio:
            msg.audio.delete(save=False)

    conversation.delete(using=DATABASE_ALIAS)
    return {
        "status": "ok",
        "deleted_conversation_id": str(conversation_uuid),
    }


def delete_chat_message(
    owner_id: str,
    conversation_id: Optional[str],
    message_id: str,
) -> dict:
    owner_uuid = _parse_uuid(owner_id, "owner_id")
    message_uuid = _parse_uuid(message_id, "message_id")

    if conversation_id and conversation_id != "any":
        conversation_uuid = _parse_uuid(conversation_id, "conversation_id")
        conversation = (
            ChatConversation.objects.using(DATABASE_ALIAS)
            .filter(id=conversation_uuid, owner_id=str(owner_uuid))
            .first()
        )
        if conversation is None:
            raise HttpError(404, "Chat not found.")

        message = (
            ChatMessage.objects.using(DATABASE_ALIAS)
            .filter(id=message_uuid, conversation_id=conversation_uuid)
            .first()
        )
    else:
        message = (
            ChatMessage.objects.using(DATABASE_ALIAS)
            .filter(id=message_uuid, conversation__owner_id=str(owner_uuid))
            .first()
        )
        if message is not None:
            conversation = message.conversation
            conversation_uuid = conversation.id
        else:
            conversation = None
            conversation_uuid = None

    if message is None:
        raise HttpError(404, "Chat message not found.")

    if message.image:
        message.image.delete(save=False)
    if message.audio:
        message.audio.delete(save=False)

    message.delete(using=DATABASE_ALIAS)
    remaining = (
        ChatMessage.objects.using(DATABASE_ALIAS)
        .filter(conversation_id=conversation_uuid)
        .count()
    )
    conversation_deleted = False
    if remaining == 0 and conversation is not None:
        conversation.delete(using=DATABASE_ALIAS)
        conversation_deleted = True

    return {
        "status": "ok",
        "deleted_message_id": str(message_uuid),
        "conversation_id": str(conversation_uuid),
        "remaining_messages": remaining,
        "conversation_deleted": conversation_deleted,
    }


def get_chat_attachment(
    owner_id: str,
    conversation_id: str,
    message_id: str,
    kind: str,
) -> FileResponse:
    owner_uuid = _parse_uuid(owner_id, "owner_id")
    conversation_uuid = _parse_uuid(conversation_id, "conversation_id")
    message_uuid = _parse_uuid(message_id, "message_id")
    if kind not in {"image", "audio"}:
        raise HttpError(404, "Attachment not found.")

    message = (
        ChatMessage.objects.using(DATABASE_ALIAS)
        .filter(
            id=message_uuid,
            conversation_id=conversation_uuid,
            conversation__owner_id=str(owner_uuid),
        )
        .first()
    )
    if message is None:
        raise HttpError(404, "Attachment not found.")

    file_field = message.image if kind == "image" else message.audio
    if not file_field:
        raise HttpError(404, "Attachment not found.")
    content_type = (
        message.image_content_type if kind == "image" else message.audio_content_type
    )
    allowed_types = (
        {"image/jpeg", "image/png", "image/webp"}
        if kind == "image"
        else {"audio/wav", "audio/mpeg"}
    )
    if content_type not in allowed_types:
        content_type = "application/octet-stream"

    response = FileResponse(file_field.open("rb"), content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = "inline"
    return response
