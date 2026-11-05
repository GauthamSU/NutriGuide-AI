import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from ninja.errors import HttpError

from backend.assistant.models import ChatConversation, ChatMessage, UserCustomRecipe
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
                "description": ai_resp.get("recognized_input_summary", ""),
                "ai_dish_name": ai_resp.get("original_dish_name") or ai_resp.get("dish_name", ""),
                "ai_description": ai_resp.get("original_description") or ai_resp.get("recognized_input_summary", ""),
                "recognized_input_summary": ai_resp.get("recognized_input_summary", ""),
                "ingredients": ai_resp.get("ingredients", []),
                "dietary_tags": ai_resp.get("dietary_tags", []),
                "health_insights": ai_resp.get("health_insights", []),
                "analysis": analysis,
                "warnings": warnings,
                "logged_to_tracker": is_logged,
                "tracker_log_id": tracker_log_id,
                "is_customized": bool(ai_resp.get("is_customized")),
                "customization_notes": ai_resp.get("customization_notes", ""),
                "original_ingredients": ai_resp.get("original_ingredients", []),
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

    from django.db.models import Q
    from backend.profile.models import UserProfile
    from backend.tracker.models import TrackedMeal
    from backend.groups.models import GroupMealLog

    messages = list(conversation.messages.all())
    message_ids = [str(m.id) for m in messages]
    dish_titles = []
    tracker_log_ids = []

    for msg in messages:
        if msg.image:
            msg.image.delete(save=False)
        if msg.audio:
            msg.audio.delete(save=False)
        ai_resp = msg.ai_response or {}
        if isinstance(ai_resp, dict):
            raw_t_id = ai_resp.get("tracker_log_id")
            if raw_t_id:
                try:
                    uuid.UUID(str(raw_t_id))
                    tracker_log_ids.append(str(raw_t_id))
                except Exception:
                    pass
            title = ai_resp.get("meal_title") or ai_resp.get("dish_name")
            if title:
                dish_titles.append(str(title).strip())

    # Cascade delete all TrackedMeal records associated with this conversation or its messages
    tm_filter = Q(conversation_id=str(conversation_uuid)) | Q(source_message_id__in=message_ids)
    if tracker_log_ids:
        tm_filter |= Q(id__in=tracker_log_ids)
    TrackedMeal.objects.filter(tm_filter).delete()

    # Cascade delete any matching GroupMealLog entries for this user and dish titles
    if dish_titles:
        prof = UserProfile.objects.filter(owner_id=str(owner_uuid)).first()
        if prof and prof.user:
            GroupMealLog.objects.filter(user=prof.user, meal_title__in=dish_titles).delete()

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

    from django.db.models import Q
    from backend.profile.models import UserProfile
    from backend.tracker.models import TrackedMeal
    from backend.groups.models import GroupMealLog

    msg_id_str = str(message_uuid)
    conv_id_str = str(conversation_uuid) if conversation_uuid else ""
    ai_resp = message.ai_response or {}
    tracker_log_id = None
    meal_title = None
    if isinstance(ai_resp, dict):
        raw_t_id = ai_resp.get("tracker_log_id")
        if raw_t_id:
            try:
                uuid.UUID(str(raw_t_id))
                tracker_log_id = str(raw_t_id)
            except Exception:
                pass
        meal_title = ai_resp.get("meal_title") or ai_resp.get("dish_name")

    # Cascade delete any TrackedMeal associated with this message turn
    tm_filter = Q(source_message_id=msg_id_str)
    if tracker_log_id:
        tm_filter |= Q(id=tracker_log_id)
    if conv_id_str and meal_title:
        tm_filter |= (Q(conversation_id=conv_id_str) & Q(meal_title=str(meal_title).strip()))
    TrackedMeal.objects.filter(tm_filter).delete()

    # Cascade delete any matching GroupMealLog for this user and dish
    if meal_title:
        prof = UserProfile.objects.filter(owner_id=str(owner_uuid)).first()
        if prof and prof.user:
            GroupMealLog.objects.filter(user=prof.user, meal_title=str(meal_title).strip()).delete()

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
        if conv_id_str:
            TrackedMeal.objects.filter(conversation_id=conv_id_str).delete()
        conversation.delete(using=DATABASE_ALIAS)
        conversation_deleted = True

    return {
        "status": "ok",
        "deleted_message_id": str(message_uuid),
        "conversation_id": str(conversation_uuid) if conversation_uuid else "",
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


def customize_dish_recipe(
    *,
    owner_id: str,
    conversation_id: Optional[str],
    message_id: str,
    customized_ingredients: list[dict],
    dish_name: Optional[str] = None,
    description: Optional[str] = None,
    notes: Optional[str] = "",
) -> dict:
    """
    Update a chat message's dish recipe with household-customized ingredients.
    Recalculates verified macronutrients & micronutrients from IFCT reference DB,
    persists a UserCustomRecipe record for recommendation engine & fine-tuning,
    and cascades updates to any linked TrackedMeal.
    """
    owner_uuid = _parse_uuid(owner_id, "owner_id")
    message_uuid = _parse_uuid(message_id, "message_id")

    query = Q(id=message_uuid, conversation__owner_id=str(owner_uuid))
    if conversation_id and conversation_id != "any":
        conv_uuid = _parse_uuid(conversation_id, "conversation_id")
        query &= Q(conversation_id=conv_uuid)

    message = ChatMessage.objects.using(DATABASE_ALIAS).filter(query).first()
    if message is None:
        if conversation_id and conversation_id != "any":
            conv_uuid = _parse_uuid(conversation_id, "conversation_id")
            message = ChatMessage.objects.using(DATABASE_ALIAS).filter(id=message_uuid, conversation_id=conv_uuid).first()
        else:
            message = ChatMessage.objects.using(DATABASE_ALIAS).filter(id=message_uuid).first()
    if message is None:
        raise HttpError(404, "Chat message not found.")

    ai_resp = dict(message.ai_response or {})

    # Preserve baseline original AI dish name and description if not already captured
    if "original_dish_name" not in ai_resp or not ai_resp.get("original_dish_name"):
        ai_resp["original_dish_name"] = str(ai_resp.get("dish_name") or ai_resp.get("meal_title") or "Meal").strip()
    original_dish_name = ai_resp["original_dish_name"]

    if "original_description" not in ai_resp or not ai_resp.get("original_description"):
        ai_resp["original_description"] = str(ai_resp.get("recognized_input_summary") or "").strip()
    original_description = ai_resp["original_description"]

    # Preserve baseline original ingredients if not already captured
    if "original_ingredients" not in ai_resp or not ai_resp.get("original_ingredients"):
        ai_resp["original_ingredients"] = list(ai_resp.get("ingredients") or [])
    original_ingredients = list(ai_resp.get("original_ingredients") or [])

    current_dish_name = (dish_name or ai_resp.get("dish_name") or original_dish_name or "Customized Meal").strip()
    current_description = (
        description
        if description is not None
        else (ai_resp.get("recognized_input_summary") or original_description)
    ).strip()

    # Validate and normalize user-provided ingredient items
    clean_ingredients = []
    for item in customized_ingredients:
        if not isinstance(item, dict):
            continue
        name = str(item.get("food_name") or item.get("ingredient_name") or "").strip()
        if not name:
            continue
        try:
            weight = float(item.get("estimated_weight_grams") or 0.0)
        except (TypeError, ValueError):
            weight = 50.0
        if weight <= 0:
            continue
        desc = str(item.get("serving_size_description") or f"{weight:g}g").strip()
        clean_ingredients.append({
            "ingredient_name": name,
            "food_name": name,
            "estimated_weight_grams": weight,
            "serving_size_description": desc,
            "confidence": float(item.get("confidence") or 1.0),
        })

    if not clean_ingredients:
        raise HttpError(400, "Please provide at least one valid ingredient with weight in grams.")

    # Recalculate nutrients from IFCT reference database
    resolve_func = resolve_dish_nutrition_from_db
    ch_mod = sys.modules.get("chat_history.services")
    if ch_mod and hasattr(ch_mod, "resolve_dish_nutrition_from_db"):
        resolve_func = ch_mod.resolve_dish_nutrition_from_db

    dish_payload = {
        "dish_name": current_dish_name,
        "meal_title": current_dish_name,
        "recognized_input_summary": (
            current_description
            or f"Household recipe for {current_dish_name}"
        ),
        "ingredients": clean_ingredients,
        "dietary_tags": ai_resp.get("dietary_tags") or [],
        "health_insights": list(ai_resp.get("health_insights") or []),
    }
    resolved_analysis = resolve_func(dish_payload)
    resolved_analysis["meal_title"] = current_dish_name
    resolved_analysis["recognized_input_summary"] = current_description

    # Store normalized customized ingredients in ChatMessage
    ai_resp["dish_name"] = current_dish_name
    ai_resp["meal_title"] = current_dish_name
    ai_resp["recognized_input_summary"] = current_description
    ai_resp["ingredients"] = [
        {
            "ingredient_name": item["food_name"],
            "serving_size_description": item["serving_size_description"],
            "estimated_weight_grams": item["estimated_weight_grams"],
            "confidence": item.get("confidence", 1.0),
        }
        for item in (resolved_analysis.get("items") or clean_ingredients)
    ]
    ai_resp["is_customized"] = True
    ai_resp["customized_at"] = datetime.now(timezone.utc).isoformat()
    ai_resp["customization_notes"] = notes or f"Customized with {len(clean_ingredients)} ingredients"
    message.ai_response = ai_resp
    message.save(using=DATABASE_ALIAS)

    # Resolve Django User if available for UserCustomRecipe relation
    from django.contrib.auth import get_user_model
    from backend.profile.models import UserProfile
    User = get_user_model()
    user_obj = None
    if owner_id.isdigit():
        user_obj = User.objects.filter(id=owner_id).first()
    if not user_obj:
        prof = UserProfile.objects.filter(owner_id=str(owner_uuid)).first()
        if prof and prof.user:
            user_obj = prof.user

    # Persist or update the UserCustomRecipe entry for ML recommendation / fine-tuning
    custom_recipe, _ = UserCustomRecipe.objects.using(DATABASE_ALIAS).update_or_create(
        owner_id=str(owner_uuid),
        message_id=str(message.id),
        defaults={
            "user": user_obj,
            "conversation_id": str(message.conversation_id),
            "dish_name": current_dish_name,
            "description": current_description,
            "ai_dish_name": original_dish_name,
            "ai_description": original_description,
            "original_ingredients": original_ingredients,
            "customized_ingredients": ai_resp["ingredients"],
            "total_macronutrients": resolved_analysis.get("total_macronutrients") or {},
            "total_micronutrients": resolved_analysis.get("total_micronutrients") or {},
            "notes": notes or f"Customized household recipe with {len(clean_ingredients)} ingredients",
        },
    )

    # Cascade recalculation to any linked TrackedMeal entries
    from backend.tracker.models import TrackedMeal
    tm_filter = Q(source_message_id=str(message.id))
    raw_t_id = ai_resp.get("tracker_log_id")
    if raw_t_id:
        try:
            uuid.UUID(str(raw_t_id))
            tm_filter |= Q(id=str(raw_t_id))
        except Exception:
            pass
    for tm in TrackedMeal.objects.filter(tm_filter):
        tm.meal_title = current_dish_name
        tm.items = resolved_analysis.get("items") or []
        tm.macronutrients = resolved_analysis.get("total_macronutrients") or {}
        tm.micronutrients = resolved_analysis.get("total_micronutrients") or {}
        tm.save()

    warnings = []
    if resolved_analysis.get("missing_ingredients"):
        warnings.append(
            "Missing database nutrients for: "
            + ", ".join(resolved_analysis["missing_ingredients"])
            + ". Their nutrients are excluded from totals."
        )

    return {
        "status": "ok",
        "message_id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "dish_name": current_dish_name,
        "description": current_description,
        "ai_dish_name": original_dish_name,
        "ai_description": original_description,
        "is_customized": True,
        "custom_recipe_id": str(custom_recipe.id),
        "analysis": resolved_analysis,
        "warnings": warnings,
        "logged_to_tracker": bool(ai_resp.get("logged_to_tracker")),
        "tracker_log_id": ai_resp.get("tracker_log_id"),
    }


def reset_dish_recipe(
    *,
    owner_id: str,
    conversation_id: Optional[str],
    message_id: str,
) -> dict:
    """
    Reverts a chat message's dish recipe back to the original baseline AI ingredients.
    """
    owner_uuid = _parse_uuid(owner_id, "owner_id")
    message_uuid = _parse_uuid(message_id, "message_id")

    query = Q(id=message_uuid, conversation__owner_id=str(owner_uuid))
    if conversation_id and conversation_id != "any":
        conv_uuid = _parse_uuid(conversation_id, "conversation_id")
        query &= Q(conversation_id=conv_uuid)

    message = ChatMessage.objects.using(DATABASE_ALIAS).filter(query).first()
    if message is None:
        if conversation_id and conversation_id != "any":
            conv_uuid = _parse_uuid(conversation_id, "conversation_id")
            message = ChatMessage.objects.using(DATABASE_ALIAS).filter(id=message_uuid, conversation_id=conv_uuid).first()
        else:
            message = ChatMessage.objects.using(DATABASE_ALIAS).filter(id=message_uuid).first()
    if message is None:
        raise HttpError(404, "Chat message not found.")

    ai_resp = dict(message.ai_response or {})
    original_ingredients = ai_resp.get("original_ingredients")
    if not original_ingredients:
        raise HttpError(400, "No original baseline recipe recorded for this message.")

    original_dish_name = ai_resp.get("original_dish_name") or ai_resp.get("dish_name") or "Meal"
    original_description = ai_resp.get("original_description") or ""

    current_dish_name = original_dish_name
    current_description = original_description

    resolve_func = resolve_dish_nutrition_from_db
    ch_mod = sys.modules.get("chat_history.services")
    if ch_mod and hasattr(ch_mod, "resolve_dish_nutrition_from_db"):
        resolve_func = ch_mod.resolve_dish_nutrition_from_db

    dish_payload = {
        "dish_name": current_dish_name,
        "meal_title": current_dish_name,
        "recognized_input_summary": current_description or f"Identified dish: {current_dish_name}",
        "ingredients": original_ingredients,
        "dietary_tags": ai_resp.get("dietary_tags") or [],
        "health_insights": list(ai_resp.get("health_insights") or []),
    }
    resolved_analysis = resolve_func(dish_payload)
    resolved_analysis["meal_title"] = current_dish_name
    resolved_analysis["recognized_input_summary"] = current_description

    ai_resp["dish_name"] = current_dish_name
    ai_resp["meal_title"] = current_dish_name
    ai_resp["recognized_input_summary"] = current_description
    ai_resp["ingredients"] = list(original_ingredients)
    ai_resp["is_customized"] = False
    ai_resp.pop("customized_at", None)
    ai_resp.pop("customization_notes", None)
    message.ai_response = ai_resp
    message.save(using=DATABASE_ALIAS)

    # Cascade to TrackedMeal if any
    from backend.tracker.models import TrackedMeal
    tm_filter = Q(source_message_id=str(message.id))
    raw_t_id = ai_resp.get("tracker_log_id")
    if raw_t_id:
        try:
            uuid.UUID(str(raw_t_id))
            tm_filter |= Q(id=str(raw_t_id))
        except Exception:
            pass
    for tm in TrackedMeal.objects.filter(tm_filter):
        tm.meal_title = current_dish_name
        tm.items = resolved_analysis.get("items") or []
        tm.macronutrients = resolved_analysis.get("total_macronutrients") or {}
        tm.micronutrients = resolved_analysis.get("total_micronutrients") or {}
        tm.save()

    # Revert user custom recipe record if present
    UserCustomRecipe.objects.using(DATABASE_ALIAS).filter(
        message_id=str(message.id),
    ).delete()

    return {
        "status": "ok",
        "message_id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "dish_name": current_dish_name,
        "description": current_description,
        "ai_dish_name": original_dish_name,
        "ai_description": original_description,
        "is_customized": False,
        "analysis": resolved_analysis,
        "logged_to_tracker": bool(ai_resp.get("logged_to_tracker")),
        "tracker_log_id": ai_resp.get("tracker_log_id"),
    }

