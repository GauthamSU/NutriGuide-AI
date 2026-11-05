from ninja import Router

from backend.assistant.services import (
    customize_dish_recipe,
    delete_chat_message,
    delete_conversation,
    get_chat_attachment,
    get_conversation,
    list_conversations,
    reset_dish_recipe,
)
from backend.common.schemas import CustomizeRecipeRequestSchema
from backend.meal_planner.services import (
    delete_meal_plan,
    list_meal_plans,
)

router = Router(tags=["Chat History"])


@router.get("/conversations")
def conversations(request, owner_id: str):
    return list_conversations(owner_id)


@router.get("/meal-plans")
def meal_plans(request, owner_id: str):
    return list_meal_plans(owner_id)


@router.delete("/meal-plans/{meal_plan_id}")
@router.post("/meal-plans/{meal_plan_id}/delete")
def remove_meal_plan(request, meal_plan_id: str, owner_id: str):
    return delete_meal_plan(owner_id, meal_plan_id)


@router.get("/conversations/{conversation_id}")
def conversation(request, conversation_id: str, owner_id: str):
    return get_conversation(owner_id, conversation_id)


@router.delete("/conversations/{conversation_id}")
@router.post("/conversations/{conversation_id}/delete")
def remove_conversation(request, conversation_id: str, owner_id: str):
    return delete_conversation(owner_id, conversation_id)


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
@router.post("/conversations/{conversation_id}/messages/{message_id}/delete")
def remove_chat_message(
    request,
    conversation_id: str,
    message_id: str,
    owner_id: str,
):
    return delete_chat_message(owner_id, conversation_id, message_id)


@router.delete("/messages/{message_id}")
@router.post("/messages/{message_id}/delete")
def remove_chat_message_direct(
    request,
    message_id: str,
    owner_id: str,
):
    return delete_chat_message(owner_id, None, message_id)


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/customize-recipe",
    summary="Customize ingredients in a dish recipe and recalculate nutrition",
)
def customize_recipe(
    request,
    conversation_id: str,
    message_id: str,
    payload: CustomizeRecipeRequestSchema,
):
    ingredients_data = [item.model_dump() for item in payload.ingredients]
    return customize_dish_recipe(
        owner_id=payload.owner_id,
        conversation_id=conversation_id,
        message_id=message_id,
        customized_ingredients=ingredients_data,
        dish_name=payload.dish_name,
        description=payload.description,
        notes=payload.notes or "",
    )


@router.post(
    "/messages/{message_id}/customize-recipe",
    summary="Customize ingredients in a dish recipe directly and recalculate nutrition",
)
def customize_recipe_direct(
    request,
    message_id: str,
    payload: CustomizeRecipeRequestSchema,
):
    ingredients_data = [item.model_dump() for item in payload.ingredients]
    return customize_dish_recipe(
        owner_id=payload.owner_id,
        conversation_id=None,
        message_id=message_id,
        customized_ingredients=ingredients_data,
        dish_name=payload.dish_name,
        description=payload.description,
        notes=payload.notes or "",
    )


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/reset-recipe",
    summary="Reset a dish recipe back to baseline AI ingredients",
)
def reset_recipe(
    request,
    conversation_id: str,
    message_id: str,
    owner_id: str,
):
    return reset_dish_recipe(
        owner_id=owner_id,
        conversation_id=conversation_id,
        message_id=message_id,
    )


@router.post(
    "/messages/{message_id}/reset-recipe",
    summary="Reset a dish recipe back to baseline AI ingredients directly",
)
def reset_recipe_direct(
    request,
    message_id: str,
    owner_id: str,
):
    return reset_dish_recipe(
        owner_id=owner_id,
        conversation_id=None,
        message_id=message_id,
    )


@router.get("/conversations/{conversation_id}/messages/{message_id}/{kind}")
def attachment(
    request,
    conversation_id: str,
    message_id: str,
    kind: str,
    owner_id: str,
):
    return get_chat_attachment(owner_id, conversation_id, message_id, kind)

